# testing/app.py
"""Luka Testing Environment — Streamlit entry point."""

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from testing.config.settings import TestingConfig
from testing.components.sidebar import render_sidebar
from testing.components.chat import render_chat
from testing.services.user_simulator import UserSimulator

st.set_page_config(
    page_title="Luka Testing",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d1117 0%, #161b22 100%);
    }
    [data-testid="stSidebar"] img {
        border-radius: 8px;
    }
    .stApp {
        background-color: #0d1117;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "config" not in st.session_state:
    st.session_state.config = TestingConfig()
if "user_simulator_initialized" not in st.session_state:
    st.session_state.user_simulator_initialized = False

# Render sidebar and get config
config = render_sidebar()

# Handle user simulation setup
if config.mode == "webhook" and config.user_registered:
    if not st.session_state.user_simulator_initialized or st.session_state.get("reset_db_requested"):
        from app.models.database import SessionLocal
        sim = UserSimulator(SessionLocal)
        sim.create_test_user(config.phone, config.user_name)
        st.session_state.user_simulator_initialized = True
        st.session_state.pop("reset_db_requested", None)

# Handle DB reset
if st.session_state.get("reset_db_requested"):
    from app.models.database import SessionLocal
    sim = UserSimulator(SessionLocal)
    sim.reset_user_data(config.phone)
    st.session_state.user_simulator_initialized = False
    st.session_state.pop("reset_db_requested", None)
    st.toast("Base de datos reseteada")

# Render chat
render_chat(config)
