"""Streamlit entry point; processing remains in the existing services."""
from idp.ui.console import main

from idp.security.auth import AccessDenied
import streamlit as st

try:
    main()
except AccessDenied:
    st.session_state.clear()
    st.warning('This operation is unavailable or your session ended. Sign in and use your authorized workspace.')
