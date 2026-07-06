$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$VenvPath = Join-Path $RepoRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "Creating virtual environment in $VenvPath"
    py -3 -m venv $VenvPath
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r requirements.txt -r requirements-build.txt

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $RepoRoot "build")
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $RepoRoot "dist")

& $PythonExe -m PyInstaller DrawPPT.spec --noconfirm --clean

$ExePath = Join-Path $RepoRoot "dist\DrawPPT\DrawPPT.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build finished but $ExePath was not found."
}

Write-Host "DrawPPT desktop executable: $ExePath"
