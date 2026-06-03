# CGM Dashboard — Deployment & Setup Guide

## Overview

This dashboard shows your LibreView CGM readings in real time with full historical data. It works in two parts:

1. **GitHub Actions background poller** — runs every 5 minutes, 24/7, fetching your latest readings from LibreView and storing them in `cache.json` in this repo. This happens even when you are not looking at the dashboard.
2. **Streamlit web dashboard** — reads from the cache on every load, shows live readings, trend charts, and statistics.

---

## Step 1 — Deploy to Streamlit Cloud

1. Go to **https://share.streamlit.io** and sign in with your GitHub account
2. Click **"New app"**
3. Fill in:
   - **Repository**: `waves-s/cgm-dashboard`
   - **Branch**: `main`
   - **Main file path**: `app.py`
4. Click **"Deploy!"**

You will get a public shareable URL like:
`https://waves-s-cgm-dashboard-app-xxxxx.streamlit.app`

---

## Step 2 — Add LibreView Credentials to Streamlit Cloud

1. In Streamlit Cloud, go to your app → **Settings** → **Secrets**
2. Paste the following (replace with your actual credentials after changing your password):

```toml
[libreview]
email = "rddhawan@yahoo.com"
password = "YOUR_NEW_LIBREVIEW_PASSWORD"
```

3. Click **Save**

> ⚠️ **Important:** Change your LibreView password at https://www.libreview.com before adding it here.

---

## Step 3 — Verify GitHub Actions is Running

The background poller should already be running. To verify:

1. Go to **https://github.com/waves-s/cgm-dashboard/actions**
2. You should see the **"CGM Background Poller"** workflow running every 5 minutes
3. Each run fetches your latest readings and commits them to `cache.json`

The workflow uses these GitHub Secrets (already configured):
- `LIBREVIEW_EMAIL` — your LibreView email
- `LIBREVIEW_PASSWORD` — your LibreView password
- `GH_PAT` — a GitHub personal access token with `repo` + `workflow` scopes

---

## Step 4 — (Optional) Seed Historical Data

The background poller builds history from today forward. If you want data from before today:

1. Go to **https://www.libreview.com** → log in → **Glucose History** → **Download glucose data**
2. Download the CSV file
3. Open your Streamlit dashboard → sidebar → **📁 Historical Data** → upload the CSV

The app will merge it with the existing cache. You only need to do this once.

---

## How It Works Day-to-Day

| Scenario | What happens |
|---|---|
| You open the dashboard | App loads `cache.json` (up to 6 months of readings) + fetches latest live data |
| You have not visited in a week | GitHub Actions has been polling every 5 min — all readings are in `cache.json` |
| You share the URL | Anyone with the link can view your dashboard in real time |
| You want to refresh manually | Click **🔄 Refresh Now** in the sidebar |

---

## Dashboard Features

| Feature | Details |
|---|---|
| **Live Reading** | Large glucose number with trend arrow and status badge (LOW / IN RANGE / HIGH) |
| **Trend Chart** | Interactive Plotly chart with target zone, Zoom: 3h/6h/12h/24h buttons |
| **Day/Week Navigation** | ⏮ ◀ ▶ ⏭ buttons + calendar date picker |
| **Units** | mg/dL, mmol/L, or Both (dual Y-axis) |
| **Custom Target Range** | Adjustable Low/High thresholds in your chosen units |
| **All Readings Tab** | Scrollable table of all readings with colour-coded rows |
| **Statistics Tab** | Average, min/max, time-in-range donut chart, daily average bar chart |
| **Auto-Refresh** | Configurable: 1, 5, 10, 15, or 30 minutes |

---

## Security Notes

- Your LibreView credentials are stored as **encrypted GitHub Secrets** — never visible in code
- The Streamlit app reads credentials from **Streamlit Cloud Secrets** (also encrypted)
- The GitHub token (`GH_PAT`) only has access to this specific repository
- **Please change your LibreView password** if it was shared in plain text

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Login fails with "Redirected to api-ca.libreview.io" | Leave region as US — the app auto-redirects |
| Chart shows no data | Check GitHub Actions is running at `/actions`; wait 5 min for first poll |
| "No patients found" error | Your LibreView account may need to be linked to a sensor in the LibreLink app |
| GitHub Actions failing | Check Secrets are set correctly at `/settings/secrets/actions` |
| "Rate limited" warning | Wait a few minutes — LibreView limits API calls |
