"""
Unit tests for the drift detector — no model loading required.
"""

import numpy as np
import pandas as pd
import pytest

from drift.detector import DriftDetector, _compute_psi

NUM_COLS = ["age", "income", "loan_amount", "credit_score",
            "months_employed", "interest_rate", "dti_ratio"]
CAT_COLS = ["education", "employment_type", "loan_purpose"]


def _make_baseline(n=1000) -> pd.DataFrame:
    return pd.DataFrame({
        "age":             np.random.randint(25, 65, n),
        "income":          np.random.normal(60000, 15000, n),
        "loan_amount":     np.random.normal(25000, 8000, n),
        "credit_score":    np.random.randint(580, 780, n),
        "months_employed": np.random.randint(6, 120, n),
        "interest_rate":   np.random.uniform(4, 15, n),
        "dti_ratio":       np.random.uniform(0.1, 0.5, n),
        "education":       np.random.choice(["Bachelor", "Master", "High School", "Phd"], n),
        "employment_type": np.random.choice(["Full-Time", "Part-Time", "Self-Employed"], n),
        "loan_purpose":    np.random.choice(["Home", "Auto", "Education", "Business"], n),
    })


class TestPSI:
    def test_identical_distributions_give_low_psi(self):
        np.random.seed(42)
        arr = np.random.normal(0, 1, 1000)
        psi = _compute_psi(arr, arr + np.random.normal(0, 0.01, 1000))
        assert psi < 0.05

    def test_shifted_distribution_gives_high_psi(self):
        np.random.seed(42)
        baseline = np.random.normal(0, 1, 1000)
        shifted  = np.random.normal(5, 1, 1000)  # major shift
        psi = _compute_psi(baseline, shifted)
        assert psi > 0.20

    def test_psi_is_non_negative(self):
        np.random.seed(0)
        a = np.random.uniform(0, 1, 500)
        b = np.random.uniform(0, 2, 500)
        assert _compute_psi(a, b) >= 0


class TestDriftDetector:
    def setup_method(self):
        np.random.seed(42)
        self.baseline = _make_baseline(1000)
        self.detector = DriftDetector(self.baseline, NUM_COLS, CAT_COLS, window_size=200)

    def test_check_returns_none_when_buffer_empty(self):
        assert self.detector.check() is None

    def test_check_returns_none_when_buffer_too_small(self):
        self.detector.add_batch(_make_baseline(30))
        assert self.detector.check() is None

    def test_check_returns_report_with_enough_data(self):
        self.detector.add_batch(_make_baseline(100))
        report = self.detector.check()
        assert report is not None

    def test_stable_data_gives_stable_status(self):
        np.random.seed(42)
        # Add data from same distribution as baseline
        self.detector.add_batch(_make_baseline(200))
        report = self.detector.check()
        assert report is not None
        assert report.overall_status in ("stable", "warning")  # should not be critical

    def test_drifted_data_detected(self):
        np.random.seed(42)
        drifted = _make_baseline(200)
        # Severely shift credit_score and income
        drifted["credit_score"] = np.random.randint(300, 400, 200)
        drifted["income"]       = np.random.normal(200000, 5000, 200)
        self.detector.add_batch(drifted)
        report = self.detector.check()
        assert report is not None
        assert report.overall_status in ("warning", "critical")

    def test_report_has_feature_results(self):
        self.detector.add_batch(_make_baseline(100))
        report = self.detector.check()
        assert len(report.feature_results) > 0

    def test_buffer_respects_window_size(self):
        self.detector.add_batch(_make_baseline(300))   # > window_size of 200
        assert len(self.detector.buffer) <= 200

    def test_add_single_record(self):
        record = self.baseline.iloc[0].to_dict()
        self.detector.add_record(record)
        assert len(self.detector.buffer) == 1

    def test_page_hinkley_resets_after_alert(self):
        # Feed many high-PSI batches to trigger PH alert
        for _ in range(20):
            drifted = _make_baseline(50)
            drifted["credit_score"] = np.random.randint(300, 350, 50)
            drifted["income"] = np.random.normal(500000, 1000, 50)
            self.detector.add_batch(drifted)
            self.detector.check()
        # After multiple alerts, detector should still function
        report = self.detector.check()
        assert report is not None
