@echo off
cd /d "%~dp0"
echo Installing the add-ons. This takes 2-5 minutes the first time...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (echo. & echo Something went wrong. See "When something goes wrong" in the guide.) else (echo. & echo All set! Now run "2 - Save my AI key".)
pause
