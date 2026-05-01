@echo off
setlocal

where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Please install Python 3.10+ and add it to PATH.
  pause
  exit /b 1
)

echo Installing/updating build dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Failed to install requirements.
  pause
  exit /b 1
)

echo Building EXE with PyInstaller...
python -m PyInstaller --noconfirm --onefile --name tello_square_mission tello_square_mission.py
if errorlevel 1 (
  echo EXE build failed.
  pause
  exit /b 1
)

echo Done. Your EXE is at: dist\tello_square_mission.exe
pause
