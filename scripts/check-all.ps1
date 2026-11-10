# Status of every part: database, AI service, backend, frontend, COLMAP, storage, authentication. Read-only.
. "$PSScriptRoot\_common.ps1"
try { Import-ProjectEnv } catch { Write-Warn2 ".env problem: $($_.Exception.Message)" }
& "$PSScriptRoot\check-services.ps1"
$services = $LASTEXITCODE
& "$PSScriptRoot\check-colmap.ps1"
$colmap = $LASTEXITCODE
$root = $env:STORAGE_ROOT
if ($root -and (Test-Path $root)) { $free = [math]::Round((Get-PSDrive ((Resolve-Path $root).Drive.Name)).Free / 1GB, 1); Write-Ok "Storage: $root ($free GB free)" } else { Write-Warn2 "Storage folder missing: $root" }
try {
    $r = Invoke-WebRequest -Uri "http://localhost:8080/api/projects" -UseBasicParsing -ErrorAction Stop
    Write-Warn2 "Backend answered /api/projects without a token (status $($r.StatusCode)); authentication may be off"
} catch { if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -in 401, 403) { Write-Ok "Authentication: protected API rejects requests without a token (401/403)" } else { Write-Warn2 "Authentication check skipped (backend not reachable)" } }
if ($services -ne 0 -or $colmap -ne 0) { exit 1 }
exit 0
