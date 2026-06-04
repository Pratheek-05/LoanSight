"""
Loan Approval Prediction API
FastAPI wrapper around the trained XGBoost model.
Endpoints:
  GET  /health        - liveness check
  GET  /ready         - readiness check (model loaded)
  POST /predict       - single prediction with SHAP explanation
  POST /predict/batch - batch predictions (up to 100 rows)
  GET  /metrics       - Prometheus metrics (scraped by Prometheus)
"""

import os
import time
import json
import logging
from contextlib import asynccontextmanager

import joblib
import numpy as np
import pandas as pd
import shap
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from prometheus_client import (
    Counter, Histogram, Gauge,
    generate_latest, CONTENT_TYPE_LATEST
)
from fastapi.responses import Response

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ── Prometheus metrics ────────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "loan_api_requests_total",
    "Total prediction requests",
    ["endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "loan_api_request_duration_seconds",
    "Request latency in seconds",
    ["endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0]
)
PREDICTION_COUNTER = Counter(
    "loan_predictions_total",
    "Total predictions made",
    ["result"]          # approved / rejected
)
CONFIDENCE_HISTOGRAM = Histogram(
    "loan_prediction_confidence",
    "Distribution of model confidence scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)
MODEL_LOADED = Gauge(
    "loan_model_loaded",
    "1 if model is loaded and ready, 0 otherwise"
)

# ── Artifact paths ────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS  = os.path.join(BASE_DIR, "artifacts")

# ── Global model state ────────────────────────────────────────────────────────
model_state: dict = {}


def load_model_artifacts():
    """Load model, preprocessor, and feature metadata."""
    logger.info("Loading model artifacts...")
    preprocessor = joblib.load(os.path.join(ARTIFACTS, "preprocessor.joblib"))
    model        = joblib.load(os.path.join(ARTIFACTS, "best_model.joblib"))
    with open(os.path.join(ARTIFACTS, "feature_meta.json")) as f:
        meta = json.load(f)

    # Build SHAP explainer (TreeExplainer is fast for XGBoost)
    explainer = shap.TreeExplainer(model)

    model_state["preprocessor"] = preprocessor
    model_state["model"]        = model
    model_state["meta"]         = meta
    model_state["explainer"]    = explainer
    MODEL_LOADED.set(1)
    logger.info("Model artifacts loaded successfully.")


# ── App lifespan ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model_artifacts()
    yield
    MODEL_LOADED.set(0)
    logger.info("API shutting down.")


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Loan Approval Prediction API",
    description=(
        "Production-grade REST API for AI-driven loan risk assessment. "
        "Uses XGBoost + SMOTE with SHAP explainability."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response schemas ────────────────────────────────────────────────
class LoanApplication(BaseModel):
    # Numerical features
    age:               int   = Field(..., ge=18, le=100,      example=35,     description="Applicant age in years")
    income:            float = Field(..., ge=0,               example=55000,  description="Annual income in USD")
    loan_amount:       float = Field(..., ge=1000,            example=25000,  description="Requested loan amount in USD")
    credit_score:      int   = Field(..., ge=300, le=850,     example=680,    description="FICO credit score")
    months_employed:   int   = Field(..., ge=0,               example=48,     description="Months at current employer")
    num_credit_lines:  int   = Field(..., ge=0,               example=4,      description="Number of open credit lines")
    interest_rate:     float = Field(..., ge=0.0, le=100.0,   example=8.5,    description="Interest rate percentage")
    loan_term:         int   = Field(...,                     example=36,     description="Loan term in months")
    dti_ratio:         float = Field(..., ge=0.0, le=1.0,     example=0.30,   description="Debt-to-income ratio (0–1)")

    # Categorical features
    education:         str   = Field(..., example="Bachelor",    description="Highest education level")
    employment_type:   str   = Field(..., example="Full-Time",   description="Employment type")
    marital_status:    str   = Field(..., example="Single",      description="Marital status")
    has_mortgage:      str   = Field(..., example="No",          description="Whether applicant has a mortgage")
    has_dependents:    str   = Field(..., example="No",          description="Whether applicant has dependents")
    loan_purpose:      str   = Field(..., example="Home",        description="Purpose of the loan")
    has_co_signer:     str   = Field(..., example="No",          description="Whether loan has a co-signer")

    @validator("education")
    def validate_education(cls, v):
        valid = {"High School", "Bachelor", "Master", "Phd"}
        if v not in valid:
            raise ValueError(f"education must be one of {valid}")
        return v

    @validator("employment_type")
    def validate_employment(cls, v):
        valid = {"Full-Time", "Part-Time", "Self-Employed", "Unemployed"}
        if v not in valid:
            raise ValueError(f"employment_type must be one of {valid}")
        return v

    @validator("marital_status")
    def validate_marital(cls, v):
        valid = {"Single", "Married", "Divorced"}
        if v not in valid:
            raise ValueError(f"marital_status must be one of {valid}")
        return v

    @validator("has_mortgage", "has_dependents", "has_co_signer")
    def validate_yes_no(cls, v):
        if v not in {"Yes", "No"}:
            raise ValueError("Must be 'Yes' or 'No'")
        return v

    @validator("loan_purpose")
    def validate_purpose(cls, v):
        valid = {"Home", "Auto", "Education", "Business", "Other"}
        if v not in valid:
            raise ValueError(f"loan_purpose must be one of {valid}")
        return v

    @validator("loan_term")
    def validate_term(cls, v):
        valid = {12, 24, 36, 48, 60}
        if v not in valid:
            raise ValueError(f"loan_term must be one of {valid}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "age": 35, "income": 55000, "loan_amount": 25000,
                "credit_score": 680, "months_employed": 48,
                "num_credit_lines": 4, "interest_rate": 8.5,
                "loan_term": 36, "dti_ratio": 0.30,
                "education": "Bachelor", "employment_type": "Full-Time",
                "marital_status": "Single", "has_mortgage": "No",
                "has_dependents": "No", "loan_purpose": "Home",
                "has_co_signer": "No"
            }
        }


class SHAPExplanation(BaseModel):
    feature:    str
    shap_value: float
    direction:  str   # "increases_risk" | "decreases_risk"


class PredictionResponse(BaseModel):
    decision:           str           # "Approved" | "Rejected"
    default_probability: float        # probability of default (0–1)
    approval_confidence: float        # probability of no default (0–1)
    risk_level:         str           # "Low" | "Medium" | "High"
    risk_score:         int           # 0–100
    top_risk_factors:   list[SHAPExplanation]
    model_version:      str
    inference_time_ms:  float


class BatchRequest(BaseModel):
    applications: list[LoanApplication] = Field(..., max_items=100)


class BatchResponse(BaseModel):
    predictions:     list[PredictionResponse]
    total:           int
    approved_count:  int
    rejected_count:  int
    avg_risk_score:  float


# ── Helper: run inference on a DataFrame ─────────────────────────────────────
def run_inference(df: pd.DataFrame) -> list[PredictionResponse]:
    preprocessor = model_state["preprocessor"]
    model        = model_state["model"]
    explainer    = model_state["explainer"]

    t0    = time.perf_counter()
    X_enc = preprocessor.transform(df)
    preds = model.predict(X_enc)
    probas = model.predict_proba(X_enc)

    # SHAP values for every row
    shap_values = explainer.shap_values(X_enc)
    # For binary XGBoost, shap_values is shape (n, features) for class 1 (default)
    if isinstance(shap_values, list):
        sv = shap_values[1]   # class 1 = default
    else:
        sv = shap_values

    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Feature names after preprocessing
    try:
        feature_names = preprocessor.get_feature_names_out()
    except Exception:
        feature_names = [f"f{i}" for i in range(X_enc.shape[1])]

    results = []
    for i in range(len(preds)):
        default_prob  = float(probas[i][1])
        approval_prob = float(probas[i][0])
        risk_score    = int(round(default_prob * 100))
        risk_level    = "Low" if risk_score < 30 else ("Medium" if risk_score < 60 else "High")
        decision      = "Approved" if preds[i] == 0 else "Rejected"

        # Top 5 SHAP contributors
        row_shap   = sv[i]
        top_idx    = np.argsort(np.abs(row_shap))[::-1][:5]
        top_factors = []
        for idx in top_idx:
            fname = feature_names[idx] if idx < len(feature_names) else f"f{idx}"
            sval  = float(row_shap[idx])
            top_factors.append(SHAPExplanation(
                feature    = fname,
                shap_value = round(sval, 4),
                direction  = "increases_risk" if sval > 0 else "decreases_risk"
            ))

        results.append(PredictionResponse(
            decision            = decision,
            default_probability = round(default_prob, 4),
            approval_confidence = round(approval_prob, 4),
            risk_level          = risk_level,
            risk_score          = risk_score,
            top_risk_factors    = top_factors,
            model_version       = "xgboost-v1.0",
            inference_time_ms   = round(elapsed_ms / len(preds), 3)
        ))

    return results


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["Ops"])
def health():
    """Liveness probe — always returns 200 if process is running."""
    return {"status": "ok"}


@app.get("/ready", tags=["Ops"])
def ready():
    """Readiness probe — returns 200 only when model is loaded."""
    if not model_state.get("model"):
        raise HTTPException(status_code=503, detail="Model not loaded yet")
    return {"status": "ready", "model": "xgboost-v1.0"}


@app.post("/predict", response_model=PredictionResponse, tags=["Prediction"])
def predict(application: LoanApplication, request: Request):
    """
    Run loan approval prediction on a single application.
    Returns decision, risk score, confidence, and top SHAP explanations.
    """
    start = time.perf_counter()
    try:
        df     = pd.DataFrame([application.model_dump()])
        result = run_inference(df)[0]
        REQUEST_COUNT.labels(endpoint="/predict", status="success").inc()
        PREDICTION_COUNTER.labels(result=result.decision.lower()).inc()
        CONFIDENCE_HISTOGRAM.observe(result.approval_confidence)
        return result
    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/predict", status="error").inc()
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        REQUEST_LATENCY.labels(endpoint="/predict").observe(
            time.perf_counter() - start
        )


@app.post("/predict/batch", response_model=BatchResponse, tags=["Prediction"])
def predict_batch(batch: BatchRequest):
    """
    Run predictions on a batch of up to 100 applications.
    Returns individual predictions plus aggregate statistics.
    """
    start = time.perf_counter()
    try:
        df      = pd.DataFrame([a.model_dump() for a in batch.applications])
        results = run_inference(df)
        approved = sum(1 for r in results if r.decision == "Approved")
        REQUEST_COUNT.labels(endpoint="/predict/batch", status="success").inc()
        return BatchResponse(
            predictions    = results,
            total          = len(results),
            approved_count = approved,
            rejected_count = len(results) - approved,
            avg_risk_score = round(sum(r.risk_score for r in results) / len(results), 1)
        )
    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/predict/batch", status="error").inc()
        logger.error(f"Batch prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        REQUEST_LATENCY.labels(endpoint="/predict/batch").observe(
            time.perf_counter() - start
        )


@app.get("/metrics", tags=["Ops"])
def metrics():
    """Prometheus metrics endpoint — scraped by Prometheus every 15s."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ── Drift monitoring integration ──────────────────────────────────────────────
# Import here so it doesn't break if drift module isn't present (CI resilience)
try:
    from drift.monitor import drift_monitor
    _drift_enabled = True
except ImportError:
    _drift_enabled = False
    logger.warning("Drift monitor not available — running without drift detection.")


# Patch lifespan to start/stop drift monitor
_original_lifespan = lifespan

from contextlib import asynccontextmanager as _acm

@_acm
async def lifespan(app):  # noqa: F811
    load_model_artifacts()
    if _drift_enabled:
        drift_monitor.start()
    yield
    if _drift_enabled:
        drift_monitor.stop()
    MODEL_LOADED.set(0)
    logger.info("API shutting down.")

app.router.lifespan_context = lifespan


# Patch /predict to push records to drift monitor
_original_predict = predict

@app.post("/predict", response_model=PredictionResponse, tags=["Prediction"], include_in_schema=False)
def predict(application: LoanApplication, request: Request):  # noqa: F811
    result = _original_predict(application, request)
    if _drift_enabled:
        drift_monitor.push_record(application.model_dump())
    return result


# ── Drift endpoints ───────────────────────────────────────────────────────────
@app.get("/drift/status", tags=["Drift"])
def drift_status():
    """
    Quick drift status check.
    Returns overall status and count of drifted features.
    """
    if not _drift_enabled:
        return {"status": "disabled"}
    report = drift_monitor.get_latest_report()
    if not report:
        return {"status": "pending", "message": "Insufficient data for drift check yet."}
    return {
        "status":           report.overall_status,
        "drifted_features": report.drifted_features,
        "window_size":      report.window_size,
        "timestamp":        report.timestamp,
        "recommendation":   report.recommendation,
    }


@app.get("/drift/report", tags=["Drift"])
def drift_report():
    """
    Full drift report — all features, scores, PSI values, Page-Hinkley alert.
    """
    if not _drift_enabled:
        return {"status": "disabled"}
    report = drift_monitor.get_latest_report()
    if not report:
        return {"status": "pending", "message": "Insufficient data for drift check yet."}
    return {
        "timestamp":           report.timestamp,
        "overall_status":      report.overall_status,
        "page_hinkley_alert":  report.page_hinkley_alert,
        "recommendation":      report.recommendation,
        "window_size":         report.window_size,
        "drifted_features":    report.drifted_features,
        "feature_results": [
            {
                "feature":       r.feature,
                "method":        r.method,
                "score":         r.score,
                "p_value":       r.p_value,
                "status":        r.status,
                "baseline_mean": r.baseline_mean,
                "current_mean":  r.current_mean,
            }
            for r in report.feature_results
        ],
    }