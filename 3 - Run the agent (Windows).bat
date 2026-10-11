@echo off
cd /d "%~dp0"
echo Running the agent. This takes about 5-15 minutes. Keep this window open.
python run_agent.py %*
pause
