# Makes sure the local PostgreSQL service is running and the application database is reachable.
# It never creates, drops or modifies data. The service is left running by stop-all.ps1.
. "$PSScriptRoot\_common.ps1"
Import-ProjectEnv
$db = Get-DbParts

Write-Step "Checking PostgreSQL on $($db.Host):$($db.Port)"
if (-not (Test-PortListening $db.Port)) {
    $svc = Get-Service | Where-Object { $_.Name -like "postgresql*" } | Select-Object -First 1
    if (-not $svc) {
        Fail "PostgreSQL is not installed or its Windows service was not found. Install it from https://www.postgresql.org/download/windows/ (see README, step 1)."
    }
    if ($svc.Status -ne "Running") {
        Write-Step "Starting Windows service '$($svc.Name)'"
        try { Start-Service -Name $svc.Name } catch { Fail "Could not start service '$($svc.Name)': $($_.Exception.Message). Run PowerShell as Administrator once, or start it from services.msc." }
    }
    if (-not (Wait-Port $db.Port 60 "PostgreSQL")) { Fail "PostgreSQL did not open port $($db.Port) within 60 seconds. Check its log under the PostgreSQL data folder." }
}
Write-Ok "PostgreSQL is listening on port $($db.Port)"

$psql = Find-Psql
if (-not $psql) {
    Write-Warn2 "psql.exe not found, so the database login was not verified. Add <PostgreSQL>\bin to PATH to enable this check."
    exit 0
}
if (-not $env:DB_PASSWORD) { Fail "DB_PASSWORD is not set in .env" }
$env:PGPASSWORD = $env:DB_PASSWORD
$r = Invoke-Native "`"$psql`" -h $($db.Host) -p $($db.Port) -U $($env:DB_USER) -d $($db.Name) -tAc `"select 1`""
if ($r.Code -ne 0) {
    Write-Host $r.Output -ForegroundColor DarkGray
    Fail "Cannot log in to database '$($db.Name)' as '$($env:DB_USER)'. If this is the first run, execute scripts\create-database.ps1 (it creates the role and database only if they are missing)."
}
Write-Ok "Database '$($db.Name)' accepts user '$($env:DB_USER)'"

exit 0
