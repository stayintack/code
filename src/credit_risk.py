"""Utilities for the UCI credit-card default portfolio project."""

from __future__ import annotations

import re
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_curve


UCI_DATASET_URL = (
    "https://archive.ics.uci.edu/static/public/350/"
    "default+of+credit+card+clients.zip"
)
TARGET = "default_flag"
DEMOGRAPHIC_COLUMNS = ["sex", "education", "marriage", "age"]
PAYMENT_STATUS_COLUMNS = ["pay_0", "pay_2", "pay_3", "pay_4", "pay_5", "pay_6"]


def _standardize_column_name(value: object) -> str:
    name = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return re.sub(r"_+", "_", name)


def load_uci_dataset(raw_dir: str | Path = "data/raw") -> pd.DataFrame:
    """Download the public UCI workbook once, then return a cleaned dataframe.

    The original workbook has a descriptive first row and its column names on
    the second row, so it is read with ``header=1``.
    """
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    workbook = raw_dir / "default_of_credit_card_clients.xls"
    if not workbook.exists():
        archive = raw_dir / "uci_credit_card_default.zip"
        urllib.request.urlretrieve(UCI_DATASET_URL, archive)
        with zipfile.ZipFile(archive) as zipped:
            workbook_names = [
                name
                for name in zipped.namelist()
                if name.lower().endswith((".xls", ".xlsx"))
            ]
            if len(workbook_names) != 1:
                raise ValueError(
                    f"Expected one Excel workbook in UCI archive, found {workbook_names}"
                )
            workbook.write_bytes(zipped.read(workbook_names[0]))

    data = pd.read_excel(workbook, header=1)
    data.columns = [_standardize_column_name(column) for column in data.columns]
    target_candidates = [
        column
        for column in data.columns
        if column in {"default_payment_next_month", "defaultpaymentnextmonth"}
    ]
    if len(target_candidates) != 1:
        raise ValueError(f"Could not identify target column in {list(data.columns)}")
    data = data.rename(columns={target_candidates[0]: TARGET})

    # Remove exact duplicate records and the source row identifier before modelling.
    data = data.drop_duplicates()
    if "id" in data.columns:
        data = data.drop(columns="id")

    # The source uses 0/5/6 for education and 0 for marriage as undocumented
    # or other categories; fold these into each field's documented "other" bin.
    if "education" in data:
        data["education"] = data["education"].replace({0: 4, 5: 4, 6: 4})
    if "marriage" in data:
        data["marriage"] = data["marriage"].replace({0: 3})

    for column in data.columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    if data.isna().any().any():
        missing = data.isna().sum().loc[lambda count: count.gt(0)].to_dict()
        raise ValueError(f"Unexpected missing/non-numeric values after loading: {missing}")
    data[TARGET] = data[TARGET].astype("int8")
    if not set(data[TARGET].unique()).issubset({0, 1}):
        raise ValueError("Target must contain only 0 (paid) and 1 (default)")
    return data.reset_index(drop=True)


class WoEEncoder:
    """Train-only quantile/categorical binning with smoothed WoE and IV.

    WoE is ``ln(good share / bad share)`` (good = non-default, bad = default).
    Numerical cut points, rare-category pooling, and WoE maps are learned only
    from the training partition. Unseen categories receive WoE 0 at scoring time.
    """

    def __init__(
        self,
        categorical_columns: list[str],
        max_bins: int = 5,
        min_category_count: int = 30,
        smoothing: float = 0.5,
    ) -> None:
        self.categorical_columns = list(categorical_columns)
        self.max_bins = max_bins
        self.min_category_count = min_category_count
        self.smoothing = smoothing
        self.numeric_edges_: dict[str, np.ndarray] = {}
        self.rare_categories_: dict[str, set[str]] = {}
        self.woe_maps_: dict[str, dict[object, float]] = {}
        self.iv_table_: pd.DataFrame | None = None
        self.feature_names_in_: list[str] = []

    def _bin_numeric(self, column: str, values: pd.Series) -> pd.Series:
        edges = self.numeric_edges_[column]
        numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
        bins = np.searchsorted(edges, numeric, side="left")
        return pd.Series(bins, index=values.index, dtype="int64")

    def _binned(self, column: str, values: pd.Series) -> pd.Series:
        if column in self.categorical_columns:
            categories = values.astype("string").fillna("__MISSING__").astype(str)
            rare = self.rare_categories_[column]
            categories = categories.where(~categories.isin(rare), "__OTHER__")
            mapping = self.woe_maps_[column]
            if "__OTHER__" in mapping:
                categories = categories.where(categories.isin(mapping), "__OTHER__")
            return categories
        return self._bin_numeric(column, values)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "WoEEncoder":
        y = pd.Series(y, index=X.index).astype(int)
        if set(y.unique()) != {0, 1}:
            raise ValueError("WoE fitting requires both target classes (0 and 1)")
        self.feature_names_in_ = list(X.columns)
        iv_rows: list[dict[str, object]] = []
        n_good = int((y == 0).sum())
        n_bad = int((y == 1).sum())

        for column in self.feature_names_in_:
            values = X[column]
            if column in self.categorical_columns:
                categories = values.astype("string").fillna("__MISSING__").astype(str)
                counts = categories.value_counts(dropna=False)
                rare = set(counts[counts < self.min_category_count].index.astype(str))
                self.rare_categories_[column] = rare
                bins = categories.where(~categories.isin(rare), "__OTHER__")
            else:
                numeric = pd.to_numeric(values, errors="coerce").astype(float)
                quantiles = np.linspace(0, 1, self.max_bins + 1)[1:-1]
                edges = np.unique(np.quantile(numeric.dropna(), quantiles))
                edges = edges[(edges > numeric.min()) & (edges < numeric.max())]
                self.numeric_edges_[column] = edges.astype(float)
                bins = self._bin_numeric(column, numeric)

            summary = pd.DataFrame({"bin": bins, "target": y})
            by_bin = summary.groupby("bin", observed=True)["target"].agg(
                bad="sum", total="size"
            )
            by_bin["good"] = by_bin["total"] - by_bin["bad"]
            bin_count = len(by_bin)
            good_share = (by_bin["good"] + self.smoothing) / (
                n_good + self.smoothing * bin_count
            )
            bad_share = (by_bin["bad"] + self.smoothing) / (
                n_bad + self.smoothing * bin_count
            )
            woe = np.log(good_share / bad_share)
            iv = float(((good_share - bad_share) * woe).sum())
            self.woe_maps_[column] = {
                key: float(value) for key, value in woe.items()
            }
            iv_rows.append(
                {
                    "feature": column,
                    "iv": iv,
                    "bins": bin_count,
                    "train_missing_pct": float(values.isna().mean()),
                }
            )

        self.iv_table_ = pd.DataFrame(iv_rows).sort_values(
            "iv", ascending=False, ignore_index=True
        )
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        if self.iv_table_ is None:
            raise RuntimeError("Call fit before transform")
        transformed: dict[str, pd.Series] = {}
        for column in self.feature_names_in_:
            bins = self._binned(column, X[column])
            transformed[column] = bins.map(self.woe_maps_[column]).fillna(0.0)
        return pd.DataFrame(transformed, index=X.index, dtype=float)

    def bin_labels(self, column: str) -> dict[object, str]:
        """Return readable bin labels keyed like the fitted WoE map."""
        if column in self.categorical_columns:
            return {key: str(key) for key in self.woe_maps_[column]}
        edges = self.numeric_edges_[column]
        boundaries = [-np.inf, *edges.tolist(), np.inf]
        labels: dict[object, str] = {}
        for index in range(len(boundaries) - 1):
            low, high = boundaries[index : index + 2]
            low_text = "-inf" if np.isneginf(low) else f"{low:,.1f}"
            high_text = "+inf" if np.isposinf(high) else f"{high:,.1f}"
            labels[index] = f"({low_text}, {high_text}]"
        return labels


def ks_statistic(y_true: pd.Series | np.ndarray, probability: np.ndarray) -> float:
    """Maximum separation between the good and bad cumulative distributions."""
    fpr, tpr, _ = roc_curve(y_true, probability)
    return float(np.max(tpr - fpr))


def score_from_probability(
    probability: np.ndarray | pd.Series,
    base_score: int = 600,
    base_good_odds: float = 50.0,
    points_to_double_odds: int = 20,
) -> np.ndarray:
    """Convert default probability to a score where higher means lower risk."""
    probability = np.clip(np.asarray(probability, dtype=float), 1e-8, 1 - 1e-8)
    factor = points_to_double_odds / np.log(2)
    good_log_odds = np.log((1 - probability) / probability)
    return base_score + factor * (good_log_odds - np.log(base_good_odds))


def build_scorecard(
    model,
    encoder: WoEEncoder,
    selected_features: list[str],
    base_score: int = 600,
    base_good_odds: float = 50.0,
    points_to_double_odds: int = 20,
) -> pd.DataFrame:
    """Create additive scorecard points from a fitted logistic/WoE model."""
    factor = points_to_double_odds / np.log(2)
    coefficients = dict(zip(selected_features, model.coef_[0], strict=True))
    base_points = base_score - factor * (
        float(model.intercept_[0]) + np.log(base_good_odds)
    )
    rows: list[dict[str, object]] = [
        {
            "feature": "BASE",
            "bin": "Intercept and base good:bad odds",
            "woe": np.nan,
            "coefficient": np.nan,
            "points": float(base_points),
        }
    ]
    for feature in selected_features:
        labels = encoder.bin_labels(feature)
        for bin_key, woe in encoder.woe_maps_[feature].items():
            rows.append(
                {
                    "feature": feature,
                    "bin": labels[bin_key],
                    "woe": float(woe),
                    "coefficient": float(coefficients[feature]),
                    "points": float(-factor * coefficients[feature] * woe),
                }
            )
    return pd.DataFrame(rows)


def approval_policy_table(
    y_true: pd.Series | np.ndarray,
    probability: np.ndarray | pd.Series,
    thresholds: list[float],
) -> pd.DataFrame:
    """Summarise approval coverage and realised default trade-offs."""
    y_true = np.asarray(y_true, dtype=int)
    probability = np.asarray(probability, dtype=float)
    total_bad = int(y_true.sum())
    rows = []
    for threshold in thresholds:
        approved = probability <= threshold
        approved_count = int(approved.sum())
        approved_bad = int(y_true[approved].sum())
        rows.append(
            {
                "PD approval threshold": threshold,
                "approval rate": float(approved.mean()),
                "bad rate among approved": (
                    approved_bad / approved_count if approved_count else np.nan
                ),
                "share of all defaults approved": (
                    approved_bad / total_bad if total_bad else np.nan
                ),
                "approved accounts": approved_count,
            }
        )
    return pd.DataFrame(rows)
