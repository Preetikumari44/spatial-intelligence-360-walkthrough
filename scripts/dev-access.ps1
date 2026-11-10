# Turns development access (login bypass for LOCAL testing) on or off by editing DEV_ACCESS in .env.
#   scripts\dev-access.ps1 on  [-Email you@example.com]
#   scripts\dev-access.ps1 off
#   scripts\dev-access.ps1 status
# The backend and the frontend read the value only at start-up: restart both afterwards.
param(
    [Parameter(Mandatory = $true, Position = 0)][ValidateSet("on", "off", "status")][string]$Mode,
    [string]$Email
)
. "$PSScriptRoot\_common.ps1"
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) { Fail ".env not found. Copy .env.example to .env first." }

function Get-EnvValue([string[]]$Lines, [string]$Key) {
    foreach ($l in $Lines) { if ($l -match "^\s*$Key\s*=\s*(.*)$") { return $Matches[1].Trim().Trim('"') } }
    return ""
}
function Set-EnvValue([string[]]$Lines, [string]$Key, [string]$Value) {
    $out = New-Object System.Collections.Generic.List[string]
    $done = $false
    foreach ($l in $Lines) {
        if ($l -match "^\s*$Key\s*=") { if (-not $done) { $out.Add("$Key=$Value"); $done = $true } }
        else { $out.Add($l) }
    }
    if (-not $done) { $out.Add("$Key=$Value") }
    return , $out.ToArray()
}

$lines = @(Get-Content $envFile)
if ($Mode -eq "status") {
    $v = Get-EnvValue $lines "DEV_ACCESS"
    if ($v -eq "true") { Write-Warn2 "Development access is ON in .env (DEV_ACCESS=true)" } else { Write-Ok "Development access is OFF in .env" }
    exit 0
}

if ($Mode -eq "on") {
    $lines = Set-EnvValue $lines "DEV_ACCESS" "true"
    if ($Email) { $lines = Set-EnvValue $lines "DEV_ACCESS_EMAIL" $Email }
} else {
    $lines = Set-EnvValue $lines "DEV_ACCESS" "false"
}
# UTF-8 without BOM: a BOM would corrupt the first key for the other scripts
[System.IO.File]::WriteAllLines($envFile, $lines, (New-Object System.Text.UTF8Encoding $false))

# The other scripts never override variables that are already set in this window, so clear the stale copy.
[Environment]::SetEnvironmentVariable("DEV_ACCESS", $null, "Process")
if ($Email) { [Environment]::SetEnvironmentVariable("DEV_ACCESS_EMAIL", $null, "Process") }

if ($Mode -eq "on") {
    Write-Warn2 "Development access ON in .env. Local testing only; never on a shared or public server."
    Write-Host "  Restart backend and frontend:  scripts\stop-all.ps1 ; scripts\start-all.ps1"
    Write-Host "  It acts as an EXISTING user: register one account once on http://localhost:$($env:FRONTEND_PORT)/login if none exists."
} else {
    Write-Ok "Development access OFF in .env"
    Write-Host "  Restart backend and frontend:  scripts\stop-all.ps1 ; scripts\start-all.ps1"
}
exit 0
