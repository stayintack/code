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

    if "id" in data.columns:
        # Remove the identifier before finding exact duplicate modeling rows;
        # otherwise unique IDs mask repeated feature/outcome profiles.
        data = data.drop_duplicates(subset=["id"], keep="first")
        data = data.drop(columns="id")

    duplicate_profiles_removed = int(data.duplicated().sum())
    data = data.drop_duplicates(keep="first").copy()

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
    data = data.reset_index(drop=True)
    data.attrs["duplicate_profiles_removed"] = duplicate_profiles_removed
    return data


class WoEEncoder:
    """Train-only monotonic binning with smoothed WoE and IV.

    WoE is ``ln(good share / bad share)`` (good = non-default, bad = default).
    Numerical cut points, repayment-status pooling, monotonic merges, and WoE
    maps are learned only from the training partition. Payment-status fields
    use three ordered groups: non-positive codes, one-month delay, and 2+ months.
    Unseen categories receive WoE 0 at scoring time.
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
        self.status_edges_: dict[str, np.ndarray] = {}
        self.status_bin_labels_: dict[str, dict[int, str]] = {}
        self.monotonic_directions_: dict[str, str] = {}
        self.rare_categories_: dict[str, set[str]] = {}
        self.woe_maps_: dict[str, dict[object, float]] = {}
        self.iv_table_: pd.DataFrame | None = None
        self.bin_table_: pd.DataFrame | None = None
        self.feature_names_in_: list[str] = []

    @staticmethod
    def _pava_blocks(
        counts: pd.DataFrame,
        *,
        increasing: bool,
        min_bin_count: int,
    ) -> list[dict[str, int]]:
        """Pool adjacent bins until event rates are monotonic and bins are large enough."""
        blocks: list[dict[str, int]] = []
        for index, row in counts.iterrows():
            blocks.append({
                "start": int(index),
                "end": int(index) + 1,
                "total": int(row["total"]),
                "bad": int(row["bad"]),
            })
            while len(blocks) >= 2:
                left, right = blocks[-2:]
                left_rate = left["bad"] / left["total"] if left["total"] else 0.0
                right_rate = right["bad"] / right["total"] if right["total"] else 0.0
                violates_order = left_rate > right_rate if increasing else left_rate < right_rate
                undersized = left["total"] < min_bin_count or right["total"] < min_bin_count
                if not (violates_order or undersized):
                    break
                blocks[-2:] = [{
                    "start": left["start"],
                    "end": right["end"],
                    "total": left["total"] + right["total"],
                    "bad": left["bad"] + right["bad"],
                }]
        return blocks

    @staticmethod
    def _status_group(values: pd.Series) -> pd.Series:
        numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
        groups = np.where(numeric <= 0, 0, np.where(numeric == 1, 1, 2))
        return pd.Series(groups, index=values.index, dtype="int64")

    def _bin_numeric(self, column: str, values: pd.Series) -> pd.Series:
        edges = self.numeric_edges_[column]
        numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
        bins = np.searchsorted(edges, numeric, side="left")
        return pd.Series(bins, index=values.index, dtype="int64")

    def _binned(self, column: str, values: pd.Series) -> pd.Series:
        if column in PAYMENT_STATUS_COLUMNS:
            groups = self._status_group(values).to_numpy()
            bins = np.searchsorted(self.status_edges_[column], groups, side="left")
            return pd.Series(bins, index=values.index, dtype="int64")
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
        bin_rows: list[dict[str, object]] = []
        status_group_names = [
            "Codes -2/-1/0 (no positive delay code)",
            "Code 1 (one month past due)",
            "Codes 2+ (two or more months past due)",
        ]

        for column in self.feature_names_in_:
            values = X[column]
            if column in PAYMENT_STATUS_COLUMNS:
                initial_bins = self._status_group(values)
                counts = (
                    pd.DataFrame({"bin": initial_bins, "target": y})
                    .groupby("bin", observed=True)["target"]
                    .agg(bad="sum", total="size")
                    .reindex(range(3), fill_value=0)
                )
                blocks = self._pava_blocks(
                    counts, increasing=True, min_bin_count=self.min_category_count
                )
                self.status_edges_[column] = np.asarray(
                    [block["end"] - 0.5 for block in blocks[:-1]], dtype=float
                )
                self.status_bin_labels_[column] = {
                    bin_index: " + ".join(status_group_names[block["start"]:block["end"]])
                    for bin_index, block in enumerate(blocks)
                }
                self.monotonic_directions_[column] = "increasing default rate by delay severity"
                bins = self._binned(column, values)
            elif column in self.categorical_columns:
                categories = values.astype("string").fillna("__MISSING__").astype(str)
                counts = categories.value_counts(dropna=False)
                rare = set(counts[counts < self.min_category_count].index.astype(str))
                self.rare_categories_[column] = rare
                bins = categories.where(~categories.isin(rare), "__OTHER__")
            else:
                numeric = pd.to_numeric(values, errors="coerce").astype(float)
                quantiles = np.linspace(0, 1, self.max_bins + 1)[1:-1]
                initial_edges = np.unique(np.quantile(numeric.dropna(), quantiles))
                initial_edges = initial_edges[(initial_edges > numeric.min()) & (initial_edges < numeric.max())]
                initial_bins = pd.Series(
                    np.searchsorted(initial_edges, numeric.to_numpy(dtype=float), side="left"),
                    index=values.index,
                    dtype="int64",
                )
                initial_bin_count = len(initial_edges) + 1
                counts = (
                    pd.DataFrame({"bin": initial_bins, "target": y})
                    .groupby("bin", observed=True)["target"]
                    .agg(bad="sum", total="size")
                    .reindex(range(initial_bin_count), fill_value=0)
                )
                rho = numeric.corr(y, method="spearman")
                increasing = bool(pd.isna(rho) or rho >= 0)
                blocks = self._pava_blocks(
                    counts, increasing=increasing, min_bin_count=self.min_category_count
                )
                self.numeric_edges_[column] = np.asarray(
                    [initial_edges[block["end"] - 1] for block in blocks[:-1]], dtype=float
                )
                self.monotonic_directions_[column] = (
                    "increasing default rate" if increasing else "decreasing default rate"
                )
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
            for key in by_bin.index:
                bin_rows.append({
                    "feature": column,
                    "bin": key,
                    "training_accounts": int(by_bin.loc[key, "total"]),
                    "training_bad_rate": float(by_bin.loc[key, "bad"] / by_bin.loc[key, "total"]),
                    "woe": float(woe.loc[key]),
                    "iv_contribution": float((good_share.loc[key] - bad_share.loc[key]) * woe.loc[key]),
                    "monotonic_direction": self.monotonic_directions_.get(column, "categorical"),
                })
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
        self.bin_table_ = pd.DataFrame(bin_rows)
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
        if column in PAYMENT_STATUS_COLUMNS:
            return self.status_bin_labels_[column]
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
    base_score: int = 500,
    base_good_odds: float = 3.52,
    points_to_double_odds: int = 20,
) -> np.ndarray:
    """Convert default probability to a score where higher means lower risk."""
    probability = np.clip(np.asarray(probability, dtype=float), 1e-8, 1 - 1e-8)
    factor = points_to_double_odds / np.log(2)
    good_log_odds = np.log((1 - probability) / probability)
    return base_score + factor * (good_log_odds - np.log(base_good_odds))


def score_new_applicants(
    applicants: pd.DataFrame,
    encoder: WoEEncoder,
    model,
    selected_features: list[str],
    *,
    base_score: int = 500,
    base_good_odds: float = 3.52,
    points_to_double_odds: int = 20,
) -> pd.DataFrame:
    """Return predicted default probabilities and integer scores for new rows.

    ``applicants`` must contain the raw behavior columns used to fit ``encoder``.
    Extra columns are ignored, so a client ID may be retained for joining results.
    """
    if not isinstance(applicants, pd.DataFrame):
        raise TypeError("applicants must be a pandas DataFrame")
    if applicants.empty:
        raise ValueError("applicants must contain at least one row")

    required = list(encoder.feature_names_in_)
    missing = [column for column in required if column not in applicants.columns]
    if missing:
        raise ValueError(f"Missing required applicant fields: {missing}")
    unknown_features = [feature for feature in selected_features if feature not in required]
    if unknown_features:
        raise ValueError(f"Selected model features were not fitted by the encoder: {unknown_features}")

    raw_features = applicants.loc[:, required].apply(pd.to_numeric, errors="coerce")
    if raw_features.isna().any().any():
        invalid = raw_features.columns[raw_features.isna().any()].tolist()
        raise ValueError(f"Missing or non-numeric applicant values in: {invalid}")

    woe_features = encoder.transform(raw_features).loc[:, selected_features]
    probability = model.predict_proba(woe_features)[:, 1]
    score = score_from_probability(
        probability,
        base_score=base_score,
        base_good_odds=base_good_odds,
        points_to_double_odds=points_to_double_odds,
    )
    return pd.DataFrame(
        {
            "probability_of_default": probability,
            "credit_score": np.rint(score).astype(int),
        },
        index=applicants.index,
    )


def build_scorecard(
    model,
    encoder: WoEEncoder,
    selected_features: list[str],
    base_score: int = 500,
    base_good_odds: float = 3.52,
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
        bin_stats = encoder.bin_table_.loc[encoder.bin_table_["feature"].eq(feature)].set_index("bin")
        for bin_key, woe in encoder.woe_maps_[feature].items():
            rows.append(
                {
                    "feature": feature,
                    "bin": labels[bin_key],
                    "woe": float(woe),
                    "coefficient": float(coefficients[feature]),
                    "points": float(-factor * coefficients[feature] * woe),
                    "training_accounts": int(bin_stats.loc[bin_key, "training_accounts"]),
                    "training_bad_rate": float(bin_stats.loc[bin_key, "training_bad_rate"]),
                    "iv_contribution": float(bin_stats.loc[bin_key, "iv_contribution"]),
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
