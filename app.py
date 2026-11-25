"""Interfejs WWW chatbota (Streamlit).  Uruchom:  streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="Tenisowy Ekspert", page_icon="🎾", layout="wide")

strony = st.navigation([
    st.Page("strony/czat.py", title="Czat z ekspertem", icon="💬", default=True),
    st.Page("strony/historia_meczow.py", title="Historia meczów", icon="📊"),
])
strony.run()
