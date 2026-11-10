import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta

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
# Connect to local SQLite file database (created automatically)
conn = sqlite3.connect("family_calendar.db", check_same_thread=False)
cursor = conn.cursor()

# Create tables if they do not exist
cursor.execute('''
    CREATE TABLE IF NOT EXISTS school_holidays (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        start_date TEXT,
        end_date TEXT
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS destinations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        location TEXT
    )
''')
conn.commit()

# ==========================================
# 3. DATA ENTRY DASHBOARD (FEEDING THE BOT)
# ==========================================
st.title("📅 Our Shared Family Calendar Optimizer")
st.markdown("Easily feed your calendar database below without opening spreadsheets.")

col_input1, col_input2 = st.columns(2)

with col_input1:
    st.subheader("🏫 Add School Holiday Break")
    h_name = st.text_input("Break Name (e.g., Spring Break)", key="h_name")
    h_start = st.date_input("Start Date", value=datetime(2027, 1, 1), key="h_start")
    h_end = st.date_input("End Date", value=datetime(2027, 1, 1), key="h_end")
    
    if st.button("💾 Save Break to Database"):
        if h_name:
            cursor.execute(
                "INSERT INTO school_holidays (name, start_date, end_date) VALUES (?, ?, ?)",
                (h_name, h_start.strftime('%Y-%m-%d'), h_end.strftime('%Y-%m-%d'))
            )
            conn.commit()
            st.success(f"Saved {h_name}!")
            st.rerun()
        else:
            st.error("Please enter a break name.")

with col_input2:
    st.subheader("✈️ Add Family Trip Destination")
    d_loc = st.text_input("Location Name (e.g., Miami)", key="d_loc")
    
    if st.button("💾 Save Destination"):
        if d_loc:
            cursor.execute("INSERT INTO destinations (location) VALUES (?)", (d_loc,))
            conn.commit()
            st.success(f"Saved {d_loc} to wishlist!")
            st.rerun()
        else:
            st.error("Please enter a location.")

# Database wiping option hidden inside an expander
with st.sidebar.expander("🚨 Advanced Database Controls"):
    if st.button("🗑️ Wipe All Holiday & Destination Data"):
        cursor.execute("DELETE FROM school_holidays")
        cursor.execute("DELETE FROM destinations")
        conn.commit()
        st.success("Database cleared!")
        st.rerun()

# ==========================================
# 4. LOAD & READ DATABASE DATA
# ==========================================
df_school = pd.read_sql_query("SELECT name as 'Holiday Name', start_date as 'Start Date', end_date as 'End Date' FROM school_holidays", conn)
df_dest = pd.read_sql_query("SELECT location as 'Location' FROM destinations", conn)

if not df_school.empty:
    df_school['Start Date'] = pd.to_datetime(df_school['Start Date'])
    df_school['End Date'] = pd.to_datetime(df_school['End Date'])

# HARDCODED 2027 FEDERAL HOLIDAYS
fed_holidays_2027 = pd.to_datetime([
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-05-31", 
    "2027-06-19", "2027-07-05", "2027-09-06", "2027-10-11", 
    "2027-11-11", "2027-11-25", "2027-12-24"
])

# ==========================================
# 5. SIDEBAR TRIP PARAMETERS
# ==========================================
st.sidebar.title("🛠️ Optimization Settings")
trip_buffer = st.sidebar.slider("Minimum days between trips", 21, 45, 28)
trip_length = st.sidebar.slider("Standard trip length (days)", 3, 7, 5)

# ==========================================
# 6. OPTIMIZATION LOGIC ENGINE
# ==========================================
def optimize_calendar(df_school, df_dest, buffer_days, length_days):
    if df_dest.empty:
        return pd.DataFrame()
        
    start_date = datetime(2027, 1, 1)
    end_date = datetime(2027, 12, 31)
    all_days = pd.date_range(start=start_date, end=end_date)
    
    # Map priority high-overlap days
    priority_days = set()
    if not df_school.empty:
        for _, row in df_school.iterrows():
            priority_days.update(pd.date_range(row['Start Date'], row['End Date']))
    priority_days.update(fed_holidays_2027)
    
    scheduled_trips = []
    last_trip_end = datetime(2026, 12, 1) # Anchor in the past
    
    for _, dest_row in df_dest.iterrows():
        location = dest_row['Location']
        trip_placed = False
        
        for current_day in all_days:
            if current_day < last_trip_end + timedelta(days=buffer_days):
                continue
                
            potential_trip = pd.date_range(current_day, current_day + timedelta(days=length_days - 1))
            if potential_trip[-1] > end_date:
                break
                
            overlap_score = sum(1 for d in potential_trip if d in priority_days)
            
            # Lock in trip if it overlaps a holiday or lands on mid-month spacing safely
            if overlap_score >= 1 or current_day.day == 15:
                pto_days = sum(1 for d in potential_trip if d.weekday() < 5 and d not in fed_holidays_2027)
                
                scheduled_trips.append({
                    "Destination": location,
                    "Start Date": current_day,
                    "End Date": potential_trip[-1],
                    "PTO Days Needed": pto_days
                })
                last_trip_end = potential_trip[-1]
                trip_placed = True
                break
                
    return pd.DataFrame(scheduled_trips)

df_trips = optimize_calendar(df_school, df_dest, trip_buffer, trip_length)

# ==========================================
# 7. METRICS & ANALYSIS PRESENTATION
# ==========================================
st.write("---")

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
    
    # 8. BURNOUT RISK GAP DETECTOR
    st.subheader("🚨 Burnout Analysis")
    break_days = set(fed_holidays_2027)
    if not df_school.empty:
        for _, row in df_school.iterrows():
            break_days.update(pd.date_range(row['Start Date'], row['End Date']))
    for _, row in df_trips.iterrows():
        break_days.update(pd.date_range(row['Start Date'], row['End Date']))
        
    current_gap = 0
    gap_start = None
    burnout_zones = []
    
    for day in pd.date_range("2027-01-01", "2027-12-31"):
        if day in break_days:
            if current_gap > 30:
                burnout_zones.append((gap_start, day - timedelta(days=1), current_gap))
            current_gap = 0
            gap_start = None
        else:
            if current_gap == 0:
                gap_start = day
            current_gap += 1
            
    if burnout_zones:
        for start, end, days in burnout_zones:
            st.error(f"⚠️ **Burnout Risk Zone:** No breaks scheduled for **{days} days** between {start.strftime('%b %d')} and {end.strftime('%b %d')}.")
    else:
        st.success("🎉 Pacing looks great! Your calendar has no stretches longer than 30 days without a break.")

    # ==========================================
    # 9. GEMINI PROMPT EXPORT ENGINE
    # ==========================================
    st.subheader("🤖 Human-Factor Optimization with Gemini AI")
    school_list = [f"{row['Holiday Name']} ({row['Start Date'].strftime('%b %d')} to {row['End Date'].strftime('%b %d')})" for _, row in df_school.iterrows()] if not df_school.empty else ["None entered"]
    current_trips = [f"{row['Destination']} from {row['Start Date'].strftime('%b %d')} to {row['End Date'].strftime('%b %d')} ({row['PTO Days Needed']} PTO days)" for _, row in df_trips.iterrows()]
    burnout_text = [f"From {start.strftime('%b %d')} to {end.strftime('%b %d')} ({days} days)" for start, end, days in burnout_zones] if burnout_zones else ["None!"]

    ai_prompt_template = f"""
I am using a Python local SQLite optimizer script for my family travel calendar. Look over our calculated dates and suggest 3 smarter alternative layouts.

Here is our active data state for 2027:
- **School Breaks:** {', '.join(school_list)}
- **Current Scheduled Trips:** {', '.join(current_trips)}
- **Total Work PTO Days Used:** {int(total_pto)} days
- **Detected Burnout Gaps (>30 days):** {', '.join(burnout_text)}
- **Buffer Constraint:** Minimum of {trip_buffer} days between trips.

Please evaluate this setup and provide alternative calendar options to maximize weekend extensions, leverage federal holidays, or resolve listed burnout gaps.
"""
    st.text_area(label="Copy this prompt and paste it directly into Gemini:", value=ai_prompt_template.strip(), height=220)

else:
    st.info("👋 Database is empty. Input a school break and a destination above to watch your calendar generate.")
