# Installs the bundled COLMAP (CPU / no-CUDA build) into tools\colmap and checks that it can start.
#   scripts\install-colmap.ps1                       use tools\colmap if complete, else extract colmap-x64-windows-nocuda.zip
#   scripts\install-colmap.ps1 -Zip C:\path\colmap-x64-windows-nocuda.zip
#   scripts\install-colmap.ps1 -InstallVcRuntime     also install the Microsoft Visual C++ 2015-2022 x64 runtime if it is missing (needs admin)
# It never replaces a working bundled build and never touches COLMAP_BIN in .env. The zip must be the one supplied with this project;
# any other COLMAP build is only used if you point COLMAP_BIN at it yourself.
param([string]$Zip = "", [switch]$InstallVcRuntime, [switch]$Force)
. "$PSScriptRoot\_common.ps1"
$dest = Get-ColmapDir
$exe = Join-Path $dest "bin\colmap.exe"

function Test-Complete {
    if (-not (Test-Path $exe)) { return $false }
    $dlls = @(Get-ChildItem (Join-Path $dest "bin") -Filter *.dll -ErrorAction SilentlyContinue)
    $core = @("Qt6Core.dll", "ceres.dll", "OpenImageIO.dll") | Where-Object { Test-Path (Join-Path $dest "bin\$_") }
    return ($dlls.Count -ge 50 -and $core.Count -eq 3)
}

if ((Test-Complete) -and -not $Force) {
    Write-Ok "Bundled COLMAP already present: $exe ($((Get-ChildItem (Join-Path $dest 'bin') -Filter *.dll).Count) DLLs)"
} else {
    $candidates = @()
    if ($Zip) { $candidates += $Zip }
    $candidates += (Join-Path $Root "tools\colmap-x64-windows-nocuda.zip"), (Join-Path $Root "colmap-x64-windows-nocuda.zip"),
                   (Join-Path ([Environment]::GetFolderPath("UserProfile")) "Downloads\colmap-x64-windows-nocuda.zip")
    $src = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
    if (-not $src) { Fail "COLMAP is not in tools\colmap and colmap-x64-windows-nocuda.zip was not found. Put the zip into $Root\tools\ or pass -Zip <path>, then rerun." }
    Write-Step "Extracting $src into $dest"
    $tmp = Join-Path $env:TEMP ("colmap-extract-" + [guid]::NewGuid().ToString("N"))
    try {
        Expand-Archive -LiteralPath $src -DestinationPath $tmp -Force
        # the zip is either <root>\bin\colmap.exe or <root>\<one folder>\bin\colmap.exe
        $hit = Get-ChildItem $tmp -Recurse -Filter colmap.exe | Select-Object -First 1
        if (-not $hit) { Fail "No colmap.exe inside $src. Is this the right archive?" }
        $srcRoot = Split-Path -Parent (Split-Path -Parent $hit.FullName)
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        # all DLLs, the exe and the Qt plugins; the *_test.exe unit-test programs are not needed at run time and are skipped
        Copy-Item -Path (Join-Path $srcRoot "bin\*") -Destination (Join-Path $dest "bin") -Recurse -Force -Exclude "*_test.exe" -ErrorAction Stop
        foreach ($extra in "plugins", "COLMAP.bat") {
            if (Test-Path (Join-Path $srcRoot $extra)) { Copy-Item -Path (Join-Path $srcRoot $extra) -Destination $dest -Recurse -Force }
        }
    } finally { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    if (-not (Test-Complete)) { Fail "Extraction finished but tools\colmap\bin looks incomplete (colmap.exe or core DLLs missing)." }
    Write-Ok "COLMAP extracted to $dest"
}

# Visual C++ runtime: colmap.exe imports vcruntime140*, msvcp140*, vcomp140; the COLMAP package does not contain them.
$missing = Get-MissingVcRuntime
if ($missing.Count -gt 0) {
    Write-Warn2 ("Visual C++ runtime DLLs missing from System32: " + ($missing -join ", "))
    if ($InstallVcRuntime) {
        $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        if (-not $isAdmin) { Fail "Installing the Visual C++ runtime needs an administrator PowerShell. Reopen PowerShell as administrator and rerun with -InstallVcRuntime." }
        $vc = Join-Path $env:TEMP "vc_redist.x64.exe"
        Write-Step "Downloading https://aka.ms/vs/17/release/vc_redist.x64.exe"
        Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $vc -UseBasicParsing
        $p = Start-Process -FilePath $vc -ArgumentList "/install", "/quiet", "/norestart" -Wait -PassThru
        if ($p.ExitCode -notin 0, 1638, 3010) { Fail "vc_redist installer exited with code $($p.ExitCode)" }
        Write-Ok "Visual C++ runtime installed (exit code $($p.ExitCode); 3010 means a restart is pending)"
    } else {
        Write-Host "  Install it from https://aka.ms/vs/17/release/vc_redist.x64.exe, or rerun: scripts\install-colmap.ps1 -InstallVcRuntime (admin)" -ForegroundColor Yellow
    }
}
& "$PSScriptRoot\check-colmap.ps1"
exit $LASTEXITCODE
