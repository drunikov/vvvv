#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Please install Python 3.10+"
  exit 1
fi

echo "Installing/updating build dependencies..."
python3 -m pip install --upgrade pip || python3 -m pip install --break-system-packages --upgrade pip
python3 -m pip install -r requirements.txt || python3 -m pip install --break-system-packages -r requirements.txt

echo "Building Linux binary with PyInstaller..."
python3 -m PyInstaller --noconfirm --onefile --name tello_square_mission_linux tello_square_mission.py

echo "Done. Binary created at: dist/tello_square_mission_linux"
