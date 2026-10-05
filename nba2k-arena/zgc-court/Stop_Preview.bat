@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo 正在核对并停止本项目的后台预览服务。
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0tools\manage_preview.ps1" -Action stop
if errorlevel 1 (
  echo.
  echo 未能安全停止，请查看上方提示。没有终止其他程序。
  pause
  exit /b 1
)
echo 本项目预览服务已停止。
endlocal
