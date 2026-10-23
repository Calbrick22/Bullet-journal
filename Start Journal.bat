@echo off
rem Double-click to start the journal. The first run sets everything up (needs the internet once).
rem From a terminal you can also pass options, e.g.  "Start Journal.bat" --demo
rem If Python is somewhere unusual, set BUJO_PYTHON to its python.exe and run this again.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto :ready

echo Setting up for the first time, this takes a minute...
call :findpython
if not defined PY goto :nopython
echo Using Python: %PY%
%PY% -m venv .venv || goto :novenv

:ready
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt || goto :failed
if not exist "config.toml" copy "config.example.toml" "config.toml" >nul

".venv\Scripts\python.exe" run.py %*
pause
exit /b


rem ---- Find a Python 3.11+ that really runs (not the Microsoft Store placeholder) ----
:findpython
set "PY="
if defined BUJO_PYTHON call :try "%BUJO_PYTHON%"
if not defined PY call :try py -3
if not defined PY call :try python3
if not defined PY call :try python
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if not defined PY call :try "%%D\python.exe"
for /d %%D in ("%ProgramFiles%\Python3*") do if not defined PY call :try "%%D\python.exe"
for /d %%D in ("C:\Python3*") do if not defined PY call :try "%%D\python.exe"
for %%F in ("%LOCALAPPDATA%\Microsoft\WindowsApps\python3.1*.exe") do if not defined PY call :try "%%F"
for %%P in ("%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "%LOCALAPPDATA%\anaconda3" "%ProgramData%\anaconda3" "%ProgramData%\miniconda3") do if not defined PY call :try "%%~P\python.exe"
exit /b

:try
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set PY=%*
exit /b


:nopython
echo.
echo Couldn't find Python 3.11 or newer.
echo  - If you have Python: open PowerShell and run   where.exe python   and   py --list
echo    then either tick "Add python.exe to PATH" when (re)installing it, or set its path:
echo        setx BUJO_PYTHON "C:\path\to\python.exe"
echo    close this window and double-click Start Journal.bat again.
echo  - If you don't: install Python 3.12 from the Microsoft Store or python.org.
pause
exit /b 1

:novenv
echo.
echo Python was found but couldn't create the .venv folder (see the message above).
pause
exit /b 1

:failed
echo.
echo Installing the app's packages failed (see the message above).
echo If it mentions a proxy or SSL certificate, your work network may block pip.
pause
exit /b 1
