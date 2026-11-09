@echo off
setlocal
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0generate_firmware.py" %*
) else (
    python "%~dp0generate_firmware.py" %*
)
exit /b %errorlevel%
