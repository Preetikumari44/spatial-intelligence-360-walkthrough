# One-time: creates ai-service\.venv and installs the Python dependencies (several GB; needs internet).
#   scripts\setup-ai.ps1          CPU build of PyTorch and the standard Open3D wheel (works on any Intel laptop).
param([switch]$Xpu)
if ($Xpu) { throw "This project is locked to CPU-only mode; Intel XPU installation is disabled." }
. "$PSScriptRoot\_common.ps1"
$dir = Join-Path $Root "ai-service"
$py = $null
foreach ($cand in @("py -3.11", "py -3.12", "py -3.10", "python")) {
    $r = Invoke-Native "$cand --version"
    if ($r.Code -eq 0 -and $r.Output -match "Python 3\.(1[0-2])\.") { $py = $cand; break }
}
if (-not $py) { Fail "Python 3.10-3.12 not found (3.11 recommended). Install it from python.org and tick 'Add python.exe to PATH'." }
Write-Step "Using $py ($((Invoke-Native "$py --version").Output))"

$venv = Join-Path $dir ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    Write-Step "Creating virtual environment"
    $r = Invoke-Native "$py -m venv `"$venv`""
    if ($r.Code -ne 0) { Fail "venv creation failed: $($r.Output)" }
}
$vpy = Join-Path $venv "Scripts\python.exe"
Write-Step "Installing PyTorch (CPU build) and dependencies (this takes a while)"
& $vpy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed" }
& $vpy -m pip install --upgrade --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { Fail "PyTorch install failed. Check your internet connection and rerun this script." }
& $vpy -m pip install -r (Join-Path $dir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "requirements install failed" }

Write-Ok "AI environment ready at $venv"
Write-Host "Check what was detected and which device each stage will use:  scripts\check-hardware.ps1"
exit 0
