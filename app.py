import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
import io
import base64
import requests
from pathlib import Path
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
.main .block-container {
    padding-top: 0 !important;
    padding-bottom: 0.5rem !important;
    max-width: 100% !important;
}
.main .block-container > div:first-child {
    margin-top: 0 !important;
    padding-top: 0 !important;
}
header[data-testid="stHeader"] {
    height: 0 !important;
    min-height: 0 !important;
    padding: 0 !important;
    visibility: hidden !important;
    display: none !important;
}
/* Remove Streamlit's default top app padding */
.appview-container .main .block-container {
    padding-top: 0 !important;
}
div[data-testid="stAppViewContainer"] > section > div:first-child {
    padding-top: 0 !important;
}
h1 { margin-top: 0 !important; margin-bottom: 0.3rem !important; font-size: 1.4rem !important; }
h2 { margin-top: 0.2rem !important; margin-bottom: 0.2rem !important; }
hr { margin: 6px 0 !important; }
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
hr { border-top: 1px solid #e0e0e0; margin: 16px 0; }
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

/* ── Sidebar Width ── */
section[data-testid="stSidebar"] {
    min-width: 320px !important;
    max-width: 320px !important;
    width: 320px !important;
}

/* ── Compact Sidebar ── */
section[data-testid="stSidebar"] > div:first-child {
    padding-top: 0.5rem !important;
    padding-bottom: 0.5rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
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
MG_TO_MMOL  = 0.0555
CACHE_FILE  = Path(__file__).parent / "cache.json"
CALGARY_TZ  = ZoneInfo("America/Edmonton")  # Calgary / Mountain Time (MDT/MST)

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
    "nav_offset_days": 0,
    "nav_view": "day",
    "cache_df": None,         # Full merged DataFrame from cache.json
    "show_last_24h": True,    # Default: show last 24h on first load
    "auto_login_attempted": False,  # Only try auto-login once per session
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
        pid = patient.patient_id  # Use patient_id (connection UUID), not id
        latest  = api.latest(patient_identifier=pid)
        graph   = api.graph(patient_identifier=pid)
        try:
            logbook = api.logbook(patient_identifier=pid)
        except Exception:
            logbook = []
        st.session_state.latest_reading = latest
        st.session_state.graph_data     = graph
        st.session_state.logbook_data   = logbook
        st.session_state.last_update    = datetime.now(CALGARY_TZ)
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
        mg_val = r.value_in_mg_per_dl if r.value_in_mg_per_dl else r.value
        ts = r.factory_timestamp if hasattr(r, 'factory_timestamp') and r.factory_timestamp else r.timestamp
        rows.append({
            "Timestamp": ts,
            "Glucose_mg": mg_val,
            "Is High": r.is_high,
            "Is Low":  r.is_low,
        })
    df = pd.DataFrame(rows)
    # Convert UTC → Calgary (Mountain Time)
    df["Timestamp"] = (
        pd.to_datetime(df["Timestamp"], utc=True)
        .dt.tz_convert(CALGARY_TZ)
        .dt.tz_localize(None)  # drop tzinfo so Plotly/pandas treat as naive local time
    )
    df["Glucose_mmol"] = (df["Glucose_mg"] * MG_TO_MMOL).round(1)
    return df.sort_values("Timestamp")

# ─── Cache Functions ───────────────────────────────────────────────────────────
def load_cache_df() -> pd.DataFrame:
    """Load cache.json and return as a DataFrame. Returns empty DataFrame if not found."""
    if not CACHE_FILE.exists():
        return pd.DataFrame()
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
        readings = data.get("readings", [])
        if not readings:
            return pd.DataFrame()
        df = pd.DataFrame(readings)
        # Handle both key names: value_in_mg_per_dl (current) and value_mg_dl (legacy poller)
        if "value_in_mg_per_dl" in df.columns and "value_mg_dl" not in df.columns:
            df.rename(columns={"timestamp": "Timestamp", "value_in_mg_per_dl": "Glucose_mg"}, inplace=True)
        elif "value_mg_dl" in df.columns and "value_in_mg_per_dl" not in df.columns:
            df.rename(columns={"timestamp": "Timestamp", "value_mg_dl": "Glucose_mg"}, inplace=True)
        else:
            # Both present — prefer value_in_mg_per_dl, fill NaN from value_mg_dl
            df["Glucose_mg"] = df["value_in_mg_per_dl"].combine_first(df["value_mg_dl"])
            df.rename(columns={"timestamp": "Timestamp"}, inplace=True)
        # Timestamps in cache.json are Calgary local naive strings (no UTC conversion needed).
        # If a timestamp has a UTC offset (legacy entries), convert it to Calgary naive.
        def parse_ts(ts_str):
            try:
                ts = pd.Timestamp(ts_str)
                if ts.tzinfo is not None:
                    # Has timezone info — convert to Calgary naive
                    return ts.tz_convert(CALGARY_TZ).tz_localize(None)
                return ts  # already naive Calgary local
            except Exception:
                return pd.NaT
        df["Timestamp"] = df["Timestamp"].apply(parse_ts)
        df = df.dropna(subset=["Timestamp", "Glucose_mg"])
        df["Glucose_mg"] = pd.to_numeric(df["Glucose_mg"], errors="coerce")
        df = df.dropna(subset=["Glucose_mg"])
        df["Glucose_mmol"] = (df["Glucose_mg"] * MG_TO_MMOL).round(1)
        df["Is High"] = False
        df["Is Low"]  = False
        return df.drop_duplicates("Timestamp").sort_values("Timestamp").reset_index(drop=True)
    except Exception as e:
        st.warning(f"Could not load cache: {e}")
        return pd.DataFrame()

def save_cache(df: pd.DataFrame):
    """Save a DataFrame back to cache.json."""
    try:
        readings = []
        for _, row in df.iterrows():
            readings.append({
                "timestamp": row["Timestamp"].isoformat(),
                "value_in_mg_per_dl": float(row["Glucose_mg"]),
                "trend": str(row.get("trend", "") or ""),
                "source": str(row.get("source", "csv") or "csv"),
            })
        data = {
            "readings": readings,
            "last_updated": datetime.now(CALGARY_TZ).isoformat(),
            "source": "merged",
        }
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        st.error(f"Could not save cache: {e}")
        return False

# ─── GitHub Repo Constants ────────────────────────────────────────────────────
GITHUB_REPO  = "waves-s/cgm-dashboard"
GITHUB_PATH  = "cache.json"   # path inside the repo
GITHUB_BRANCH = "main"

def commit_cache_to_github(df: pd.DataFrame) -> tuple[bool, str]:
    """
    Serialise df to cache.json format and commit it directly to the GitHub repo
    via the GitHub Contents API.  Requires a GH_PAT secret in Streamlit secrets
    with repo write access.

    Returns (success: bool, message: str).
    """
    try:
        # Read token from Streamlit secrets
        gh_token = st.secrets.get("github", {}).get("pat") or st.secrets.get("GH_PAT", "")
        if not gh_token:
            return False, "GitHub token not found in secrets. Add [github] pat = '...' to Streamlit secrets."

        # Build the JSON payload
        readings = []
        for _, row in df.iterrows():
            readings.append({
                "timestamp": row["Timestamp"].isoformat(),
                "value_in_mg_per_dl": float(row["Glucose_mg"]),
                "trend": str(row.get("trend", "") or ""),
                "source": str(row.get("source", "csv") or "csv"),
            })
        data = {
            "readings": readings,
            "last_updated": datetime.now(CALGARY_TZ).isoformat(),
            "source": "merged",
        }
        content_str = json.dumps(data, indent=2)
        content_b64 = base64.b64encode(content_str.encode()).decode()

        headers = {
            "Authorization": f"token {gh_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"

        # Get the current file SHA (needed to update an existing file)
        get_resp = requests.get(api_url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=15)
        sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

        # Commit the new content
        payload = {
            "message": f"seed: upload {len(readings):,} historical readings via dashboard",
            "content": content_b64,
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha  # required when updating an existing file

        put_resp = requests.put(api_url, headers=headers, json=payload, timeout=30)
        if put_resp.status_code in (200, 201):
            return True, f"✅ {len(readings):,} readings committed to GitHub repo — visible to everyone worldwide."
        else:
            detail = put_resp.json().get("message", put_resp.text[:200])
            return False, f"GitHub API error {put_resp.status_code}: {detail}"

    except Exception as e:
        return False, f"Commit failed: {e}"


def parse_libreview_csv(uploaded_file) -> pd.DataFrame:
    """
    Parse a LibreView CSV export file.
    LibreView CSV has metadata rows at the top; glucose data starts after the header row
    containing 'Device Timestamp'.
    """
    try:
        content = uploaded_file.read().decode("utf-8", errors="replace")
        lines = content.splitlines()

        # Find the header row (contains 'Device Timestamp')
        header_idx = None
        for i, line in enumerate(lines):
            if "Device Timestamp" in line or "device timestamp" in line.lower():
                header_idx = i
                break

        if header_idx is None:
            return pd.DataFrame(), "Could not find 'Device Timestamp' column in CSV. Please use a LibreView export file."

        # Parse from the header row onwards
        csv_content = "\n".join(lines[header_idx:])
        df = pd.read_csv(io.StringIO(csv_content))

        # Normalise column names
        df.columns = [c.strip() for c in df.columns]

        # Find timestamp column
        ts_col = next((c for c in df.columns if "timestamp" in c.lower()), None)
        if ts_col is None:
            return pd.DataFrame(), "Could not find timestamp column."

        # Find glucose value column — LibreView uses 'Historic Glucose mg/dL' or 'Historic Glucose mmol/L'
        # or 'Scan Glucose mg/dL' / 'Scan Glucose mmol/L'
        glucose_col_mg   = next((c for c in df.columns if "historic glucose mg" in c.lower() or "scan glucose mg" in c.lower()), None)
        glucose_col_mmol = next((c for c in df.columns if "historic glucose mmol" in c.lower() or "scan glucose mmol" in c.lower()), None)

        if glucose_col_mg is None and glucose_col_mmol is None:
            # Try generic fallback
            glucose_col_mg = next((c for c in df.columns if "glucose" in c.lower() and "mg" in c.lower()), None)
            glucose_col_mmol = next((c for c in df.columns if "glucose" in c.lower() and "mmol" in c.lower()), None)

        if glucose_col_mg is None and glucose_col_mmol is None:
            return pd.DataFrame(), f"Could not find glucose column. Available columns: {list(df.columns)}"

        # Build result DataFrame
        result = pd.DataFrame()
        # CONFIRMED: LibreView CSV timestamps are already in the device/account local time
        # (Calgary Mountain Time). Parse as naive datetimes — no timezone conversion needed.
        # dayfirst=True handles the DD-MM-YYYY format used by LibreView.
        result["Timestamp"] = pd.to_datetime(df[ts_col], errors="coerce", dayfirst=True)
        result = result.dropna(subset=["Timestamp"])

        if glucose_col_mg:
            result["Glucose_mg"] = pd.to_numeric(df[glucose_col_mg], errors="coerce")
        else:
            # Convert mmol/L to mg/dL
            result["Glucose_mg"] = pd.to_numeric(df[glucose_col_mmol], errors="coerce") / MG_TO_MMOL

        result = result.dropna(subset=["Glucose_mg"])
        result["Glucose_mmol"] = (result["Glucose_mg"] * MG_TO_MMOL).round(1)
        result["Is High"] = False
        result["Is Low"]  = False
        result["source"]  = "csv"
        result["trend"]   = "STABLE"

        return result.drop_duplicates("Timestamp").sort_values("Timestamp").reset_index(drop=True), None

    except Exception as e:
        return pd.DataFrame(), f"Error parsing CSV: {e}"

def merge_with_cache(new_df: pd.DataFrame, existing_df: pd.DataFrame) -> pd.DataFrame:
    """Merge two DataFrames, deduplicate by Timestamp, sort by time."""
    if new_df.empty:
        return existing_df
    if existing_df.empty:
        return new_df
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    combined = combined.drop_duplicates("Timestamp").sort_values("Timestamp").reset_index(drop=True)
    return combined

def get_full_df() -> pd.DataFrame:
    """
    Return the full merged DataFrame:
    cache.json (background-polled + CSV history) + current live session data.
    """
    # Load from cache file (background poller writes here every 5 min)
    cache_df = load_cache_df()

    # Also merge current live session data
    live_readings = list(st.session_state.graph_data or []) + list(st.session_state.logbook_data or [])
    live_df = readings_to_df(live_readings)

    return merge_with_cache(live_df, cache_df)

# ─── Auto-Login from Streamlit Secrets ────────────────────────────────────────
# Attempt silent authentication on first page load so visitors never see a login form.
# authenticate() is now defined above, so this call is safe.
if not st.session_state.authenticated and not st.session_state.auto_login_attempted:
    st.session_state.auto_login_attempted = True
    try:
        # Support both [libreview] table and flat LIBREVIEW_* keys
        if "libreview" in st.secrets:
            _auto_email    = st.secrets["libreview"]["email"]
            _auto_password = st.secrets["libreview"]["password"]
        elif "LIBREVIEW_EMAIL" in st.secrets:
            _auto_email    = st.secrets["LIBREVIEW_EMAIL"]
            _auto_password = st.secrets["LIBREVIEW_PASSWORD"]
        else:
            _auto_email = _auto_password = None

        if _auto_email and _auto_password:
            authenticate(_auto_email, _auto_password, "US")
            # authenticate() sets st.session_state.authenticated = True on success
    except Exception:
        pass  # Secrets not configured — fall back to manual login form

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📊 CGM Dashboard")
    st.markdown("---")

    # ── Units (always visible — no login required) ─────────────────────────────
    st.markdown("### 📐 Units")
    unit_choice = st.radio(
        "Display units",
        options=["mg/dL", "mmol/L", "Both"],
        index=1,  # default: mmol/L
        horizontal=True,
    )

    st.markdown("---")

    # ── Target Range (always visible) ─────────────────────────────────────────
    st.markdown("### 🎯 Target Range")
    if unit_choice == "mmol/L":
        low_default  = 4.0
        high_default = 6.0
        low_mmol  = st.number_input("Low (mmol/L)",  min_value=1.0, max_value=10.0, value=low_default,  step=0.1, format="%.1f")
        high_mmol = st.number_input("High (mmol/L)", min_value=5.0, max_value=25.0, value=high_default, step=0.1, format="%.1f")
        target_low_mg  = round(low_mmol  / MG_TO_MMOL)
        target_high_mg = round(high_mmol / MG_TO_MMOL)
        st.caption(f"≈ {target_low_mg:.0f} – {target_high_mg:.0f} mg/dL")
    else:
        target_low_mg  = st.number_input("Low (mg/dL)",  min_value=40,  max_value=180, value=70,  step=1)
        target_high_mg = st.number_input("High (mg/dL)", min_value=100, max_value=400, value=180, step=1)
        st.caption(f"≈ {mg_to_mmol(target_low_mg):.1f} – {mg_to_mmol(target_high_mg):.1f} mmol/L")

    st.markdown("---")

    # ── Refresh (only when live API is connected) ──────────────────────────────
    if st.session_state.authenticated:
        st.markdown("### 🔄 Refresh")
        refresh_interval = st.selectbox(
            "Auto-refresh every",
            options=[1, 5, 10, 15, 30],
            index=1,
            format_func=lambda x: f"{x} min"
        )
        if st.button("🔄 Refresh Now", use_container_width=True):
            if st.session_state.selected_patient:
                with st.spinner("Fetching latest readings…"):
                    fetch_data(st.session_state.selected_patient)
                st.rerun()

        if st.session_state.last_update:
            lu = st.session_state.last_update
            tz_abbr = lu.strftime("%Z") if lu.tzinfo else "MT"
            st.caption(f"Last fetched: {lu.strftime('%H:%M:%S')} {tz_abbr}")
    else:
        refresh_interval = 5  # default when not authenticated

    # Show cache status
    cache_df_info = load_cache_df()
    if not cache_df_info.empty:
        oldest = cache_df_info["Timestamp"].min().strftime("%b %d, %Y")
        newest = cache_df_info["Timestamp"].max().strftime("%b %d %H:%M")
        st.caption(f"📦 Cache: {len(cache_df_info):,} readings\n{oldest} → {newest}")

    st.markdown("---")

    # ── Historical Data (CSV Upload) ───────────────────────────────────────────
    st.markdown("### 📁 Historical Data")
    st.caption(
        "Upload a LibreView CSV to permanently store history in GitHub. "
        "Once committed, every viewer worldwide sees the full history."
    )

    uploaded = st.file_uploader(
        "Upload LibreView CSV",
        type=["csv"],
        label_visibility="collapsed",
        help="Download from LibreView website → Glucose History → Download glucose data"
    )
    if uploaded is not None:
        with st.spinner("Parsing CSV…"):
            csv_df, err = parse_libreview_csv(uploaded)
        if err:
            st.error(f"CSV error: {err}")
        elif csv_df.empty:
            st.warning("No glucose readings found in CSV.")
        else:
            existing = load_cache_df()
            merged   = merge_with_cache(csv_df, existing)
            added    = len(merged) - len(existing)
            with st.spinner(f"Committing {len(merged):,} readings to GitHub repo…"):
                ok, msg = commit_cache_to_github(merged)
            if ok:
                save_cache(merged)
                st.success(f"{msg}\n+{added:,} new readings added ({len(merged):,} total).")
                st.rerun()
            else:
                save_cache(merged)
                st.warning(
                    f"⚠️ Could not commit to GitHub: {msg}\n\n"
                    "Data saved for this session only."
                )
                st.rerun()

    # ── Admin: manual login (hidden at bottom, only shown when not auto-logged in) ──
    if not st.session_state.authenticated:
        st.markdown("---")
        with st.expander("🔐 Admin Login", expanded=False):
            _email    = st.text_input("LibreView Email", placeholder="you@example.com", key="manual_email")
            _password = st.text_input("Password", type="password", key="manual_password")
            _region   = st.selectbox("Region", options=["US", "EU", "EU2", "CA", "AU", "AE", "DE", "FR", "JP", "RU"], index=0, key="manual_region")
            if st.button("Login", use_container_width=True, type="primary", key="manual_login_btn"):
                if _email and _password:
                    with st.spinner("Authenticating…"):
                        ok, err = authenticate(_email, _password, _region)
                    if ok:
                        st.success("Logged in!")
                        st.rerun()
                    else:
                        st.error(err)
                else:
                    st.warning("Please enter email and password.")
    else:
        if len(st.session_state.patients) > 1:
            patient_names = [f"{p.first_name} {p.last_name}" for p in st.session_state.patients]
            idx = st.selectbox("Patient", range(len(patient_names)), format_func=lambda i: patient_names[i])
            st.session_state.selected_patient = st.session_state.patients[idx]
        st.markdown("---")
        if st.button("🚪 Logout", use_container_width=True):
            for k in ["api", "authenticated", "patients", "selected_patient",
                      "latest_reading", "graph_data", "logbook_data", "last_update"]:
                st.session_state[k] = None if k in ["api", "selected_patient", "latest_reading", "last_update"] else []
            st.session_state.authenticated = False
            st.rerun()

# ─── Auto-refresh ─────────────────────────────────────────────────────────────
# Always fetch live data on every page load/refresh when authenticated.
# This ensures the chart is always up to date regardless of GitHub Actions schedule.
if st.session_state.authenticated and st.session_state.selected_patient:
    if st.session_state.last_update is None:
        with st.spinner("Loading latest readings…"):
            fetch_data(st.session_state.selected_patient)
    else:
        # Re-fetch on every page load (Streamlit reruns), but throttle to at most
        # once every 60 seconds to avoid hammering the LibreView API on rapid reruns
        elapsed = (datetime.now(CALGARY_TZ) - st.session_state.last_update).total_seconds()
        if elapsed >= 60:
            fetch_data(st.session_state.selected_patient)

# ─── Main Content ─────────────────────────────────────────────────────────────
st.markdown(
    '<div style="margin-top:-3rem;padding-top:0.5rem;margin-bottom:0.2rem;">'
    '<span style="font-size:1.3rem;font-weight:800;">📊 CGM Dashboard</span>'
    '</div>',
    unsafe_allow_html=True
)
st.markdown('<hr style="margin:4px 0 8px 0;">', unsafe_allow_html=True)

# ─── Latest Reading Header (only when live API data is available) ─────────────
latest = st.session_state.latest_reading

# Show live reading header only when live API data is available
if latest is not None:
    latest_mg = float(latest.value_in_mg_per_dl if latest.value_in_mg_per_dl else latest.value)
    trend_obj  = latest.trend_arrow if hasattr(latest, 'trend_arrow') else None
    trend_text = TREND_LABELS.get(trend_obj, "→") if trend_obj else "→"
    status_label, glucose_class, badge_class = glucose_status(latest_mg, target_low_mg, target_high_mg)

    if unit_choice == "mmol/L":
        display_val  = f"{mg_to_mmol(latest_mg):.1f}"
        display_unit = "mmol/L"
    elif unit_choice == "Both":
        display_val  = f"{latest_mg:.0f} / {mg_to_mmol(latest_mg):.1f}"
        display_unit = "mg/dL  |  mmol/L"
    else:
        display_val  = f"{latest_mg:.0f}"
        display_unit = "mg/dL"

    ts = latest.factory_timestamp if hasattr(latest, 'factory_timestamp') and latest.factory_timestamp else latest.timestamp
    if hasattr(ts, 'astimezone'):
        ts_calgary = ts.astimezone(CALGARY_TZ)
        tz_abbr = ts_calgary.strftime("%Z")
        reading_time_str = ts_calgary.strftime(f"%b %d, %Y  %H:%M:%S {tz_abbr}")
    else:
        reading_time_str = str(ts)

    col_glucose, col_trend, col_status, col_last = st.columns([2, 1, 1, 2])
    with col_glucose:
        st.markdown(
            f'<div class="glucose-display {glucose_class}">{display_val}</div>'
            f'<div style="font-size:14px;color:#888;margin-top:4px;">{display_unit}</div>',
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
        if unit_choice == "mg/dL":
            st.caption(f"≈ {mg_to_mmol(latest_mg):.1f} mmol/L")
        elif unit_choice == "mmol/L":
            st.caption(f"≈ {latest_mg:.0f} mg/dL")
    st.markdown("---")

# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab_chart, tab_readings, tab_stats = st.tabs(["📈 Trend Chart", "📋 All Readings", "📊 Statistics"])

# ─── Get Full Merged Data ─────────────────────────────────────────────────────
full_df = get_full_df()

# ── Tab 1: Chart ──────────────────────────────────────────────────────────────
with tab_chart:
    if full_df.empty:
        st.info("No chart data available. Click Refresh Now in the sidebar.")
    else:
        wide_df = full_df.copy()

        # ── Time Navigation Controls ──────────────────────────────────────────
        data_min_date  = wide_df["Timestamp"].min().date()
        data_max_date  = wide_df["Timestamp"].max().date()
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

        st.session_state.nav_offset_days = max(min_offset, min(0, st.session_state.nav_offset_days))
        offset = st.session_state.nav_offset_days

        with nav_col2:
            st.write("")
            if st.button("⏮ Oldest", use_container_width=True):
                st.session_state.nav_offset_days = min_offset
                st.session_state.show_last_24h = False
                st.rerun()
        with nav_col3:
            st.write("")
            step = 1 if st.session_state.nav_view == "day" else 7
            if st.button("◄ Back", use_container_width=True):
                st.session_state.nav_offset_days = max(min_offset, offset - step)
                st.session_state.show_last_24h = False
                st.rerun()
        with nav_col4:
            st.write("")
            if st.button("Forward ►", use_container_width=True):
                st.session_state.nav_offset_days = min(0, offset + step)
                st.session_state.show_last_24h = False
                st.rerun()
        with nav_col5:
            st.write("")
            if st.button("Latest ⏭", use_container_width=True):
                st.session_state.nav_offset_days = 0
                st.session_state.nav_view = "day"
                st.session_state.show_last_24h = True
                st.rerun()

        anchor_date = data_max_date + timedelta(days=st.session_state.nav_offset_days)

        # ── Latest ⏭ mode: show rolling last-24h window ────────────────────────────
        if st.session_state.show_last_24h and st.session_state.nav_view == "day":
            latest_ts   = wide_df["Timestamp"].max()
            window_end   = latest_ts
            window_start = latest_ts - timedelta(hours=24)
            period_label = f"Last 24 hours  (–{latest_ts.strftime('%b %d %H:%M')} MT)"
        elif st.session_state.nav_view == "day":
            window_start = datetime.combine(anchor_date, datetime.min.time())
            window_end   = datetime.combine(anchor_date, datetime.max.time())
            period_label = anchor_date.strftime("%A, %b %d %Y")
        else:
            # Any week navigation clears the 24h mode
            st.session_state.show_last_24h = False
            week_start   = anchor_date - timedelta(days=anchor_date.weekday())
            week_end     = week_start + timedelta(days=6)
            window_start = datetime.combine(week_start, datetime.min.time())
            window_end   = datetime.combine(week_end,   datetime.max.time())
            period_label = f"Week of {week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}"
            week_days    = [week_start + timedelta(days=i) for i in range(7)]

        with nav_col6:
            st.markdown(
                f'<div style="padding-top:28px;font-size:15px;font-weight:600;color:#333;">📅 {period_label}</div>',
                unsafe_allow_html=True
            )

        # ── Calendar date picker (Day view only) ──────────────────────────────
        if st.session_state.nav_view == "day" and available_dates:
            cal_col1, cal_col2 = st.columns([1, 3])
            with cal_col1:
                st.markdown('<div style="padding-top:6px;font-size:13px;font-weight:600;color:#555;">🗓️ Jump to date:</div>',
                            unsafe_allow_html=True)
            with cal_col2:
                # value= always reflects current anchor_date so the widget stays in sync.
                # When user picks a different date, picked != anchor_date triggers rerun.
                picked = st.date_input(
                    "jump_date",
                    value=anchor_date,
                    min_value=data_min_date,
                    max_value=data_max_date,
                    label_visibility="collapsed",
                )
                if picked != anchor_date:
                    new_offset = (picked - data_max_date).days
                    st.session_state.nav_offset_days = max(min_offset, min(0, new_offset))
                    st.session_state.show_last_24h = False
                    st.rerun()

        chart_df = wide_df[
            (wide_df["Timestamp"] >= window_start) &
            (wide_df["Timestamp"] <= window_end)
        ].copy()

        if chart_df.empty:
            st.info(f"No readings found for {period_label}.")
        else:
            target_low_mmol  = round(target_low_mg  * MG_TO_MMOL, 1)
            target_high_mmol = round(target_high_mg * MG_TO_MMOL, 1)

            def centered_yrange_mg(tgt_lo, tgt_hi, data_min, data_max):
                tgt_centre = (tgt_lo + tgt_hi) / 2
                tgt_half   = (tgt_hi - tgt_lo) / 2
                half_span  = max(tgt_half * 3.0, 60)
                half_span  = max(half_span, tgt_centre - data_min + 20, data_max - tgt_centre + 20)
                y_min = max(0, tgt_centre - half_span)
                y_max = tgt_centre + half_span
                return y_min, y_max

            def build_day_chart(day_df, day_label, unit_choice,
                                target_low_mg, target_high_mg,
                                target_low_mmol, target_high_mmol,
                                show_zoom_buttons=True):
                """Build a single-day Plotly figure with target bands and midnight dotted lines."""
                if day_df.empty:
                    return None

                data_min_mg = day_df["Glucose_mg"].min()
                data_max_mg = day_df["Glucose_mg"].max()
                y_min_mg, y_max_mg = centered_yrange_mg(target_low_mg, target_high_mg, data_min_mg, data_max_mg)
                y_min_mmol = round(y_min_mg * MG_TO_MMOL, 1)
                y_max_mmol = round(y_max_mg * MG_TO_MMOL, 1)

                fig = go.Figure()

                rangeselector_cfg = dict(
                    buttons=[
                        dict(count=3,  label="3h",  step="hour", stepmode="backward"),
                        dict(count=6,  label="6h",  step="hour", stepmode="backward"),
                        dict(count=12, label="12h", step="hour", stepmode="backward"),
                        dict(count=24, label="24h", step="hour", stepmode="backward"),
                    ],
                    bgcolor="#f0f4ff", activecolor="#1a73e8",
                    font=dict(size=11),
                    x=0.055, y=1.08,
                    xanchor="left",
                ) if show_zoom_buttons else None

                zoom_annotation = dict(
                    text="<b>Zoom:</b>", x=0.0, y=1.10, xref="paper", yref="paper",
                    showarrow=False, font=dict(size=12, color="#555"),
                    xanchor="left", yanchor="middle"
                ) if show_zoom_buttons else None

                if unit_choice == "Both":
                    colors_mg = day_df["Glucose_mg"].apply(
                        lambda v: "#cc0000" if v > target_high_mg else ("#e65c00" if v < target_low_mg else "#1a73e8")
                    )
                    fig.add_trace(go.Scatter(
                        x=day_df["Timestamp"], y=day_df["Glucose_mg"],
                        mode="lines+markers", name="mg/dL", yaxis="y1",
                        line=dict(color="#1a73e8", width=2),
                        marker=dict(color=colors_mg, size=6),
                        hovertemplate="%{x|%H:%M}<br><b>%{y:.0f} mg/dL</b><extra></extra>"
                    ))
                    fig.add_trace(go.Scatter(
                        x=day_df["Timestamp"], y=day_df["Glucose_mmol"],
                        mode="lines", name="mmol/L", yaxis="y2",
                        line=dict(color="#1a73e8", width=0), showlegend=True,
                        hovertemplate="%{x|%H:%M}<br><b>%{y:.1f} mmol/L</b><extra></extra>"
                    ))
                    fig.add_hrect(y0=target_low_mg, y1=target_high_mg,
                                  fillcolor="rgba(0,200,0,0.07)", line_width=0,
                                  annotation_text="Target Range", annotation_position="top left")
                    fig.add_hline(y=target_low_mg,  line_dash="dot", line_color="#e65c00",
                                  annotation_text=f"Low ({target_low_mg} mg/dL)", annotation_position="bottom right")
                    fig.add_hline(y=target_high_mg, line_dash="dot", line_color="#cc0000",
                                  annotation_text=f"High ({target_high_mg} mg/dL)", annotation_position="top right")
                    layout_extra = dict(
                        yaxis=dict(title="Glucose (mg/dL)", range=[y_min_mg, y_max_mg], side="left"),
                        yaxis2=dict(title="Glucose (mmol/L)", range=[y_min_mmol, y_max_mmol],
                                    overlaying="y", side="right", showgrid=False),
                        legend=dict(orientation="h", y=1.05),
                    )
                else:
                    if unit_choice == "mmol/L":
                        y_col, y_label = "Glucose_mmol", "Glucose (mmol/L)"
                        y_range = [y_min_mmol, y_max_mmol]
                        tgt_low, tgt_high = target_low_mmol, target_high_mmol
                        low_ann  = f"Low ({target_low_mmol} mmol/L)"
                        high_ann = f"High ({target_high_mmol} mmol/L)"
                        hover_fmt = "%{x|%H:%M}<br><b>%{y:.1f} mmol/L</b><extra></extra>"
                    else:
                        y_col, y_label = "Glucose_mg", "Glucose (mg/dL)"
                        y_range = [y_min_mg, y_max_mg]
                        tgt_low, tgt_high = target_low_mg, target_high_mg
                        low_ann  = f"Low ({target_low_mg} mg/dL)"
                        high_ann = f"High ({target_high_mg} mg/dL)"
                        hover_fmt = "%{x|%H:%M}<br><b>%{y:.0f} mg/dL</b><extra></extra>"

                    colors = day_df[y_col].apply(
                        lambda v: "#cc0000" if v > tgt_high else ("#e65c00" if v < tgt_low else "#1a73e8")
                    )
                    fig.add_hrect(y0=tgt_low, y1=tgt_high,
                                  fillcolor="rgba(0,200,0,0.07)", line_width=0,
                                  annotation_text="Target Range", annotation_position="top left")
                    fig.add_trace(go.Scatter(
                        x=day_df["Timestamp"], y=day_df[y_col],
                        mode="lines+markers", name="Glucose",
                        line=dict(color="#1a73e8", width=2),
                        marker=dict(color=colors, size=7),
                        hovertemplate=hover_fmt
                    ))
                    fig.add_hline(y=tgt_low,  line_dash="dot", line_color="#e65c00",
                                  annotation_text=low_ann,  annotation_position="bottom right")
                    fig.add_hline(y=tgt_high, line_dash="dot", line_color="#cc0000",
                                  annotation_text=high_ann, annotation_position="top right")
                    layout_extra = dict(
                        yaxis=dict(title=y_label, range=y_range),
                        showlegend=False,
                    )

                xaxis_cfg = dict(rangeslider=dict(visible=False), title="Time")
                if show_zoom_buttons and rangeselector_cfg:
                    xaxis_cfg["rangeselector"] = rangeselector_cfg

                annotations = []
                if show_zoom_buttons and zoom_annotation:
                    annotations.append(zoom_annotation)

                # t=55 gives room for zoom buttons (rangeselector) without overlapping date label
                right_margin = 60 if unit_choice == "Both" else 0
                fig.update_layout(
                    hovermode="x unified", height=420, template="plotly_white",
                    margin=dict(l=0, r=right_margin, t=55, b=50),
                    xaxis=xaxis_cfg,
                    annotations=annotations,
                    **layout_extra,
                )
                return fig

            # ── Day View ──────────────────────────────────────────────────────
            if st.session_state.nav_view == "day":
                date_str = anchor_date.strftime("%A, %B %d, %Y")
                st.markdown(
                    f'<div style="font-size:13px;font-weight:600;color:#1a73e8;'
                    f'background:#f0f4ff;border:1px solid #c5d3f5;border-radius:8px;'
                    f'padding:5px 14px;display:inline-block;margin-bottom:6px;">'
                    f'📆 {date_str}</div>',
                    unsafe_allow_html=True
                )
                fig = build_day_chart(
                    chart_df, date_str, unit_choice,
                    target_low_mg, target_high_mg,
                    target_low_mmol, target_high_mmol,
                    show_zoom_buttons=True
                )
                if fig:
                    st.plotly_chart(fig, use_container_width=True)

            # ── Week View: one chart per day ──────────────────────────────────
            else:
                st.markdown(
                    f'<div style="font-size:13px;font-weight:600;color:#1a73e8;'
                    f'background:#f0f4ff;border:1px solid #c5d3f5;border-radius:8px;'
                    f'padding:5px 14px;display:inline-block;margin-bottom:10px;">'
                    f'📆 {period_label}</div>',
                    unsafe_allow_html=True
                )
                for day in week_days:
                    day_start = datetime.combine(day, datetime.min.time())
                    day_end   = datetime.combine(day, datetime.max.time())
                    day_df    = chart_df[
                        (chart_df["Timestamp"] >= day_start) &
                        (chart_df["Timestamp"] <= day_end)
                    ].copy()
                    day_label = day.strftime("%A, %B %d, %Y")
                    if day_df.empty:
                        st.markdown(
                            f'<div style="font-size:12px;color:#999;padding:4px 0;">{day_label} — no data</div>',
                            unsafe_allow_html=True
                        )
                        continue
                    fig = build_day_chart(
                        day_df, day_label, unit_choice,
                        target_low_mg, target_high_mg,
                        target_low_mmol, target_high_mmol,
                        show_zoom_buttons=False  # no zoom buttons in week view to keep it compact
                    )
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
                    st.markdown('<hr style="border-top:1px dashed #ccc;margin:4px 0 8px 0;">', unsafe_allow_html=True)

# ── Tab 2: Readings Table ─────────────────────────────────────────────────────
with tab_readings:
    if full_df.empty:
        st.info("No readings available.")
    else:
        all_df = full_df.drop_duplicates("Timestamp").sort_values("Timestamp", ascending=False).copy()

        if unit_choice == "mg/dL":
            all_df["Glucose"] = all_df["Glucose_mg"].apply(lambda v: f"{v:.0f} mg/dL")
        elif unit_choice == "mmol/L":
            all_df["Glucose"] = all_df["Glucose_mmol"].apply(lambda v: f"{v:.1f} mmol/L")
        else:
            all_df["Glucose"] = all_df.apply(
                lambda r: f"{r['Glucose_mg']:.0f} mg/dL  |  {r['Glucose_mmol']:.1f} mmol/L", axis=1
            )

        all_df["Status"] = all_df["Glucose_mg"].apply(
            lambda v: "HIGH" if v > target_high_mg else ("LOW" if v < target_low_mg else "In Range")
        )
        all_df["Time"] = all_df["Timestamp"].dt.strftime("%Y-%m-%d %H:%M") + " MT"

        display_df = all_df[["Time", "Glucose", "Status"]].copy()
        # Ensure all columns are plain strings — avoids Styler serialisation errors
        display_df["Time"]    = display_df["Time"].astype(str)
        display_df["Glucose"] = display_df["Glucose"].astype(str)
        display_df["Status"]  = display_df["Status"].astype(str)
        display_df = display_df.reset_index(drop=True)

        st.caption(f"Showing {len(display_df):,} readings")
        st.dataframe(
            display_df,
            use_container_width=True,
            height=500,
            column_config={
                "Status": st.column_config.TextColumn(
                    "Status",
                    help="HIGH = above target  |  LOW = below target  |  In Range = within target",
                ),
            },
            hide_index=True,
        )

# ── Tab 3: Statistics ─────────────────────────────────────────────────────────
with tab_stats:
    if full_df.empty:
        st.info("No statistics data available.")
    else:
        stats_df = full_df.copy()
        vals_mg  = stats_df["Glucose_mg"]

        if unit_choice == "mmol/L":
            vals    = stats_df["Glucose_mmol"]
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

        date_range_str = (f"{stats_df['Timestamp'].min().strftime('%b %d, %Y')} – "
                          f"{stats_df['Timestamp'].max().strftime('%b %d, %Y')}")
        st.caption(f"Statistics based on {len(stats_df):,} readings  ·  {date_range_str}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Average",  avg_fmt)
        c2.metric("Minimum",  min_fmt)
        c3.metric("Maximum",  max_fmt)
        c4.metric("Std Dev",  std_fmt)

        st.markdown("---")
        st.subheader("Time in Range")

        total      = len(vals_mg)
        low_pct    = (vals_mg < target_low_mg).sum()  / total * 100
        normal_pct = ((vals_mg >= target_low_mg) & (vals_mg <= target_high_mg)).sum() / total * 100
        high_pct   = (vals_mg > target_high_mg).sum() / total * 100

        if unit_choice == "mmol/L":
            range_label = f"{mg_to_mmol(target_low_mg):.1f}–{mg_to_mmol(target_high_mg):.1f} mmol/L"
            low_thr  = f"{mg_to_mmol(target_low_mg):.1f}"
            high_thr = f"{mg_to_mmol(target_high_mg):.1f}"
        else:
            range_label = f"{target_low_mg}–{target_high_mg} mg/dL"
            low_thr  = str(target_low_mg)
            high_thr = str(target_high_mg)

        col_l, col_n, col_h = st.columns(3)
        col_l.metric(f"🟠 Low (<{low_thr} {u_label})",         f"{low_pct:.1f}%")
        col_n.metric(f"🟢 In Range ({range_label})",            f"{normal_pct:.1f}%")
        col_h.metric(f"🔴 High (>{high_thr} {u_label})",        f"{high_pct:.1f}%")

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
        stats_df["Date"] = stats_df["Timestamp"].dt.date

        target_low_mmol  = round(target_low_mg  * MG_TO_MMOL, 1)
        target_high_mmol = round(target_high_mg * MG_TO_MMOL, 1)

        if unit_choice == "mmol/L":
            daily = stats_df.groupby("Date")["Glucose_mmol"].mean().reset_index()
            daily.columns = ["Date", "Avg"]
            bar_colors = ["#cc0000" if v > target_high_mmol else ("#e65c00" if v < target_low_mmol else "#1a73e8") for v in daily["Avg"]]
            y_title = "Average Glucose (mmol/L)"
            hlines  = [(target_low_mmol, "#e65c00"), (target_high_mmol, "#cc0000")]
        else:
            daily = stats_df.groupby("Date")["Glucose_mg"].mean().reset_index()
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
