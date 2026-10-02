@echo off
REM MindCare server launcher (ASCII only - do NOT add Chinese text here)
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
python -m server.httpd --port 8080 --data-dir .\data
endlocal
