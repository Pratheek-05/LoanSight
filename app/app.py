import streamlit as st
import pandas as pd
import numpy as np
import joblib
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import shap
import os

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="LoanSight AI — Loan Approval Platform",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=Playfair+Display:wght@700;800&display=swap');

* { font-family: 'DM Sans', sans-serif; }

/* ── Global background ── */
[data-testid="stAppViewContainer"] {
    background: #fafafa;
}
[data-testid="stHeader"] { background: transparent; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #ffffff;
    border-right: 1px solid #f0ece8;
}

[data-testid="stSidebar"] .stSlider > div > div > div { background: #e8380d !important; }
[data-testid="stSidebar"] label { font-weight: 500; font-size: 0.82rem; color: #555 !important; letter-spacing: 0.03em; }

/* ── Sidebar section headers ── */
.sidebar-section {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #e8380d !important;
    margin: 1.4rem 0 0.6rem;
    padding-bottom: 0.4rem;
    border-bottom: 2px solid #fde8e3;
}

/* ── Header banner ── */
.top-header {
    background: #ffffff;
    border-bottom: 3px solid #e8380d;
    padding: 1.6rem 2.5rem 1.4rem;
    margin-bottom: 2rem;
    display: flex;
    align-items: center;
    gap: 1.2rem;
    box-shadow: 0 2px 12px rgba(232,56,13,0.07);
}
.top-header .logo-mark {
    width: 48px; height: 48px;
    background: linear-gradient(135deg, #e8380d, #f5830a);
    border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.5rem;
    box-shadow: 0 4px 14px rgba(232,56,13,0.3);
}
.top-header h1 {
    font-family: 'Playfair Display', serif;
    font-size: 1.7rem;
    font-weight: 800;
    color: #111;
    margin: 0;
    line-height: 1;
}
.top-header p {
    font-size: 0.82rem;
    color: #888;
    margin: 0.25rem 0 0;
    font-weight: 400;
}
.header-badge {
    margin-left: auto;
    background: #fff5f2;
    border: 1px solid #fdd5c9;
    color: #e8380d;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 0.3rem 0.8rem;
    border-radius: 20px;
    letter-spacing: 0.05em;
}

/* ── Result cards ── */
.result-approved {
    background: linear-gradient(135deg, #f0fdf4, #dcfce7);
    border: 1px solid #86efac;
    border-left: 5px solid #16a34a;
    padding: 1.6rem 2rem;
    border-radius: 14px;
}
.result-rejected {
    background: linear-gradient(135deg, #fff5f2, #fee2e2);
    border: 1px solid #fca5a5;
    border-left: 5px solid #e8380d;
    padding: 1.6rem 2rem;
    border-radius: 14px;
}
.result-approved h2 { color: #15803d; font-size: 1.6rem; margin: 0 0 0.4rem; font-weight: 700; }
.result-rejected h2 { color: #e8380d; font-size: 1.6rem; margin: 0 0 0.4rem; font-weight: 700; }
.result-approved p, .result-rejected p { color: #444; margin: 0; font-size: 0.92rem; }

/* ── Metric cards ── */
.metric-card {
    background: #ffffff;
    border: 1px solid #f0ece8;
    border-radius: 14px;
    padding: 1.2rem 1.4rem;
    text-align: center;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    transition: box-shadow 0.2s;
}
.metric-card:hover { box-shadow: 0 4px 16px rgba(232,56,13,0.1); }
.metric-card .label {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #aaa;
    margin-bottom: 0.4rem;
}
.metric-card .value { font-size: 1.6rem; font-weight: 700; color: #111; }
.metric-card .sub { font-size: 0.75rem; color: #bbb; margin-top: 0.2rem; }

/* ── Section title ── */
.section-title {
    font-family: 'Playfair Display', serif;
    font-size: 1.15rem;
    font-weight: 700;
    color: #111;
    margin: 2rem 0 1rem;
    padding-bottom: 0.6rem;
    border-bottom: 2px solid #fde8e3;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

/* ── Predict button ── */
div[data-testid="stButton"] > button {
    background: linear-gradient(135deg, #e8380d, #f5830a) !important;
    color: white !important;
    border: none !important;
    padding: 0.75rem 2rem !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    border-radius: 10px !important;
    width: 100% !important;
    letter-spacing: 0.03em !important;
    box-shadow: 0 4px 14px rgba(232,56,13,0.35) !important;
    transition: all 0.2s !important;
}
div[data-testid="stButton"] > button:hover {
    box-shadow: 0 6px 20px rgba(232,56,13,0.45) !important;
    transform: translateY(-1px) !important;
}

/* ── Landing state cards ── */
.feature-pill {
    display: inline-block;
    background: #fff5f2;
    border: 1px solid #fdd5c9;
    color: #e8380d;
    font-size: 0.78rem;
    font-weight: 600;
    padding: 0.3rem 0.75rem;
    border-radius: 20px;
    margin: 0.2rem;
}

/* ── Divider ── */
hr { border: none; border-top: 1px solid #f0ece8; margin: 1.5rem 0; }


/* ── Force light sidebar text ── */
[data-testid="stSidebar"] label { color: #333 !important; }
[data-testid="stSidebar"] p { color: #1a1a1a !important; }
[data-testid="stSidebar"] input { color: #111 !important; background: #f9f9f9 !important; }
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] * { color: #111 !important; background: #f9f9f9 !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: #fafafa; }
::-webkit-scrollbar-thumb { background: #fdd5c9; border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

# ── Load artifacts ────────────────────────────────────────────────────────────
BASE      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS = os.path.join(BASE, "artifacts")

@st.cache_resource
def load_artifacts():
    preprocessor = joblib.load(os.path.join(ARTIFACTS, "preprocessor.joblib"))
    model        = joblib.load(os.path.join(ARTIFACTS, "best_model.joblib"))
    with open(os.path.join(ARTIFACTS, "feature_meta.json")) as f:
        meta = json.load(f)
    explainer = shap.TreeExplainer(model)
    return preprocessor, model, meta, explainer

preprocessor, model, meta, explainer = load_artifacts()
NUM_COLS = meta["num_cols"]
CAT_COLS = meta["cat_cols"]

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="top-header">
  <div class="logo-mark">🏦</div>
  <div>
    <h1>LoanSight AI</h1>
    <p>Enterprise Loan Risk Assessment Platform · Powered by XGBoost + SHAP</p>
  </div>
  <div class="header-badge">● LIVE MODEL</div>
</div>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div style="padding:1rem 0 0.5rem"><span style="font-family:Playfair Display,serif;font-size:1.1rem;font-weight:800;color:#111">Applicant Details</span></div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section">Personal</div>', unsafe_allow_html=True)
    age            = st.slider("Age", 18, 80, 35)
    marital_status = st.selectbox("Marital Status", ["Single", "Married", "Divorced"])
    has_dependents = st.selectbox("Has Dependents", ["No", "Yes"])

    st.markdown('<div class="sidebar-section">Financial</div>', unsafe_allow_html=True)
    income       = st.number_input("Annual Income ($)", 10000, 500000, 55000, step=1000)
    credit_score = st.slider("Credit Score", 300, 850, 680)
    dti_ratio    = st.slider("Debt-to-Income Ratio", 0.01, 0.95, 0.30, step=0.01)
    has_mortgage = st.selectbox("Has Mortgage", ["No", "Yes"])

    st.markdown('<div class="sidebar-section">Employment</div>', unsafe_allow_html=True)
    employment_type = st.selectbox("Employment Type", ["Full-Time", "Part-Time", "Self-Employed", "Unemployed"])
    months_employed = st.slider("Months Employed", 0, 360, 48)
    education       = st.selectbox("Education Level", ["High School", "Bachelor", "Master", "Phd"])

    st.markdown('<div class="sidebar-section">Loan Details</div>', unsafe_allow_html=True)
    loan_amount      = st.number_input("Loan Amount ($)", 1000, 500000, 25000, step=500)
    interest_rate    = st.slider("Interest Rate (%)", 1.0, 30.0, 8.5, step=0.5)
    loan_term        = st.selectbox("Loan Term (months)", [12, 24, 36, 48, 60], index=2)
    num_credit_lines = st.slider("No. of Credit Lines", 1, 20, 4)
    loan_purpose     = st.selectbox("Loan Purpose", ["Home", "Auto", "Education", "Business", "Other"])
    has_co_signer    = st.selectbox("Has Co-Signer", ["No", "Yes"])

    st.markdown("<br>", unsafe_allow_html=True)
    predict_btn = st.button("Run Risk Assessment →")

# ── Input DataFrame ───────────────────────────────────────────────────────────
input_data = {
    "age": age, "income": income, "loan_amount": loan_amount,
    "credit_score": credit_score, "months_employed": months_employed,
    "num_credit_lines": num_credit_lines, "interest_rate": interest_rate,
    "loan_term": loan_term, "dti_ratio": dti_ratio,
    "education": education, "employment_type": employment_type,
    "marital_status": marital_status, "has_mortgage": has_mortgage,
    "has_dependents": has_dependents, "loan_purpose": loan_purpose,
    "has_co_signer": has_co_signer,
}
input_df = pd.DataFrame([input_data])

# ── Main ──────────────────────────────────────────────────────────────────────
if predict_btn:
    X_enc  = preprocessor.transform(input_df)
    pred   = model.predict(X_enc)[0]
    proba  = model.predict_proba(X_enc)[0]
    default_prob  = proba[1]
    approved_prob = proba[0]
    risk_score    = int(round(default_prob * 100))
    risk_label    = "Low" if risk_score < 30 else ("Medium" if risk_score < 60 else "High")
    risk_color    = "#16a34a" if risk_score < 30 else ("#f5830a" if risk_score < 60 else "#e8380d")

    # ── SHAP values ──
    shap_values = explainer.shap_values(X_enc)
    sv = shap_values[1] if isinstance(shap_values, list) else shap_values
    try:
        feature_names = list(preprocessor.get_feature_names_out())
    except Exception:
        feature_names = [f"f{i}" for i in range(X_enc.shape[1])]

    top_idx   = np.argsort(np.abs(sv[0]))[::-1][:8]
    top_names = [feature_names[i].replace("num__", "").replace("cat__", "").replace("_", " ").title() for i in top_idx]
    top_vals  = [float(sv[0][i]) for i in top_idx]

    # ── Row 1: Decision + Metrics ──
    col1, col2 = st.columns([3, 2])

    with col1:
        if pred == 0:
            st.markdown(f"""
            <div class="result-approved">
              <h2>✅ Loan Approved</h2>
              <p>The applicant presents an acceptable risk profile. Recommended for standard loan terms with continued monitoring.</p>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="result-rejected">
              <h2>❌ Application Declined</h2>
              <p>Risk indicators exceed acceptable thresholds. This application does not meet current approval criteria.</p>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.markdown(f"""<div class="metric-card">
              <div class="label">Default Risk</div>
              <div class="value" style="color:{risk_color}">{default_prob:.1%}</div>
              <div class="sub">probability</div>
            </div>""", unsafe_allow_html=True)
        with m2:
            st.markdown(f"""<div class="metric-card">
              <div class="label">Approval Score</div>
              <div class="value">{approved_prob:.1%}</div>
              <div class="sub">confidence</div>
            </div>""", unsafe_allow_html=True)
        with m3:
            st.markdown(f"""<div class="metric-card">
              <div class="label">Risk Level</div>
              <div class="value" style="color:{risk_color}">{risk_label}</div>
              <div class="sub">classification</div>
            </div>""", unsafe_allow_html=True)
        with m4:
            st.markdown(f"""<div class="metric-card">
              <div class="label">Risk Score</div>
              <div class="value" style="color:{risk_color}">{risk_score}</div>
              <div class="sub">out of 100</div>
            </div>""", unsafe_allow_html=True)

    with col2:
        # Donut chart — clean white bg
        fig, ax = plt.subplots(figsize=(3.8, 3.8), facecolor='#ffffff')
        ax.set_facecolor('#ffffff')
        outer = [default_prob, 1 - default_prob]
        colors_outer = [risk_color, '#f0ece8']
        wedges, _ = ax.pie(outer, radius=1, colors=colors_outer, startangle=90,
               wedgeprops=dict(width=0.38, edgecolor='#ffffff', linewidth=3))
        ax.text(0, 0.08, f"{default_prob:.0%}", ha='center', va='center',
                fontsize=22, fontweight='700', color=risk_color)
        ax.text(0, -0.22, "Default Risk", ha='center', va='center',
                fontsize=9, color='#888', fontweight='500')
        ax.set_title("Risk Probability", color='#333', pad=10, fontsize=11, fontweight='600')
        plt.tight_layout(pad=0.5)
        st.pyplot(fig, use_container_width=True)
        plt.close()

    # ── Row 2: SHAP Chart ──
    st.markdown('<div class="section-title">🔍 AI Explainability — SHAP Feature Impact</div>', unsafe_allow_html=True)
    st.caption("Each bar shows how much a feature pushed the risk score up (red) or down (green) for this specific applicant.")

    fig2, ax2 = plt.subplots(figsize=(10, 4), facecolor='#ffffff')
    ax2.set_facecolor('#ffffff')

    colors = ['#e8380d' if v > 0 else '#16a34a' for v in top_vals]
    bars = ax2.barh(top_names[::-1], top_vals[::-1], color=colors[::-1],
                    height=0.55, edgecolor='none')

    # Value labels
    for bar, val in zip(bars, top_vals[::-1]):
        x = bar.get_width()
        label = f"+{val:.3f}" if val > 0 else f"{val:.3f}"
        ax2.text(x + (0.002 if x >= 0 else -0.002), bar.get_y() + bar.get_height()/2,
                 label, va='center', ha='left' if x >= 0 else 'right',
                 fontsize=8.5, color='#333', fontweight='500')

    ax2.axvline(0, color='#ddd', linewidth=1.2)
    ax2.set_xlabel("SHAP Value (impact on default probability)", fontsize=9, color='#888')
    ax2.tick_params(axis='y', labelsize=9, colors='#333')
    ax2.tick_params(axis='x', labelsize=8, colors='#aaa')
    for spine in ['top', 'right', 'left']:
        ax2.spines[spine].set_visible(False)
    ax2.spines['bottom'].set_color('#eee')
    ax2.set_facecolor('#ffffff')
    fig2.patch.set_facecolor('#ffffff')

    # Legend
    red_patch   = mpatches.Patch(color='#e8380d', label='Increases default risk')
    green_patch = mpatches.Patch(color='#16a34a', label='Decreases default risk')
    ax2.legend(handles=[red_patch, green_patch], loc='lower right',
               fontsize=8, framealpha=0, labelcolor='#555')

    plt.tight_layout()
    st.pyplot(fig2, use_container_width=True)
    plt.close()

    # ── Row 3: Risk Factor Gauges ──
    st.markdown('<div class="section-title">📊 Key Risk Indicators</div>', unsafe_allow_html=True)

    factors = {
        "Credit Score":    (credit_score,    300, 850,    credit_score > 700),
        "DTI Ratio":       (dti_ratio,        0,   1,     dti_ratio < 0.4),
        "Annual Income":   (income,       10000, 500000,  income > 50000),
        "Months Employed": (months_employed,  0, 360,     months_employed > 24),
        "Interest Rate":   (interest_rate,    1,  30,     interest_rate < 12),
        "Loan Amount":     (loan_amount,    1000, 500000, loan_amount < 50000),
    }

    fig3, axes = plt.subplots(1, 6, figsize=(14, 2.2), facecolor='#ffffff')
    fig3.subplots_adjust(wspace=0.5)

    for ax, (label, (val, vmin, vmax, is_good)) in zip(axes, factors.items()):
        ax.set_facecolor('#ffffff')
        norm_val = (val - vmin) / (vmax - vmin)
        bar_color = '#16a34a' if is_good else '#e8380d'
        bg_color  = '#f0fdf4' if is_good else '#fff5f2'

        # Background track
        ax.barh([0], [1],   color='#f4f4f4', height=0.5, edgecolor='none')
        ax.barh([0], [norm_val], color=bar_color, height=0.5,
                edgecolor='none', alpha=0.85)

        ax.set_xlim(0, 1)
        ax.set_ylim(-0.8, 0.8)
        ax.set_yticks([])
        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        if label in ("Annual Income", "Loan Amount"):
            disp = f"${val:,.0f}"
        elif label == "DTI Ratio":
            disp = f"{val:.0%}"
        elif label == "Interest Rate":
            disp = f"{val:.1f}%"
        else:
            disp = str(val)

        ax.set_title(label, color='#555', fontsize=7.5, pad=3, fontweight='600')
        ax.text(0.5, -0.55, disp, transform=ax.transAxes, ha='center',
                fontsize=8, color='#111', fontweight='700')
        status = "✓ Good" if is_good else "✗ Risk"
        ax.text(0.5, 0.85, status, transform=ax.transAxes, ha='center',
                fontsize=7.5, color=bar_color, fontweight='600')

    fig3.patch.set_facecolor('#ffffff')
    plt.tight_layout()
    st.pyplot(fig3, use_container_width=True)
    plt.close()

    # ── Row 4: Full Summary ──
    with st.expander("📋 Full Applicant Summary", expanded=False):
        summary_df = pd.DataFrame({
            "Feature": [k.replace("_", " ").title() for k in input_data.keys()],
            "Value":   [str(v) for v in input_data.values()]
        })
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

else:
    # ── Landing state ──
    st.markdown("""
    <div style="text-align:center; padding: 3rem 2rem 1.5rem;">
      <div style="font-size:4rem; margin-bottom:1rem;">🏦</div>
      <h3 style="font-family:'Playfair Display',serif; color:#111; font-size:1.8rem; margin-bottom:0.5rem;">
        Enterprise-Grade Loan Risk Assessment
      </h3>
      <p style="color:#888; font-size:0.95rem; max-width:480px; margin:0 auto 1.5rem;">
        Fill in the applicant details in the sidebar and click <strong style="color:#e8380d">Run Risk Assessment</strong> to get an AI-powered decision with full explainability.
      </p>
      <div>
        <span class="feature-pill">XGBoost Model</span>
        <span class="feature-pill">SHAP Explainability</span>
        <span class="feature-pill">SMOTE Balancing</span>
        <span class="feature-pill">16 Risk Features</span>
        <span class="feature-pill">Prometheus Metrics</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
        <div class="metric-card">
          <div style="font-size:2rem; margin-bottom:0.5rem">🤖</div>
          <div style="font-weight:700; color:#111; font-size:0.95rem">XGBoost + SMOTE</div>
          <div class="sub" style="margin-top:0.3rem;color:#aaa;font-size:0.8rem">Ensemble model with class balancing for unbiased predictions</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div class="metric-card">
          <div style="font-size:2rem; margin-bottom:0.5rem">🔍</div>
          <div style="font-weight:700; color:#111; font-size:0.95rem">SHAP Explainability</div>
          <div class="sub" style="margin-top:0.3rem;color:#aaa;font-size:0.8rem">Every decision explained — see exactly which factors drove the outcome</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown("""
        <div class="metric-card">
          <div style="font-size:2rem; margin-bottom:0.5rem">📡</div>
          <div style="font-weight:700; color:#111; font-size:0.95rem">Production API</div>
          <div class="sub" style="margin-top:0.3rem;color:#aaa;font-size:0.8rem">FastAPI backend with Prometheus metrics and full observability</div>
        </div>""", unsafe_allow_html=True)
