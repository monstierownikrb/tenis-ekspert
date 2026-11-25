#!/usr/bin/env bash
cd "$(dirname "$0")"
# ROS 2 (i inne środowiska) ustawiają PYTHONPATH – odcinamy go, żeby .venv używał tylko swoich bibliotek
unset PYTHONPATH
source .venv/bin/activate
streamlit run app.py
