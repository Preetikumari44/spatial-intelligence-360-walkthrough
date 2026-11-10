# Runs the AI-service tests (frame extraction, camera poses vs. known ground truth, Open3D point cloud / TSDF mesh / ICP,
# Gaussian splat training and file formats, cancellation, memory guard). About 2-5 minutes on a laptop CPU.
. "$PSScriptRoot\_common.ps1"
Import-ProjectEnv
$dir = Join-Path $Root "ai-service"
$vpy = Join-Path $dir ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { Fail "Python environment missing. Run scripts\setup-ai.ps1 once first." }
Push-Location $dir
try { & $vpy -m pytest -q } finally { Pop-Location }
exit $LASTEXITCODE
