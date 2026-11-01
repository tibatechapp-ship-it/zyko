# ZYKO installer — Windows PowerShell.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Dev
#
# Installs into an isolated venv (default) or the user site (-SystemUser).
param(
    [switch]$Dev,
    [switch]$SystemUser
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "error: python is required (3.11+). Install it from https://python.org" -ForegroundColor Red
    exit 1
}

$version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "==> Installing ZYKO (Python $version)"

if ($SystemUser) {
    & python -m pip install --user .
    Write-Host ""
    Write-Host "==> ZYKO installed. Run it with:  zyko --version"
    Write-Host "    First try, keyless:           zyko ask `"hello`" --demo"
    exit 0
}

$venv = if ($env:ZYKO_VENV) { $env:ZYKO_VENV } else { "$env:USERPROFILE\.zyko\venv" }
Write-Host "==> Creating isolated environment at $venv"
& python -m venv $venv
& "$venv\Scripts\python" -m pip install --upgrade pip -q

if ($Dev) {
    & "$venv\Scripts\python" -m pip install -q -e ".[dev]"
} else {
    & "$venv\Scripts\python" -m pip install -q .
}

Write-Host ""
Write-Host "==> ZYKO installed."
Write-Host "    Run it with:            $venv\Scripts\zyko.exe --version"
Write-Host "    Or add it to PATH:      `$env:PATH = `"$venv\Scripts;`$env:PATH`""
Write-Host "    First try, keyless:     zyko ask `"hello`" --demo"
Write-Host "    Verify your machine:    zyko doctor"
