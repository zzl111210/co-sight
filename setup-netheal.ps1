$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $RepoRoot

$BootstrapPython = (Get-Command python -ErrorAction Stop).Source
$VersionOk = & $BootstrapPython -c "import sys; print(int(sys.version_info >= (3, 11)))"
if ($LASTEXITCODE -ne 0 -or $VersionOk.Trim() -ne "1") {
    throw "NetHeal-Agent requires Python 3.11 or newer."
}

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[1/5] Creating Python virtual environment..."
    & $BootstrapPython -m venv (Join-Path $RepoRoot ".venv")
}

Write-Host "[2/5] Installing pinned dependencies..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")

$EnvFile = Join-Path $RepoRoot ".env"
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-Host "[3/5] Creating local .env from the safe template..."
    Copy-Item -LiteralPath (Join-Path $RepoRoot ".env_template") -Destination $EnvFile
} else {
    Write-Host "[3/5] Existing .env preserved."
}

Write-Host "[4/5] Running NetHeal automated tests..."
& $VenvPython -m unittest discover -s tests -p "test_netheal*.py" -v

Write-Host "[5/5] Running six acceptance cases..."
& $VenvPython -m app.netheal.acceptance_runner

Write-Host ""
Write-Host "Setup complete. Edit .env locally, then start with:"
Write-Host "  .\.venv\Scripts\python.exe cosight_server\deep_research\main.py"
Write-Host "Open: http://localhost:7788/cosight/netheal.html"
