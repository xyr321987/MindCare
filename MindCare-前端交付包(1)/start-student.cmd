@echo off
REM MindCare student desktop launcher (ASCII only - do NOT add Chinese text here)
REM usage: start-student.cmd [server-url], default http://127.0.0.1:8080
setlocal
set SERVER=%1
if "%SERVER%"=="" set SERVER=http://127.0.0.1:8080
set PYTHONUTF8=1
set PYTHONPATH=%~dp0;%~dp0student-desktop
cd /d "%~dp0"
python -m student_desktop.app.main --server %SERVER%
endlocal
