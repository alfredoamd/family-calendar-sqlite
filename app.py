import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import json
import plotly.express as px
import plotly.graph_objects as go

# Try to import the Google GenAI library
try:
    import google.generativeai as genai
except ImportError:
    st.error("Please add required items to requirements.txt.")
    st.stop()

# ==========================================
# 1. FIXED PASSWORD PROTECTION (WITH MEMORY)
# ==========================================
def check_password():
    if st.session_state.get("password_correct", False):
        return True
    
    st.title("👨‍👩‍👧‍👦 Family Calendar Chatbot & Optimizer")
    user_input = st.text_input("Enter Family Password", type="password")
    
    if user_input == st.secrets["password"]:
        st.session_state["password_correct"] = True
        st.rerun()
        return True
    elif user_input != "":
        st.error("❌ Incorrect password, please try again.")
    return False

if not check_password():
    st.stop()

# ==========================================
# 2. SQLITE DATABASE INITIALIZATION
# ==========================================
conn = sqlite3.connect("family_calendar.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS school_holidays (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, start_date TEXT, end_date TEXT
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS destinations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, location TEXT
    )
''')
conn.commit()

st.title("📅 Our Shared Family Calendar Optimizer")

# ==========================================
# 3. LIVE AUTOMATED PDF UPLOADER VIA GEMINI
# ==========================================
with st.sidebar.expander("🤖 Auto-Populate via School PDF"):
    uploaded_pdf = st.file_uploader("Drop school calendar PDF here:", type=["pdf"])
    if uploaded_pdf and "gemini_api_key" in st.secrets:
        with St.spinner("Parsing PDF..."):
            try:
                genai.configure(api_key=st.secrets["gemini_api_key"])
                model = genai.GenerativeModel('gemini-3.8-flash')
                pdf_bytes = uploaded_pdf.read()
                ai_prompt = "Extract school closures for 2027 into a raw JSON list: [{\"name\": \"...\", \"start\": \"YYYY-MM-DD\", \"end\": \"YYYY-MM-DD\"}]"
                response = model.generate_content([{'mime_type': 'application/pdf', 'data': pdf_bytes}, ai_prompt])
                clean_json = response.text.replace("```json", "").replace("```", "").strip()
                for h in json.loads(clean_json):
                    cursor.execute("INSERT INTO school_holidays (name, start_date, end_date) VALUES (?, ?, ?)", (h['name'], h['start'], h['end']))
                conn.commit()
                st.success("Extracted successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Quota/API hold active: Please use the manual entry form below.")

# ==========================================
# 4. DATA INPUT DASHBOARD FOR DATA SEEDING
# ==========================================
col_input1, col_input2 = st.columns(2)

with col_input1:
    st.subheader("🏫 Manual Add Holiday")
    h_name = st.text_input("Break Name", key="manual_hname")
    h_start = st.date_input("Start Date", value=datetime(2027, 1, 1), key="manual_hstart")
    h_end = st.date_input("End Date", value=datetime(2027, 1, 1), key="manual_hend")
    if st.button("💾 Save Break"):
        if h_name:
            cursor.execute("INSERT INTO school_holidays (name, start_date, end_date) VALUES (?, ?, ?)", (h_name, h_start.strftime('%Y-%m-%d'), h_end.strftime('%Y-%m-%d')))
            conn.commit()
            st.rerun()

with col_input2:
    st.subheader("✈️ Add Trip Destination")
    d_loc = st.text_input("Location Name", key="manual_dloc")
    if st.button("💾 Save Destination"):
        if d_loc:
            cursor.execute("INSERT INTO destinations (location) VALUES (?)", (d_loc,))
            conn.commit()
            st.rerun()

with st.sidebar.expander("🚨 Advanced Database Controls"):
    if st.button("🗑️ Wipe All Holiday & Destination Data"):
        cursor.execute("DELETE FROM school_holidays")
        cursor.execute("DELETE FROM destinations")
        conn.commit()
        st.rerun()

# ==========================================
# 5. DATA COMPILATION & OPTIMIZATION LOGIC
# ==========================================
df_school = pd.read_sql_query("SELECT name as 'Holiday Name', start_date as 'Start Date', end_date as 'End Date' FROM school_holidays", conn)
df_dest = pd.read_sql_query("SELECT location as 'Location' FROM destinations", conn)

if not df_school.empty:
    df_school['Start Date'] = pd.to_datetime(df_school['Start Date'])
    df_school['End Date'] = pd.to_datetime(df_school['End Date'])

fed_holidays_2027 = pd.to_datetime([
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-05-31", 
    "2027-06-19", "2027-07-05", "2027-09-06", "2027-10-11", 
    "2027-11-11", "2027-11-25", "2027-12-24"
])

st.sidebar.title("🛠️ Optimization Settings")
trip_buffer = st.sidebar.slider("Minimum days between trips", 21, 45, 28)
trip_length = st.sidebar.slider("Standard trip length (days)", 3, 7, 5)

def optimize_calendar(df_school, df_dest, buffer_days, length_days):
    if df_dest.empty: return pd.DataFrame()
    start_date, end_date = datetime(2027, 1, 1), datetime(2027, 12, 31)
    all_days = pd.date_range(start=start_date, end=end_date)
    priority_days = set()
    if not df_school.empty:
        for _, row in df_school.iterrows(): priority_days.update(pd.date_range(row['Start Date'], row['End Date']))
    priority_days.update(fed_holidays_2027)
    
    scheduled_trips = []
    last_trip_end = datetime(2026, 12, 1)
    
    for _, dest_row in df_dest.iterrows():
        location = dest_row['Location']
        trip_placed = False
        for current_day in all_days:
            if current_day < last_trip_end + timedelta(days=buffer_days): continue
            potential_trip = pd.date_range(current_day, current_day + timedelta(days=length_days - 1))
            if potential_trip[-1] > end_date: break
            overlap_score = sum(1 for d in potential_trip if d in priority_days)
            if overlap_score >= 1 or current_day.day == 15:
                pto_days = sum(1 for d in potential_trip if d.weekday() < 5 and d not in fed_holidays_2027)
                scheduled_trips.append({"Destination": location, "Start Date": current_day, "End Date": potential_trip[-1], "PTO Days Needed": pto_days})
                last_trip_end = potential_trip[-1]
                trip_placed = True
                break
    return pd.DataFrame(scheduled_trips)

df_trips = optimize_calendar(df_school, df_dest, trip_buffer, trip_length)

# ==========================================
# 6. HIGH-END 12-MONTH VISUAL CALENDAR GRID
# ==========================================
st.write("---")
st.subheader("🗓️ 2027 Master Annual Calendar Matrix View")

# Define status integers for categorization mapping
# 0 = Normal Day, 1 = Federal Holiday, 2 = School Holiday, 3 = Family Trip Vacation
year_days = pd.date_range(start="2027-01-01", end="2027-12-31")
df_vis = pd.DataFrame({"Date": year_days})
df_vis["Status"] = "Routine Day"

# Inject Data Profiles into Matrix
if not df_school.empty:
    for _, row in df_school.iterrows():
        df_vis.loc[(df_vis["Date"] >= row["Start Date"]) & (df_vis["Date"] <= row["End Date"]), "Status"] = f"School Break: {row['Holiday Name']}"

for f_day in fed_holidays_2027:
    df_vis.loc[df_vis["Date"] == f_day, "Status"] = "Federal Holiday"

if not df_trips.empty:
    for _, row in df_trips.iterrows():
        df_vis.loc[(df_vis["Date"] >= row["Start Date"]) & (df_vis["Date"] <= row["End Date"]), "Status"] = f"Family Trip: {row['Destination']}"

df_vis["Month"] = df_vis["Date"].dt.strftime("%B")
df_vis["Day"] = df_vis["Date"].dt.day
df_vis["WeekOfMonth"] = df_vis["Date"].apply(lambda d: (d.day-1)//7 + 1)
df_vis["DayOfWeek"] = df_vis["Date"].dt.strftime("%a")

# Create 12 distinct subplots using a Plotly Facet Grid
months_order = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

fig = px.gantt() # Empty layout init object wrapper fallback replacement
fig = go.Figure()

# Custom color palette coordinates mapping
color_map = {
    "Routine Day": "#F0F2F6",
    "Federal Holiday": "#31333F",
    "School Break": "#FF4B4B",
    "Family Trip": "#00C0F2"
}

# Simplify status strings into main categories for cleaner color matching
def parse_category(status):
    if "School Break" in status: return "School Break"
    if "Family Trip" in status: return "Family Trip"
    if "Federal" in status: return "Federal Holiday"
    return "Routine Day"

df_vis["ColorCategory"] = df_vis["Status"].apply(parse_category)
df_vis["ColorCode"] = df_vis["ColorCategory"].map(color_map)

# Draw an interactive visual matrix directly inside Streamlit container windows
st.markdown(
    "🟢 **Light Teal:** Family Vacation | 🔴 **Red:** School Breaks | 🔵 **Dark Charcoal:** Federal Holidays | ⚪ **Light Grey:** Normal Days"
)

# Plotly calendar matrix rendering chunk
fig = px.scatter(
    df_vis, 
    x="DayOfWeek", 
    y="WeekOfMonth", 
    color="ColorCategory",
    hover_data={"Date": "|%b %d, %Y", "Status": True, "DayOfWeek": False, "WeekOfMonth": False},
    text="Day",
    facet_col="Month", 
    facet_col_wrap=4,
    category_orders={"Month": months_order, "DayOfWeek": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]},
    color_discrete_map=color_map,
    title="2027 Comprehensive Family Schedule View"
)

fig.update_traces(marker=dict(size=24, symbol="square"), textfont=dict(size=9, color="black"))
fig.update_yaxes(autorange="reverse", visible=False)
fig.update_xaxes(title_text="")
fig.update_layout(height=650, showlegend=False, margin=dict(t=40, b=10, l=10, r=10))

