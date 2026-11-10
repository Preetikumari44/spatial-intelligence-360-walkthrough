# Prints CPU threads, free RAM, Intel graphics, CPU Open3D/PyTorch status, COLMAP, and the device each stage will use.
. "$PSScriptRoot\_common.ps1"
Import-ProjectEnv
$dir = Join-Path $Root "ai-service"
$vpy = Join-Path $dir ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { Fail "Python environment missing. Run scripts\setup-ai.ps1 once first." }
Push-Location $dir
try { & $vpy -m app.hardware } finally { Pop-Location }
exit 0
