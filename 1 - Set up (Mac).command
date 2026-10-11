#!/bin/bash
cd "$(dirname "$0")"
echo "Installing the add-ons. This takes 2-5 minutes the first time..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt && echo && echo "All set! Now run 2 - Save my AI key."
read -p "Press Enter to close"
