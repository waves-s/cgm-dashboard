import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import time
from pylibrelinkup import PyLibreLinkUp, APIUrl
from pylibrelinkup.exceptions import (
    AuthenticationError, LLUAPIRateLimitError, PrivacyPolicyError, TermsOfUseError, RedirectError
)
from pylibrelinkup.models.data import Trend

# ─── Page Configuration ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="CGM Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Main background */
.main { background-color: #ffffff; }

/* Metric card styling */
div[data-testid="metric-container"] {
    background-color: #f8f9fa;
    border: 1px solid #e0e0e0;
    border-radius: 12px;
    padding: 16px;
}

/* Big glucose number */
.glucose-display {
    font-size: 72px;
    font-weight: 900;
    line-height: 1;
    letter-spacing: -2px;
}
.glucose-normal  { color: #000000; }
.glucose-high    { color: #cc0000; }
.glucose-low     { color: #e65c00; }

/* Status badge */
.badge-normal { background:#e8f5e9; color:#1b5e20; border-radius:8px; padding:4px 12px; font-weight:700; }
.badge-high   { background:#ffebee; color:#b71c1c; border-radius:8px; padding:4px 12px; font-weight:700; }
.badge-low    { background:#fff3e0; color:#e65c00; border-radius:8px; padding:4px 12px; font-weight:700; }

/* Section divider */
hr { border-top: 1px solid #e0e0e0; margin: 16px 0; }

/* Hide Streamlit branding */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ─── Session State Initialization ─────────────────────────────────────────────
for key, default in {
    "api": None,
    "authenticated": False,
    "patients": [],
    "selected_patient": None,
    "last_update": None,
    "graph_data": [],
    "logbook_data": [],
    "latest_reading": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ─── Helper Functions ──────────────────────────────────────────────────────────
TREND_LABELS = {
    Trend.DOWN_FAST: "Falling Fast ↓",
    Trend.DOWN_SLOW: "Falling ↘",
    Trend.STABLE:    "Stable →",
    Trend.UP_SLOW:   "Rising ↗",
    Trend.UP_FAST:   "Rising Fast ↑",
}

def glucose_status(value: float):
    if value < 70:
        return "LOW", "glucose-low", "badge-low"
    elif value > 180:
        return "HIGH", "glucose-high", "badge-high"
    else:
        return "IN RANGE", "glucose-normal", "badge-normal"

def authenticate(email: str, password: str, region: str):
    try:
        api_url = APIUrl[region]
        api = PyLibreLinkUp(email=email, password=password, api_url=api_url)
        try:
            api.authenticate()
        except RedirectError as redirect:
            # Auto-retry with the correct regional server
            api = PyLibreLinkUp(email=email, password=password, api_url=redirect.region)
            api.authenticate()
        patients = api.get_patients()
        st.session_state.api = api
        st.session_state.authenticated = True
        st.session_state.patients = patients
        if patients:
            st.session_state.selected_patient = patients[0]
        return True, None
    except AuthenticationError as e:
        return False, f"Authentication failed: {e}"
    except PrivacyPolicyError:
        return False, "Please accept the Privacy Policy in the LibreLink app first."
    except TermsOfUseError:
        return False, "Please accept the Terms of Use in the LibreLink app first."
    except Exception as e:
        return False, f"Unexpected error: {e}"

def fetch_data(patient):
    try:
        api = st.session_state.api
        latest  = api.latest(patient)
        graph   = api.graph(patient)
        logbook = api.logbook(patient)
        st.session_state.latest_reading = latest
        st.session_state.graph_data     = graph
        st.session_state.logbook_data   = logbook
        st.session_state.last_update    = datetime.now()
        return True
    except LLUAPIRateLimitError as e:
        st.warning(f"Rate limited. Retry after {e.retry_after}s.")
        return False
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return False

def readings_to_df(readings):
    if not readings:
        return pd.DataFrame()
    rows = []
    for r in readings:
        rows.append({
            "Timestamp": r.timestamp,
            "Glucose (mg/dL)": r.value,
            "Is High": r.is_high,
            "Is Low":  r.is_low,
        })
    df = pd.DataFrame(rows)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    return df.sort_values("Timestamp")

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📊 CGM Dashboard")
    st.markdown("---")

    if not st.session_state.authenticated:
        st.markdown("### 🔐 Login")
        email    = st.text_input("LibreView Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password")
        region   = st.selectbox(
            "Region",
            options=["US", "EU", "EU2", "CA", "AU", "AP", "AE", "DE", "FR", "JP", "LA", "RU"],
            index=0,
            help="Select your region. The app will auto-detect and redirect to the correct server if needed."
        )
        st.caption("💡 Not sure? Leave as US — the app will auto-redirect to your correct region.")
        if st.button("Login", use_container_width=True, type="primary"):
            if email and password:
                with st.spinner("Authenticating…"):
                    ok, err = authenticate(email, password, region)
                if ok:
                    st.success("Logged in!")
                    st.rerun()
                else:
                    st.error(err)
            else:
                st.warning("Please enter email and password.")
    else:
        st.success("✅ Authenticated")

        # Patient selector
        if len(st.session_state.patients) > 1:
            patient_names = [f"{p.first_name} {p.last_name}" for p in st.session_state.patients]
            idx = st.selectbox("Patient", range(len(patient_names)), format_func=lambda i: patient_names[i])
            st.session_state.selected_patient = st.session_state.patients[idx]

        st.markdown("---")
        st.markdown("### 🔄 Refresh")
        refresh_min = st.selectbox(
            "Auto-refresh every",
            options=[1, 5, 10, 15, 30],
            index=1,
            format_func=lambda x: f"{x} min"
        )
        if st.button("Refresh Now", use_container_width=True):
            with st.spinner("Fetching…"):
                fetch_data(st.session_state.selected_patient)
            st.rerun()

        if st.session_state.last_update:
            st.caption(f"Last updated: {st.session_state.last_update.strftime('%H:%M:%S')}")

        st.markdown("---")
        if st.button("Logout", use_container_width=True):
            for k in ["api", "authenticated", "patients", "selected_patient",
                      "last_update", "graph_data", "logbook_data", "latest_reading"]:
                st.session_state[k] = None if k != "patients" else []
            st.session_state.authenticated = False
            st.rerun()

# ─── Main Content ─────────────────────────────────────────────────────────────
if not st.session_state.authenticated:
    st.title("📊 Continuous Glucose Monitor Dashboard")
    st.info("👈 Please log in using your LibreView credentials in the sidebar.")
    st.markdown("""
**What you'll see after logging in:**

| Feature | Description |
|---|---|
| Live Reading | Current glucose value with trend arrow |
| Trend Chart | Interactive 12-hour glucose graph |
| Reading History | Scrollable table of all recent readings |
| Statistics | Average, min, max, std deviation |
| Time in Range | % of time in low / normal / high zones |

**How to connect:**
1. Open the sidebar and enter your LibreView email and password
2. Select your region (US is default)
3. Click **Login** — your data loads immediately
4. Use the **Refresh** button or set auto-refresh to keep data live
    """)
    st.stop()

# ─── Auto-fetch on first load ─────────────────────────────────────────────────
if st.session_state.latest_reading is None and st.session_state.selected_patient:
    with st.spinner("Loading your glucose data…"):
        fetch_data(st.session_state.selected_patient)

# ─── Auto-refresh via meta refresh ───────────────────────────────────────────
if st.session_state.authenticated and st.session_state.last_update:
    elapsed = (datetime.now() - st.session_state.last_update).total_seconds()
    refresh_seconds = refresh_min * 60
    if elapsed >= refresh_seconds:
        fetch_data(st.session_state.selected_patient)
        st.rerun()

# ─── Dashboard Header ─────────────────────────────────────────────────────────
patient = st.session_state.selected_patient
patient_name = f"{patient.first_name} {patient.last_name}" if patient else "Patient"
st.title(f"📊 {patient_name}'s Glucose Dashboard")

latest = st.session_state.latest_reading

if latest is None:
    st.warning("No data available. Click **Refresh Now** in the sidebar.")
    st.stop()

# ─── Current Reading Banner ───────────────────────────────────────────────────
status_label, glucose_class, badge_class = glucose_status(latest.value)
trend_text = TREND_LABELS.get(latest.trend, "→") if hasattr(latest, "trend") else "→"

col_val, col_trend, col_status, col_time = st.columns([2, 2, 2, 2])

with col_val:
    st.markdown(
        f'<div class="glucose-display {glucose_class}">{latest.value:.0f}</div>'
        '<div style="font-size:14px;color:#666;margin-top:4px;">mg/dL</div>',
        unsafe_allow_html=True
    )

with col_trend:
    st.metric("Trend", trend_text)

with col_status:
    st.markdown(
        f'<br><span class="{badge_class}">{status_label}</span>',
        unsafe_allow_html=True
    )

with col_time:
    st.metric("Reading Time", latest.timestamp.strftime("%H:%M:%S"))

st.markdown("---")

# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab_chart, tab_readings, tab_stats = st.tabs(["📈 Trend Chart", "📋 All Readings", "📊 Statistics"])

# ── Tab 1: Chart ──────────────────────────────────────────────────────────────
with tab_chart:
    graph_df = readings_to_df(st.session_state.graph_data)

    if graph_df.empty:
        st.info("No chart data available.")
    else:
        # Time range filter
        hours = st.slider("Show last N hours", min_value=1, max_value=12, value=6, step=1)
        cutoff = datetime.now() - timedelta(hours=hours)
        chart_df = graph_df[graph_df["Timestamp"] >= cutoff]

        fig = go.Figure()

        # Shaded target zone
        fig.add_hrect(y0=70, y1=180, fillcolor="rgba(0,200,0,0.07)",
                      line_width=0, annotation_text="Target Range", annotation_position="top left")

        # Colour points by status
        colors = chart_df["Glucose (mg/dL)"].apply(
            lambda v: "#cc0000" if v > 180 else ("#e65c00" if v < 70 else "#000000")
        )

        fig.add_trace(go.Scatter(
            x=chart_df["Timestamp"],
            y=chart_df["Glucose (mg/dL)"],
            mode="lines+markers",
            name="Glucose",
            line=dict(color="#000000", width=2),
            marker=dict(color=colors, size=7),
            hovertemplate="%{x|%H:%M}<br><b>%{y} mg/dL</b><extra></extra>"
        ))

        # Reference lines
        fig.add_hline(y=70,  line_dash="dot", line_color="#e65c00",
                      annotation_text="Low (70)",  annotation_position="bottom right")
        fig.add_hline(y=180, line_dash="dot", line_color="#cc0000",
                      annotation_text="High (180)", annotation_position="top right")

        fig.update_layout(
            xaxis_title="Time",
            yaxis_title="Glucose (mg/dL)",
            yaxis=dict(range=[40, 300]),
            hovermode="x unified",
            height=420,
            template="plotly_white",
            margin=dict(l=0, r=0, t=20, b=0),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

# ── Tab 2: Readings Table ─────────────────────────────────────────────────────
with tab_readings:
    # Combine graph + logbook for a longer history
    all_readings = list(st.session_state.graph_data or []) + list(st.session_state.logbook_data or [])
    all_df = readings_to_df(all_readings)

    if all_df.empty:
        st.info("No readings available.")
    else:
        all_df = all_df.drop_duplicates("Timestamp").sort_values("Timestamp", ascending=False)
        all_df["Timestamp"] = all_df["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

        def highlight_row(row):
            v = row["Glucose (mg/dL)"]
            if v > 180:
                return ["background-color: #fff0f0"] * len(row)
            elif v < 70:
                return ["background-color: #fff8f0"] * len(row)
            return [""] * len(row)

        styled = all_df[["Timestamp", "Glucose (mg/dL)"]].style.apply(highlight_row, axis=1)
        st.dataframe(styled, use_container_width=True, height=500)

# ── Tab 3: Statistics ─────────────────────────────────────────────────────────
with tab_stats:
    logbook_df = readings_to_df(st.session_state.logbook_data)

    if logbook_df.empty:
        st.info("No statistics data available.")
    else:
        vals = logbook_df["Glucose (mg/dL)"]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Average",  f"{vals.mean():.1f} mg/dL")
        c2.metric("Minimum",  f"{vals.min():.0f} mg/dL")
        c3.metric("Maximum",  f"{vals.max():.0f} mg/dL")
        c4.metric("Std Dev",  f"{vals.std():.1f}")

        st.markdown("---")
        st.subheader("Time in Range (last ~14 days)")

        total = len(vals)
        low_pct    = (vals < 70).sum()    / total * 100
        normal_pct = ((vals >= 70) & (vals <= 180)).sum() / total * 100
        high_pct   = (vals > 180).sum()   / total * 100

        col_l, col_n, col_h = st.columns(3)
        col_l.metric("🟠 Low (<70 mg/dL)",       f"{low_pct:.1f}%")
        col_n.metric("🟢 In Range (70–180)",      f"{normal_pct:.1f}%")
        col_h.metric("🔴 High (>180 mg/dL)",      f"{high_pct:.1f}%")

        # Donut chart
        fig_pie = px.pie(
            values=[low_pct, normal_pct, high_pct],
            names=["Low", "In Range", "High"],
            color_discrete_sequence=["#e65c00", "#000000", "#cc0000"],
            hole=0.55,
        )
        fig_pie.update_traces(textinfo="label+percent")
        fig_pie.update_layout(
            height=320,
            margin=dict(l=0, r=0, t=20, b=0),
            showlegend=True,
        )
        st.plotly_chart(fig_pie, use_container_width=True)

        st.markdown("---")
        st.subheader("Daily Average Trend")
        logbook_df["Date"] = logbook_df["Timestamp"].dt.date
        daily = logbook_df.groupby("Date")["Glucose (mg/dL)"].mean().reset_index()
        daily.columns = ["Date", "Average Glucose (mg/dL)"]

        fig_daily = go.Figure(go.Bar(
            x=daily["Date"],
            y=daily["Average Glucose (mg/dL)"],
            marker_color=[
                "#cc0000" if v > 180 else ("#e65c00" if v < 70 else "#000000")
                for v in daily["Average Glucose (mg/dL)"]
            ]
        ))
        fig_daily.add_hline(y=70,  line_dash="dot", line_color="#e65c00")
        fig_daily.add_hline(y=180, line_dash="dot", line_color="#cc0000")
        fig_daily.update_layout(
            xaxis_title="Date",
            yaxis_title="Average Glucose (mg/dL)",
            height=300,
            template="plotly_white",
            margin=dict(l=0, r=0, t=20, b=0),
        )
        st.plotly_chart(fig_daily, use_container_width=True)
