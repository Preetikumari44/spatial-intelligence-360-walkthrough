# Checks PostgreSQL, the Python FastAPI service and the Java Spring Boot backend INDEPENDENTLY of each other,
# straight from this machine (no service is asked to vouch for another). Exit code 0 only if all three are up.
. "$PSScriptRoot\_common.ps1"
Import-ProjectEnv
$bad = 0
function Show([string]$name, [bool]$ok, [string]$detail) {
    if ($ok) { Write-Ok ("{0,-11} {1}" -f $name, $detail) } else { Write-Host ("[ DOWN ] {0,-11} {1}" -f $name, $detail) -ForegroundColor Red; $script:bad++ }
}

# 1. PostgreSQL: TCP port, then a real login and query with psql (if psql is installed)
$db = Get-DbParts
if (-not (Test-PortListening $db.Port)) {
    Show "PostgreSQL" $false "nothing listens on port $($db.Port). Run scripts\start-database.ps1"
} else {
    $psql = Find-Psql
    if (-not $psql) { Show "PostgreSQL" $true "port $($db.Port) is open (psql not found, login not tested)" }
    else {
        $env:PGPASSWORD = $env:DB_PASSWORD
        $r = & $psql -h $db.Host -p $db.Port -U $env:DB_USER -d $db.Name -tAc "select count(*) from users" 2>&1 | Out-String
        $code = $LASTEXITCODE
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
        if ($code -eq 0) { Show "PostgreSQL" $true "login ok, database '$($db.Name)', $($r.Trim()) user(s)" }
        else { Show "PostgreSQL" $false ("login or query failed: " + $r.Trim()) }
    }
}

# 2. Python FastAPI
try {
    $h = Invoke-RestMethod -Uri "http://localhost:$($env:AI_PORT)/health" -TimeoutSec 5
    $caps = ($h.capabilities.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ", "
    Show "Python" ($h.status -eq "ok") "FastAPI /health: $($h.status)   [$caps]"
} catch { Show "Python" $false "no answer from http://localhost:$($env:AI_PORT)/health. Run scripts\start-ai.ps1" }

# 3. Java Spring Boot (its own health endpoint), plus what it reports about its links when development access is on
try {
    $j = Invoke-RestMethod -Uri "http://localhost:$($env:BACKEND_PORT)/actuator/health" -TimeoutSec 5
    Show "Java" ($j.status -eq "UP") "Spring Boot /actuator/health: $($j.status)"
    try {
        $d = Invoke-RestMethod -Uri "http://localhost:$($env:BACKEND_PORT)/api/dev/status" -TimeoutSec 8
        if ($d.devAccess.enabled) {
            Write-Warn2 "development access is ON: $($d.devAccess.message)"
            Write-Host "           backend's own view: postgres=$($d.services.postgres.status), python=$($d.services.python.status)"
        }
    } catch { }
} catch { Show "Java" $false "no answer from http://localhost:$($env:BACKEND_PORT)/actuator/health. Run scripts\start-backend.ps1" }

if ($bad -gt 0) { Write-Host "`n$bad service(s) down." -ForegroundColor Red; exit 1 }
Write-Ok "All three services are up"
exit 0
