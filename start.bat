@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 goto failure
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failure
.venv\Scripts\python.exe -m hydroflow init
if errorlevel 1 goto failure
.venv\Scripts\python.exe -m hydroflow serve
goto :eof
:failure
echo HydroFlow could not start. Check Python and the messages above.
pause
