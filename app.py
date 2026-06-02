import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, timezone
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
.main { background-color: #ffffff; }
div[data-testid="metric-container"] {
    background-color: #f8f9fa;
    border: 1px solid #e0e0e0;
    border-radius: 12px;
    padding: 16px;
}
.glucose-display {
    font-size: 72px;
    font-weight: 900;
    line-height: 1;
    letter-spacing: -2px;
}
.glucose-normal  { color: #000000; }
.glucose-high    { color: #cc0000; }
.glucose-low     { color: #e65c00; }
.badge-normal { background:#e8f5e9; color:#1b5e20; border-radius:8px; padding:4px 12px; font-weight:700; font-size:14px; display:inline-block; }
.badge-high   { background:#ffebee; color:#b71c1c; border-radius:8px; padding:4px 12px; font-weight:700; font-size:14px; display:inline-block; }
.badge-low    { background:#fff3e0; color:#e65c00; border-radius:8px; padding:4px 12px; font-weight:700; font-size:14px; display:inline-block; }
.last-reading-box {
    background: #f8f9fa;
    border: 1px solid #e0e0e0;
    border-radius: 12px;
    padding: 12px 16px;
    text-align: center;
}
/* ── Chart control bar ── */
.ctrl-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    background: #f8f9fa;
    border: 1px solid #e0e0e0;
    border-radius: 14px;
    padding: 10px 18px;
    margin-bottom: 12px;
}
.ctrl-period {
    font-size: 15px;
    font-weight: 700;
    color: #1a1a1a;
    white-space: nowrap;
    flex: 1;
}
.ctrl-period span {
    font-size: 12px;
    font-weight: 400;
    color: #888;
    margin-left: 6px;
}
/* ── Zoom pill ── */
.zoom-bar {
    display: flex;
    align-items: center;
    gap: 14px;
    background: #f0f4ff;
    border: 1px solid #c5d3f5;
    border-radius: 12px;
    padding: 8px 16px;
    margin-bottom: 10px;
}
.zoom-label {
    font-size: 12px;
    font-weight: 600;
    color: #555;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    white-space: nowrap;
}
.zoom-value {
    font-size: 26px;
    font-weight: 900;
    color: #1a73e8;
    line-height: 1;
    min-width: 52px;
    text-align: right;
}
.zoom-sub {
    font-size: 11px;
    color: #888;
    margin-top: 1px;
}
hr { border-top: 1px solid #e0e0e0; margin: 16px 0; }
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

/* ── Compact Sidebar ── */
section[data-testid="stSidebar"] > div:first-child {
    padding-top: 0.5rem !important;
    padding-bottom: 0.5rem !important;
    padding-left: 0.75rem !important;
    padding-right: 0.75rem !important;
}
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] .stMarkdown h3 {
    margin-bottom: 2px !important;
    margin-top: 2px !important;
}
section[data-testid="stSidebar"] .stMarkdown h3 {
    font-size: 0.85rem !important;
}
section[data-testid="stSidebar"] .stRadio > label,
section[data-testid="stSidebar"] .stSelectbox > label,
section[data-testid="stSidebar"] .stNumberInput > label,
section[data-testid="stSidebar"] .stSlider > label {
    font-size: 0.78rem !important;
    margin-bottom: 0px !important;
}
section[data-testid="stSidebar"] .stRadio,
section[data-testid="stSidebar"] .stSelectbox,
section[data-testid="stSidebar"] .stNumberInput,
section[data-testid="stSidebar"] .stSlider,
section[data-testid="stSidebar"] .stButton {
    margin-bottom: 4px !important;
    margin-top: 0px !important;
}
section[data-testid="stSidebar"] hr {
    margin: 6px 0 !important;
}
section[data-testid="stSidebar"] .stButton > button {
    padding: 4px 8px !important;
    font-size: 0.78rem !important;
}
</style>
""", unsafe_allow_html=True)

# ─── Constants ────────────────────────────────────────────────────────────────
MG_TO_MMOL = 0.0555   # 1 mg/dL × 0.0555 = mmol/L

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
    "nav_offset_days": 0,   # 0 = today/latest, negative = days back
    "nav_view": "day",      # "day" or "week"
    "history_data": [],     # extended history from glucoseHistory endpoint
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ─── Helper Functions ──────────────────────────────────────────────────────────
TREND_LABELS = {
    Trend.DOWN_FAST: "↓↓",
    Trend.DOWN_SLOW: "↘",
    Trend.STABLE:    "→",
    Trend.UP_SLOW:   "↗",
    Trend.UP_FAST:   "↑↑",
}

def mg_to_mmol(v):
    return round(v * MG_TO_MMOL, 1)

def mmol_to_mg(v):
    return round(v / MG_TO_MMOL, 0)

def format_value(v_mg, unit):
    """Format a mg/dL value for display in the chosen unit."""
    if unit == "mmol/L":
        return f"{mg_to_mmol(v_mg):.1f}"
    return f"{v_mg:.0f}"

def glucose_status(value_mg: float, low_mg: float, high_mg: float):
    if value_mg < low_mg:
        return "LOW", "glucose-low", "badge-low"
    elif value_mg > high_mg:
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

def fetch_extended_history(num_periods: int = 5, period_days: int = 14):
    """Fetch extended glucose history via the glucoseHistory endpoint.
    Returns a list of dicts with 'timestamp' and 'value_in_mg_per_dl'.
    """
    try:
        api = st.session_state.api
        import requests as _req
        url = f"{api.api_url}/glucoseHistory?numPeriods={num_periods}&period={period_days}"
        headers = api._get_headers()
        r = _req.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        rows = []
        for period in data.get("data", {}).get("periods", []):
            for entry in period.get("data", []):
                ts_raw = entry.get("FactoryTimestamp") or entry.get("Timestamp")
                val    = entry.get("Value")  # mg/dL in this endpoint
                if ts_raw and val is not None:
                    rows.append({"timestamp": ts_raw, "value_in_mg_per_dl": float(val)})
        st.session_state.history_data = rows
        return True, len(rows)
    except Exception as e:
        return False, str(e)


def readings_to_df(readings):
    if not readings:
        return pd.DataFrame()
    rows = []
    for r in readings:
        # Always use value_in_mg_per_dl as the authoritative mg/dL source.
        # The 'value' field reflects the account's display unit (mmol/L for CA accounts)
        # so it must NOT be used as mg/dL.
        mg_val = r.value_in_mg_per_dl if r.value_in_mg_per_dl else r.value
        rows.append({
            "Timestamp": r.timestamp,
            "Glucose_mg": mg_val,
            "Is High": r.is_high,
            "Is Low":  r.is_low,
        })
    df = pd.DataFrame(rows)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], utc=True).dt.tz_localize(None)
    df["Glucose_mmol"] = (df["Glucose_mg"] * MG_TO_MMOL).round(1)
    return df.sort_values("Timestamp")


def history_to_df(history_rows):
    """Convert extended history dicts to a DataFrame compatible with readings_to_df output."""
    if not history_rows:
        return pd.DataFrame()
    df = pd.DataFrame(history_rows)
    df.rename(columns={"timestamp": "Timestamp", "value_in_mg_per_dl": "Glucose_mg"}, inplace=True)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], utc=True, errors="coerce").dt.tz_localize(None)
    df = df.dropna(subset=["Timestamp", "Glucose_mg"])
    df["Glucose_mmol"] = (df["Glucose_mg"] * MG_TO_MMOL).round(1)
    df["Is High"] = False
    df["Is Low"]  = False
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
            help="The app will auto-detect and redirect to your correct regional server."
        )
        st.caption("💡 Not sure? Leave as US — the app will auto-redirect.")
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

        # ── Units ──────────────────────────────────────────────────────────────
        st.markdown("### 📐 Units")
        unit_choice = st.radio(
            "Display units",
            options=["mg/dL", "mmol/L", "Both"],
            index=0,
            horizontal=True,
        )

        st.markdown("---")

        # ── Target Range ───────────────────────────────────────────────────────
        st.markdown("### 🎯 Target Range")
        if unit_choice == "mmol/L":
            low_default  = round(70  * MG_TO_MMOL, 1)
            high_default = round(180 * MG_TO_MMOL, 1)
            low_mmol  = st.number_input("Low threshold (mmol/L)",  min_value=1.0, max_value=10.0, value=low_default,  step=0.1, format="%.1f")
            high_mmol = st.number_input("High threshold (mmol/L)", min_value=5.0, max_value=25.0, value=high_default, step=0.1, format="%.1f")
            target_low_mg  = round(low_mmol  / MG_TO_MMOL)
            target_high_mg = round(high_mmol / MG_TO_MMOL)
            st.caption(f"≈ {target_low_mg:.0f} – {target_high_mg:.0f} mg/dL")
        else:
            target_low_mg  = st.number_input("Low threshold (mg/dL)",  min_value=40,  max_value=180, value=70,  step=1)
            target_high_mg = st.number_input("High threshold (mg/dL)", min_value=100, max_value=400, value=180, step=1)
            if unit_choice == "Both":
                st.caption(f"≈ {mg_to_mmol(target_low_mg):.1f} – {mg_to_mmol(target_high_mg):.1f} mmol/L")

        st.markdown("---")

        # ── Refresh ────────────────────────────────────────────────────────────
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
            st.caption(f"Last fetched: {st.session_state.last_update.strftime('%H:%M:%S')}")

        st.markdown("---")

        # ── Extended History ───────────────────────────────────────────────────
        st.markdown("### 📅 Extended History")
        st.caption("Load up to 70+ days of historical data via the LibreView API.")
        hist_periods = st.slider("Periods × 14 days", min_value=1, max_value=10, value=5, step=1,
                                  help="Each period = 14 days. 5 periods = ~70 days.")
        if st.button("Load Extended History", use_container_width=True):
            with st.spinner(f"Fetching {hist_periods * 14} days of history…"):
                ok, result = fetch_extended_history(num_periods=hist_periods, period_days=14)
            if ok:
                st.success(f"Loaded {result:,} readings ({hist_periods * 14} days)")
                st.rerun()
            else:
                st.warning(f"Extended history unavailable: {result}")
        if st.session_state.history_data:
            st.caption(f"📂 {len(st.session_state.history_data):,} extended readings loaded")

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
| Live Reading | Current glucose value with trend arrow and status |
| Units Toggle | Switch between mg/dL, mmol/L, or show both |
| Custom Target Range | Set your own Low / High thresholds |
| Trend Chart | Interactive 12-hour glucose graph |
| Reading History | Scrollable table of all recent readings |
| Statistics | Average, min, max, time in range |
    """)
    st.stop()

# ─── Auto-fetch on first load ─────────────────────────────────────────────────
if st.session_state.latest_reading is None and st.session_state.selected_patient:
    with st.spinner("Loading your glucose data…"):
        fetch_data(st.session_state.selected_patient)

# ─── Auto-refresh ─────────────────────────────────────────────────────────────
if st.session_state.authenticated and st.session_state.last_update:
    elapsed = (datetime.now() - st.session_state.last_update).total_seconds()
    if elapsed >= refresh_min * 60:
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
# Use value_in_mg_per_dl as the authoritative base for all calculations
latest_mg = latest.value_in_mg_per_dl if latest.value_in_mg_per_dl else latest.value
status_label, glucose_class, badge_class = glucose_status(latest_mg, target_low_mg, target_high_mg)
trend_text = TREND_LABELS.get(latest.trend, "→") if hasattr(latest, "trend") else "→"

# Format reading timestamp (strip UTC offset for display)
reading_ts = pd.to_datetime(latest.timestamp, utc=True).tz_localize(None)
reading_time_str = reading_ts.strftime("%b %d, %Y  %H:%M:%S")

col_val, col_trend, col_status, col_last = st.columns([2, 2, 2, 3])

with col_val:
    if unit_choice == "mg/dL":
        display_val = f"{latest_mg:.0f}"
        display_unit = "mg/dL"
    elif unit_choice == "mmol/L":
        display_val = f"{mg_to_mmol(latest_mg):.1f}"
        display_unit = "mmol/L"
    else:  # Both
        display_val = f"{latest_mg:.0f}"
        display_unit = f"mg/dL &nbsp;|&nbsp; {mg_to_mmol(latest_mg):.1f} mmol/L"

    st.markdown(
        f'<div class="glucose-display {glucose_class}">{display_val}</div>'
        f'<div style="font-size:14px;color:#666;margin-top:4px;">{display_unit}</div>',
        unsafe_allow_html=True
    )

with col_trend:
    st.metric("Trend", trend_text)

with col_status:
    st.markdown(
        f'<div style="padding-top:8px;">'
        f'<div style="font-size:12px;color:#888;margin-bottom:4px;">Status</div>'
        f'<span class="{badge_class}">{status_label}</span>'
        f'</div>',
        unsafe_allow_html=True
    )

with col_last:
    st.markdown(
        f'<div class="last-reading-box">'
        f'<div style="font-size:12px;color:#888;margin-bottom:4px;">Last Reading</div>'
        f'<div style="font-size:20px;font-weight:700;">{display_val} <span style="font-size:13px;font-weight:400;color:#555;">{display_unit}</span></div>'
        f'<div style="font-size:13px;color:#444;margin-top:2px;">🕐 {reading_time_str}</div>'
        f'</div>',
        unsafe_allow_html=True
    )
    # Also show mmol/L equivalent when in mg/dL mode and vice versa
    if unit_choice == "mg/dL":
        st.caption(f"≈ {mg_to_mmol(latest_mg):.1f} mmol/L")
    elif unit_choice == "mmol/L":
        st.caption(f"≈ {latest_mg:.0f} mg/dL")

st.markdown("---")

# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab_chart, tab_readings, tab_stats = st.tabs(["📈 Trend Chart", "📋 All Readings", "📊 Statistics"])

# ── Tab 1: Chart ──────────────────────────────────────────────────────────────
with tab_chart:
    # Combine graph (12h) + logbook (14d) + extended history for the widest possible window
    all_chart_readings = list(st.session_state.graph_data or []) + list(st.session_state.logbook_data or [])
    recent_df  = readings_to_df(all_chart_readings)
    hist_df    = history_to_df(st.session_state.history_data or [])
    if not recent_df.empty and not hist_df.empty:
        full_df = pd.concat([recent_df, hist_df], ignore_index=True)
    elif not hist_df.empty:
        full_df = hist_df
    else:
        full_df = recent_df
    if not full_df.empty:
        full_df = full_df.drop_duplicates("Timestamp").sort_values("Timestamp")

    # For week/calendar view, prefer extended history if available, else logbook
    logbook_df = readings_to_df(list(st.session_state.logbook_data or []))
    if not logbook_df.empty:
        logbook_df = logbook_df.drop_duplicates("Timestamp").sort_values("Timestamp")
    wide_df = full_df  # includes extended history

    if full_df.empty:
        st.info("No chart data available. Click Refresh Now in the sidebar.")
    else:
        # ── Time Navigation Controls ──────────────────────────────────────────
        # Determine available date range across all data sources
        data_min_date = wide_df["Timestamp"].min().date()
        data_max_date = wide_df["Timestamp"].max().date()
        available_dates = sorted(wide_df["Timestamp"].dt.date.unique())

        nav_col1, nav_col2, nav_col3, nav_col4, nav_col5, nav_col6 = st.columns([1.2, 1, 1, 1, 1, 2])
        with nav_col1:
            view_mode = st.radio("View", ["Day", "Week"], horizontal=True,
                                  index=0 if st.session_state.nav_view == "day" else 1,
                                  key="view_mode_radio")
            st.session_state.nav_view = view_mode.lower()

        if st.session_state.nav_view == "day":
            min_offset = -(data_max_date - data_min_date).days
        else:
            min_offset = -((data_max_date - data_min_date).days // 7) * 7
        # Clamp offset
        st.session_state.nav_offset_days = max(min_offset, min(0, st.session_state.nav_offset_days))
        offset = st.session_state.nav_offset_days

        with nav_col2:
            st.write("")
            if st.button("⏮ Oldest", use_container_width=True):
                st.session_state.nav_offset_days = min_offset
                st.rerun()
        with nav_col3:
            st.write("")
            step = 1 if st.session_state.nav_view == "day" else 7
            if st.button("◀ Back", use_container_width=True):
                st.session_state.nav_offset_days = max(min_offset, offset - step)
                st.rerun()
        with nav_col4:
            st.write("")
            if st.button("Forward ▶", use_container_width=True):
                st.session_state.nav_offset_days = min(0, offset + step)
                st.rerun()
        with nav_col5:
            st.write("")
            if st.button("Latest ⏭", use_container_width=True):
                st.session_state.nav_offset_days = 0
                st.rerun()

        # Compute the window to display
        anchor_date = data_max_date + timedelta(days=st.session_state.nav_offset_days)
        if st.session_state.nav_view == "day":
            window_start = datetime.combine(anchor_date, datetime.min.time())
            window_end   = datetime.combine(anchor_date, datetime.max.time())
            period_label = anchor_date.strftime("%A, %b %d %Y")
        else:
            week_start = anchor_date - timedelta(days=anchor_date.weekday())
            week_end   = week_start + timedelta(days=6)
            window_start = datetime.combine(week_start, datetime.min.time())
            window_end   = datetime.combine(week_end,   datetime.max.time())
            period_label = f"Week of {week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}"

        with nav_col6:
            st.markdown(
                f'<div style="padding-top:28px;font-size:15px;font-weight:600;color:#333;">📅 {period_label}</div>',
                unsafe_allow_html=True
            )

        # ── Calendar date picker (Day view only) ──────────────────────────────────
        if st.session_state.nav_view == "day" and available_dates:
            # Sync the calendar widget value to the current anchor_date whenever
            # it drifts (e.g. after Back/Forward button clicks)
            if st.session_state.get("cal_picker") != anchor_date:
                st.session_state["cal_picker"] = anchor_date

            cal_col1, cal_col2 = st.columns([1, 3])
            with cal_col1:
                st.markdown('<div style="padding-top:6px;font-size:13px;font-weight:600;color:#555;">🗓️ Jump to date:</div>',
                            unsafe_allow_html=True)
            with cal_col2:
                picked = st.date_input(
                    "jump_date",
                    min_value=data_min_date,
                    max_value=data_max_date,
                    label_visibility="collapsed",
                    key="cal_picker",
                )
                if picked != anchor_date:
                    new_offset = (picked - data_max_date).days
                    st.session_state.nav_offset_days = max(min_offset, min(0, new_offset))
                    st.rerun()

        # Use appropriate data source
        source_df = wide_df

        chart_df = source_df[
            (source_df["Timestamp"] >= window_start) &
            (source_df["Timestamp"] <= window_end)
        ].copy()
        if chart_df.empty:
            st.info(f"No readings found for {period_label}.")
        else:
            # Day view: show date label only
            if st.session_state.nav_view == "day":
                date_str = anchor_date.strftime("%A, %B %d, %Y")
                st.markdown(
                    f'<div style="font-size:13px;font-weight:600;color:#1a73e8;'
                    f'background:#f0f4ff;border:1px solid #c5d3f5;border-radius:8px;'
                    f'padding:5px 14px;display:inline-block;margin-bottom:6px;">'
                    f'📆 {date_str}</div>',
                    unsafe_allow_html=True
                )

        # Convert target range for display
        target_low_mmol  = round(target_low_mg  * MG_TO_MMOL, 1)
        target_high_mmol = round(target_high_mg * MG_TO_MMOL, 1)

        if not chart_df.empty:
            # ── Dynamic Y-axis: centre the target range with equal padding ──────
            # Compute a Y range that places the target band in the vertical middle,
            # while also ensuring all actual data points are visible.
            def centered_yrange_mg(tgt_lo, tgt_hi, data_min, data_max):
                """Return (y_min, y_max) that centres [tgt_lo, tgt_hi] in the chart
                and includes all data points with comfortable padding.
                Y-axis minimum is clamped to 0 (glucose cannot be negative)."""
                tgt_centre = (tgt_lo + tgt_hi) / 2
                tgt_half   = (tgt_hi - tgt_lo) / 2
                # Half-span needed to show target range + 50% padding on each side
                half_span  = max(tgt_half * 3.0, 60)   # at least ±60 mg/dL
                # Expand to include actual data
                half_span  = max(half_span, tgt_centre - data_min + 20,
                                            data_max - tgt_centre + 20)
                y_min = max(0, tgt_centre - half_span)  # never below 0
                y_max = tgt_centre + half_span
                return y_min, y_max

            data_min_mg = chart_df["Glucose_mg"].min()
            data_max_mg = chart_df["Glucose_mg"].max()
            y_min_mg, y_max_mg = centered_yrange_mg(
                target_low_mg, target_high_mg, data_min_mg, data_max_mg
            )
            y_min_mmol = round(y_min_mg * MG_TO_MMOL, 1)
            y_max_mmol = round(y_max_mg * MG_TO_MMOL, 1)

            fig = go.Figure()

            if unit_choice == "Both":
                # Primary Y axis: mg/dL
                colors_mg = chart_df["Glucose_mg"].apply(
                    lambda v: "#cc0000" if v > target_high_mg else ("#e65c00" if v < target_low_mg else "#1a73e8")
                )
                fig.add_trace(go.Scatter(
                    x=chart_df["Timestamp"],
                    y=chart_df["Glucose_mg"],
                    mode="lines+markers",
                    name="mg/dL",
                    yaxis="y1",
                    line=dict(color="#1a73e8", width=2),
                    marker=dict(color=colors_mg, size=6),
                    hovertemplate="%{x|%H:%M}<br><b>%{y:.0f} mg/dL</b><extra></extra>"
                ))
                # Secondary Y axis: mmol/L (invisible trace for axis scaling)
                fig.add_trace(go.Scatter(
                    x=chart_df["Timestamp"],
                    y=chart_df["Glucose_mmol"],
                    mode="lines",
                    name="mmol/L",
                    yaxis="y2",
                    line=dict(color="#1a73e8", width=0),
                    showlegend=True,
                    hovertemplate="%{x|%H:%M}<br><b>%{y:.1f} mmol/L</b><extra></extra>"
                ))
                fig.add_hrect(y0=target_low_mg, y1=target_high_mg,
                              fillcolor="rgba(0,200,0,0.07)", line_width=0,
                              annotation_text="Target Range", annotation_position="top left")
                fig.add_hline(y=target_low_mg,  line_dash="dot", line_color="#e65c00",
                              annotation_text=f"Low ({target_low_mg} mg/dL)", annotation_position="bottom right")
                fig.add_hline(y=target_high_mg, line_dash="dot", line_color="#cc0000",
                              annotation_text=f"High ({target_high_mg} mg/dL)", annotation_position="top right")
                fig.update_layout(
                    xaxis_title="Time",
                    yaxis=dict(title="Glucose (mg/dL)", range=[y_min_mg, y_max_mg], side="left"),
                    yaxis2=dict(
                        title="Glucose (mmol/L)",
                        range=[y_min_mmol, y_max_mmol],
                        overlaying="y",
                        side="right",
                        showgrid=False,
                    ),
                    hovermode="x unified",
                    height=500,
                    template="plotly_white",
                    margin=dict(l=0, r=60, t=20, b=60),
                    legend=dict(orientation="h", y=1.05),
                    xaxis=dict(
                        rangeslider=dict(visible=False),
                        rangeselector=dict(
                            buttons=[
                                dict(count=3,  label="3h",  step="hour",  stepmode="backward"),
                                dict(count=6,  label="6h",  step="hour",  stepmode="backward"),
                                dict(count=12, label="12h", step="hour",  stepmode="backward"),
                                dict(count=24, label="24h", step="hour",  stepmode="backward"),
                            ],
                            bgcolor="#f0f4ff", activecolor="#1a73e8",
                            font=dict(size=11),
                            x=0.055, y=1.08,
                            xanchor="left",
                        ),
                    ),
                    annotations=[
                        dict(text="<b>Zoom:</b>", x=0.0, y=1.10, xref="paper", yref="paper",
                             showarrow=False, font=dict(size=12, color="#555"),
                             xanchor="left", yanchor="middle"),
                    ],
                )

            else:
                # Single axis
                if unit_choice == "mmol/L":
                    y_col     = "Glucose_mmol"
                    y_label   = "Glucose (mmol/L)"
                    y_range   = [y_min_mmol, y_max_mmol]
                    tgt_low   = target_low_mmol
                    tgt_high  = target_high_mmol
                    low_ann   = f"Low ({target_low_mmol} mmol/L)"
                    high_ann  = f"High ({target_high_mmol} mmol/L)"
                    hover_fmt = "%{x|%H:%M}<br><b>%{y:.1f} mmol/L</b><extra></extra>"
                else:
                    y_col     = "Glucose_mg"
                    y_label   = "Glucose (mg/dL)"
                    y_range   = [y_min_mg, y_max_mg]
                    tgt_low   = target_low_mg
                    tgt_high  = target_high_mg
                    low_ann   = f"Low ({target_low_mg} mg/dL)"
                    high_ann  = f"High ({target_high_mg} mg/dL)"
                    hover_fmt = "%{x|%H:%M}<br><b>%{y:.0f} mg/dL</b><extra></extra>"

                colors = chart_df[y_col].apply(
                    lambda v: "#cc0000" if v > tgt_high else ("#e65c00" if v < tgt_low else "#1a73e8")
                )
                fig.add_hrect(y0=tgt_low, y1=tgt_high,
                              fillcolor="rgba(0,200,0,0.07)", line_width=0,
                              annotation_text="Target Range", annotation_position="top left")
                fig.add_trace(go.Scatter(
                    x=chart_df["Timestamp"],
                    y=chart_df[y_col],
                    mode="lines+markers",
                    name="Glucose",
                    line=dict(color="#1a73e8", width=2),
                    marker=dict(color=colors, size=7),
                    hovertemplate=hover_fmt
                ))
                fig.add_hline(y=tgt_low,  line_dash="dot", line_color="#e65c00",
                              annotation_text=low_ann,  annotation_position="bottom right")
                fig.add_hline(y=tgt_high, line_dash="dot", line_color="#cc0000",
                              annotation_text=high_ann, annotation_position="top right")
                fig.update_layout(
                    xaxis_title="Time",
                    yaxis=dict(title=y_label, range=y_range),
                    hovermode="x unified",
                    height=500,
                    template="plotly_white",
                    margin=dict(l=0, r=0, t=20, b=60),
                    showlegend=False,
                    xaxis=dict(
                        rangeslider=dict(visible=False),
                        rangeselector=dict(
                            buttons=[
                                dict(count=3,  label="3h",  step="hour",  stepmode="backward"),
                                dict(count=6,  label="6h",  step="hour",  stepmode="backward"),
                                dict(count=12, label="12h", step="hour",  stepmode="backward"),
                                dict(count=24, label="24h", step="hour",  stepmode="backward"),
                            ],
                            bgcolor="#f0f4ff", activecolor="#1a73e8",
                            font=dict(size=11),
                            x=0.055, y=1.08,
                            xanchor="left",
                        ),
                    ),
                    annotations=[
                        dict(text="<b>Zoom:</b>", x=0.0, y=1.10, xref="paper", yref="paper",
                             showarrow=False, font=dict(size=12, color="#555"),
                             xanchor="left", yanchor="middle"),
                    ],
                )

            st.plotly_chart(fig, use_container_width=True)

# ── Tab 2: Readings Table ─────────────────────────────────────────────────────
with tab_readings:
    all_readings = list(st.session_state.graph_data or []) + list(st.session_state.logbook_data or [])
    all_df = readings_to_df(all_readings)

    if all_df.empty:
        st.info("No readings available.")
    else:
        all_df = all_df.drop_duplicates("Timestamp").sort_values("Timestamp", ascending=False).copy()

        # Build display columns based on unit choice
        if unit_choice == "mg/dL":
            all_df["Glucose"] = all_df["Glucose_mg"].apply(lambda v: f"{v:.0f} mg/dL")
            status_col = all_df["Glucose_mg"].apply(
                lambda v: "HIGH" if v > target_high_mg else ("LOW" if v < target_low_mg else "In Range")
            )
        elif unit_choice == "mmol/L":
            all_df["Glucose"] = all_df["Glucose_mmol"].apply(lambda v: f"{v:.1f} mmol/L")
            status_col = all_df["Glucose_mg"].apply(
                lambda v: "HIGH" if v > target_high_mg else ("LOW" if v < target_low_mg else "In Range")
            )
        else:  # Both
            all_df["Glucose"] = all_df.apply(
                lambda r: f"{r['Glucose_mg']:.0f} mg/dL  |  {r['Glucose_mmol']:.1f} mmol/L", axis=1
            )
            status_col = all_df["Glucose_mg"].apply(
                lambda v: "HIGH" if v > target_high_mg else ("LOW" if v < target_low_mg else "In Range")
            )

        all_df["Status"] = status_col
        all_df["Time"] = all_df["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

        display_df = all_df[["Time", "Glucose", "Status"]].copy()

        def highlight_row(row):
            s = row["Status"]
            if s == "HIGH":
                return ["background-color: #fff0f0"] * len(row)
            elif s == "LOW":
                return ["background-color: #fff8f0"] * len(row)
            return [""] * len(row)

        styled = display_df.style.apply(highlight_row, axis=1)
        st.dataframe(styled, use_container_width=True, height=500)

# ── Tab 3: Statistics ─────────────────────────────────────────────────────────
with tab_stats:
    logbook_df = readings_to_df(st.session_state.logbook_data)

    if logbook_df.empty:
        st.info("No statistics data available.")
    else:
        vals_mg = logbook_df["Glucose_mg"]

        if unit_choice == "mmol/L":
            vals    = logbook_df["Glucose_mmol"]
            u_label = "mmol/L"
            avg_fmt = f"{vals.mean():.1f} mmol/L"
            min_fmt = f"{vals.min():.1f} mmol/L"
            max_fmt = f"{vals.max():.1f} mmol/L"
            std_fmt = f"{vals.std():.2f}"
        else:
            vals    = vals_mg
            u_label = "mg/dL"
            avg_fmt = f"{vals.mean():.1f} mg/dL"
            min_fmt = f"{vals.min():.0f} mg/dL"
            max_fmt = f"{vals.max():.0f} mg/dL"
            std_fmt = f"{vals.std():.1f}"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Average",  avg_fmt)
        c2.metric("Minimum",  min_fmt)
        c3.metric("Maximum",  max_fmt)
        c4.metric("Std Dev",  std_fmt)

        st.markdown("---")
        st.subheader("Time in Range (last ~14 days)")

        total      = len(vals_mg)
        low_pct    = (vals_mg < target_low_mg).sum()  / total * 100
        normal_pct = ((vals_mg >= target_low_mg) & (vals_mg <= target_high_mg)).sum() / total * 100
        high_pct   = (vals_mg > target_high_mg).sum() / total * 100

        if unit_choice == "mmol/L":
            range_label = f"{mg_to_mmol(target_low_mg):.1f}–{mg_to_mmol(target_high_mg):.1f} mmol/L"
        else:
            range_label = f"{target_low_mg}–{target_high_mg} mg/dL"

        col_l, col_n, col_h = st.columns(3)
        col_l.metric(f"🟠 Low (<{target_low_mg if unit_choice != 'mmol/L' else mg_to_mmol(target_low_mg)} {u_label})",  f"{low_pct:.1f}%")
        col_n.metric(f"🟢 In Range ({range_label})", f"{normal_pct:.1f}%")
        col_h.metric(f"🔴 High (>{target_high_mg if unit_choice != 'mmol/L' else mg_to_mmol(target_high_mg)} {u_label})", f"{high_pct:.1f}%")

        fig_pie = px.pie(
            values=[low_pct, normal_pct, high_pct],
            names=["Low", "In Range", "High"],
            color_discrete_sequence=["#e65c00", "#1a73e8", "#cc0000"],
            hole=0.55,
        )
        fig_pie.update_traces(textinfo="label+percent")
        fig_pie.update_layout(height=320, margin=dict(l=0, r=0, t=20, b=0), showlegend=True)
        st.plotly_chart(fig_pie, use_container_width=True)

        st.markdown("---")
        st.subheader("Daily Average Trend")
        logbook_df["Date"] = logbook_df["Timestamp"].dt.date

        if unit_choice == "mmol/L":
            daily = logbook_df.groupby("Date")["Glucose_mmol"].mean().reset_index()
            daily.columns = ["Date", "Avg"]
            bar_colors = ["#cc0000" if v > target_high_mmol else ("#e65c00" if v < target_low_mmol else "#1a73e8") for v in daily["Avg"]]
            y_title = "Average Glucose (mmol/L)"
            hlines  = [(target_low_mmol, "#e65c00"), (target_high_mmol, "#cc0000")]
        else:
            daily = logbook_df.groupby("Date")["Glucose_mg"].mean().reset_index()
            daily.columns = ["Date", "Avg"]
            bar_colors = ["#cc0000" if v > target_high_mg else ("#e65c00" if v < target_low_mg else "#1a73e8") for v in daily["Avg"]]
            y_title = "Average Glucose (mg/dL)"
            hlines  = [(target_low_mg, "#e65c00"), (target_high_mg, "#cc0000")]

        fig_daily = go.Figure(go.Bar(x=daily["Date"], y=daily["Avg"], marker_color=bar_colors))
        for h_val, h_col in hlines:
            fig_daily.add_hline(y=h_val, line_dash="dot", line_color=h_col)
        fig_daily.update_layout(
            xaxis_title="Date", yaxis_title=y_title,
            height=300, template="plotly_white",
            margin=dict(l=0, r=0, t=20, b=0),
        )
        st.plotly_chart(fig_daily, use_container_width=True)
