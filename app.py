import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import json

# Try to import the Google GenAI library; install message if missing
try:
    import google.generativeai as genai
except ImportError:
    st.error("Please add 'google-generativeai' to your repository's requirements.txt file.")
    st.stop()

# ==========================================
# 1. SIMPLE PASSWORD PROTECTION
# ==========================================
def check_password():
    if "password" not in st.session_state:
        st.session_state.password = ""
    if st.session_state.password == st.secrets["password"]:
        return True
    st.title("👨‍👩‍👧‍👦 Family Calendar Chatbot & Optimizer")
    st.text_input("Enter Family Password", type="password", key="password")
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

# ==========================================
# 3. LIVE AUTOMATED PDF UPLOADER VIA GEMINI
# ==========================================
st.title("📅 Our Shared Family Calendar Optimizer")

st.subheader("🤖 Auto-Populate from School Calendar PDF")
uploaded_pdf = st.file_uploader("Drop your school calendar PDF here to instantly parse it:", type=["pdf"])

if uploaded_pdf:
    if "gemini_api_key" not in st.secrets:
        st.error("Missing 'gemini_api_key' in your Streamlit Secrets.")
    else:
        with st.spinner("Gemini is reading the PDF and parsing holiday ranges..."):
            try:
                # Configure Gemini
                genai.configure(api_key=st.secrets["gemini_api_key"])
                model = genai.GenerativeModel('gemini-1.5-flash')
                
                # Read PDF raw bytes to pass directly to Gemini
                pdf_bytes = uploaded_pdf.read()
                
                # Robust engineering prompt to force structured JSON data
                ai_prompt = """
                Analyze this school calendar. Identify all school holiday closures and breaks that take place in the year 2027.
                Ignore half-day closures or simple teacher-prep single days if they don't block out a full vacation block.
                Format the final answer strictly as a raw JSON list with no markdown wrapper, like this:
                [
                  {"name": "Winter Break", "start": "2027-01-01", "end": "2027-01-03"},
                  {"name": "Spring Break", "start": "2027-04-05", "end": "2027-04-07"}
                ]
                """
                
                response = model.generate_content([
                    {'mime_type': 'application/pdf', 'data': pdf_bytes},
                    ai_prompt
                ])
                
                # Sanitize the output text string to parse JSON reliably
                clean_json_text = response.text.replace("```json", "").replace("```", "").strip()
                extracted_holidays = json.loads(clean_json_text)
                
                # Write discoveries directly to SQLite database
                inserted_count = 0
                for holiday in extracted_holidays:
                    cursor.execute(
                        "INSERT INTO school_holidays (name, start_date, end_date) VALUES (?, ?, ?)",
                        (holiday['name'], holiday['start'], holiday['end'])
                    )
                    inserted_count += 1
                conn.commit()
                
                st.success(f"🎉 Success! Gemini successfully extracted and saved {inserted_count} holiday blocks to your database.")
                st.rerun()
                
            except Exception as e:
                st.error(f"AI Parsing Error: {e}")

# ==========================================
# 4. MANUAL INPUT FALLBACKS
# ==========================================
st.write("---")
col_input1, col_input2 = st.columns(2)

with col_input1:
    st.subheader("🏫 Manual Add Holiday")
    h_name = st.text_input("Break Name")
    h_start = st.date_input("Start Date", value=datetime(2027, 1, 1))
    h_end = st.date_input("End Date", value=datetime(2027, 1, 1))
    if st.button("💾 Save Break"):
        if h_name:
            cursor.execute("INSERT INTO school_holidays (name, start_date, end_date) VALUES (?, ?, ?)", (h_name, h_start.strftime('%Y-%m-%d'), h_end.strftime('%Y-%m-%d')))
            conn.commit()
            st.rerun()

with col_input2:
    st.subheader("✈️ Add Trip Destination")
    d_loc = st.text_input("Location Name")
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
# 5. DATA COMPILATION & CALCULATIONS
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
# 6. GRAPHICS & ANALYSIS DISPLAY
# ==========================================
if not df_trips.empty:
    total_pto = df_trips["PTO Days Needed"].sum()
    m_col1, m_col2 = st.columns(2)
    m_col1.metric("Total Planned Trips", len(df_trips))
    m_col2.metric("Total Work PTO Days Needed", int(total_pto))
    
    st.subheader("✈️ Calculated Travel Windows")
    display_df = df_trips.copy()
    display_df["Start Date"] = display_df["Start Date"].dt.strftime('%A, %b %d, %Y')
    display_df["End Date"] = display_df["End Date"].dt.strftime('%A, %b %d, %Y')
    st.dataframe(display_df, use_container_width=True)
    
    st.subheader("🚨 Burnout Analysis")
    break_days = set(fed_holidays_2027)
    if not df_school.empty:
        for _, row in df_school.iterrows(): break_days.update(pd.date_range(row['Start Date'], row['End Date']))
    for _, row in df_trips.iterrows(): break_days.update(pd.date_range(row['Start Date'], row['End Date']))
    
    current_gap, gap_start, burnout_zones = 0, None, []
    for day in pd.date_range("2027-01-01", "2027-12-31"):
        if day in break_days:
            if current_gap > 30: burnout_zones.append((gap_start, day - timedelta(days=1), current_gap))
            current_gap, gap_start = 0, None
        else:
            if current_gap == 0: gap_start = day
            current_gap += 1
            
    if burnout_zones:
        for start, end, days in burnout_zones:
            st.error(f"⚠️ **Burnout Risk Zone:** No breaks scheduled for **{days} days** between {start.strftime('%b %d')} and {end.strftime('%b %d')}.")
    else:
        st.success("🎉 Pacing looks great! Your calendar has no stretches longer than 30 days without a break.")
else:
    st.info("👋 Upload a school calendar PDF or type a destination above to watch your automated travel calendar map out.")
