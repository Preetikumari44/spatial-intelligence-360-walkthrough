# Runs every check that can run on this machine and prints PASS / FAIL / NOT TESTED per item. Nothing is marked PASS unless it ran.
#   scripts\test-full-pipeline.ps1                         unit tests + COLMAP check + synthetic-video pipeline
#   scripts\test-full-pipeline.ps1 -Video C:\path\x.mp4    also run YOUR video through the pipeline
#   scripts\test-full-pipeline.ps1 -Full                   also Maven tests, TypeScript check and the production frontend build
param([string]$Video = "", [switch]$Full, [switch]$SkipSplat)
. "$PSScriptRoot\_common.ps1"
Import-ProjectEnv
$results = [ordered]@{}
function Rec([string]$name, [string]$status, [string]$detail = "") { $results[$name] = @{ status = $status; detail = $detail }
    $c = switch ($status) { "PASS" { "Green" } "FAIL" { "Red" } default { "Yellow" } }
    Write-Host ("[{0,-10}] {1}  {2}" -f $status, $name, $detail) -ForegroundColor $c }
$ai = Join-Path $Root "ai-service"
$vpy = Join-Path $ai ".venv\Scripts\python.exe"

# A. Python unit tests (COLMAP compat, frames, poses, Open3D, mesh, Gaussian, tour, API)
if (Test-Path $vpy) {
    Push-Location $ai
    try { $out = & $vpy -m pytest -q 2>&1 | Out-String; $tail = ($out -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
          Rec "Python unit tests (pytest)" $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL" }) $tail } finally { Pop-Location }
} else { Rec "Python unit tests (pytest)" "NOT TESTED" "run scripts\setup-ai.ps1 first" }

# B. COLMAP: starts, version, options
& "$PSScriptRoot\check-colmap.ps1" | Out-Null
Rec "COLMAP executable, DLLs and options" $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL" }) "see scripts\check-colmap.ps1"

# C. synthetic video through the real pipeline (frames -> poses -> sparse -> Open3D -> mesh -> Gaussian)
if (Test-Path $vpy) {
    $syn = Join-Path $env:TEMP "spatial_synthetic_room.mp4"
    & $vpy (Join-Path $PSScriptRoot "make_test_video.py") $syn | Out-Null
    $reports = @(@{ Name = "synthetic room video"; Path = $syn })
    if ($Video) { if (Test-Path $Video) { $reports += @{ Name = "your video"; Path = (Resolve-Path $Video).Path } } else { Rec "your video" "NOT TESTED" "file not found: $Video" } }
    foreach ($r in $reports) {
        $rep = Join-Path $Root ("acceptance_" + ($r.Name -replace " ", "_") + ".json")
        Push-Location $ai
        try { $a = @("tools\cpu_acceptance.py", $r.Path, "--out", $rep); if ($SkipSplat) { $a += "--skip-splat" }
              & $vpy @a | Out-Host; $code = $LASTEXITCODE } finally { Pop-Location }
        if (Test-Path $rep) {
            $j = Get-Content $rep -Raw | ConvertFrom-Json
            foreach ($st in $j.stages.PSObject.Properties) { Rec "$($r.Name): stage $($st.Name)" $(if ($st.Value.status -eq "ok") { "PASS" } else { "FAIL" }) "$($st.Value.error)" }
            foreach ($ft in $j.features.PSObject.Properties) { Rec "$($r.Name): $($ft.Name)" $(if ($ft.Value.generated -eq "yes") { "PASS" } elseif ($ft.Value.tested -eq "yes") { "FAIL" } else { "NOT TESTED" }) "$($ft.Value.detail)" }
        } else { Rec "$($r.Name): acceptance run" "FAIL" "no report written (exit $code)" }
    }
} else { Rec "synthetic video pipeline" "NOT TESTED" "AI environment missing" }

# D. services (only if running)
& "$PSScriptRoot\check-services.ps1" | Out-Null
Rec "Services: PostgreSQL + AI + backend health" $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "NOT TESTED" }) $(if ($LASTEXITCODE -ne 0) { "start them with scripts\start-all.ps1, then rerun" } else { "all three answered" })

# E. Java / TypeScript / Next build
if ($Full) {
    Push-Location (Join-Path $Root "backend"); try { & cmd.exe /c "mvn -q test"; Rec "Java compile + backend tests (mvn test)" $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL" }) } finally { Pop-Location }
    Push-Location (Join-Path $Root "frontend")
    try { & cmd.exe /c "npx tsc --noEmit"; Rec "Frontend TypeScript (tsc --noEmit)" $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL" })
          & cmd.exe /c "npm run build"; Rec "Next.js production build" $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL" }) } finally { Pop-Location }
} else { foreach ($n in "Java compile + backend tests (mvn test)", "Frontend TypeScript (tsc --noEmit)", "Next.js production build") { Rec $n "NOT TESTED" "add -Full" } }
Rec "Browser: Virtual Walkthrough / Digital Twin render" "NOT TESTED" "manual: open the project in the app after a successful job"

$out = Join-Path $Root "test_results.json"
$results | ConvertTo-Json -Depth 4 | Set-Content $out -Encoding UTF8
$fail = @($results.Values | Where-Object { $_.status -eq "FAIL" }).Count
$nt = @($results.Values | Where-Object { $_.status -eq "NOT TESTED" }).Count
Write-Host "`nPASS $(@($results.Values | Where-Object { $_.status -eq 'PASS' }).Count)  FAIL $fail  NOT TESTED $nt   (written to $out)"
exit $(if ($fail -gt 0) { 1 } else { 0 })
