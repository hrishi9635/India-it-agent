#!/bin/bash
cd "$(dirname "$0")"
python3 run_agent.py --set-key
read -p "Press Enter to close"
