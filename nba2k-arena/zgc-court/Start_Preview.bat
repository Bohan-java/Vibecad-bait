@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo 中关村球场预览正在后台启动，成功后会打开浏览器。
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0tools\manage_preview.ps1" -Action start
if errorlevel 1 (
  echo.
  echo 预览启动失败，请查看上方提示及 .preview-runtime 中的日志。
  pause
  exit /b 1
)
echo 预览已在后台运行，关闭此窗口不会停止。需要结束时双击 Stop_Preview.bat。
endlocal
