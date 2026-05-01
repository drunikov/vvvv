#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Please install Python 3.10+"
  exit 1
fi

echo "Installing/updating requirements..."
python3 -m pip install --upgrade pip || python3 -m pip install --break-system-packages --upgrade pip
python3 -m pip install -r requirements.txt || python3 -m pip install --break-system-packages -r requirements.txt

echo "Starting Tello square mission..."
python3 tello_square_mission.py "$@"
