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
        artifact_path = PROJECT_ROOT / "models" / "credit_default_scorecard.joblib"
        cls.bundle = joblib.load(artifact_path)

    def test_saved_bundle_scores_new_rows(self) -> None:
        encoder = self.bundle["encoder"]
        features = list(encoder.feature_names_in_)
        applicants = pd.DataFrame(
            [{feature: 0 for feature in features}, {feature: 1 for feature in features}],
            index=["applicant-a", "applicant-b"],
        )
        results = score_new_applicants(applicants, **{
            "encoder": encoder,
            "model": self.bundle["model"],
            "selected_features": self.bundle["selected_features"],
            "base_score": self.bundle["base_score"],
            "base_good_odds": self.bundle["base_good_odds"],
            "points_to_double_odds": self.bundle["points_to_double_odds"],
        })

        expected_pd = self.bundle["model"].predict_proba(
            encoder.transform(applicants[features])[list(self.bundle["selected_features"])]
        )[:, 1]
        np.testing.assert_allclose(results["probability_of_default"], expected_pd)
        self.assertEqual(results.index.tolist(), applicants.index.tolist())
        self.assertTrue(results["credit_score"].between(0, 1_000).all())

    def test_missing_required_field_is_reported(self) -> None:
        encoder = self.bundle["encoder"]
        features = list(encoder.feature_names_in_)
        applicants = pd.DataFrame([{feature: 0 for feature in features[:-1]}])
        with self.assertRaisesRegex(ValueError, "Missing required applicant fields"):
            score_new_applicants(
                applicants,
                encoder,
                self.bundle["model"],
                list(self.bundle["selected_features"]),
            )

    def test_missing_or_non_numeric_value_is_rejected(self) -> None:
        encoder = self.bundle["encoder"]
        features = list(encoder.feature_names_in_)
        applicants = pd.DataFrame([{feature: 0 for feature in features}])
        applicants[features[0]] = pd.Series(["not-a-number"], dtype="object")
        with self.assertRaisesRegex(ValueError, "non-numeric applicant values"):
            score_new_applicants(
                applicants,
                encoder,
                self.bundle["model"],
                list(self.bundle["selected_features"]),
            )


if __name__ == "__main__":
    unittest.main()
