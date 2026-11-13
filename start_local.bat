@echo off
setlocal
chcp 65001 >nul
set "ROOT=%~dp0"
if not exist "%ROOT%venv\Scripts\python.exe" (
  echo 请先创建 venv 并安装 requirements.txt，详见 DEPLOY.md。
  exit /b 1
)
set "MODE=%~1"
if "%MODE%"=="" set "MODE=all"
"%ROOT%venv\Scripts\python.exe" "%ROOT%scripts\manage.py" "%MODE%"
exit /b %ERRORLEVEL%
