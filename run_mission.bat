@echo off
setlocal

where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Please install Python 3.10+ and add it to PATH.
  pause
  exit /b 1
)

echo Installing/updating requirements...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Failed to install requirements.
  pause
  exit /b 1
)

echo Starting Tello square mission...
python tello_square_mission.py %*

pause
