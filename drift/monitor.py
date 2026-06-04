"""
Drift Monitor Service
---------------------
Runs as a background thread inside the FastAPI process.
- Receives incoming prediction records via an in-memory queue
- Runs drift checks every CHECK_INTERVAL_SECONDS
- Exposes /drift/status and /drift/report endpoints
- Emits Prometheus metrics for drift score and alert status
"""

import json
import logging
import os
import queue
import threading
import time
from typing import Optional

import numpy as np
import pandas as pd
from prometheus_client import Counter, Gauge

from drift.detector import DriftDetector, DriftReport

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
CHECK_INTERVAL_SECONDS = int(os.getenv("DRIFT_CHECK_INTERVAL", "120"))   # every 2 min
BASELINE_CSV_PATH      = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "Loan_default.csv"
)
FEATURE_META_PATH      = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "artifacts", "feature_meta.json"
)

# ── Prometheus metrics ────────────────────────────────────────────────────────
DRIFT_SCORE = Gauge(
    "loan_drift_mean_psi",
    "Mean PSI score across numerical features in the current window"
)
DRIFT_ALERT = Gauge(
    "loan_drift_alert_active",
    "1 if drift is at critical level, 0 otherwise"
)
DRIFT_CHECKS_TOTAL = Counter(
    "loan_drift_checks_total",
    "Total number of drift checks run",
    ["status"]
)
DRIFT_WINDOW_SIZE = Gauge(
    "loan_drift_window_size",
    "Number of records in the current drift detection window"
)


# ── Drift Monitor ─────────────────────────────────────────────────────────────
class DriftMonitor:
    """
    Singleton service that wraps DriftDetector with:
    - A thread-safe queue for receiving records from the predict endpoint
    - A background scheduler thread
    - Latest report storage for API endpoints
    """

    def __init__(self):
        self._detector:      Optional[DriftDetector] = None
        self._latest_report: Optional[DriftReport]   = None
        self._record_queue:  queue.Queue              = queue.Queue(maxsize=10_000)
        self._lock           = threading.Lock()
        self._thread:        Optional[threading.Thread] = None
        self._running        = False

    def start(self):
        """Load baseline and start background monitoring thread."""
        try:
            with open(FEATURE_META_PATH) as f:
                meta = json.load(f)
            num_cols = meta["num_cols"]
            cat_cols = meta["cat_cols"]

            if os.path.exists(BASELINE_CSV_PATH):
                baseline_df = pd.read_csv(BASELINE_CSV_PATH)
                logger.info(f"Loaded baseline: {len(baseline_df)} rows")
            else:
                # Minimal synthetic baseline if CSV not present (e.g. in CI)
                logger.warning("Baseline CSV not found — using synthetic baseline.")
                baseline_df = _synthetic_baseline(num_cols, cat_cols)

            self._detector = DriftDetector(baseline_df, num_cols, cat_cols, window_size=500)
            self._running  = True
            self._thread   = threading.Thread(
                target=self._run_loop, daemon=True, name="drift-monitor"
            )
            self._thread.start()
            logger.info(f"Drift monitor started (check interval: {CHECK_INTERVAL_SECONDS}s)")

        except Exception as e:
            logger.error(f"Drift monitor failed to start: {e}")

    def stop(self):
        self._running = False

    def push_record(self, record: dict):
        """Called from /predict endpoint — non-blocking."""
        try:
            self._record_queue.put_nowait(record)
        except queue.Full:
            pass   # drop silently — drift monitoring is best-effort

    def get_latest_report(self) -> Optional[DriftReport]:
        with self._lock:
            return self._latest_report

    def _run_loop(self):
        while self._running:
            time.sleep(CHECK_INTERVAL_SECONDS)
            self._drain_queue()
            self._run_check()

    def _drain_queue(self):
        """Move all queued records into the detector buffer."""
        if not self._detector:
            return
        records = []
        while not self._record_queue.empty():
            try:
                records.append(self._record_queue.get_nowait())
            except queue.Empty:
                break
        if records:
            self._detector.add_batch(pd.DataFrame(records))
            DRIFT_WINDOW_SIZE.set(len(self._detector.buffer))

    def _run_check(self):
        if not self._detector:
            return
        try:
            report = self._detector.check()
            if report:
                with self._lock:
                    self._latest_report = report

                # Update Prometheus metrics
                psi_scores = [r.score for r in report.feature_results if r.method == "psi"]
                if psi_scores:
                    DRIFT_SCORE.set(sum(psi_scores) / len(psi_scores))

                DRIFT_ALERT.set(1 if report.overall_status == "critical" else 0)
                DRIFT_CHECKS_TOTAL.labels(status=report.overall_status).inc()

        except Exception as e:
            logger.error(f"Drift check failed: {e}")


# ── Synthetic baseline fallback ───────────────────────────────────────────────
def _synthetic_baseline(num_cols: list, cat_cols: list) -> pd.DataFrame:
    """Generates a minimal synthetic baseline when CSV is absent (CI/test mode)."""
    n = 1000
    data = {
        "age":              np.random.randint(20, 70, n),
        "income":           np.random.normal(60000, 20000, n),
        "loan_amount":      np.random.normal(25000, 10000, n),
        "credit_score":     np.random.randint(550, 800, n),
        "months_employed":  np.random.randint(0, 120, n),
        "num_credit_lines": np.random.randint(1, 10, n),
        "interest_rate":    np.random.uniform(3, 20, n),
        "loan_term":        np.random.choice([12, 24, 36, 48, 60], n),
        "dti_ratio":        np.random.uniform(0.1, 0.6, n),
        "education":        np.random.choice(["High School", "Bachelor", "Master", "Phd"], n),
        "employment_type":  np.random.choice(["Full-Time", "Part-Time", "Self-Employed", "Unemployed"], n),
        "marital_status":   np.random.choice(["Single", "Married", "Divorced"], n),
        "has_mortgage":     np.random.choice(["Yes", "No"], n),
        "has_dependents":   np.random.choice(["Yes", "No"], n),
        "loan_purpose":     np.random.choice(["Home", "Auto", "Education", "Business", "Other"], n),
        "has_co_signer":    np.random.choice(["Yes", "No"], n),
    }
    return pd.DataFrame(data)


# ── Singleton instance ────────────────────────────────────────────────────────
drift_monitor = DriftMonitor()