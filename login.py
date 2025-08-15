# login.py
import streamlit as st
from finance.db_helpers import validate_login

# Streamlit page config
st.set_page_config(page_title="Finance Tracker - Login", page_icon="💰")

st.title("💰 Smart Personal Finance Tracker")
st.subheader("🔐 Login to Your Account")

# Login form
with st.form("login_form"):
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    submit_btn = st.form_submit_button("Login")

# When form submitted
if submit_btn:
    if username.strip() == "" or password.strip() == "":
        st.warning("Please enter both username and password.")
    else:
        if validate_login(username, password):
            st.success(f"Welcome back, {username}!")
            st.session_state["logged_in"] = True
            st.session_state["username"] = username
        else:
            st.error("Invalid username or password.")
