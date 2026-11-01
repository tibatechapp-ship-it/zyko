@echo off
REM ZYKO zero-install runner — Windows (cmd).
REM
REM Usage:
REM   zyko.cmd --version
REM   zyko.cmd ask "hello" --demo
REM
REM Runs the globally installed zyko when present; otherwise creates an
REM isolated venv under %USERPROFILE%\.zyko\venv and installs ZYKO from this
REM directory (or from GitHub when run outside a clone).

setlocal
set "REPO_DIR=%~dp0"

where zyko >nul 2>nul
if %errorlevel%==0 (
    zyko %*
    exit /b %errorlevel%
)

set "VENV=%ZYKO_VENV%%USERPROFILE%\.zyko\venv"
if not exist "%VENV%\Scripts\zyko.exe" (
    echo [zyko.cmd] first run - creating an isolated environment at %VENV%
    python -m venv "%VENV%"
    "%VENV%\Scripts\python" -m pip install --upgrade pip -q
    if exist "%REPO_DIR%pyproject.toml" (
        "%VENV%\Scripts\python" -m pip install -q "%REPO_DIR%."
    ) else (
        "%VENV%\Scripts\python" -m pip install -q "git+https://github.com/tibatechapp-ship-it/zyko.git"
    )
    echo [zyko.cmd] done.
)

"%VENV%\Scripts\zyko.exe" %*
exit /b %errorlevel%
