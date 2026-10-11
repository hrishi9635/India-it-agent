#!/bin/bash
cd "$(dirname "$0")"
echo "Opening the dashboard in your browser... Keep this window open while you use it."
python3 -m streamlit run app.py
