"""Small unit tests for data cleaning and scorecard inference."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.credit_risk import (  # noqa: E402
    TARGET,
    WoEEncoder,
    load_uci_dataset,
    score_new_applicants,
)


class DataCleaningTests(unittest.TestCase):
    def test_loader_drops_repeated_profile_after_removing_id(self) -> None:
        source = pd.DataFrame(
            {
                "ID": [1, 2, 3],
                "Limit Balance": [20_000, 20_000, 20_000],
                "Default Payment Next Month": [0, 0, 1],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory)
            (raw_dir / "default_of_credit_card_clients.xls").touch()
            with patch("src.credit_risk.pd.read_excel", return_value=source):
                cleaned = load_uci_dataset(raw_dir)

        self.assertEqual(len(cleaned), 2)
        self.assertNotIn("id", cleaned.columns)
        self.assertEqual(cleaned.attrs["duplicate_profiles_removed"], 1)
        self.assertEqual(set(cleaned[TARGET]), {0, 1})


class ScorecardInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rng = np.random.default_rng(7)
        X = pd.DataFrame(
            {
                "limit_bal": rng.choice([20_000, 50_000, 100_000, 200_000], 160),
                "pay_0": rng.choice([-1, 0, 1, 2], 160),
                "pay_amt1": rng.choice([0, 500, 1_500, 5_000], 160),
            }
        )
        y = ((X["pay_0"] >= 1) | ((X["limit_bal"] <= 50_000) & (X["pay_amt1"] <= 500))).astype(int)
        cls.X, cls.y = X, y
        cls.encoder = WoEEncoder(
            categorical_columns=["pay_0"], max_bins=4, min_category_count=1
        ).fit(X, y)
        cls.selected_features = ["pay_0", "limit_bal", "pay_amt1"]
        cls.model = LogisticRegression(max_iter=1_000).fit(
            cls.encoder.transform(X)[cls.selected_features], y
        )
        cls.bundle = {
            "encoder": cls.encoder,
            "model": cls.model,
            "selected_features": tuple(cls.selected_features),
            "base_score": 500,
            "base_good_odds": 3.52,
            "points_to_double_odds": 20,
        }

    def test_saved_bundle_scores_new_rows(self) -> None:
        features = list(self.encoder.feature_names_in_)
        applicants = pd.DataFrame(
            [
                {"limit_bal": 20_000, "pay_0": 2, "pay_amt1": 0},
                {"limit_bal": 100_000, "pay_0": -1, "pay_amt1": 5_000},
            ],
            index=["applicant-a", "applicant-b"],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scorecard.joblib"
            joblib.dump(self.bundle, path)
            bundle = joblib.load(path)
        results = score_new_applicants(applicants, **bundle)

        expected_pd = bundle["model"].predict_proba(
            bundle["encoder"].transform(applicants[features])[list(bundle["selected_features"])]
        )[:, 1]
        np.testing.assert_allclose(results["probability_of_default"], expected_pd)
        self.assertEqual(results.index.tolist(), applicants.index.tolist())
        self.assertTrue(results["credit_score"].between(0, 1_000).all())

    def test_missing_required_field_is_reported(self) -> None:
        applicants = pd.DataFrame([{"limit_bal": 20_000, "pay_0": 0}])
        with self.assertRaisesRegex(ValueError, "Missing required applicant fields"):
            score_new_applicants(
                applicants, self.encoder, self.model, self.selected_features
            )

    def test_only_selected_fields_are_required(self) -> None:
        applicants = pd.DataFrame(
            [{"pay_0": 0, "pay_amt1": 1_500}], index=["applicant-c"]
        )
        subset = ["pay_0", "pay_amt1"]
        model = LogisticRegression(max_iter=1_000).fit(
            self.encoder.transform(self.X, columns=subset), self.y
        )
        results = score_new_applicants(applicants, self.encoder, model, subset)
        self.assertEqual(results.index.tolist(), ["applicant-c"])
        self.assertTrue(results["probability_of_default"].between(0, 1).all())

    def test_out_of_range_values_are_rejected(self) -> None:
        valid = {"limit_bal": 50_000, "pay_0": 0, "pay_amt1": 500}
        cases = {
            "pay_0": [10, -3, 1.5],
            "limit_bal": [0, -5_000],
            "pay_amt1": [-1],
        }
        for column, bad_values in cases.items():
            for bad_value in bad_values:
                with self.subTest(column=column, value=bad_value):
                    applicants = pd.DataFrame([{**valid, column: bad_value}])
                    with self.assertRaisesRegex(ValueError, f"Out-of-range applicant values: {column}"):
                        score_new_applicants(
                            applicants, self.encoder, self.model, self.selected_features
                        )

    def test_infinite_value_is_rejected(self) -> None:
        applicants = pd.DataFrame(
            [{"limit_bal": np.inf, "pay_0": 0, "pay_amt1": 500}]
        )
        with self.assertRaisesRegex(ValueError, "non-numeric applicant values"):
            score_new_applicants(
                applicants, self.encoder, self.model, self.selected_features
            )

    def test_missing_or_non_numeric_value_is_rejected(self) -> None:
        applicants = pd.DataFrame(
            [{"limit_bal": 20_000, "pay_0": 0, "pay_amt1": "not-a-number"}]
        )
        with self.assertRaisesRegex(ValueError, "non-numeric applicant values"):
            score_new_applicants(
                applicants, self.encoder, self.model, self.selected_features
            )


if __name__ == "__main__":
    unittest.main()
