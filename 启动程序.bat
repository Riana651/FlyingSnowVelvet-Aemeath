@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
cd /d "%~sdp0"

set "PYTHONPATH=.;config;lib"

if not exist "py.ini" (
    echo py.ini not found. Please run install_deps.py first.
    pause
    exit /b 1
)

set "PYTHONW_EXE="
for /f "usebackq tokens=1,* delims==" %%A in ("py.ini") do (
    set "KEY=%%A"
    set "VAL=%%B"
    set "KEY=!KEY: =!"
    for /f "tokens=* delims= " %%I in ("!VAL!") do set "VAL=%%I"
    if /I "!KEY!"=="pythonw_executable" set "PYTHONW_EXE=!VAL!"
)

if not defined PYTHONW_EXE (
    echo pythonw_executable not found in py.ini
    pause
    exit /b 1
)

for /f "delims=" %%I in ('cmd /c echo !PYTHONW_EXE!') do set "PYTHONW_EXE=%%I"

start "" /b "!PYTHONW_EXE!" "lib\core\qt_desktop_pet.py"
