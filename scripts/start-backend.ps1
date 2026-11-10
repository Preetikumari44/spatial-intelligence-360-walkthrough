# Starts the Spring Boot backend on port 8080 (or BACKEND_PORT) with mvn spring-boot:run.
. "$PSScriptRoot\_common.ps1"
Import-ProjectEnv
Assert-BackendEnv
$port = [int]$env:BACKEND_PORT

$j = Invoke-Native "java -version"
if ($j.Code -ne 0 -or $j.Output -notmatch 'version "(\d+)') { Fail "Java not found. Install JDK 21 (e.g. Temurin) and make sure JAVA_HOME or PATH points to it." }
if ([int]$Matches[1] -lt 21) { Fail "Java $($Matches[1]) found but JDK 21 or newer is required." }
$m = Invoke-Native "mvn -v"
if ($m.Code -ne 0) { Fail "Maven (mvn) not found on PATH. Install Apache Maven 3.9+ and open a new terminal." }

if (Get-TrackedPid "backend") { Write-Ok "Backend already running (tracked process)"; exit 0 }
if (Test-PortListening $port) { Fail "Port $port is already used by another program. Close it or change BACKEND_PORT in .env." }
$db = Get-DbParts
if (-not (Test-PortListening $db.Port)) { Fail "PostgreSQL is not listening on port $($db.Port). Run scripts\start-database.ps1 first." }

# Normal authentication is the default. Development access (login bypass) runs only if .env says DEV_ACCESS=true.
if (-not $env:DEV_ACCESS) { $env:DEV_ACCESS = "false" }
if ($env:DEV_ACCESS -eq "true") { Write-Warn2 "DEV_ACCESS=true: authentication is bypassed for requests from this machine. Local testing only (docs\DEV_ACCESS.md)." }
Write-Step "Starting backend (the first start downloads Maven dependencies and can take several minutes)"
$env:SERVER_PORT = "$port"
$p = Start-Tracked "backend" "mvn -q spring-boot:run" (Join-Path $Root "backend")
if (-not (Wait-Http "http://localhost:$port/actuator/health" 600 "backend")) {
    Show-LogTail "backend"
    Stop-Tracked "backend"
    Fail "Backend did not become healthy. See .run\logs\backend.*.log"
}
Write-Ok "Backend is up: http://localhost:$port  (Swagger: /swagger-ui.html)"

exit 0
