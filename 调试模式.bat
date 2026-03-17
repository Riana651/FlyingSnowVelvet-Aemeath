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

set "PYTHON_EXE="
for /f "usebackq tokens=1,* delims==" %%A in ("py.ini") do (
    set "KEY=%%A"
    set "VAL=%%B"
    set "KEY=!KEY: =!"
    for /f "tokens=* delims= " %%I in ("!VAL!") do set "VAL=%%I"
    if /I "!KEY!"=="python_executable" set "PYTHON_EXE=!VAL!"
)

if not defined PYTHON_EXE (
    echo python_executable not found in py.ini
    pause
    exit /b 1
)

for /f "delims=" %%I in ('cmd /c echo !PYTHON_EXE!') do set "PYTHON_EXE=%%I"

"!PYTHON_EXE!" "lib\core\qt_desktop_pet.py"
