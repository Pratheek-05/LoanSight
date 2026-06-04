"""
Test suite for LoanSight AI — FastAPI prediction API
Run with: pytest tests/ -v
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

# ── Shared fixture ────────────────────────────────────────────────────────────
VALID_PAYLOAD = {
    "age": 35, "income": 55000, "loan_amount": 25000,
    "credit_score": 680, "months_employed": 48,
    "num_credit_lines": 4, "interest_rate": 8.5,
    "loan_term": 36, "dti_ratio": 0.30,
    "education": "Bachelor", "employment_type": "Full-Time",
    "marital_status": "Single", "has_mortgage": "No",
    "has_dependents": "No", "loan_purpose": "Home",
    "has_co_signer": "No"
}

HIGH_RISK_PAYLOAD = {
    "age": 22, "income": 18000, "loan_amount": 80000,
    "credit_score": 320, "months_employed": 2,
    "num_credit_lines": 12, "interest_rate": 24.5,
    "loan_term": 60, "dti_ratio": 0.92,
    "education": "High School", "employment_type": "Unemployed",
    "marital_status": "Single", "has_mortgage": "No",
    "has_dependents": "Yes", "loan_purpose": "Other",
    "has_co_signer": "No"
}


# ── Health & Readiness ────────────────────────────────────────────────────────
class TestOpsEndpoints:
    def test_health_returns_200(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_ready_returns_200_when_model_loaded(self):
        r = client.get("/ready")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_metrics_endpoint_returns_prometheus_format(self):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "loan_api_requests_total" in r.text


# ── Single Prediction ─────────────────────────────────────────────────────────
class TestPredictEndpoint:
    def test_valid_payload_returns_200(self):
        r = client.post("/predict", json=VALID_PAYLOAD)
        assert r.status_code == 200

    def test_response_has_required_fields(self):
        r = client.post("/predict", json=VALID_PAYLOAD)
        data = r.json()
        for field in ["decision", "default_probability", "approval_confidence",
                      "risk_level", "risk_score", "top_risk_factors", "model_version"]:
            assert field in data, f"Missing field: {field}"

    def test_decision_is_approved_or_rejected(self):
        r = client.post("/predict", json=VALID_PAYLOAD)
        assert r.json()["decision"] in ("Approved", "Rejected")

    def test_probabilities_sum_to_one(self):
        r = client.post("/predict", json=VALID_PAYLOAD)
        data = r.json()
        total = round(data["default_probability"] + data["approval_confidence"], 2)
        assert total == 1.0, f"Probabilities don't sum to 1: {total}"

    def test_risk_score_is_0_to_100(self):
        r = client.post("/predict", json=VALID_PAYLOAD)
        score = r.json()["risk_score"]
        assert 0 <= score <= 100

    def test_risk_level_is_valid(self):
        r = client.post("/predict", json=VALID_PAYLOAD)
        assert r.json()["risk_level"] in ("Low", "Medium", "High")

    def test_shap_explanations_returned(self):
        r = client.post("/predict", json=VALID_PAYLOAD)
        factors = r.json()["top_risk_factors"]
        assert len(factors) > 0
        assert all("feature" in f and "shap_value" in f and "direction" in f for f in factors)

    def test_shap_direction_values(self):
        r = client.post("/predict", json=VALID_PAYLOAD)
        for factor in r.json()["top_risk_factors"]:
            assert factor["direction"] in ("increases_risk", "decreases_risk")

    def test_high_risk_applicant_rejected(self):
        r = client.post("/predict", json=HIGH_RISK_PAYLOAD)
        data = r.json()
        # High-risk applicant should have high default probability
        assert data["default_probability"] > 0.5 or data["decision"] == "Rejected"

    def test_model_version_present(self):
        r = client.post("/predict", json=VALID_PAYLOAD)
        assert r.json()["model_version"] == "xgboost-v1.0"


# ── Validation ────────────────────────────────────────────────────────────────
class TestInputValidation:
    def test_invalid_credit_score_rejected(self):
        payload = {**VALID_PAYLOAD, "credit_score": 200}   # below 300
        r = client.post("/predict", json=payload)
        assert r.status_code == 422

    def test_invalid_education_rejected(self):
        payload = {**VALID_PAYLOAD, "education": "Diploma"}
        r = client.post("/predict", json=payload)
        assert r.status_code == 422

    def test_invalid_employment_type_rejected(self):
        payload = {**VALID_PAYLOAD, "employment_type": "Freelance"}
        r = client.post("/predict", json=payload)
        assert r.status_code == 422

    def test_invalid_loan_term_rejected(self):
        payload = {**VALID_PAYLOAD, "loan_term": 18}   # not in {12,24,36,48,60}
        r = client.post("/predict", json=payload)
        assert r.status_code == 422

    def test_dti_ratio_above_1_rejected(self):
        payload = {**VALID_PAYLOAD, "dti_ratio": 1.5}
        r = client.post("/predict", json=payload)
        assert r.status_code == 422

    def test_missing_required_field_rejected(self):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "credit_score"}
        r = client.post("/predict", json=payload)
        assert r.status_code == 422

    def test_empty_body_rejected(self):
        r = client.post("/predict", json={})
        assert r.status_code == 422


# ── Batch Prediction ──────────────────────────────────────────────────────────
class TestBatchEndpoint:
    def test_batch_with_two_applications(self):
        payload = {"applications": [VALID_PAYLOAD, HIGH_RISK_PAYLOAD]}
        r = client.post("/predict/batch", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2
        assert data["approved_count"] + data["rejected_count"] == 2

    def test_batch_avg_risk_score_in_range(self):
        payload = {"applications": [VALID_PAYLOAD, HIGH_RISK_PAYLOAD]}
        r = client.post("/predict/batch", json=payload)
        avg = r.json()["avg_risk_score"]
        assert 0 <= avg <= 100

    def test_batch_returns_individual_predictions(self):
        payload = {"applications": [VALID_PAYLOAD]}
        r = client.post("/predict/batch", json=payload)
        preds = r.json()["predictions"]
        assert len(preds) == 1
        assert "decision" in preds[0]


# ── Drift Endpoints ───────────────────────────────────────────────────────────
class TestDriftEndpoints:
    def test_drift_status_returns_200(self):
        r = client.get("/drift/status")
        assert r.status_code == 200

    def test_drift_report_returns_200(self):
        r = client.get("/drift/report")
        assert r.status_code == 200
