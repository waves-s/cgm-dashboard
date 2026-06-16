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
MG_TO_MMOL        = 0.0555
CACHE_FILE        = Path(__file__).parent / "cache.json"
RENPHO_CACHE_FILE = Path(__file__).parent / "renpho_cache.json"
CALGARY_TZ        = ZoneInfo("America/Edmonton")  # Calgary / Mountain Time (MDT/MST)

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
    "rate_limit_until": 0,            # Timestamp when rate limit expires
    "renpho_df": None,                 # Cached Renpho DataFrame
    "renpho_selected_metrics": None,   # Selected metrics for Renpho chart
    "renpho_weight_unit": "lb",         # Weight display unit: 'lb' or 'kg'
    "renpho_date_range_days": 0,        # 0 = all time; otherwise number of days
    "renpho_upload_done": False,        # Flag to suppress rerun loop after upload
    "compare_days": [],                  # List of date strings for Day Comparison mode
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
        # Store when we're allowed to retry — suppress the warning from the UI
        st.session_state.rate_limit_until = datetime.now(CALGARY_TZ).timestamp() + (e.retry_after or 300)
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

def pull_cache_from_github() -> bool:
    """
    Download the latest cache.json from GitHub and overwrite the local file.
    Called on every auto-refresh so the app always has fresh poller data.
    Returns True if the local file was updated, False otherwise.
    """
    try:
        gh_token = st.secrets.get("github", {}).get("pat") or st.secrets.get("GH_PAT", "")
        headers = {}
        if gh_token:
            headers["Authorization"] = f"token {gh_token}"
        # Use the raw download URL — works for large files (>1 MB) unlike the Contents API
        # which base64-encodes and has a 1 MB limit.
        raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{GITHUB_PATH}"
        resp = requests.get(raw_url, headers=headers, timeout=30)
        if resp.status_code == 200:
            try:
                new_data = resp.json()
            except Exception:
                return False  # malformed JSON — don't overwrite local
            # Compare only by latest timestamp (count comparison is unreliable
            # if the poller was previously trimming old readings)
            new_latest = max((r["timestamp"] for r in new_data.get("readings", [])), default="")
            old_latest = ""
            if CACHE_FILE.exists():
                try:
                    with open(CACHE_FILE) as f:
                        old_data = json.load(f)
                    old_latest = max((r["timestamp"] for r in old_data.get("readings", [])), default="")
                    # Also check if GitHub has more readings (e.g. after a CSV merge)
                    old_count = len(old_data.get("readings", []))
                    new_count = len(new_data.get("readings", []))
                    if new_latest <= old_latest and new_count <= old_count:
                        return False  # already up to date
                except Exception:
                    pass
            with open(CACHE_FILE, "w") as f:
                json.dump(new_data, f, indent=2)
            return True
        return False
    except Exception:
        return False


def commit_cache_to_github(df: pd.DataFrame) -> tuple[bool, str]:
    """
    Serialise df to cache.json and commit it directly to the GitHub repo.
    Uses the Git Data API (blob + tree + commit) which has no file-size limit,
    unlike the Contents API which fails silently for files over ~1 MB.

    Returns (success: bool, message: str).
    """
    try:
        gh_token = st.secrets.get("github", {}).get("pat") or st.secrets.get("GH_PAT", "")
        if not gh_token:
            return False, "GitHub token not found in secrets."

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

        headers = {
            "Authorization": f"token {gh_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        base_url = f"https://api.github.com/repos/{GITHUB_REPO}"

        # Step 1: Create a blob with the new file content
        blob_resp = requests.post(
            f"{base_url}/git/blobs",
            headers=headers,
            json={"content": content_str, "encoding": "utf-8"},
            timeout=60,
        )
        if blob_resp.status_code != 201:
            return False, f"Blob creation failed: {blob_resp.json().get('message', blob_resp.text[:200])}"
        blob_sha = blob_resp.json()["sha"]

        # Step 2: Get the current HEAD commit SHA for the branch
        ref_resp = requests.get(
            f"{base_url}/git/refs/heads/{GITHUB_BRANCH}",
            headers=headers, timeout=15,
        )
        if ref_resp.status_code != 200:
            return False, f"Could not get branch ref: {ref_resp.json().get('message', '')}"
        head_sha = ref_resp.json()["object"]["sha"]

        # Step 3: Get the tree SHA of the current HEAD commit
        commit_resp = requests.get(
            f"{base_url}/git/commits/{head_sha}",
            headers=headers, timeout=15,
        )
        if commit_resp.status_code != 200:
            return False, f"Could not get commit: {commit_resp.json().get('message', '')}"
        base_tree_sha = commit_resp.json()["tree"]["sha"]

        # Step 4: Create a new tree that updates only cache.json
        tree_resp = requests.post(
            f"{base_url}/git/trees",
            headers=headers,
            json={
                "base_tree": base_tree_sha,
                "tree": [{
                    "path": GITHUB_PATH,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha,
                }],
            },
            timeout=30,
        )
        if tree_resp.status_code != 201:
            return False, f"Tree creation failed: {tree_resp.json().get('message', tree_resp.text[:200])}"
        new_tree_sha = tree_resp.json()["sha"]

        # Step 5: Create a new commit
        new_commit_resp = requests.post(
            f"{base_url}/git/commits",
            headers=headers,
            json={
                "message": f"data: merge {len(readings):,} readings via dashboard upload [skip poll]",
                "tree": new_tree_sha,
                "parents": [head_sha],
            },
            timeout=30,
        )
        if new_commit_resp.status_code != 201:
            return False, f"Commit creation failed: {new_commit_resp.json().get('message', new_commit_resp.text[:200])}"
        new_commit_sha = new_commit_resp.json()["sha"]

        # Step 6: Update the branch ref to point to the new commit
        update_resp = requests.patch(
            f"{base_url}/git/refs/heads/{GITHUB_BRANCH}",
            headers=headers,
            json={"sha": new_commit_sha},
            timeout=15,
        )
        if update_resp.status_code != 200:
            return False, f"Ref update failed: {update_resp.json().get('message', update_resp.text[:200])}"

        return True, f"✅ {len(readings):,} readings committed to GitHub — visible to all users worldwide."

    except Exception as e:
        return False, f"Commit failed: {e}"


# ─── Renpho Cache Helpers ─────────────────────────────────────────────────────
RENPHO_GITHUB_PATH = "renpho_cache.json"

# Renpho metric definitions: (column_name_in_df, display_label, unit)
RENPHO_METRICS = [
    ("Weight_lb",           "Weight",             "lb"),
    ("BMI",                 "BMI",                ""),
    ("Body_Fat_pct",        "Body Fat",           "%"),
    ("Fat_Free_Weight_lb",  "Fat-free Weight",    "lb"),
    ("Subcutaneous_Fat_pct","Subcutaneous Fat",   "%"),
    ("Visceral_Fat",        "Visceral Fat",       ""),
    ("Body_Water_pct",      "Body Water",         "%"),
    ("Skeletal_Muscle_pct", "Skeletal Muscle",    "%"),
    ("Muscle_Mass_lb",      "Muscle Mass",        "lb"),
    ("Bone_Mass_lb",        "Bone Mass",          "lb"),
    ("Protein_pct",         "Protein",            "%"),
    ("BMR_kcal",            "BMR",                "kcal"),
    ("Metabolic_Age",       "Metabolic Age",      "yrs"),
]
RENPHO_METRIC_KEYS   = [m[0] for m in RENPHO_METRICS]
RENPHO_METRIC_LABELS = {m[0]: m[1] for m in RENPHO_METRICS}
RENPHO_METRIC_UNITS  = {m[0]: m[2] for m in RENPHO_METRICS}


def parse_renpho_csv(uploaded_file) -> tuple[pd.DataFrame, str]:
    """Parse a Renpho CSV export and return a normalised DataFrame."""
    try:
        content = uploaded_file.read().decode("utf-8", errors="replace")
        df = pd.read_csv(io.StringIO(content))
        df.columns = [c.strip() for c in df.columns]

        # Find timestamp column
        ts_col = next((c for c in df.columns if "time" in c.lower()), None)
        if ts_col is None:
            return pd.DataFrame(), "Could not find a time/date column in the Renpho CSV."

        # Parse timestamps (Renpho format: 04/23/2026, 07:23:15)
        df["Timestamp"] = pd.to_datetime(df[ts_col], format="%m/%d/%Y, %H:%M:%S", errors="coerce")
        df = df.dropna(subset=["Timestamp"]).copy()

        # Column mapping: Renpho CSV name → normalised name
        col_map = {
            "Weight(lb)":                "Weight_lb",
            "BMI":                       "BMI",
            "Body Fat(%)": "Body_Fat_pct",
            "Fat-free Body Weight(lb)":  "Fat_Free_Weight_lb",
            "Subcutaneous Fat(%)": "Subcutaneous_Fat_pct",
            "Visceral Fat":              "Visceral_Fat",
            "Body Water(%)": "Body_Water_pct",
            "Skeletal Muscle(%)": "Skeletal_Muscle_pct",
            "Muscle Mass(lb)":           "Muscle_Mass_lb",
            "Bone Mass(lb)":             "Bone_Mass_lb",
            "Protein(%)": "Protein_pct",
            "BMR(kcal)":                 "BMR_kcal",
            "Metabolic Age":             "Metabolic_Age",
        }
        for src, dst in col_map.items():
            if src in df.columns:
                df[dst] = pd.to_numeric(df[src].replace("--", pd.NA), errors="coerce")

        # Keep only known metric columns + Timestamp
        keep = ["Timestamp"] + [c for c in RENPHO_METRIC_KEYS if c in df.columns]
        df = df[keep].copy()

        # Sort and deduplicate — keep the row with the most non-null values per timestamp
        df = df.sort_values("Timestamp")
        df = df.loc[df.notna().sum(axis=1).groupby(df["Timestamp"]).transform("max") == df.notna().sum(axis=1)]
        df = df.drop_duplicates(subset="Timestamp", keep="last").reset_index(drop=True)

        if df.empty:
            return pd.DataFrame(), "No valid readings found in Renpho CSV."
        return df, ""
    except Exception as e:
        return pd.DataFrame(), f"Error parsing Renpho CSV: {e}"


def load_renpho_df() -> pd.DataFrame:
    """Load renpho_cache.json from disk into a DataFrame."""
    if st.session_state.renpho_df is not None:
        return st.session_state.renpho_df
    if not RENPHO_CACHE_FILE.exists():
        return pd.DataFrame()
    try:
        with open(RENPHO_CACHE_FILE, "r") as f:
            data = json.load(f)
        rows = data.get("readings", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
        df = df.dropna(subset=["Timestamp"]).sort_values("Timestamp").reset_index(drop=True)
        for col in RENPHO_METRIC_KEYS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        st.session_state.renpho_df = df
        return df
    except Exception:
        return pd.DataFrame()


def save_renpho_cache(df: pd.DataFrame) -> bool:
    """Save Renpho DataFrame to renpho_cache.json on disk."""
    try:
        readings = []
        for _, row in df.iterrows():
            entry = {"Timestamp": row["Timestamp"].isoformat()}
            for col in RENPHO_METRIC_KEYS:
                if col in row and pd.notna(row[col]):
                    entry[col] = float(row[col])
                else:
                    entry[col] = None
            readings.append(entry)
        data = {
            "readings": readings,
            "last_updated": datetime.now(CALGARY_TZ).isoformat(),
            "source": "renpho_csv",
        }
        with open(RENPHO_CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
        st.session_state.renpho_df = df
        return True
    except Exception as e:
        st.error(f"Could not save Renpho cache: {e}")
        return False


def commit_renpho_to_github(df: pd.DataFrame) -> tuple[bool, str]:
    """Commit renpho_cache.json to GitHub repo via Contents API."""
    try:
        gh_token = st.secrets.get("github", {}).get("pat") or st.secrets.get("GH_PAT", "")
        if not gh_token:
            return False, "GitHub token not found in secrets."

        readings = []
        for _, row in df.iterrows():
            entry = {"Timestamp": row["Timestamp"].isoformat()}
            for col in RENPHO_METRIC_KEYS:
                if col in row and pd.notna(row[col]):
                    entry[col] = float(row[col])
                else:
                    entry[col] = None
            readings.append(entry)
        data = {
            "readings": readings,
            "last_updated": datetime.now(CALGARY_TZ).isoformat(),
            "source": "renpho_csv",
        }
        content_str = json.dumps(data, indent=2)
        content_b64 = base64.b64encode(content_str.encode()).decode()

        headers = {
            "Authorization": f"token {gh_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{RENPHO_GITHUB_PATH}"
        get_resp = requests.get(api_url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=15)
        sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

        payload = {
            "message": f"seed: upload {len(readings):,} Renpho measurements via dashboard",
            "content": content_b64,
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha

        put_resp = requests.put(api_url, headers=headers, json=payload, timeout=30)
        if put_resp.status_code in (200, 201):
            return True, f"✅ {len(readings):,} Renpho measurements committed to GitHub — visible to everyone."
        else:
            detail = put_resp.json().get("message", put_resp.text[:200])
            return False, f"GitHub API error {put_resp.status_code}: {detail}"
    except Exception as e:
        return False, f"Commit failed: {e}"


def merge_renpho(existing: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    """Merge two Renpho DataFrames, deduplicate by Timestamp, keep newest."""
    if existing.empty:
        return new_df
    combined = pd.concat([existing, new_df], ignore_index=True)
    combined = combined.sort_values("Timestamp")
    combined = combined.drop_duplicates(subset="Timestamp", keep="last").reset_index(drop=True)
    return combined


def parse_libreview_csv(uploaded_file) -> tuple[pd.DataFrame, str]:
    """
    Parse a CGM CSV export file.
    Supports:
      - FreeStyle Libre / LibreView exports (header row contains 'Device Timestamp')
      - Dexcom Clarity exports (header row contains 'Timestamp (YYYY-MM-DDThh:mm:ss)')
    Always merges into existing cache — never replaces it.
    """
    try:
        content = uploaded_file.read().decode("utf-8", errors="replace")
        lines = content.splitlines()

        # ── Detect format ──────────────────────────────────────────────────────
        is_dexcom = any("Timestamp (YYYY-MM-DDThh:mm:ss)" in line for line in lines[:10])

        if is_dexcom:
            # ── Dexcom Clarity format ──────────────────────────────────────────
            # Header row is row 0 (no metadata rows)
            df = pd.read_csv(io.StringIO(content))
            df.columns = [c.strip() for c in df.columns]

            ts_col = next((c for c in df.columns if c.startswith("Timestamp")), None)
            # Support both mg/dL and mmol/L Dexcom exports
            mg_col   = next((c for c in df.columns if "Glucose Value (mg/dL)" in c), None)
            mmol_col = next((c for c in df.columns if "Glucose Value (mmol/L)" in c), None)

            if ts_col is None or (mg_col is None and mmol_col is None):
                return pd.DataFrame(), (
                    f"Dexcom Clarity CSV: could not find required columns. "
                    f"Found: {list(df.columns)}"
                )

            # Keep only EGV rows (Event Type == 'EGV')
            if "Event Type" in df.columns:
                df = df[df["Event Type"].astype(str).str.strip() == "EGV"].copy()

            result = pd.DataFrame()
            result["Timestamp"] = pd.to_datetime(df[ts_col], errors="coerce")
            # Dexcom timestamps are already in local time (no tz conversion needed)
            result["Timestamp"] = result["Timestamp"].dt.tz_localize(None)
            result = result.dropna(subset=["Timestamp"])

            if mg_col:
                # mg/dL column — handle 'Low' / 'High' text values
                raw = df[mg_col].astype(str).str.strip()
                result["Glucose_mg"] = raw.replace({"Low": "40", "High": "400"}).pipe(pd.to_numeric, errors="coerce")
            else:
                # mmol/L column — convert to mg/dL
                raw = df[mmol_col].astype(str).str.strip()
                mmol_vals = raw.replace({"Low": "2.2", "High": "22.2"}).pipe(pd.to_numeric, errors="coerce")
                result["Glucose_mg"] = mmol_vals / MG_TO_MMOL

            result = result.dropna(subset=["Glucose_mg"])
            result["source"] = "dexcom_csv"

        else:
            # ── FreeStyle Libre / LibreView format ────────────────────────────
            header_idx = None
            for i, line in enumerate(lines):
                if "Device Timestamp" in line or "device timestamp" in line.lower():
                    header_idx = i
                    break

            if header_idx is None:
                return pd.DataFrame(), (
                    "Could not recognise CSV format. "
                    "Please use a LibreView (FreeStyle Libre) or Dexcom Clarity export file."
                )

            csv_content = "\n".join(lines[header_idx:])
            df = pd.read_csv(io.StringIO(csv_content))
            df.columns = [c.strip() for c in df.columns]

            ts_col = next((c for c in df.columns if "timestamp" in c.lower()), None)
            if ts_col is None:
                return pd.DataFrame(), "Could not find timestamp column."

            glucose_col_mg   = next((c for c in df.columns if "historic glucose mg" in c.lower() or "scan glucose mg" in c.lower()), None)
            glucose_col_mmol = next((c for c in df.columns if "historic glucose mmol" in c.lower() or "scan glucose mmol" in c.lower()), None)

            if glucose_col_mg is None and glucose_col_mmol is None:
                glucose_col_mg   = next((c for c in df.columns if "glucose" in c.lower() and "mg" in c.lower()), None)
                glucose_col_mmol = next((c for c in df.columns if "glucose" in c.lower() and "mmol" in c.lower()), None)

            if glucose_col_mg is None and glucose_col_mmol is None:
                return pd.DataFrame(), f"Could not find glucose column. Available columns: {list(df.columns)}"

            result = pd.DataFrame()
            # LibreView timestamps are in local Calgary time; dayfirst=True for DD-MM-YYYY
            result["Timestamp"] = pd.to_datetime(df[ts_col], errors="coerce", dayfirst=True)
            result = result.dropna(subset=["Timestamp"])

            if glucose_col_mg:
                result["Glucose_mg"] = pd.to_numeric(df[glucose_col_mg], errors="coerce")
            else:
                result["Glucose_mg"] = pd.to_numeric(df[glucose_col_mmol], errors="coerce") / MG_TO_MMOL

            result = result.dropna(subset=["Glucose_mg"])
            result["source"] = "csv"

        # ── Common post-processing ─────────────────────────────────────────────
        result["Glucose_mmol"] = (result["Glucose_mg"] * MG_TO_MMOL).round(1)
        result["Is High"] = False
        result["Is Low"]  = False
        result["trend"]   = "STABLE"

        result = result.drop_duplicates("Timestamp").sort_values("Timestamp").reset_index(drop=True)
        if result.empty:
            return pd.DataFrame(), "No valid glucose readings found in CSV."
        return result, None

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

# ─── Constants ───────────────────────────────────────────────────────────────
REFRESH_INTERVAL_MINUTES = 5  # auto-refresh interval (minutes)

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
        low_default  = 3.0
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

    # ── Refresh ─────────────────────────────────────────────────────────────
    st.markdown("### 🔄 Refresh")
    if st.button("🔄 Refresh Now", use_container_width=True):
        with st.spinner("Pulling latest data from GitHub & LibreView…"):
            pull_cache_from_github()
            if st.session_state.authenticated and st.session_state.selected_patient:
                fetch_data(st.session_state.selected_patient)
        st.rerun()

    if st.session_state.last_update:
        lu = st.session_state.last_update
        tz_abbr = lu.strftime("%Z") if lu.tzinfo else "MT"
        st.caption(f"Last fetched: {lu.strftime('%H:%M:%S')} {tz_abbr}")

    st.caption(f"⏱️ Auto-refreshes every {REFRESH_INTERVAL_MINUTES} min")

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

    # Patient selector (only shown when multiple patients exist on the account)
    if st.session_state.authenticated and len(st.session_state.patients) > 1:
        patient_names = [f"{p.first_name} {p.last_name}" for p in st.session_state.patients]
        idx = st.selectbox("Patient", range(len(patient_names)), format_func=lambda i: patient_names[i])
        st.session_state.selected_patient = st.session_state.patients[idx]

# ─── Auto-refresh ─────────────────────────────────────────────────────────────
# Always fetch live data on every page load/refresh when authenticated.
# Respects LibreView rate limits silently — no warning shown to user.
if st.session_state.authenticated and st.session_state.selected_patient:
    _now_ts = datetime.now(CALGARY_TZ).timestamp()
    _rate_ok = _now_ts >= st.session_state.get("rate_limit_until", 0)
    if st.session_state.last_update is None:
        if _rate_ok:
            with st.spinner("Loading latest readings…"):
                fetch_data(st.session_state.selected_patient)
            # Rerun so the chart renders with the freshly fetched graph_data
            st.rerun()
    else:
        # Re-fetch silently in the background, throttled to once every 60s.
        # Do NOT call st.rerun() here — the auto-refresh fragment handles reruns
        # when new data actually arrives, preventing an infinite rerun loop.
        elapsed = (datetime.now(CALGARY_TZ) - st.session_state.last_update).total_seconds()
        if elapsed >= 60 and _rate_ok:
            fetch_data(st.session_state.selected_patient)

# ─── Main Content ─────────────────────────────────────────────────────────────
st.markdown(
    '<div style="margin-top:-3rem;padding-top:0.5rem;margin-bottom:0.2rem;">'
    '<span style="font-size:1.3rem;font-weight:800;">📊 CGM Dashboard</span>'
    '</div>',
    unsafe_allow_html=True
)
st.markdown('<hr style="margin:4px 0 8px 0;">', unsafe_allow_html=True)

# ─── Latest Reading Header ────────────────────────────────────────────────────
# Show from live API if available, otherwise fall back to most recent cache entry
latest = st.session_state.latest_reading
_header_source = "live"
_header_ts_str = None

if latest is not None:
    latest_mg  = float(latest.value_in_mg_per_dl if latest.value_in_mg_per_dl else latest.value)
    trend_obj  = latest.trend_arrow if hasattr(latest, 'trend_arrow') else None
    trend_text = TREND_LABELS.get(trend_obj, "→") if trend_obj else "→"
    ts = latest.factory_timestamp if hasattr(latest, 'factory_timestamp') and latest.factory_timestamp else latest.timestamp
    if hasattr(ts, 'astimezone'):
        ts_calgary = ts.astimezone(CALGARY_TZ)
        tz_abbr = ts_calgary.strftime("%Z")
        _header_ts_str = ts_calgary.strftime(f"%b %d, %Y  %H:%M:%S {tz_abbr}")
    else:
        _header_ts_str = str(ts)
else:
    # Fall back to most recent cache entry
    _cache_fb = load_cache_df()
    if not _cache_fb.empty:
        _last_row = _cache_fb.iloc[-1]
        latest_mg  = float(_last_row["Glucose_mg"])
        trend_text = "→"
        _header_source = "cache"
        _ts_fb = _last_row["Timestamp"]
        _header_ts_str = _ts_fb.strftime("%b %d, %Y  %H:%M MT") + " (cached)"
    else:
        latest_mg = None

if latest_mg is not None:
    status_label, glucose_class, badge_class = glucose_status(latest_mg, target_low_mg, target_high_mg)
    reading_time_str = _header_ts_str or ""

    if unit_choice == "mmol/L":
        display_val  = f"{mg_to_mmol(latest_mg):.1f}"
        display_unit = "mmol/L"
    elif unit_choice == "Both":
        display_val  = f"{latest_mg:.0f} / {mg_to_mmol(latest_mg):.1f}"
        display_unit = "mg/dL  |  mmol/L"
    else:
        display_val  = f"{latest_mg:.0f}"
        display_unit = "mg/dL"

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
tab_chart, tab_readings, tab_stats, tab_renpho = st.tabs(["📈 CGM Chart", "📋 CGM All Readings", "📊 CGM Statistics", "⚖️ Body Composition Renpho"])

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
            _view_options = ["Day", "1 Week", "2 Weeks", "Month", "Compare"]
            _view_map     = {"day": 0, "week": 1, "2weeks": 2, "month": 3, "compare": 4}
            _view_idx     = _view_map.get(st.session_state.nav_view, 0)
            # No key= so Streamlit doesn't override session state on rerun
            view_mode = st.radio("View", _view_options, horizontal=True, index=_view_idx)
            _new_nav_view = {"Day": "day", "1 Week": "week", "2 Weeks": "2weeks",
                             "Month": "month", "Compare": "compare"}[view_mode]
            if _new_nav_view != st.session_state.nav_view:
                st.session_state.nav_view = _new_nav_view
                st.rerun()

        if st.session_state.nav_view in ("day", "compare"):
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
            _step_map = {"day": 1, "week": 7, "2weeks": 14, "month": 30, "compare": 1}
            step = _step_map.get(st.session_state.nav_view, 1)
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
            # Any multi-day navigation clears the 24h mode
            st.session_state.show_last_24h = False
            if st.session_state.nav_view == "month":
                # Month: show the calendar month containing anchor_date
                import calendar as _cal
                month_start  = anchor_date.replace(day=1)
                last_day     = _cal.monthrange(month_start.year, month_start.month)[1]
                month_end    = month_start.replace(day=last_day)
                period_label = month_start.strftime("%B %Y")
                week_days    = [month_start + timedelta(days=i) for i in range(last_day)]
                window_start = datetime.combine(month_start, datetime.min.time())
                window_end   = datetime.combine(month_end,   datetime.max.time())
            elif st.session_state.nav_view == "compare":
                # Compare: window covers full data range; actual days chosen via UI below
                period_label = "Day Comparison"
                week_days    = []  # not used for compare
                window_start = datetime.combine(data_min_date, datetime.min.time())
                window_end   = datetime.combine(data_max_date, datetime.max.time())
            else:
                week_start   = anchor_date - timedelta(days=anchor_date.weekday())
                if st.session_state.nav_view == "2weeks":
                    week_end     = week_start + timedelta(days=13)
                    period_label = f"2 Weeks: {week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}"
                    week_days    = [week_start + timedelta(days=i) for i in range(14)]
                else:
                    week_end     = week_start + timedelta(days=6)
                    period_label = f"Week of {week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}"
                    week_days    = [week_start + timedelta(days=i) for i in range(7)]
                window_start = datetime.combine(week_start, datetime.min.time())
                window_end   = datetime.combine(week_end,   datetime.max.time())

        with nav_col6:
            st.markdown(
                f'<div style="padding-top:28px;font-size:15px;font-weight:600;color:#333;">📅 {period_label}</div>',
                unsafe_allow_html=True
            )

        # ── Calendar date picker (Day, Week, Month views) ────────────────────
        if available_dates and st.session_state.nav_view != "compare":
            cal_col1, cal_col2 = st.columns([1, 3])
            with cal_col1:
                _picker_labels = {
                    "day": "🗓️ Jump to date:",
                    "week": "🗓️ Jump to week of:",
                    "2weeks": "🗓️ Jump to 2-week start:",
                    "month": "🗓️ Jump to month:",
                }
                st.markdown(
                    f'<div style="padding-top:6px;font-size:13px;font-weight:600;color:#555;">'
                    f'{_picker_labels.get(st.session_state.nav_view, "🗓️ Jump to:")}</div>',
                    unsafe_allow_html=True
                )
            with cal_col2:
                if st.session_state.nav_view == "day":
                    # Dynamic key forces re-init when anchor_date changes (e.g. after Latest button)
                    picked = st.date_input(
                        "jump_date", value=anchor_date,
                        min_value=data_min_date, max_value=data_max_date,
                        label_visibility="collapsed",
                        key=f"cal_picker_day_{anchor_date.isoformat()}",
                    )
                    if picked != anchor_date:
                        st.session_state.nav_offset_days = max(min_offset, min(0, (picked - data_max_date).days))
                        st.session_state.show_last_24h = False
                        st.rerun()
                elif st.session_state.nav_view == "month":
                    _cur_month_1st = anchor_date.replace(day=1)
                    picked_m = st.date_input(
                        "jump_month", value=_cur_month_1st,
                        min_value=data_min_date, max_value=data_max_date,
                        label_visibility="collapsed",
                        key=f"cal_picker_month_{_cur_month_1st.isoformat()}",
                    )
                    picked_month_1st = picked_m.replace(day=1)
                    if picked_month_1st != _cur_month_1st:
                        st.session_state.nav_offset_days = max(min_offset, min(0, (picked_month_1st - data_max_date).days))
                        st.session_state.show_last_24h = False
                        st.rerun()
                else:
                    # Week / 2-week view: snap to Monday of picked week
                    current_week_start = anchor_date - timedelta(days=anchor_date.weekday())
                    _wk_key = f"cal_picker_{'2week' if st.session_state.nav_view == '2weeks' else 'week'}_{current_week_start.isoformat()}"
                    picked_week = st.date_input(
                        "jump_week", value=current_week_start,
                        min_value=data_min_date, max_value=data_max_date,
                        label_visibility="collapsed", key=_wk_key,
                    )
                    picked_week_monday = picked_week - timedelta(days=picked_week.weekday())
                    if picked_week_monday != current_week_start:
                        st.session_state.nav_offset_days = max(min_offset, min(0, (picked_week_monday - data_max_date).days))
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
                                show_zoom_buttons=True,
                                chart_height=420,
                                x_range_hours=24,
                                forced_y_range_mg=None):
                """Build a single-day Plotly figure with target bands and midnight dotted lines."""
                # x_range_hours: 24 = full day, or (start_h, end_h) tuple
                # forced_y_range_mg: if provided, use this (y_min_mg, y_max_mg) instead of per-day auto-range
                if day_df.empty:
                    return None

                data_min_mg = day_df["Glucose_mg"].min()
                data_max_mg = day_df["Glucose_mg"].max()
                if forced_y_range_mg is not None:
                    y_min_mg, y_max_mg = forced_y_range_mg
                else:
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
                    # Dashed grey reference lines at key glucose levels
                    if unit_choice == "mmol/L":
                        ref_vals = [4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0]
                    else:
                        ref_vals = [72, 90, 108, 126, 144, 180, 216]
                    for rv in ref_vals:
                        if rv not in (tgt_low, tgt_high):
                            lbl = f"{rv:.1f}" if unit_choice == "mmol/L" else str(int(rv))
                            fig.add_hline(
                                y=rv,
                                line_dash="dash",
                                line_color="rgba(150,150,150,0.45)",
                                line_width=1,
                                annotation_text=lbl,
                                annotation_position="right",
                                annotation_font_size=9,
                                annotation_font_color="#888",
                            )
                    layout_extra = dict(
                        yaxis=dict(title=y_label, range=y_range),
                        showlegend=False,
                    )

                xaxis_cfg = dict(rangeslider=dict(visible=False), title="Time")
                if show_zoom_buttons and rangeselector_cfg:
                    xaxis_cfg["rangeselector"] = rangeselector_cfg

                # Apply time-range window to x-axis
                # x_range_hours is either 24 (full day) or a (start_h, end_h) tuple
                if isinstance(x_range_hours, tuple) and not day_df.empty:
                    start_h, end_h = x_range_hours
                    if start_h != 0 or end_h != 24:  # only restrict if not full day
                        day_date = day_df["Timestamp"].dt.date.iloc[0]
                        x_start  = datetime.combine(day_date, datetime.min.time()) + timedelta(hours=start_h)
                        x_end    = datetime.combine(day_date, datetime.min.time()) + timedelta(hours=end_h)
                        xaxis_cfg["range"] = [x_start, x_end]

                annotations = []
                if show_zoom_buttons and zoom_annotation:
                    annotations.append(zoom_annotation)

                right_margin = 60 if unit_choice == "Both" else 0
                title_font_size = 13 if show_zoom_buttons else 12
                top_margin   = 46 if not show_zoom_buttons else 62
                fig.update_layout(
                    hovermode="x unified", height=chart_height, template="plotly_white",
                    margin=dict(l=0, r=right_margin, t=top_margin, b=35),
                    title=dict(
                        text=f"<b>{day_label}</b>",
                        x=0.5, xanchor="center",
                        y=1.0, yanchor="top",
                        font=dict(size=title_font_size, color="#333", family="Arial, sans-serif"),
                        pad=dict(t=4),
                    ),
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
                # Time-range slider — dynamic key resets to 00-24 when switching days
                _day_time_range = st.slider(
                    "Time window",
                    min_value=0, max_value=24, value=(0, 24), step=1,
                    key=f"day_time_slider_{anchor_date.isoformat()}",
                    help="Drag to zoom into a specific part of the day",
                    format="%02d:00",
                )
                # If user drags slider away from full range, exit Last 24h mode
                # so the chart shows the selected day's data (not a rolling 24h window)
                if _day_time_range != (0, 24) and st.session_state.show_last_24h:
                    st.session_state.show_last_24h = False
                    st.rerun()
                # In Last 24h mode, chart_df already spans Jun 9 → Jun 10;
                # pass the slider range so the user can still zoom within that window
                fig = build_day_chart(
                    chart_df, date_str, unit_choice,
                    target_low_mg, target_high_mg,
                    target_low_mmol, target_high_mmol,
                    show_zoom_buttons=False,
                    x_range_hours=_day_time_range,
                )
                if fig:
                    st.plotly_chart(fig, use_container_width=True)

            # ── Compare View: pick 2–3 independent days side-by-side ─────────────
            elif st.session_state.nav_view == "compare":
                st.markdown("**Select 2 or 3 days to compare side-by-side:**")
                _cmp_picker_cols = st.columns(3)
                _cmp_days = []
                _cmp_defaults = st.session_state.compare_days
                for _ci in range(3):
                    with _cmp_picker_cols[_ci]:
                        _default_val = None
                        if _ci < len(_cmp_defaults):
                            try:
                                from datetime import date as _date_cls
                                _dv = _date_cls.fromisoformat(_cmp_defaults[_ci])
                                if data_min_date <= _dv <= data_max_date:
                                    _default_val = _dv
                            except Exception:
                                pass
                        if _default_val is None:
                            _default_val = data_max_date - timedelta(days=_ci)
                        _label = f"Day {_ci + 1}" if _ci < 2 else "Day 3 (optional)"
                        _picked_cmp = st.date_input(
                            _label, value=_default_val,
                            min_value=data_min_date, max_value=data_max_date,
                            key=f"cmp_day_{_ci}",
                        )
                        _cmp_days.append(_picked_cmp)
                st.session_state.compare_days = [str(d) for d in _cmp_days]

                _cmp_time_range = st.slider(
                    "Time window",
                    min_value=0, max_value=24, value=(0, 24), step=1,
                    key="cmp_time_slider",
                    help="Show the same time window across all compared days",
                    format="%02d:00",
                )

                # Shared y-range across selected days
                _cmp_all_dfs = []
                for _cd in _cmp_days:
                    _cd_df = wide_df[
                        (wide_df["Timestamp"] >= datetime.combine(_cd, datetime.min.time())) &
                        (wide_df["Timestamp"] <= datetime.combine(_cd, datetime.max.time()))
                    ]
                    if not _cd_df.empty:
                        _cmp_all_dfs.append(_cd_df)
                if _cmp_all_dfs:
                    import pandas as _pd
                    _cmp_combined = _pd.concat(_cmp_all_dfs)
                    _cmp_shared_y = centered_yrange_mg(
                        target_low_mg, target_high_mg,
                        _cmp_combined["Glucose_mg"].min(),
                        _cmp_combined["Glucose_mg"].max()
                    )
                else:
                    _cmp_shared_y = None

                _cmp_render_cols = st.columns(3)
                for _ci, _cd in enumerate(_cmp_days):
                    _cd_df = wide_df[
                        (wide_df["Timestamp"] >= datetime.combine(_cd, datetime.min.time())) &
                        (wide_df["Timestamp"] <= datetime.combine(_cd, datetime.max.time()))
                    ].copy()
                    _cd_label = _cd.strftime("%A, %b %d %Y")
                    with _cmp_render_cols[_ci]:
                        if _cd_df.empty:
                            st.markdown(
                                f'<div style="font-size:12px;color:#999;padding:40px 0;'
                                f'text-align:center;border:1px dashed #ddd;border-radius:6px;">'
                                f'{_cd_label}<br><em>no data</em></div>',
                                unsafe_allow_html=True
                            )
                        else:
                            fig = build_day_chart(
                                _cd_df, _cd_label, unit_choice,
                                target_low_mg, target_high_mg,
                                target_low_mmol, target_high_mmol,
                                show_zoom_buttons=False,
                                chart_height=340,
                                x_range_hours=_cmp_time_range,
                                forced_y_range_mg=_cmp_shared_y,
                            )
                            if fig:
                                st.plotly_chart(fig, use_container_width=True)

            # ── Week / 2-Week / Month View: grid of day charts ──────────────────
            else:
                # ── Controls row: columns + time-range slider ─────────────────────
                _wv_ctrl1, _wv_ctrl2, _wv_ctrl3 = st.columns([0.8, 2.5, 2])
                with _wv_ctrl1:
                    _n_cols = st.radio(
                        "Columns", [2, 3], index=1, horizontal=True,
                        key="week_grid_cols",
                        help="Number of day charts per row"
                    )
                with _wv_ctrl2:
                    _time_range = st.slider(
                        "Time window (hours)",
                        min_value=0, max_value=24,
                        value=(0, 24),
                        step=1,
                        key="week_time_slider",
                        help="Drag to select which hours of the day to show across all charts",
                        format="%02d:00",
                    )
                    _x_hrs = _time_range  # tuple (start_h, end_h)
                with _wv_ctrl3:
                    st.markdown(
                        f'<div style="padding-top:8px;font-size:13px;font-weight:600;'
                        f'color:#1a73e8;background:#f0f4ff;border:1px solid #c5d3f5;'
                        f'border-radius:8px;padding:5px 14px;display:inline-block;">'
                        f'📆 {period_label}</div>',
                        unsafe_allow_html=True
                    )

                # Chart height shrinks with more columns so they fit nicely
                _grid_height = 255 if _n_cols == 3 else 295

                # ── Pre-compute shared Y-range across all days in the period ──────────────
                # Filter chart_df to the selected time window for a fair shared range
                if isinstance(_x_hrs, tuple) and (_x_hrs[0] != 0 or _x_hrs[1] != 24):
                    _sh, _eh = _x_hrs
                    _windowed = chart_df[
                        chart_df["Timestamp"].apply(
                            lambda ts: _sh <= ts.hour < _eh or (_eh == 24 and ts.hour >= _sh)
                        )
                    ]
                else:
                    _windowed = chart_df

                if not _windowed.empty:
                    _global_min_mg = _windowed["Glucose_mg"].min()
                    _global_max_mg = _windowed["Glucose_mg"].max()
                    _shared_y_mg   = centered_yrange_mg(
                        target_low_mg, target_high_mg, _global_min_mg, _global_max_mg
                    )
                else:
                    _shared_y_mg = None

                # Render days in a responsive grid
                _cols_iter = None
                for _i, day in enumerate(week_days):
                    if _i % _n_cols == 0:
                        _cols_iter = st.columns(_n_cols)
                    _col = _cols_iter[_i % _n_cols]

                    day_start = datetime.combine(day, datetime.min.time())
                    day_end   = datetime.combine(day, datetime.max.time())
                    day_df    = chart_df[
                        (chart_df["Timestamp"] >= day_start) &
                        (chart_df["Timestamp"] <= day_end)
                    ].copy()
                    day_label_str = day.strftime("%a %b %d")

                    with _col:
                        if day_df.empty:
                            st.markdown(
                                f'<div style="font-size:12px;color:#999;padding:20px 0;'
                                f'text-align:center;border:1px dashed #ddd;border-radius:6px;'
                                f'margin-bottom:6px;">{day_label_str}<br><em>no data</em></div>',
                                unsafe_allow_html=True
                            )
                        else:
                            fig = build_day_chart(
                                day_df, day_label_str, unit_choice,
                                target_low_mg, target_high_mg,
                                target_low_mmol, target_high_mmol,
                                show_zoom_buttons=False,
                                chart_height=_grid_height,
                                x_range_hours=_x_hrs,
                                forced_y_range_mg=_shared_y_mg,
                            )
                            if fig:
                                st.plotly_chart(fig, use_container_width=True)

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

# ─── Renpho Body Composition Tab ────────────────────────────────────────────────
with tab_renpho:
    renpho_df = load_renpho_df()

    # ── Weight unit toggle ───────────────────────────────────────────────────────
    LB_TO_KG = 0.453592

    def _convert_weight(df, to_unit):
        """Return a copy of df with lb-based weight columns converted if needed."""
        df = df.copy()
        if to_unit == "kg":
            for col in ["Weight_lb", "Fat_Free_Weight_lb", "Muscle_Mass_lb", "Bone_Mass_lb"]:
                if col in df.columns:
                    df[col] = df[col] * LB_TO_KG
        return df

    # ── Metric selector ──────────────────────────────────────────────────────────
    available_metrics = [m for m in RENPHO_METRIC_KEYS if not renpho_df.empty and m in renpho_df.columns and renpho_df[m].notna().any()]

    # Fix 3: default to ALL available metrics
    if st.session_state.renpho_selected_metrics is None:
        st.session_state.renpho_selected_metrics = available_metrics[:]

    if not renpho_df.empty:
        # ── Controls row ─────────────────────────────────────────────────────────
        ctrl1, ctrl2, ctrl3 = st.columns([3, 1, 1])

        with ctrl1:
            selected = st.multiselect(
                "Select metrics to chart:",
                options=available_metrics,
                default=[m for m in st.session_state.renpho_selected_metrics if m in available_metrics],
                format_func=lambda k: RENPHO_METRIC_LABELS.get(k, k),
                key="renpho_metric_select",
            )
            st.session_state.renpho_selected_metrics = selected

        with ctrl2:
            # Fix 4: weight unit toggle
            w_unit = st.radio("Weight unit", ["lb", "kg"], horizontal=True,
                              index=0 if st.session_state.renpho_weight_unit == "lb" else 1,
                              key="renpho_w_unit_radio")
            st.session_state.renpho_weight_unit = w_unit

        with ctrl3:
            # Fix 1: dynamic date range — styled label to make it obvious it's interactive
            range_options = {"All time": 0, "1 week": 7, "2 weeks": 14, "1 month": 30, "2 months": 60,
                             "3 months": 90, "6 months": 180, "1 year": 365}
            st.markdown("**📅 Select Date Range**")
            range_label = st.selectbox(
                "Filter by date range:",
                list(range_options.keys()),
                index=0,
                key="renpho_range_sel",
                label_visibility="collapsed",
                help="Filter charts to show only measurements within this time window",
            )
            range_days = range_options[range_label]
            st.session_state.renpho_date_range_days = range_days

        # ── Date filter ──────────────────────────────────────────────────────────
        plot_df = _convert_weight(renpho_df, w_unit)
        now_dt  = datetime.now(CALGARY_TZ).replace(tzinfo=None)
        if range_days > 0:
            plot_df = plot_df[plot_df["Timestamp"] >= now_dt - pd.Timedelta(days=range_days)]

        # Dynamic unit labels after conversion
        def _unit_for(metric):
            base = RENPHO_METRIC_UNITS[metric]
            if base == "lb" and w_unit == "kg":
                return "kg"
            return base

        # Birth year for chronological age baseline
        BIRTH_YEAR = 1960

        # ── Summary stats row ────────────────────────────────────────────────────
        if selected:
            stat_cols = st.columns(min(len(selected), 4))
            for i, metric in enumerate(selected[:4]):
                col_data = plot_df[metric].dropna()
                if not col_data.empty:
                    label = RENPHO_METRIC_LABELS[metric]
                    unit  = _unit_for(metric)
                    latest_val = col_data.iloc[-1]
                    first_val  = col_data.iloc[0]
                    delta      = latest_val - first_val
                    with stat_cols[i % 4]:
                        if metric == "Metabolic_Age":
                            # Show metabolic age vs chronological age
                            latest_ts   = plot_df.loc[plot_df[metric].notna(), "Timestamp"].iloc[-1]
                            chron_age   = latest_ts.year - BIRTH_YEAR
                            met_delta   = int(round(latest_val - chron_age))
                            delta_str   = f"{met_delta:+d} yrs vs. chronological age {chron_age}"
                            st.metric(
                                label="Metabolic Age",
                                value=f"{int(round(latest_val))} yrs",
                                delta=delta_str,
                                delta_color="inverse",  # positive delta (older) = red
                            )
                        else:
                            st.metric(
                                label=label,
                                value=f"{latest_val:.1f} {unit}".strip(),
                                delta=f"{delta:+.1f} {unit}".strip(),
                                delta_color="inverse" if metric in ("Weight_lb", "Body_Fat_pct", "Visceral_Fat", "Subcutaneous_Fat_pct", "BMI") else "normal",
                            )
            st.markdown("")

        # ── Charts — one per selected metric ────────────────────────────────────
        if selected and not plot_df.empty:
            for metric in selected:
                col_data = plot_df[["Timestamp", metric]].dropna(subset=[metric])
                if col_data.empty:
                    continue
                label   = RENPHO_METRIC_LABELS[metric]
                unit    = _unit_for(metric)
                y_label = f"{label} ({unit})" if unit else label

                # ── Special chart for Metabolic Age — delta only ──────────────
                if metric == "Metabolic_Age":
                    col_data = col_data.copy()
                    col_data["Chron_Age"] = col_data["Timestamp"].apply(
                        lambda ts: ts.year - BIRTH_YEAR + (ts.month - 1) / 12
                    )
                    col_data["Delta"] = col_data[metric] - col_data["Chron_Age"]

                    latest_delta = col_data["Delta"].iloc[-1]
                    delta_sign   = f"+{latest_delta:.1f}" if latest_delta > 0 else f"{latest_delta:.1f}"

                    delta_labels = col_data["Delta"].apply(
                        lambda d: f"+{d:.1f} yrs" if d > 0 else f"{d:.1f} yrs"
                    )

                    # Blue palette matching the CGM chart
                    LINE_BLUE   = "#1f77b4"
                    FILL_BLUE   = "rgba(31,119,180,0.12)"
                    TREND_ORANGE = "#e65c00"

                    fig = go.Figure()
                    # Zero reference line
                    fig.add_hline(
                        y=0, line_width=1.5, line_dash="dash", line_color="#555",
                        annotation_text="= Chronological age",
                        annotation_position="bottom right",
                        annotation_font_size=10,
                        annotation_font_color="#555",
                    )
                    # Main delta line with markers
                    fig.add_trace(go.Scatter(
                        x=col_data["Timestamp"],
                        y=col_data["Delta"],
                        mode="lines+markers",
                        name="± Chronological Age",
                        line=dict(color=LINE_BLUE, width=2),
                        marker=dict(size=5, color=LINE_BLUE),
                        customdata=delta_labels,
                        hovertemplate="%{x|%b %d, %Y}<br><b>%{customdata}</b><extra></extra>",
                    ))
                    # Annotation at the latest point
                    fig.add_annotation(
                        x=col_data["Timestamp"].iloc[-1],
                        y=latest_delta,
                        text=f"<b>{delta_sign} yrs now</b>",
                        showarrow=True, arrowhead=2,
                        ax=50, ay=-35,
                        font=dict(color=LINE_BLUE, size=12),
                        bgcolor="white", bordercolor=LINE_BLUE, borderwidth=1,
                    )
                    fig.update_layout(
                        yaxis_title="± Chronological Age (yrs)",
                        yaxis=dict(tickformat="+.0f", zeroline=False),
                        height=320,
                        template="plotly_white",
                        margin=dict(l=0, r=0, t=45, b=0),
                        hovermode="x unified",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        title=dict(
                            text=f"Metabolic Age Gap  <span style='color:{LINE_BLUE};font-size:14px'>{delta_sign} yrs currently</span>",
                            font=dict(size=14), x=0,
                        ),
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    continue

                # ── Standard chart for all other metrics ─────────────────────────
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=col_data["Timestamp"],
                    y=col_data[metric],
                    mode="lines+markers",
                    name=label,
                    line=dict(color="#1a73e8", width=2),
                    marker=dict(size=5),
                    hovertemplate=f"%{{x|%b %d, %Y}}<br>{label}: %{{y:.1f}} {unit}<extra></extra>",
                ))
                fig.update_layout(
                    yaxis_title=y_label,
                    height=260,
                    template="plotly_white",
                    margin=dict(l=0, r=0, t=30, b=0),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    title=dict(text=label, font=dict(size=14), x=0),
                )
                st.plotly_chart(fig, use_container_width=True)
        elif not selected:
            st.info("Select at least one metric above to display charts.")

        # ── Full data table ──────────────────────────────────────────────────────
        with st.expander("📋 View full Renpho data table", expanded=False):
            display_df = _convert_weight(renpho_df, w_unit)
            display_df["Date & Time"] = display_df["Timestamp"].dt.strftime("%Y-%m-%d %H:%M")
            show_cols = ["Date & Time"] + [m for m in RENPHO_METRIC_KEYS if m in display_df.columns]
            rename_map = {m: f"{RENPHO_METRIC_LABELS[m]} ({_unit_for(m)})" if _unit_for(m) else RENPHO_METRIC_LABELS[m] for m in RENPHO_METRIC_KEYS}
            st.dataframe(
                display_df[show_cols].rename(columns=rename_map).sort_values("Date & Time", ascending=False),
                use_container_width=True,
                height=400,
            )

    else:
        st.info("No Renpho data loaded yet. Upload a Renpho CSV export below to get started.")

    # ── CSV Upload ───────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📤 Upload New Renpho Data")
    st.info(
        "**Have a newer Renpho export?** Upload it here to add new measurements. "
        "Existing data is preserved — only new readings are added. "
        "Once uploaded, the data is permanently saved to GitHub and visible to everyone."
    )
    st.caption("Export from the Renpho app: **Profile → Data → Export CSV**")
    renpho_upload = st.file_uploader(
        "Upload new Renpho CSV export",
        type=["csv"],
        key="renpho_uploader",
        help="Only new measurements not already in the database will be added.",
    )
    if renpho_upload is not None and not st.session_state.renpho_upload_done:
        st.session_state.renpho_upload_done = True
        with st.spinner("Parsing Renpho CSV…"):
            new_df, err = parse_renpho_csv(renpho_upload)
        if err:
            st.error(f"CSV error: {err}")
            st.session_state.renpho_upload_done = False
        elif new_df.empty:
            st.warning("No valid measurements found in the uploaded file.")
            st.session_state.renpho_upload_done = False
        else:
            existing_renpho = load_renpho_df()
            merged_renpho   = merge_renpho(existing_renpho, new_df)
            added = len(merged_renpho) - len(existing_renpho)
            with st.spinner(f"Saving {len(merged_renpho):,} measurements to GitHub…"):
                ok, msg = commit_renpho_to_github(merged_renpho)
            save_renpho_cache(merged_renpho)
            st.session_state.renpho_df = None   # force reload on next render
            if ok:
                st.success(f"{msg} +{added:,} new measurements added ({len(merged_renpho):,} total).")
            else:
                st.warning(f"⚠️ Could not commit to GitHub: {msg}\n\nData saved for this session only.")
    elif renpho_upload is None:
        # Reset flag when uploader is cleared so a new file can be processed
        st.session_state.renpho_upload_done = False

# ─── Auto-Refresh Timer ───────────────────────────────────────────────────────
# Use st.fragment(run_every=N) to:
#  1. Pull the latest cache.json from GitHub (so poller updates are seen immediately)
#  2. Re-fetch live LibreView data if authenticated
#  3. Trigger a full page rerun so charts update
_refresh_secs = REFRESH_INTERVAL_MINUTES * 60

@st.fragment(run_every=_refresh_secs)
def _auto_refresh_fragment():
    """Runs every N seconds; pulls fresh cache from GitHub, fetches live data, reruns page."""
    # Pull the latest cache from GitHub — only rerun if new data arrived
    _cache_updated = pull_cache_from_github()

    # Also try to fetch live data from LibreView API if authenticated.
    # Only rerun if the cache was updated — live fetch updates session state
    # silently; the next natural render cycle will pick it up.
    _now = datetime.now(CALGARY_TZ).timestamp()
    _ok  = _now >= st.session_state.get("rate_limit_until", 0)
    if st.session_state.authenticated and st.session_state.selected_patient and _ok:
        fetch_data(st.session_state.selected_patient)

    # Only trigger a full-page rerun when the GitHub cache actually had new data.
    # This prevents the constant rerun loop when there is no new data.
    if _cache_updated:
        st.rerun()

_auto_refresh_fragment()
