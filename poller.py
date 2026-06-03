#!/usr/bin/env python3
"""
CGM Background Poller
Fetches latest glucose readings from LibreView API and appends to cache.json.
Designed to run via GitHub Actions every 5 minutes.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CALGARY_TZ = ZoneInfo("America/Edmonton")  # Calgary / Mountain Time

from pylibrelinkup import PyLibreLinkUp, APIUrl
from pylibrelinkup.exceptions import RedirectError

CACHE_FILE = Path(__file__).parent / "cache.json"
MAX_CACHE_READINGS = 52560  # ~6 months at 1 reading/5 min


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
        except (json.JSONDecodeError, KeyError):
            pass
    return {"readings": [], "last_updated": None, "source": "live_api"}


def save_cache(data: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def authenticate(email: str, password: str):
    """Try to authenticate, auto-handling region redirects."""
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


def fetch_readings(client) -> list[dict]:
    """Fetch latest readings from graph endpoint and return as list of dicts."""
    patients = client.get_patients()
    if not patients:
        print("No patients found.")
        return []

    patient = patients[0]
    readings = []

    try:
        # Use patient.patient_id (the connection UUID) as the identifier
        graph_readings = client.graph(patient_identifier=patient.patient_id)
        for r in graph_readings:
            # Convert UTC timestamp to Calgary local naive ISO string
            ts_utc = r.factory_timestamp
            ts_calgary = ts_utc.astimezone(CALGARY_TZ).replace(tzinfo=None)
            readings.append({
                "timestamp": ts_calgary.isoformat(),
                "value_mg_dl": float(r.value_in_mg_per_dl),
                "trend": "",
                "source": "live",
            })
    except Exception as e:
        print(f"Error fetching graph data: {e}")

    # Also try latest reading
    try:
        latest = client.latest(patient_identifier=patient.patient_id)
        if latest:
            trend_val = ""
            if hasattr(latest, 'trend') and latest.trend is not None:
                trend_val = latest.trend.name if hasattr(latest.trend, 'name') else str(latest.trend)
            ts_utc = latest.factory_timestamp
            ts_calgary = ts_utc.astimezone(CALGARY_TZ).replace(tzinfo=None)
            readings.append({
                "timestamp": ts_calgary.isoformat(),
                "value_mg_dl": float(latest.value_in_mg_per_dl),
                "trend": trend_val,
                "source": "live",
            })
    except Exception as e:
        print(f"Error fetching latest reading: {e}")

    return readings


def merge_readings(existing: list[dict], new_readings: list[dict]) -> list[dict]:
    """Merge new readings into existing, deduplicate by timestamp, sort by time."""
    all_readings = {r["timestamp"]: r for r in existing}
    for r in new_readings:
        all_readings[r["timestamp"]] = r

    merged = sorted(all_readings.values(), key=lambda x: x["timestamp"])

    # Trim to max size (keep most recent)
    if len(merged) > MAX_CACHE_READINGS:
        merged = merged[-MAX_CACHE_READINGS:]

    return merged


def main():
    email = os.environ.get("LIBREVIEW_EMAIL", "")
    password = os.environ.get("LIBREVIEW_PASSWORD", "")

    if not email or not password:
        print("ERROR: LIBREVIEW_EMAIL and LIBREVIEW_PASSWORD environment variables must be set.")
        sys.exit(1)

    now_utc = datetime.now(timezone.utc)
    now_calgary = now_utc.astimezone(CALGARY_TZ)
    print(f"[{now_utc.isoformat()}] Starting CGM poll... (Calgary: {now_calgary.strftime('%Y-%m-%d %H:%M:%S %Z')})")

    # Load existing cache
    cache = load_cache()
    existing_count = len(cache.get("readings", []))
    print(f"Existing cache: {existing_count} readings")

    # Authenticate and fetch
    try:
        client = authenticate(email, password)
        print("Authenticated successfully.")
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)

    new_readings = fetch_readings(client)
    print(f"Fetched {len(new_readings)} readings from API.")

    if not new_readings:
        print("No new readings to add.")
        sys.exit(0)

    # Merge and save
    merged = merge_readings(cache.get("readings", []), new_readings)
    cache["readings"] = merged
    cache["last_updated"] = datetime.now(CALGARY_TZ).isoformat()
    cache["source"] = "live_api"

    save_cache(cache)
    added = len(merged) - existing_count
    print(f"Cache updated: {len(merged)} total readings (+{max(0, added)} new).")
    print("Done.")


if __name__ == "__main__":
    main()
