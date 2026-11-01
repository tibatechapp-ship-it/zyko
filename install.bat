@echo off
REM ZYKO installer - Windows (cmd fallback for machines without PowerShell policy).
REM
REM   install.bat          (isolated venv at %%USERPROFILE%%\.zyko\venv)
REM   install.bat --dev    (with test/lint tooling)

setlocal
cd /d "%~dp0"

python --version >nul 2>nul
if errorlevel 1 (
    echo error: python is required ^(3.11+^). Install it from https://python.org
    exit /b 1
)

set "VENV=%USERPROFILE%\.zyko\venv"
echo ==^> Creating isolated environment at %VENV%
python -m venv "%VENV%" || exit /b 1
"%VENV%\Scripts\python" -m pip install --upgrade pip -q

if "%1"=="--dev" (
    "%VENV%\Scripts\python" -m pip install -q -e ".[dev]"
) else (
    "%VENV%\Scripts\python" -m pip install -q .
)

echo.
echo ==^> ZYKO installed.
echo     Run it with:            "%VENV%\Scripts\zyko.exe" --version
echo     Or add it to PATH:      set PATH=%VENV%\Scripts;%%PATH%%
echo     First try, keyless:     zyko ask "hello" --demo
echo     Verify your machine:    zyko doctor
