# Shared helpers, dot-sourced by other scripts.
# Compatible with Windows PowerShell 5.1 and PowerShell 7.

$ErrorActionPreference = "Stop"

$script:Root   = Split-Path -Parent $PSScriptRoot
$script:RunDir = Join-Path $script:Root ".run"
$script:LogDir = Join-Path $script:RunDir "logs"

New-Item -ItemType Directory -Force -Path $script:LogDir | Out-Null


# ------------------------------------------------------------
# Logging helpers
# ------------------------------------------------------------

function Write-Step($msg) {
    Write-Host "[spatial] $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "[  ok  ] $msg" -ForegroundColor Green
}

function Write-Warn2($msg) {
    Write-Host "[ warn ] $msg" -ForegroundColor Yellow
}

function Fail($msg) {
    Write-Host "[ FAIL ] $msg" -ForegroundColor Red
    exit 1
}


# ------------------------------------------------------------
# Native command execution
# ------------------------------------------------------------

function Invoke-Native([string]$CommandLine) {
    $out = & cmd.exe /c "$CommandLine 2>&1" | Out-String

    return @{
        Output = $out.Trim()
        Code   = $LASTEXITCODE
    }
}


function Test-Command([string]$Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}


# ------------------------------------------------------------
# Project environment loading
# ------------------------------------------------------------

function Import-ProjectEnv {

    $envFile = Join-Path $script:Root ".env"

    if (-not (Test-Path $envFile)) {
        Fail ".env not found. Copy .env.example to .env and configure DB_PASSWORD and JWT_SECRET."
    }

    foreach ($line in Get-Content $envFile) {

        $t = $line.Trim()

        if ($t -eq "" -or $t.StartsWith("#")) {
            continue
        }

        $i = $t.IndexOf("=")

        if ($i -lt 1) {
            continue
        }

        $k = $t.Substring(0, $i).Trim()
        $v = $t.Substring($i + 1).Trim()

        if ($v.StartsWith('"') -and $v.EndsWith('"') -and $v.Length -ge 2) {
            $v = $v.Substring(1, $v.Length - 2)
        }
        elseif ($v -match '^(.*?)\s+#') {
            $v = $Matches[1].Trim()
        }

        if ($v -eq "") {
            continue
        }

        if (-not [Environment]::GetEnvironmentVariable($k, "Process")) {
            [Environment]::SetEnvironmentVariable($k, $v, "Process")
        }
    }

    $defaults = @{
        DB_URL              = "jdbc:postgresql://localhost:5432/spatial"
        DB_USER             = "spatial"
        BACKEND_PORT        = "8080"
        AI_PORT             = "8000"
        FRONTEND_PORT       = "3000"
        AI_SERVICE_URL      = "http://localhost:8000"
        NEXT_PUBLIC_API_URL = "http://localhost:8080"
        CORS_ORIGINS        = "http://localhost:3000,http://127.0.0.1:3000"
        STORAGE_ROOT        = (Join-Path $script:Root "data\storage")
    }

    foreach ($k in $defaults.Keys) {

        if (-not [Environment]::GetEnvironmentVariable($k, "Process")) {
            [Environment]::SetEnvironmentVariable(
                $k,
                $defaults[$k],
                "Process"
            )
        }
    }

    New-Item -ItemType Directory -Force -Path $env:STORAGE_ROOT | Out-Null

    # Initialize bundled COLMAP environment.
    [void](Initialize-ColmapEnv)
}


# ------------------------------------------------------------
# Environment validation
# ------------------------------------------------------------

function Assert-BackendEnv {

    if (-not $env:DB_PASSWORD) {
        Fail "DB_PASSWORD is not set in .env"
    }

    if (-not $env:JWT_SECRET -or $env:JWT_SECRET.Length -lt 32) {
        Fail "JWT_SECRET must be set in .env and be at least 32 characters"
    }
}


# ------------------------------------------------------------
# PostgreSQL helpers
# ------------------------------------------------------------

function Get-DbParts {

    if ($env:DB_URL -notmatch "^jdbc:postgresql://([^:/]+):(\d+)/([^?]+)") {
        Fail "DB_URL '$($env:DB_URL)' is not a valid PostgreSQL JDBC URL"
    }

    return @{
        Host = $Matches[1]
        Port = [int]$Matches[2]
        Name = $Matches[3]
    }
}


function Test-PortListening([int]$Port) {

    return $null -ne (
        Get-NetTCPConnection `
            -State Listen `
            -LocalPort $Port `
            -ErrorAction SilentlyContinue
    )
}


function Wait-Port(
    [int]$Port,
    [int]$TimeoutSec,
    [string]$What
) {

    $deadline = (Get-Date).AddSeconds($TimeoutSec)

    while ((Get-Date) -lt $deadline) {

        if (Test-PortListening $Port) {
            return $true
        }

        Start-Sleep -Seconds 1
    }

    return $false
}


# ------------------------------------------------------------
# HTTP health check
# ------------------------------------------------------------

function Wait-Http(
    [string]$Url,
    [int]$TimeoutSec,
    [string]$Name
) {

    $deadline = (Get-Date).AddSeconds($TimeoutSec)

    while ((Get-Date) -lt $deadline) {

        if (-not (Get-TrackedPid $Name)) {
            return $false
        }

        try {

            $r = Invoke-WebRequest `
                -Uri $Url `
                -UseBasicParsing `
                -TimeoutSec 3

            if ($r.StatusCode -eq 200) {
                return $true
            }

        }
        catch {
            # Service may still be starting.
        }

        Start-Sleep -Seconds 2
    }

    return $false
}


# ------------------------------------------------------------
# Process tracking
# ------------------------------------------------------------

function Get-TrackedPid([string]$Name) {

    $f = Join-Path $script:RunDir "$Name.pid"

    if (-not (Test-Path $f)) {
        return $null
    }

    $content = Get-Content $f -ErrorAction SilentlyContinue

    if (-not $content) {
        Remove-Item $f -Force -ErrorAction SilentlyContinue
        return $null
    }

    $p = 0

    if (-not [int]::TryParse([string]$content, [ref]$p)) {
        Remove-Item $f -Force -ErrorAction SilentlyContinue
        return $null
    }

    if ($p -and (Get-Process -Id $p -ErrorAction SilentlyContinue)) {
        return $p
    }

    Remove-Item $f -Force -ErrorAction SilentlyContinue

    return $null
}


function Start-Tracked(
    [string]$Name,
    [string]$ArgsLine,
    [string]$WorkDir
) {

    $out = Join-Path $script:LogDir "$Name.out.log"
    $err = Join-Path $script:LogDir "$Name.err.log"

    $p = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/c", $ArgsLine `
        -WorkingDirectory $WorkDir `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err

    Set-Content `
        -Path (Join-Path $script:RunDir "$Name.pid") `
        -Value $p.Id

    return $p
}


function Show-LogTail([string]$Name) {

    foreach ($s in "err", "out") {

        $f = Join-Path $script:LogDir "$Name.$s.log"

        if ((Test-Path $f) -and (Get-Item $f).Length -gt 0) {

            Write-Host "--- last lines of $Name.$s.log ---" -ForegroundColor DarkGray

            Get-Content $f -Tail 15
        }
    }
}


function Stop-Tracked([string]$Name) {

    $p = Get-TrackedPid $Name

    if (-not $p) {
        Write-Host "  ${Name}: not running (nothing tracked)"
        return
    }

    & taskkill.exe /PID $p /T /F | Out-Null

    Remove-Item `
        (Join-Path $script:RunDir "$Name.pid") `
        -Force `
        -ErrorAction SilentlyContinue

    Write-Ok "$Name stopped (pid $p)"
}


# ------------------------------------------------------------
# PostgreSQL executable discovery
# ------------------------------------------------------------

function Find-Psql {

    $c = Get-Command psql -ErrorAction SilentlyContinue

    if ($c) {
        return $c.Source
    }

    $hit = Get-ChildItem `
        -Path "C:\Program Files\PostgreSQL\*\bin\psql.exe" `
        -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1

    if ($hit) {
        return $hit.FullName
    }

    return $null
}


# ------------------------------------------------------------
# Bundled COLMAP integration
# ------------------------------------------------------------

function Get-ColmapDir {

    return (Join-Path $script:Root "tools\colmap")
}


function Get-ColmapExe {

    # 1. COLMAP_BIN override from .env
    # 2. Bundled COLMAP
    # 3. System PATH

    $o = $env:COLMAP_BIN

    if ($o -and $o -notin @("colmap", "colmap.exe", "auto")) {

        if (Test-Path -LiteralPath $o -PathType Leaf) {
            return (Resolve-Path -LiteralPath $o).Path
        }

        if (Test-Path -LiteralPath (Join-Path $o "colmap.exe")) {
            return (Join-Path $o "colmap.exe")
        }

        if (Test-Path -LiteralPath (Join-Path $o "bin\colmap.exe")) {
            return (Join-Path $o "bin\colmap.exe")
        }
    }

    $b = Join-Path (Get-ColmapDir) "bin\colmap.exe"

    if (Test-Path -LiteralPath $b) {
        return $b
    }

    $c = Get-Command colmap -ErrorAction SilentlyContinue

    if ($c) {
        return $c.Source
    }

    return $null
}


function Initialize-ColmapEnv {

    $exe = Get-ColmapExe

    if (-not $exe) {
        return $null
    }

    $bin = Split-Path -Parent $exe

    if (($env:PATH -split ";") -notcontains $bin) {
        $env:PATH = "$bin;$env:PATH"
    }

    $env:QT_QPA_PLATFORM = "offscreen"

    return $exe
}


# ------------------------------------------------------------
# Visual C++ runtime validation
# ------------------------------------------------------------

function Get-MissingVcRuntime {

    $need = @(
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
        "vcomp140.dll"
    )

    $sys = Join-Path $env:SystemRoot "System32"

    return @(
        $need | Where-Object {
            -not (Test-Path (Join-Path $sys $_))
        }
    )
}
