@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ========================================
echo  Flying Snow Velvet LTS - Install and Launch
echo ========================================
echo.

REM =============================================
REM  Goal: find any usable Python to run install_deps.py
REM  install_deps.py will scan and select the best version internally
REM =============================================

set "PYTHON_CMD="
set "PYTHON_ARGS="

REM [1] Windows Python Launcher (most reliable)
where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3 --version >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHON_CMD=py"
        set "PYTHON_ARGS=-3"
        goto :run
    )
)

REM [2] Direct python command (avoids parsing where-output with non-ASCII paths)
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
    goto :run
)

REM [3] Direct python3 command
python3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python3"
    goto :run
)

REM [4] Registry + user install scan via PowerShell (Unicode-safe)
for /f "usebackq delims=" %%i in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue';$paths=@();$roots=@('HKLM:\SOFTWARE\Python\PythonCore','HKCU:\SOFTWARE\Python\PythonCore','HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore');foreach($root in $roots){if(Test-Path $root){Get-ChildItem $root | ForEach-Object {$ip=(Join-Path $_.PSPath 'InstallPath');$exe=(Get-ItemProperty -Path $ip -Name ExecutablePath -ErrorAction SilentlyContinue).ExecutablePath;if($exe -and (Test-Path $exe)){$paths+=$exe}else{$base=(Get-ItemProperty -Path $ip -ErrorAction SilentlyContinue).'(default)';if($base){$alt=Join-Path $base 'python.exe';if(Test-Path $alt){$paths+=$alt}}}}}};$local=Join-Path $env:LOCALAPPDATA 'Programs\Python';if(Test-Path $local){Get-ChildItem $local -Directory -Filter 'Python*' | Sort-Object Name -Descending | ForEach-Object {$exe=Join-Path $_.FullName 'python.exe';if(Test-Path $exe){$paths+=$exe}}};$paths | Select-Object -Unique | ForEach-Object {& $_ --version >$null 2>$null;if($LASTEXITCODE -eq 0){Write-Output $_;exit 0}};exit 1"`) do (
    if not defined PYTHON_CMD set "PYTHON_CMD=%%i"
)
if defined PYTHON_CMD goto :run

REM [5] User local install: %LOCALAPPDATA%\Programs\Python
set "LOCALPY=%LOCALAPPDATA%\Programs\Python"
for %%V in (313 312 311 310 39 38 37) do (
    if not defined PYTHON_CMD (
        set "TRY=%LOCALPY%\Python%%V\python.exe"
        if exist "!TRY!" (
            "!TRY!" --version >nul 2>&1
            if !errorlevel! equ 0 set "PYTHON_CMD=!TRY!"
        )
    )
)
if defined PYTHON_CMD goto :run

REM [6] Common fixed paths on system drive
for %%P in (
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Python39\python.exe"
    "C:\Python38\python.exe"
    "C:\Python37\python.exe"
    "C:\Program Files\Python313\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Program Files\Python311\python.exe"
    "C:\Program Files\Python310\python.exe"
    "C:\aemeath\python\python.exe"
) do (
    if not defined PYTHON_CMD (
        if exist %%P (
            %%P --version >nul 2>&1
            if !errorlevel! equ 0 set "PYTHON_CMD=%%~P"
        )
    )
)
if defined PYTHON_CMD goto :run

REM --- No Python found ---
echo [ERROR] No usable Python environment found!
echo.
echo Please download and install Python from:
echo   https://www.python.org/downloads/
echo.
echo Make sure to check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:run
echo [INFO] Using Python: %PYTHON_CMD% %PYTHON_ARGS%
echo.
"%PYTHON_CMD%" %PYTHON_ARGS% install_deps.py

:end
pause
