# CGM Dashboard - LibreView Glucose Monitor

A real-time continuous glucose monitor (CGM) dashboard built with Streamlit that displays your LibreView glucose readings with interactive charts, statistics, and time-in-range analysis.

## Features

- **Real-time Glucose Readings**: View your latest glucose value with trend information
- **Interactive Charts**: Visualize glucose trends over time with Plotly
- **Reading History**: Scroll through all recent glucose readings
- **Statistics**: View average, min, max, and standard deviation
- **Time-in-Range Analysis**: See percentage of time in target, low, and high ranges
- **Auto-Refresh**: Automatic data refresh at configurable intervals
- **Secure Authentication**: Uses your LibreView email and password

## Installation

### Local Development

1. Clone the repository:
```bash
git clone https://github.com/yourusername/cgm-dashboard.git
cd cgm-dashboard
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run the app:
```bash
streamlit run app.py
```

The app will open at `http://localhost:8501`

## Deployment to Streamlit Cloud

### Step 1: Push to GitHub

1. Create a new GitHub repository (e.g., `cgm-dashboard`)
2. Push this code to your repository:
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/yourusername/cgm-dashboard.git
git push -u origin main
```

### Step 2: Deploy on Streamlit Cloud

1. Go to [Streamlit Cloud](https://streamlit.io/cloud)
2. Click "New app"
3. Select your GitHub repository (`cgm-dashboard`)
4. Select the branch (`main`) and file (`app.py`)
5. Click "Deploy"

### Step 3: Add Secrets

1. In Streamlit Cloud, go to your app settings
2. Click "Secrets" in the left sidebar
3. Add your LibreView credentials in the secrets editor:

```toml
LIBREVIEW_EMAIL = "your@email.com"
LIBREVIEW_PASSWORD = "your_password"
```

4. Click "Save"

The app will automatically reload with your credentials.

## Usage

1. **First Time**: Enter your LibreView email and password in the sidebar
2. **View Dashboard**: Your glucose data will load automatically
3. **Explore Data**: Use the tabs to view charts, readings, and statistics
4. **Refresh**: Set your preferred refresh interval or click "Refresh Now"
5. **Share**: Copy the Streamlit Cloud URL to share with others

## Security Notes

- Your credentials are only used to authenticate with LibreView
- Never commit credentials to GitHub
- Use Streamlit Cloud's Secrets Manager for secure credential storage
- The app does not store your credentials locally

## Data Privacy

- This app only reads your glucose data from LibreView
- No data is stored on external servers
- Your data remains private and is only displayed in your dashboard

## Troubleshooting

### Authentication Failed
- Verify your LibreView email and password are correct
- Check if your LibreView account is active
- Ensure you have access to LibreView in your region

### No Data Displayed
- Check your internet connection
- Verify your sensor is active and synced
- Try clicking "Refresh Now"

### Chart Not Loading
- Ensure you have recent glucose readings (within last 24 hours)
- Check browser console for errors

## Support

For issues or feature requests, please open an issue on GitHub.

## License

This project is provided as-is for personal use.

## Disclaimer

This is an unofficial dashboard for LibreView. It is not affiliated with Abbott Diabetes Care, Inc. or any of its subsidiaries. Always consult with your healthcare provider regarding your diabetes management.
