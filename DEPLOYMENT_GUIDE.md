# CGM Dashboard — Streamlit Cloud Deployment Guide

## Your GitHub Repository

Your code is live at:
**https://github.com/waves-s/cgm-dashboard**

---

## Step-by-Step: Deploy to Streamlit Cloud

### Step 1 — Sign up / Log in to Streamlit Cloud

1. Go to **https://share.streamlit.io**
2. Click **"Sign in with GitHub"**
3. Authorize Streamlit to access your GitHub account (wavess@gmail.com)

---

### Step 2 — Create a New App

1. Once logged in, click **"New app"** (top right)
2. Fill in the form:
   - **Repository**: `waves-s/cgm-dashboard`
   - **Branch**: `main`
   - **Main file path**: `app.py`
3. Click **"Deploy!"**

---

### Step 3 — Add Your LibreView Credentials (Secrets)

> This is the secure way to store your password — it is encrypted and never visible in code.

1. After deploying, go to your app's **Settings** (gear icon ⚙️)
2. Click **"Secrets"** in the left menu
3. Paste the following into the secrets box:

```toml
[libreview]
email = "rddhawan@yahoo.com"
password = "YOUR_NEW_PASSWORD_HERE"
```

> **Important**: Use your **new** LibreView password (please change it first at https://www.libreview.com)

4. Click **"Save"**
5. The app will automatically restart and your credentials will be loaded securely

---

### Step 4 — Get Your Shareable Link

Once deployed, Streamlit gives you a public URL like:
```
https://waves-s-cgm-dashboard-app-xxxxxx.streamlit.app
```

You can **share this link with anyone** — they will see your live glucose dashboard without needing to log in again (the credentials are stored in secrets on the server side).

---

## How to Use the Dashboard

| Feature | How to Access |
|---|---|
| **Current Reading** | Shown at the top with trend arrow and status badge |
| **Trend Chart** | Click the "📈 Trend Chart" tab — use the slider to adjust time window |
| **Scrollable Readings** | Click the "📋 All Readings" tab — scroll through full history |
| **Statistics** | Click the "📊 Statistics" tab — avg, min, max, time-in-range, daily chart |
| **Auto-Refresh** | In the sidebar, select refresh interval (1, 5, 10, 15, or 30 min) |
| **Manual Refresh** | Click "Refresh Now" in the sidebar |

---

## Glucose Range Reference

| Zone | Range | Color |
|---|---|---|
| Low | < 70 mg/dL | 🟠 Orange |
| In Range | 70–180 mg/dL | 🟢 Green |
| High | > 180 mg/dL | 🔴 Red |

---

## Troubleshooting

| Issue | Solution |
|---|---|
| "Authentication failed" | Check your LibreView email/password in Secrets |
| "Privacy Policy error" | Open the LibreLink app and accept the latest privacy policy |
| "Terms of Use error" | Open the LibreLink app and accept the latest terms |
| "Rate limited" | Wait a few minutes and refresh — LibreView limits API calls |
| No data showing | Make sure your CGM sensor is active and synced to LibreView |

---

## Security Notes

- Your LibreView credentials are stored **encrypted** in Streamlit Cloud Secrets
- They are **never** stored in the GitHub repository
- The GitHub token used to push code has **already expired** (30-day token, used once)
- It is strongly recommended to **change your LibreView password** since it was shared in chat

---

## Need to Update the App?

If you want to make changes to the dashboard in the future:
1. Edit `app.py` directly on GitHub (click the file → pencil icon ✏️)
2. Commit the change
3. Streamlit Cloud will automatically redeploy within ~1 minute
