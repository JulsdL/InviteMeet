import streamlit as st
import pandas as pd
import sqlite3
import pytz
from datetime import datetime, timedelta
import os
import os.path
import base64
from email.mime.text import MIMEText
from email_validator import validate_email, EmailNotValidError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set the scopes for Gmail and Calendar APIs
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar'
]

# Database connection
def get_db_connection():
    conn = sqlite3.connect('database.db')
    return conn

# Function to check access code
def check_access_code(code):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT used FROM access_codes WHERE code = ?', (code,))
    result = cursor.fetchone()
    conn.close()
    if result is None:
        return False  # Invalid code
    elif result[0]:
        return False  # Code already used
    else:
        return True   # Valid code

# Function to mark access code as used
def mark_code_as_used(code):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE access_codes SET used = 1 WHERE code = ?', (code,))
    conn.commit()
    conn.close()

# Function to get booked slots (confirmed bookings)
def get_booked_slots():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT slot FROM bookings WHERE confirmed = 1')
    slots = [row[0] for row in cursor.fetchall()]
    conn.close()
    return slots

# Function to add a booking
def add_booking(access_code, name, email, slot, confirmed=0):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO bookings (access_code, name, email, slot, confirmed)
        VALUES (?, ?, ?, ?, ?)
    ''', (access_code, name, email, slot, confirmed))
    conn.commit()
    conn.close()

# Function to confirm a booking
def confirm_booking(booking_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE bookings SET confirmed = 1 WHERE id = ?', (booking_id,))
    conn.commit()
    conn.close()

# Function to delete a booking
def delete_booking(booking_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM bookings WHERE id = ?', (booking_id,))
    conn.commit()
    conn.close()

# Function to get credentials for Google APIs
def get_credentials():
    creds = None
    token_file = 'token.json'
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    # If there are no valid credentials, prompt for login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials
        with open(token_file, 'w') as token:
            token.write(creds.to_json())
    return creds

# Function to get busy times from Google Calendar
def get_busy_times(creds, start_datetime, end_datetime, timezone):
    service = build('calendar', 'v3', credentials=creds)
    body = {
        "timeMin": start_datetime.isoformat(),
        "timeMax": end_datetime.isoformat(),
        "timeZone": timezone,
        "items": [{"id": "primary"}]
    }
    events_result = service.freebusy().query(body=body).execute()
    busy_times = events_result['calendars']['primary'].get('busy', [])
    return busy_times

# Function to generate available time slots based on Google Calendar availability
def generate_time_slots(creds, start_datetime, end_datetime, start_hour, end_hour, interval_minutes, timezone):
    slots = []
    current_date = start_datetime
    busy_times = get_busy_times(creds, start_datetime, end_datetime, timezone)

    # Convert busy times to datetime objects
    busy_periods = []
    for period in busy_times:
        start = datetime.fromisoformat(period['start']).astimezone(pytz.timezone(timezone))
        end = datetime.fromisoformat(period['end']).astimezone(pytz.timezone(timezone))
        busy_periods.append((start, end))

    while current_date <= end_datetime:
        for hour in range(start_hour, end_hour):
            for minute in range(0, 60, interval_minutes):
                slot_time = current_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if slot_time > datetime.now(pytz.timezone(timezone)):
                    slot_available = True
                    for busy_start, busy_end in busy_periods:
                        if busy_start <= slot_time < busy_end:
                            slot_available = False
                            break
                    if slot_available:
                        slots.append(slot_time)
        current_date += timedelta(days=1)
    return slots

# Function to send confirmation email to the user
def send_confirmation_email(to_email, name, slot, timezone_str):
    creds = get_credentials()
    # Create the email message
    message = MIMEText(
        f"Hello {name},\n\nYour meeting request for {slot} ({timezone_str}) has been received and is pending approval.\n\nBest regards,\nYour Name"
    )
    message['to'] = to_email
    message['from'] = 'me'  # Indicates authenticated user
    message['subject'] = 'Meeting Request Received'

    # Encode the message
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    # Send the email
    try:
        service = build('gmail', 'v1', credentials=creds)
        message_body = {'raw': raw_message}
        sent_message = service.users().messages().send(userId='me', body=message_body).execute()
        st.info(f"Confirmation email sent to {to_email}")
    except Exception as e:
        st.error("Failed to send confirmation email.")
        st.error(f"Error: {e}")
        print(e)

# Function to send notification email to admin
def send_admin_notification(name, email, slot):
    creds = get_credentials()
    admin_email = os.environ.get("ADMIN_EMAIL")
    if not admin_email:
        st.error("Admin email not set in environment variables.")
        return

    message = MIMEText(
        f"New booking request from {name} ({email}) for {slot}.\n\nPlease log in to the admin dashboard to confirm or decline the booking."
    )
    message['to'] = admin_email
    message['from'] = 'me'
    message['subject'] = 'New Booking Request'

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    try:
        service = build('gmail', 'v1', credentials=creds)
        message_body = {'raw': raw_message}
        sent_message = service.users().messages().send(userId='me', body=message_body).execute()
        st.info(f"Notification email sent to admin.")
    except Exception as e:
        st.error("Failed to send notification email to admin.")
        st.error(f"Error: {e}")
        print(e)

# Function to view pending bookings
def view_pending_bookings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, email, slot FROM bookings WHERE confirmed = 0')
    pending_bookings = cursor.fetchall()
    conn.close()
    return pending_bookings

# Function to handle admin login
def admin_login():
    st.sidebar.header("Admin Login")
    admin_password_input = st.sidebar.text_input("Enter admin password", type="password")
    if st.sidebar.button("Login"):
        admin_password = os.environ.get("ADMIN_PASSWORD")
        if admin_password_input == admin_password:
            st.session_state['admin_logged_in'] = True
            st.sidebar.success("Logged in as admin")
        else:
            st.sidebar.error("Incorrect password")

# Function for admin actions
def admin_actions():
    st.header("Admin Dashboard")
    pending_bookings = view_pending_bookings()
    if pending_bookings:
        for booking in pending_bookings:
            booking_id, name, email, slot = booking
            st.subheader(f"Booking ID: {booking_id}")
            st.write(f"Name: {name}")
            st.write(f"Email: {email}")
            st.write(f"Slot: {slot}")
            col1, col2 = st.columns(2)
            with col1:
                if st.button(f"Confirm Booking {booking_id}"):
                    confirm_booking(booking_id)
                    st.success(f"Booking {booking_id} confirmed.")
                    # Optionally, send a confirmation email to the user
            with col2:
                if st.button(f"Delete Booking {booking_id}"):
                    delete_booking(booking_id)
                    st.warning(f"Booking {booking_id} deleted.")
    else:
        st.write("No pending bookings.")

# Streamlit app starts here
def main():
    st.title("Personal Booking App")

    if 'access_granted' not in st.session_state:
        st.session_state['access_granted'] = False

    if 'admin_logged_in' not in st.session_state:
        st.session_state['admin_logged_in'] = False

    # Admin Login
    admin_login()

    if st.session_state['admin_logged_in']:
        admin_actions()
        return

    # Step 1: Access Code Verification
    if not st.session_state['access_granted']:
        st.header("Enter Access Code")
        access_code = st.text_input("Access Code")
        if st.button("Verify"):
            if check_access_code(access_code):
                st.success("Access code verified!")
                st.session_state['access_granted'] = True
                st.session_state['access_code'] = access_code
                # Optionally mark the code as used now or after booking
                mark_code_as_used(access_code)
            else:
                st.error("Invalid or already used access code.")
        return  # Stop the app until access is granted

    # Step 2: Booking Interface
    st.header("Book a Meeting Slot")
    name = st.text_input("Your Name")
    email = st.text_input("Your Email")

    # Timezone Selection
    timezones = pytz.common_timezones
    selected_timezone = st.selectbox("Select Your Time Zone", timezones, index=timezones.index('UTC'))
    user_timezone = pytz.timezone(selected_timezone)

    # Get credentials
    creds = get_credentials()

    # Define availability
    start_datetime = datetime.now(pytz.timezone(selected_timezone))
    end_datetime = start_datetime + timedelta(days=14)

    # Generate available time slots based on Google Calendar
    time_slots = generate_time_slots(
        creds, start_datetime, end_datetime, 9, 17, 30, selected_timezone
    )

    # Select a date
    selected_date = st.date_input(
        "Select a date",
        value=start_datetime.date(),
        min_value=start_datetime.date(),
        max_value=end_datetime.date()
    )

    available_times = [slot for slot in time_slots if slot.date() == selected_date]

    if available_times:
        slot_options = [slot.strftime('%H:%M') for slot in available_times]
        selected_time_str = st.selectbox("Available Times:", slot_options)
        selected_slot_str = f"{selected_date} {selected_time_str}"
    else:
        st.info("No available times on this date.")
        return

    if st.button("Book Meeting"):
        if name and email and selected_slot_str:
            # Email Validation
            try:
                valid = validate_email(email)
                email = valid.email  # Get the normalized email
            except EmailNotValidError as e:
                st.error(f"Invalid email address: {e}")
                return  # Stop further execution

            # Convert selected_slot_str to datetime
            try:
                selected_slot = datetime.strptime(selected_slot_str, '%Y-%m-%d %H:%M')
                selected_slot = user_timezone.localize(selected_slot)
            except ValueError:
                st.error("Invalid date or time selected.")
                return

            # Convert to UTC before storing
            selected_slot_utc = selected_slot.astimezone(pytz.utc)
            selected_slot_utc_str = selected_slot_utc.strftime('%Y-%m-%d %H:%M')

            # Add booking to the database (confirmed=0)
            add_booking(st.session_state['access_code'], name, email, selected_slot_utc_str, confirmed=0)
            st.success(f"Meeting request submitted for {selected_slot_str} ({selected_timezone}). Awaiting confirmation.")
            send_confirmation_email(email, name, selected_slot_str, selected_timezone)
            send_admin_notification(name, email, selected_slot_str)
        else:
            st.error("Please fill in all the details.")

if __name__ == "__main__":
    main()
