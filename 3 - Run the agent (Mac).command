#!/bin/bash
cd "$(dirname "$0")"
echo "Running the agent. This takes about 5-15 minutes. Keep this window open."
python3 run_agent.py "$@"
read -p "Press Enter to close"
