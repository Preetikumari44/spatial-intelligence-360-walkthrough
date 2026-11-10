# One-time setup for the whole project on Windows 11 (native, no Docker). Safe to rerun: it never overwrites an existing .env value,
# never drops or truncates database data, and skips whatever is already done.
#   scripts\setup-all.ps1                  everything
#   scripts\setup-all.ps1 -SkipAi          skip the Python/PyTorch/Open3D install (several GB)
#   scripts\setup-all.ps1 -NonInteractive  never prompt; stops with a clear message if a credential is missing
param([switch]$SkipAi, [switch]$Xpu, [switch]$NonInteractive, [switch]$InstallVcRuntime)
if ($Xpu) { throw "This project is locked to CPU-only mode; Intel XPU installation is disabled." }
. "$PSScriptRoot\_common.ps1"
$failed = @()
function Step([string]$n) { Write-Host ""; Write-Host "== $n" -ForegroundColor Cyan }

# ---- 1. prerequisites ------------------------------------------------------------------------------------------------------
Step "1/8 Prerequisites"
$j = Invoke-Native "java -version"
if ($j.Code -ne 0 -or $j.Output -notmatch 'version "(\d+)') { Fail "Java not found. Install JDK 21 (Temurin) and open a new terminal." }
if ([int]$Matches[1] -lt 21) { Fail "Java $($Matches[1]) found, but this project needs 21 or newer." }
Write-Ok "Java $($Matches[1])"
$m = Invoke-Native "mvn -v"
if ($m.Code -ne 0) { Fail "Maven (mvn) not found on PATH. Install Apache Maven 3.9+ and open a new terminal." }
Write-Ok ($m.Output -split "`r?`n" | Select-Object -First 1)
$n = Invoke-Native "node -v"
if ($n.Code -ne 0 -or $n.Output -notmatch "v(\d+)") { Fail "Node.js not found. Install Node.js 20 LTS." }
if ([int]$Matches[1] -lt 18) { Fail "Node.js $($Matches[1]) is too old; install 20 LTS." }
if ((Invoke-Native "npm -v").Code -ne 0) { Fail "npm not found on PATH." }
Write-Ok "Node.js $($n.Output.Trim()), npm $((Invoke-Native 'npm -v').Output.Trim())"
$psql = Find-Psql
if (-not $psql) { Fail "PostgreSQL not found (psql.exe). Install PostgreSQL 15+ and remember the 'postgres' password; this script will not invent one." }
Write-Ok "PostgreSQL client: $psql"
if (Test-Command ffmpeg) { Write-Ok "FFmpeg on PATH (optional: the AI service decodes video through OpenCV's bundled FFmpeg)" }
else { Write-Warn2 "ffmpeg.exe not on PATH. Not required: OpenCV's wheel includes its own FFmpeg decoder. Only needed if you want to re-encode odd formats by hand." }

# ---- 2. .env (never overwritten; JWT secret generated once) -------------------------------------------------------------------
Step "2/8 Environment file"
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $Root ".env.example") $envFile
    Write-Ok "Created .env from .env.example"
} else { Write-Ok ".env already exists and is kept as it is" }

function Get-EnvValue([string]$key) {
    foreach ($l in Get-Content $envFile) {
        $t = $l.Trim()
        if ($t.StartsWith("#") -or -not $t.Contains("=")) { continue }
        $i = $t.IndexOf("=")
        if ($t.Substring(0, $i).Trim() -eq $key) { $v = $t.Substring($i + 1).Trim(); if ($v -match '^(.*?)\s+#') { $v = $Matches[1].Trim() }; return $v.Trim('"') }
    }
    return ""
}
function Set-EnvValue([string]$key, [string]$value) {
    $lines = @(Get-Content $envFile)
    $done = $false
    for ($k = 0; $k -lt $lines.Count; $k++) {
        $t = $lines[$k].Trim()
        if (-not $t.StartsWith("#") -and $t.StartsWith("$key=")) { $lines[$k] = "$key=$value"; $done = $true; break }
    }
    if (-not $done) { $lines += "$key=$value" }
    Set-Content -Path $envFile -Value $lines -Encoding UTF8
}
$jwt = Get-EnvValue "JWT_SECRET"
if ($jwt.Length -lt 32) {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create(); $rng.GetBytes($bytes); $rng.Dispose()
    Set-EnvValue "JWT_SECRET" ([Convert]::ToBase64String($bytes))
    Write-Ok "Generated a new random JWT_SECRET (48 random bytes) in .env only"
} else { Write-Ok "JWT_SECRET already set (kept; existing login sessions stay valid)" }
if (-not (Get-EnvValue "DB_PASSWORD")) {
    if ($NonInteractive) { Fail "DB_PASSWORD is empty in .env. Put the password of the PostgreSQL role '$(Get-EnvValue 'DB_USER')' there (or rerun without -NonInteractive). It is never invented." }
    Write-Host "DB_PASSWORD is empty. Enter the password for the application database role (the one in DB_USER). If the role already exists, enter its current password."
    $sec = Read-Host "Database password" -AsSecureString
    $bs = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bs); [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bs)
    if (-not $plain) { Fail "No password entered." }
    Set-EnvValue "DB_PASSWORD" $plain
    Write-Ok "Saved DB_PASSWORD to .env (local file only, ignored by git)"
}
Import-ProjectEnv
New-Item -ItemType Directory -Force -Path $env:STORAGE_ROOT | Out-Null
foreach ($d in "videos", "images", "jobs", "panoramas", "models") { New-Item -ItemType Directory -Force -Path (Join-Path $env:STORAGE_ROOT $d) | Out-Null }
Write-Ok "Storage folders under $($env:STORAGE_ROOT)"
Assert-BackendEnv
Write-Ok "Configuration valid (JWT_SECRET length $($env:JWT_SECRET.Length), CORS $($env:CORS_ORIGINS))"

# ---- 3. COLMAP --------------------------------------------------------------------------------------------------------------
Step "3/8 COLMAP (bundled, CPU build)"
$ic = @{}; if ($InstallVcRuntime) { $ic["InstallVcRuntime"] = $true }
& "$PSScriptRoot\install-colmap.ps1" @ic
if ($LASTEXITCODE -ne 0) { $failed += "COLMAP (see messages above; the OpenCV fallback still works for flat video)"; Write-Warn2 "COLMAP check failed; continuing" }

# ---- 4. PostgreSQL ------------------------------------------------------------------------------------------------------------
Step "4/8 PostgreSQL"
$db = Get-DbParts
if (-not (Test-PortListening $db.Port)) { & "$PSScriptRoot\start-database.ps1"; if ($LASTEXITCODE -ne 0) { Fail "PostgreSQL is not running on port $($db.Port) and could not be started." } }
$env:PGPASSWORD = $env:DB_PASSWORD
$probe = & $psql -h $db.Host -p $db.Port -U $env:DB_USER -d $db.Name -tAc "select 1" 2>&1 | Out-String
$probeCode = $LASTEXITCODE
Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
if ($probeCode -eq 0) { Write-Ok "Database '$($db.Name)' reachable as '$($env:DB_USER)'. Existing data is untouched; Flyway adds tables on backend start." }
elseif ($NonInteractive) { Fail "Cannot log in to database '$($db.Name)' as '$($env:DB_USER)': $($probe.Trim()). Run scripts\create-database.ps1 once, or fix DB_PASSWORD." }
else { Write-Warn2 "Login failed ($($probe.Trim())). Running scripts\create-database.ps1 (asks for the 'postgres' superuser password; it only creates what is missing)."; & "$PSScriptRoot\create-database.ps1"; if ($LASTEXITCODE -ne 0) { Fail "Database setup failed." } }

# ---- 5. AI environment ---------------------------------------------------------------------------------------------------------
Step "5/8 Python AI environment (CPU PyTorch, OpenCV, Open3D)"
if ($SkipAi) { Write-Warn2 "Skipped (-SkipAi)" }
else {
    & "$PSScriptRoot\setup-ai.ps1"
    if ($LASTEXITCODE -ne 0) { $failed += "AI environment"; Write-Warn2 "AI environment setup failed" }
}

# ---- 6. backend -----------------------------------------------------------------------------------------------------------------
Step "6/8 Spring Boot dependencies"
Push-Location (Join-Path $Root "backend")
try { & cmd.exe /c "mvn -q -DskipTests compile"; if ($LASTEXITCODE -ne 0) { $failed += "Backend compile"; Write-Warn2 "mvn compile failed" } else { Write-Ok "Backend compiles" } } finally { Pop-Location }

# ---- 7. frontend ----------------------------------------------------------------------------------------------------------------
Step "7/8 Frontend dependencies"
Push-Location (Join-Path $Root "frontend")
try {
    if (Test-Path "package-lock.json") { & cmd.exe /c "npm ci --no-audit --no-fund" } else { & cmd.exe /c "npm install --no-audit --no-fund" }
    if ($LASTEXITCODE -ne 0) { $failed += "Frontend packages"; Write-Warn2 "npm install failed" } else { Write-Ok "Frontend packages installed" }
} finally { Pop-Location }

# ---- 8. summary ----------------------------------------------------------------------------------------------------------------
Step "8/8 Summary"
if ($failed.Count -gt 0) { foreach ($f in $failed) { Write-Host "[ FAIL ] $f" -ForegroundColor Red }; Write-Host "Fix the items above and rerun scripts\setup-all.ps1 (completed steps are skipped)." -ForegroundColor Yellow; exit 1 }
Write-Ok "Setup complete. Start everything with:  .\scripts\start-all.ps1"
exit 0
