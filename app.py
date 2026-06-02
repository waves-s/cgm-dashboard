import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
from pylibrelinkup import PyLibreLinkUp
from pylibrelinkup.exceptions import AuthenticationError
import os

# Page configuration
st.set_page_config(
    page_title="CGM Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
    <style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    .high-glucose {
        color: #ff4444;
        font-weight: bold;
    }
    .normal-glucose {
        color: #44aa44;
        font-weight: bold;
    }
    .low-glucose {
        color: #ff6600;
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if 'api' not in st.session_state:
    st.session_state.api = None
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'last_update' not in st.session_state:
    st.session_state.last_update = None

def get_glucose_color(glucose_value):
    """Return color based on glucose level"""
    if glucose_value < 70:
        return "low-glucose"
    elif glucose_value > 180:
        return "high-glucose"
    else:
        return "normal-glucose"

def authenticate_user(email, password):
    """Authenticate with LibreView API"""
    try:
        api = PyLibreLinkUp(email, password)
        api.authenticate()
        st.session_state.api = api
        st.session_state.authenticated = True
        st.success("✅ Successfully authenticated with LibreView!")
        return True
    except AuthenticationError as e:
        st.error(f"❌ Authentication failed: {str(e)}")
        return False
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
        return False

def fetch_glucose_data():
    """Fetch glucose data from LibreView API"""
    try:
        if st.session_state.api is None:
            return None, None
        
        # Get latest reading
        latest = st.session_state.api.latest()
        
        # Get graph data (last 24 hours)
        graph_data = st.session_state.api.graph()
        
        st.session_state.last_update = datetime.now()
        return latest, graph_data
    except Exception as e:
        st.error(f"Error fetching data: {str(e)}")
        return None, None

def format_glucose_reading(glucose_value):
    """Format glucose reading with appropriate styling"""
    color_class = get_glucose_color(glucose_value)
    return f'<span class="{color_class}">{glucose_value} mg/dL</span>'

# Main app layout
st.title("📊 Continuous Glucose Monitor Dashboard")

# Sidebar for authentication
with st.sidebar:
    st.header("🔐 Authentication")
    
    if not st.session_state.authenticated:
        st.info("Enter your LibreView credentials to get started")
        
        email = st.text_input("Email", type="default", placeholder="your@email.com")
        password = st.text_input("Password", type="password", placeholder="Your password")
        
        if st.button("Login", use_container_width=True):
            if email and password:
                with st.spinner("Authenticating..."):
                    authenticate_user(email, password)
            else:
                st.warning("Please enter both email and password")
    else:
        st.success("✅ Authenticated")
        if st.button("Logout", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.api = None
            st.rerun()
    
    st.divider()
    
    # Refresh settings
    st.header("🔄 Refresh Settings")
    refresh_interval = st.selectbox(
        "Auto-refresh interval",
        options=[1, 5, 10, 15, 30],
        index=1,
        format_func=lambda x: f"{x} minutes"
    )
    
    if st.button("Refresh Now", use_container_width=True):
        st.rerun()
    
    st.divider()
    
    # Last update info
    if st.session_state.last_update:
        st.caption(f"Last updated: {st.session_state.last_update.strftime('%H:%M:%S')}")

# Main content
if st.session_state.authenticated:
    # Fetch data
    latest, graph_data = fetch_glucose_data()
    
    if latest and graph_data:
        # Extract current glucose value
        current_glucose = latest.get("value", 0)
        trend = latest.get("trend", "")
        timestamp = latest.get("timestamp", "")
        
        # Display current reading prominently
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(
                "Current Glucose",
                f"{current_glucose} mg/dL",
                delta=f"Trend: {trend}" if trend else None
            )
        
        with col2:
            st.metric(
                "Last Reading",
                timestamp if timestamp else "N/A"
            )
        
        with col3:
            status = "🟢 Normal"
            if current_glucose < 70:
                status = "🔴 Low"
            elif current_glucose > 180:
                status = "🟠 High"
            st.metric("Status", status)
        
        st.divider()
        
        # Tabs for different views
        tab1, tab2, tab3 = st.tabs(["📈 Chart", "📋 Readings", "📊 Statistics"])
        
        with tab1:
            st.subheader("Glucose Trend Chart")
            
            # Prepare data for chart
            if isinstance(graph_data, list) and len(graph_data) > 0:
                df = pd.DataFrame(graph_data)
                
                if 'timestamp' in df.columns and 'value' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                    df = df.sort_values('timestamp')
                    
                    # Create interactive chart
                    fig = go.Figure()
                    
                    fig.add_trace(go.Scatter(
                        x=df['timestamp'],
                        y=df['value'],
                        mode='lines+markers',
                        name='Glucose Level',
                        line=dict(color='#1f77b4', width=2),
                        marker=dict(size=6)
                    ))
                    
                    # Add target range
                    fig.add_hline(y=70, line_dash="dash", line_color="orange", 
                                 annotation_text="Low (70)", annotation_position="right")
                    fig.add_hline(y=180, line_dash="dash", line_color="red", 
                                 annotation_text="High (180)", annotation_position="right")
                    
                    fig.update_layout(
                        title="Glucose Readings Over Time",
                        xaxis_title="Time",
                        yaxis_title="Glucose (mg/dL)",
                        hovermode='x unified',
                        height=500,
                        template="plotly_white"
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("Chart data format not recognized")
            else:
                st.info("No graph data available")
        
        with tab2:
            st.subheader("Recent Readings")
            
            if isinstance(graph_data, list) and len(graph_data) > 0:
                df = pd.DataFrame(graph_data)
                
                if 'timestamp' in df.columns and 'value' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                    df = df.sort_values('timestamp', ascending=False)
                    df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
                    df = df.rename(columns={'value': 'Glucose (mg/dL)', 'timestamp': 'Time'})
                    
                    # Display as scrollable table
                    st.dataframe(
                        df[['Time', 'Glucose (mg/dL)']],
                        use_container_width=True,
                        height=400
                    )
                else:
                    st.warning("Reading data format not recognized")
            else:
                st.info("No readings available")
        
        with tab3:
            st.subheader("Statistics")
            
            if isinstance(graph_data, list) and len(graph_data) > 0:
                df = pd.DataFrame(graph_data)
                
                if 'value' in df.columns:
                    glucose_values = df['value'].astype(float)
                    
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        st.metric("Average", f"{glucose_values.mean():.1f} mg/dL")
                    
                    with col2:
                        st.metric("Min", f"{glucose_values.min():.0f} mg/dL")
                    
                    with col3:
                        st.metric("Max", f"{glucose_values.max():.0f} mg/dL")
                    
                    with col4:
                        st.metric("Std Dev", f"{glucose_values.std():.1f}")
                    
                    # Time in range calculation
                    st.divider()
                    st.subheader("Time in Range Analysis")
                    
                    low_count = (glucose_values < 70).sum()
                    normal_count = ((glucose_values >= 70) & (glucose_values <= 180)).sum()
                    high_count = (glucose_values > 180).sum()
                    total_count = len(glucose_values)
                    
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        low_pct = (low_count / total_count * 100) if total_count > 0 else 0
                        st.metric("🔴 Low (<70)", f"{low_pct:.1f}%")
                    
                    with col2:
                        normal_pct = (normal_count / total_count * 100) if total_count > 0 else 0
                        st.metric("🟢 Normal (70-180)", f"{normal_pct:.1f}%")
                    
                    with col3:
                        high_pct = (high_count / total_count * 100) if total_count > 0 else 0
                        st.metric("🟠 High (>180)", f"{high_pct:.1f}%")
                else:
                    st.warning("Statistics data format not recognized")
            else:
                st.info("No data available for statistics")
    else:
        st.error("Failed to fetch glucose data. Please check your credentials and try again.")

else:
    st.info("👈 Please log in using your LibreView credentials in the sidebar to view your glucose data.")
    
    st.markdown("""
    ## About This Dashboard
    
    This dashboard displays your continuous glucose monitor (CGM) readings from LibreView in real-time.
    
    **Features:**
    - 📊 Real-time glucose readings
    - 📈 Interactive trend charts
    - 📋 Scrollable reading history
    - 📊 Statistics and time-in-range analysis
    - 🔄 Auto-refresh capability
    
    **How to use:**
    1. Enter your LibreView email and password in the sidebar
    2. Click "Login" to authenticate
    3. Your glucose data will load automatically
    4. Use the tabs to view charts, readings, and statistics
    5. Set your preferred refresh interval
    """)
