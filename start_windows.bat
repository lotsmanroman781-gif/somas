@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  set "PY_CMD=py"
) else (
  set "PY_CMD=python"
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto :error
)
call ".venv\Scripts\activate.bat"
echo Installing dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto :error
echo.
echo SOMAS v1.1 user workspaces: http://127.0.0.1:8000
python run.py
if errorlevel 1 goto :error
exit /b 0
:error
echo.
echo SOMAS could not start. Make sure Python 3.10+ is installed.
pause
exit /b 1
