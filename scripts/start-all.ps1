# Starts PostgreSQL (if stopped), backend, AI service and frontend, in that order.
$here = $PSScriptRoot
$steps = @("start-database.ps1", "start-ai.ps1", "start-backend.ps1", "start-frontend.ps1")
foreach ($s in $steps) {
    Write-Host ""
    & "$here\$s"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nStopped at $s. Services started so far keep running; use scripts\stop-all.ps1 to stop them." -ForegroundColor Red
        exit 1
    }
}
. "$here\_common.ps1"
Import-ProjectEnv
Write-Host ""
Write-Ok "Everything is running"
Write-Host "  App:      http://localhost:$($env:FRONTEND_PORT)"
Write-Host "  Backend:  http://localhost:$($env:BACKEND_PORT)/swagger-ui.html"
Write-Host "  AI:       http://localhost:$($env:AI_PORT)/health"
Write-Host "  Logs:     $RunDir\logs"

exit 0
