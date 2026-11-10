# Starts the Next.js dev server on port 3000 (or FRONTEND_PORT).
. "$PSScriptRoot\_common.ps1"
Import-ProjectEnv
$port = [int]$env:FRONTEND_PORT
$dir = Join-Path $Root "frontend"

$n = Invoke-Native "node -v"
if ($n.Code -ne 0 -or $n.Output -notmatch "v(\d+)") { Fail "Node.js not found. Install Node.js 20 LTS from nodejs.org." }
if ([int]$Matches[1] -lt 18) { Fail "Node $($n.Output) is too old; Node 18 or newer is required (20 LTS recommended)." }
if ((Invoke-Native "npm -v").Code -ne 0) { Fail "npm not found on PATH." }

if (Get-TrackedPid "frontend") { Write-Ok "Frontend already running (tracked process)"; exit 0 }
if (Test-PortListening $port) { Fail "Port $port is already used by another program. Close it or change FRONTEND_PORT in .env." }

if (-not (Test-Path (Join-Path $dir "node_modules"))) {
    Write-Step "Running npm install (first start only)"
    Push-Location $dir
    & cmd.exe /c "npm install --no-audit --no-fund"
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Fail "npm install failed" }
}
# One switch for both services: the frontend only skips /login when DEV_ACCESS=true in .env.
if (-not $env:DEV_ACCESS) { $env:DEV_ACCESS = "false" }
$env:NEXT_PUBLIC_DEV_ACCESS = $env:DEV_ACCESS
if ($env:DEV_ACCESS -eq "true") { Write-Warn2 "DEV_ACCESS=true: the login screen is skipped in this dev server. Local testing only (docs\DEV_ACCESS.md)." }
Write-Step "Starting frontend"
$p = Start-Tracked "frontend" "npm run dev -- -p $port" $dir
if (-not (Wait-Port $port 120 "frontend")) {
    Show-LogTail "frontend"
    Stop-Tracked "frontend"
    Fail "Frontend did not open port $port. See .run\logs\frontend.*.log"
}
Write-Ok "Frontend is up: http://localhost:$port"

exit 0
