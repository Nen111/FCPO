@echo off
REM Launch the FCPO Supply & Demand Dashboard on http://localhost:1001
setlocal
set PY=C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
cd /d "%~dp0"
"%PY%" -m streamlit run app.py --server.port 1001 --browser.gatherUsageStats false
endlocal
