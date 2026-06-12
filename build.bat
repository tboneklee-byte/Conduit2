@echo off
REM ============================================================
REM  Build Conduit.exe  -  run this on the Windows PC.
REM  Keep build.bat, pc_remote.py, and index.html in one folder.
REM ============================================================

REM Stop any running instance so the .exe isn't locked (fixes "Access is denied")
taskkill /F /IM Conduit.exe /T >nul 2>&1

REM Remove old build artifacts (now that the exe is closed)
rmdir /s /q build >nul 2>&1
rmdir /s /q dist  >nul 2>&1
del /q Conduit.spec >nul 2>&1

echo Installing build tools and dependencies...
python -m pip install pyinstaller aiohttp pynput qrcode
if errorlevel 1 (
  echo.
  echo pip failed. Make sure Python is installed and on PATH.
  pause
  exit /b 1
)

echo.
echo Building Conduit.exe ^(this can take a minute^)...
python -m PyInstaller --onefile --noconfirm --clean --name Conduit --add-data "index.html;." pc_remote.py
if errorlevel 1 (
  echo.
  echo Build failed.
  echo If it said "Access is denied":
  echo   1. Make sure Conduit.exe is not running ^(Task Manager - End task^).
  echo   2. Close any Explorer window sitting in the dist folder.
  echo   3. Your antivirus may be locking the new file - add this folder
  echo      as an exclusion, then run build.bat again.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  Done!  Your app is here:   dist\Conduit.exe
echo  Double-click Conduit.exe to run it - index.html is baked in,
echo  so you can move/copy that single .exe anywhere.
echo ============================================================
pause
