"""
Concept Drift Detector for LoanSight AI
----------------------------------------
Watches incoming prediction request feature distributions and flags
when they diverge significantly from the training data baseline.

Methods used:
  - Numerical features  : Population Stability Index (PSI)
  - Categorical features: Chi-squared test
  - Overall alert       : Page-Hinkley test on rolling PSI score

This ties directly into the DRL concept drift detection work from
the NMIT Centre for Digital Transformation internship.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
PSI_WARNING_THRESHOLD  = 0.10   # PSI 0.10–0.20 = moderate drift
PSI_CRITICAL_THRESHOLD = 0.20   # PSI > 0.20    = significant drift
CHI2_P_VALUE_THRESHOLD = 0.05   # p < 0.05 = distribution has shifted
PAGE_HINKLEY_DELTA     = 0.005  # sensitivity (lower = more sensitive)
PAGE_HINKLEY_LAMBDA    = 50     # detection threshold


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class FeatureDriftResult:
    feature:        str
    method:         str        # "psi" | "chi2"
    score:          float
    p_value:        Optional[float]
    status:         str        # "stable" | "warning" | "critical"
    baseline_mean:  Optional[float] = None
    current_mean:   Optional[float] = None


@dataclass
class DriftReport:
    timestamp:          str
    window_size:        int
    overall_status:     str        # "stable" | "warning" | "critical"
    drifted_features:   list[str]
    feature_results:    list[FeatureDriftResult]
    page_hinkley_alert: bool
    recommendation:     str


@dataclass
class PageHinkleyState:
    """Tracks cumulative PSI for sequential change detection."""
    cumsum:    float = 0.0
    min_val:   float = float("inf")
    n:         int   = 0
    alert:     bool  = False


# ── PSI calculation ───────────────────────────────────────────────────────────
def _compute_psi(baseline: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """
    Population Stability Index.
    PSI = sum((current% - baseline%) * ln(current% / baseline%))
    """
    # Build bins from baseline
    breakpoints = np.percentile(baseline, np.linspace(0, 100, bins + 1))
    breakpoints = np.unique(breakpoints)
    if len(breakpoints) < 3:
        return 0.0

    baseline_counts = np.histogram(baseline, bins=breakpoints)[0]
    current_counts  = np.histogram(current,  bins=breakpoints)[0]

    # Avoid division by zero / log(0)
    baseline_pct = (baseline_counts + 0.0001) / len(baseline)
    current_pct  = (current_counts  + 0.0001) / len(current)

    psi = np.sum((current_pct - baseline_pct) * np.log(current_pct / baseline_pct))
    return float(psi)


# ── Main detector class ───────────────────────────────────────────────────────
class DriftDetector:
    """
    Monitors feature distributions in a rolling window against a baseline.

    Usage:
        detector = DriftDetector(baseline_df, num_cols, cat_cols)
        detector.add_batch(incoming_df)
        report = detector.check()
    """

    def __init__(
        self,
        baseline_df:  pd.DataFrame,
        num_cols:     list[str],
        cat_cols:     list[str],
        window_size:  int = 500,
    ):
        self.num_cols    = num_cols
        self.cat_cols    = cat_cols
        self.window_size = window_size
        self.buffer:     list[dict] = []
        self.ph_state    = PageHinkleyState()

        # Compute baseline stats once at init
        self.baseline_stats = self._compute_baseline_stats(baseline_df)
        logger.info(
            f"DriftDetector initialised | window={window_size} | "
            f"num_features={len(num_cols)} | cat_features={len(cat_cols)}"
        )

    def _compute_baseline_stats(self, df: pd.DataFrame) -> dict:
        stats_out = {}
        for col in self.num_cols:
            if col in df.columns:
                arr = df[col].dropna().values.astype(float)
                stats_out[col] = {"type": "numerical", "values": arr,
                                  "mean": float(arr.mean()), "std": float(arr.std())}
        for col in self.cat_cols:
            if col in df.columns:
                freq = df[col].value_counts(normalize=True).to_dict()
                stats_out[col] = {"type": "categorical", "freq": freq,
                                  "categories": list(freq.keys())}
        return stats_out

    def add_record(self, record: dict):
        """Add a single prediction request to the rolling buffer."""
        self.buffer.append(record)
        if len(self.buffer) > self.window_size:
            self.buffer.pop(0)

    def add_batch(self, df: pd.DataFrame):
        """Add a DataFrame of records to the buffer."""
        for _, row in df.iterrows():
            self.add_record(row.to_dict())

    def _page_hinkley_update(self, psi_score: float) -> bool:
        """
        Page-Hinkley test for sequential change detection on the PSI score.
        Returns True if a change point is detected.
        """
        self.ph_state.n      += 1
        self.ph_state.cumsum += psi_score - PAGE_HINKLEY_DELTA
        self.ph_state.min_val = min(self.ph_state.min_val, self.ph_state.cumsum)

        ph_val = self.ph_state.cumsum - self.ph_state.min_val
        if ph_val > PAGE_HINKLEY_LAMBDA:
            self.ph_state.alert  = True
            self.ph_state.cumsum = 0.0    # reset after alert
            self.ph_state.min_val = float("inf")
            return True
        return False

    def check(self) -> Optional[DriftReport]:
        """
        Run drift check on the current buffer vs baseline.
        Returns None if buffer is too small (< 50 records).
        """
        if len(self.buffer) < 50:
            logger.debug(f"Buffer too small ({len(self.buffer)}), skipping check.")
            return None

        current_df     = pd.DataFrame(self.buffer)
        feature_results: list[FeatureDriftResult] = []
        drifted         = []
        psi_scores      = []

        # ── Numerical: PSI ──
        for col in self.num_cols:
            if col not in self.baseline_stats or col not in current_df.columns:
                continue
            baseline_vals = self.baseline_stats[col]["values"]
            current_vals  = current_df[col].dropna().values.astype(float)
            if len(current_vals) < 10:
                continue

            psi   = _compute_psi(baseline_vals, current_vals)
            psi_scores.append(psi)
            status = ("critical" if psi > PSI_CRITICAL_THRESHOLD
                      else "warning" if psi > PSI_WARNING_THRESHOLD
                      else "stable")

            if status != "stable":
                drifted.append(col)

            feature_results.append(FeatureDriftResult(
                feature       = col,
                method        = "psi",
                score         = round(psi, 4),
                p_value       = None,
                status        = status,
                baseline_mean = round(self.baseline_stats[col]["mean"], 4),
                current_mean  = round(float(current_vals.mean()), 4),
            ))

        # ── Categorical: Chi-squared ──
        for col in self.cat_cols:
            if col not in self.baseline_stats or col not in current_df.columns:
                continue
            baseline_freq = self.baseline_stats[col]["freq"]
            categories    = self.baseline_stats[col]["categories"]
            current_freq  = current_df[col].value_counts(normalize=True).to_dict()

            # Align categories
            baseline_counts = np.array([baseline_freq.get(c, 1e-6) for c in categories])
            current_counts  = np.array([current_freq.get(c, 1e-6) for c in categories])

            # Scale to counts for chi2
            n          = len(current_df)
            obs        = current_counts  * n
            exp        = baseline_counts * n
            chi2, pval = stats.chisquare(obs, f_exp=exp)
            status     = "critical" if pval < CHI2_P_VALUE_THRESHOLD else "stable"

            if status != "stable":
                drifted.append(col)
                psi_scores.append(0.25)   # treat as high PSI for PH test

            feature_results.append(FeatureDriftResult(
                feature  = col,
                method   = "chi2",
                score    = round(float(chi2), 4),
                p_value  = round(float(pval), 4),
                status   = status,
            ))

        # ── Page-Hinkley on mean PSI ──
        mean_psi = float(np.mean(psi_scores)) if psi_scores else 0.0
        ph_alert = self._page_hinkley_update(mean_psi)

        # ── Overall status ──
        critical_count = sum(1 for r in feature_results if r.status == "critical")
        warning_count  = sum(1 for r in feature_results if r.status == "warning")
        if critical_count > 0 or ph_alert:
            overall = "critical"
        elif warning_count > 0:
            overall = "warning"
        else:
            overall = "stable"

        recommendation = {
            "stable":   "No action needed. Model is performing within expected parameters.",
            "warning":  "Monitor closely. Consider scheduling a model evaluation.",
            "critical": "⚠️  Significant drift detected. Trigger model retraining pipeline.",
        }[overall]

        from datetime import datetime, timezone
        report = DriftReport(
            timestamp          = datetime.now(timezone.utc).isoformat(),
            window_size        = len(self.buffer),
            overall_status     = overall,
            drifted_features   = drifted,
            feature_results    = feature_results,
            page_hinkley_alert = ph_alert,
            recommendation     = recommendation,
        )

        logger.info(
            f"Drift check | status={overall} | drifted={drifted} | "
            f"mean_psi={mean_psi:.4f} | ph_alert={ph_alert}"
        )
        return report