# Mandatory CPU acceptance run. Usage: .\scripts\test-cpu-pipeline.ps1 -Video C:\path\to\walkthrough.mp4
# Runs COLMAP, Open3D and Gaussian training on YOUR video without CUDA and prints installed / initialized / tested / generated
# separately for each. Writes acceptance_report.json in the repository root. Exit code 0 only if every feature generated output.
param([Parameter(Mandatory = $true)][string]$Video, [switch]$SkipSplat)
. "$PSScriptRoot\_common.ps1"
Import-ProjectEnv
$dir = Join-Path $Root "ai-service"
$vpy = Join-Path $dir ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { Fail "Python environment missing. Run scripts\setup-ai.ps1 once first." }
if (-not (Test-Path $Video)) { Fail "Video not found: $Video" }
$report = Join-Path $Root "acceptance_report.json"
Push-Location $dir
try {
    $args = @("tools\cpu_acceptance.py", (Resolve-Path $Video).Path, "--out", $report)
    if ($SkipSplat) { $args += "--skip-splat" }
    & $vpy @args
    exit $LASTEXITCODE
} finally { Pop-Location }
