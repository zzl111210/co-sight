param(
    [string[]]$Scenario,
    [switch]$SkipSafetyCases
)

$ErrorActionPreference = "Stop"
$nethealUtf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $nethealUtf8
[Console]::OutputEncoding = $nethealUtf8
$OutputEncoding = $nethealUtf8
$env:PYTHONUTF8 = "1"
$nethealRepoRoot = Split-Path -Parent $PSScriptRoot
$nethealPython = Join-Path $nethealRepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $nethealPython)) {
    throw "未找到项目虚拟环境：$nethealPython"
}

$nethealArguments = @(
    "-m",
    "app.netheal.acceptance_runner",
    "--output-dir",
    (Join-Path $nethealRepoRoot "work_space\netheal_acceptance")
)

foreach ($nethealScenario in $Scenario) {
    $nethealArguments += @("--scenario", $nethealScenario)
}

if ($SkipSafetyCases) {
    $nethealArguments += "--skip-safety-cases"
}

Push-Location $nethealRepoRoot
try {
    & $nethealPython @nethealArguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
