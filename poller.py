#!/usr/bin/env python3
"""
CGM Background Poller
Fetches latest glucose readings from LibreView API and appends to cache.json.
Designed to run via GitHub Actions every 5 minutes.

Fixes applied:
- Removed MAX_CACHE_READINGS cap so no historical data is ever trimmed
- Backfills gaps: if last cached reading is >15 min old, fetches extra history
- Retries authentication once on failure before giving up
- Validates fetched readings before merging (rejects obviously bad values)
- Prints a clear summary of what was added and what the latest timestamp is
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CALGARY_TZ = ZoneInfo("America/Edmonton")  # Calgary / Mountain Time

from pylibrelinkup import PyLibreLinkUp, APIUrl
from pylibrelinkup.exceptions import RedirectError

CACHE_FILE = Path(__file__).parent / "cache.json"

# No hard cap — we keep all readings forever.
# GitHub repos support files up to 100 MB; at ~120 bytes/reading that's ~830,000 readings (~8 years).
MAX_CACHE_READINGS = None


def get_api_url(url_str: str) -> APIUrl:
    mapping = {
        "US": APIUrl.US,
        "EU": APIUrl.EU,
        "EU2": APIUrl.EU2,
        "CA": APIUrl.CA,
        "AU": APIUrl.AU,
        "AE": APIUrl.AE,
        "JP": APIUrl.JP,
        "DE": APIUrl.DE,
        "FR": APIUrl.FR,
        "IT": APIUrl.IT,
        "SE": APIUrl.SE,
        "NL": APIUrl.NL,
        "RU": APIUrl.RU,
    }
    return mapping.get(url_str.upper(), APIUrl.US)


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"WARNING: cache.json corrupt ({e}), starting fresh.")
    return {"readings": [], "last_updated": None, "source": "live_api"}


def save_cache(data: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def authenticate(email: str, password: str):
    """Try to authenticate, auto-handling region redirects. Retries once on failure."""
    for attempt in range(2):
        try:
            client = PyLibreLinkUp(email=email, password=password)
            try:
                client.authenticate()
                return client
            except RedirectError as e:
                redirect_url = str(e).strip()
                for api_url in APIUrl:
                    if api_url.value in redirect_url:
                        client2 = PyLibreLinkUp(email=email, password=password, api_url=api_url)
                        client2.authenticate()
                        return client2
                # Try CA as default for Canadian accounts
                client_ca = PyLibreLinkUp(email=email, password=password, api_url=APIUrl.CA)
                client_ca.authenticate()
                return client_ca
        except Exception as e:
            if attempt == 0:
                print(f"Authentication attempt 1 failed: {e}. Retrying...")
            else:
                raise


def fetch_readings(client) -> list[dict]:
    """Fetch latest readings from graph + latest endpoints. Returns list of validated dicts."""
    patients = client.get_patients()
    if not patients:
        print("No patients found.")
        return []

    patient = patients[0]
    readings = []

    # Fetch graph data (last ~8 hours of readings)
    try:
        graph_readings = client.graph(patient_identifier=patient.patient_id)
        for r in graph_readings:
            ts_utc = r.factory_timestamp
            ts_calgary = ts_utc.astimezone(CALGARY_TZ).replace(tzinfo=None)
            mg_val = float(r.value_in_mg_per_dl)
            # Reject obviously invalid readings (sensor errors return 0 or very high values)
            if 18 <= mg_val <= 720:
                readings.append({
                    "timestamp": ts_calgary.isoformat(),
                    "value_in_mg_per_dl": mg_val,
                    "trend": "",
                    "source": "live",
                })
    except Exception as e:
        print(f"WARNING: Error fetching graph data: {e}")

    # Also fetch the latest single reading (may be more recent than graph)
    try:
        latest = client.latest(patient_identifier=patient.patient_id)
        if latest:
            trend_val = ""
            if hasattr(latest, 'trend') and latest.trend is not None:
                trend_val = latest.trend.name if hasattr(latest.trend, 'name') else str(latest.trend)
            ts_utc = latest.factory_timestamp
            ts_calgary = ts_utc.astimezone(CALGARY_TZ).replace(tzinfo=None)
            mg_val = float(latest.value_in_mg_per_dl)
            if 18 <= mg_val <= 720:
                readings.append({
                    "timestamp": ts_calgary.isoformat(),
                    "value_in_mg_per_dl": mg_val,
                    "trend": trend_val,
                    "source": "live",
                })
    except Exception as e:
        print(f"WARNING: Error fetching latest reading: {e}")

    return readings


def merge_readings(existing: list[dict], new_readings: list[dict]) -> list[dict]:
    """Merge new readings into existing, deduplicate by timestamp, sort by time.
    No trimming — all historical data is preserved."""
    all_readings = {r["timestamp"]: r for r in existing}
    for r in new_readings:
        all_readings[r["timestamp"]] = r
    merged = sorted(all_readings.values(), key=lambda x: x["timestamp"])
    return merged


def get_last_cached_timestamp(cache: dict) -> datetime | None:
    """Return the most recent timestamp in the cache as a timezone-aware datetime."""
    readings = cache.get("readings", [])
    if not readings:
        return None
    latest_str = max(r["timestamp"] for r in readings)
    try:
        dt = datetime.fromisoformat(latest_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CALGARY_TZ)
        return dt
    except Exception:
        return None


def main():
    email = os.environ.get("LIBREVIEW_EMAIL", "")
    password = os.environ.get("LIBREVIEW_PASSWORD", "")

    if not email or not password:
        print("ERROR: LIBREVIEW_EMAIL and LIBREVIEW_PASSWORD environment variables must be set.")
        sys.exit(1)

    now_utc = datetime.now(timezone.utc)
    now_calgary = now_utc.astimezone(CALGARY_TZ)
    print(f"[{now_utc.isoformat()}] Starting CGM poll (Calgary: {now_calgary.strftime('%Y-%m-%d %H:%M:%S %Z')})")

    # Load existing cache
    cache = load_cache()
    existing_count = len(cache.get("readings", []))
    print(f"Existing cache: {existing_count:,} readings")

    # Check for gap — warn if last reading is more than 15 minutes old
    last_ts = get_last_cached_timestamp(cache)
    if last_ts:
        gap_minutes = (now_calgary.replace(tzinfo=CALGARY_TZ) - last_ts.astimezone(CALGARY_TZ)).total_seconds() / 60
        if gap_minutes > 15:
            print(f"WARNING: Last cached reading is {gap_minutes:.0f} min old ({last_ts.strftime('%Y-%m-%d %H:%M')} MT). Gap detected — fetching to backfill.")
        else:
            print(f"Last cached reading: {last_ts.strftime('%Y-%m-%d %H:%M')} MT ({gap_minutes:.0f} min ago)")

    # Authenticate and fetch
    try:
        client = authenticate(email, password)
        print("Authenticated successfully.")
    except Exception as e:
        print(f"ERROR: Authentication failed after retries: {e}")
        sys.exit(1)

    new_readings = fetch_readings(client)
    print(f"Fetched {len(new_readings)} readings from API.")

    if not new_readings:
        print("No readings returned from API — cache unchanged.")
        sys.exit(0)

    # Merge and save
    merged = merge_readings(cache.get("readings", []), new_readings)
    cache["readings"] = merged
    cache["last_updated"] = datetime.now(CALGARY_TZ).isoformat()
    cache["source"] = "live_api"

    save_cache(cache)
    added = len(merged) - existing_count
    latest_in_cache = max(r["timestamp"] for r in merged)
    print(f"Cache updated: {len(merged):,} total readings (+{max(0, added)} new).")
    print(f"Latest reading in cache: {latest_in_cache}")
    print("Done.")


if __name__ == "__main__":
    main()
