# Starts the FastAPI AI service on port 8000 (or AI_PORT) from ai-service\.venv.
. "$PSScriptRoot\_common.ps1"
Import-ProjectEnv
$port = [int]$env:AI_PORT
$dir = Join-Path $Root "ai-service"
$vpy = Join-Path $dir ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { Fail "Python environment missing. Run scripts\setup-ai.ps1 once first." }

if (Get-TrackedPid "ai") { Write-Ok "AI service already running (tracked process)"; exit 0 }
if (Test-PortListening $port) { Fail "Port $port is already used by another program. Close it or change AI_PORT in .env." }

Write-Step "Starting AI service"
$p = Start-Tracked "ai" "`"$vpy`" -m uvicorn app.main:app --host 127.0.0.1 --port $port --workers 1" $dir
if (-not (Wait-Http "http://localhost:$port/health" 180 "ai")) {
    Show-LogTail "ai"
    Stop-Tracked "ai"
    Fail "AI service did not start. See .run\logs\ai.*.log"
}
Write-Ok "AI service is up: http://localhost:$port"
try {
    $caps = (Invoke-RestMethod -Uri "http://localhost:$port/health" -TimeoutSec 5).capabilities
    foreach ($n in $caps.PSObject.Properties) {
        $line = ("  {0,-24} {1}" -f $n.Name, $n.Value)
        if ($n.Value) { Write-Host $line -ForegroundColor Green } else { Write-Host $line -ForegroundColor DarkYellow }
    }
    if (-not $caps.colmap) { Write-Warn2 "COLMAP not found: run scripts\install-colmap.ps1. Until then flat videos use the built-in OpenCV pipeline (CPU); 360 degree video needs COLMAP." }
    else {
        try {
            $cs = Invoke-RestMethod -Uri "http://localhost:$port/colmap/status" -TimeoutSec 60
            if ($cs.start.started) { Write-Ok "COLMAP $($cs.version) ($($cs.location.source)): $($cs.location.path)  [CUDA: $(if ($cs.cuda -eq $false) { 'no, CPU build' } elseif ($cs.cuda) { 'yes' } else { 'unreported' })]" }
            else { Write-Warn2 "COLMAP was found but did not start: $($cs.start.explanation) $($cs.error)" }
        } catch { Write-Warn2 "Could not read /colmap/status: $($_.Exception.Message)" }
    }
    Write-Host "  Run scripts\\check-hardware.ps1 to see which devices (CPU / Intel XPU) each stage will use." -ForegroundColor DarkGray
} catch { }

exit 0
