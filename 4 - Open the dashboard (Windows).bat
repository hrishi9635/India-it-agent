@echo off
cd /d "%~dp0"
echo Opening the dashboard in your browser... Keep this window open while you use it.
python -m streamlit run app.py
pause
