@echo off
rem Double-click to start the journal. The first run sets everything up (needs the internet once).
rem From a terminal you can also pass options, e.g.  "Start Journal.bat" --demo
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Setting up for the first time, this takes a minute...
  py -3 -m venv .venv || python -m venv .venv || goto :nopython
)
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt || goto :failed
if not exist "config.toml" copy "config.example.toml" "config.toml" >nul

".venv\Scripts\python.exe" run.py %*
pause
exit /b

:nopython
echo.
echo Couldn't find Python. Install Python 3.11 or newer (python.org or the Microsoft Store), then try again.
pause
exit /b 1

:failed
echo.
echo Installing the app's packages failed (see the message above).
pause
exit /b 1
