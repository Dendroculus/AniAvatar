@echo off
setlocal EnableExtensions

if /i "%~1"=="run" goto run

start "AniAvatar App" cmd /k "%~f0" run
exit /b

:run
set "START_DIR=%CD%"
set "ROOT="

:find_root
if exist "%START_DIR%\main.py" (
    set "ROOT=%START_DIR%"
    goto run_app
)

for %%I in ("%START_DIR%\..") do set "PARENT=%%~fI"

if "%PARENT%"=="%START_DIR%" goto not_found

set "START_DIR=%PARENT%"
goto find_root

:run_app
cd /d "%ROOT%"
echo [INFO] Project root found: %ROOT%
echo [INFO] Running python main.py...
python main.py
echo.
echo [INFO] App stopped.
pause
exit /b %ERRORLEVEL%

:not_found
echo [ERROR] main.py not found in current folder or parent folders.
pause
exit /b 1