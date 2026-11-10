# Verifies the COLMAP that the AI service will use: where it is, whether Windows can start it (DLL loading), its version,
# whether it is a CUDA build, and whether the options this project passes exist in THIS binary. Exit code 0 only if it works.
. "$PSScriptRoot\_common.ps1"
try { Import-ProjectEnv } catch { }   # .env is optional here
$exe = Initialize-ColmapEnv
$bad = 0
function Row([string]$name, [bool]$ok, [string]$detail) {
    if ($ok) { Write-Ok ("{0,-22} {1}" -f $name, $detail) } else { Write-Host ("[ FAIL ] {0,-22} {1}" -f $name, $detail) -ForegroundColor Red; $script:bad++ }
}
if (-not $exe) { Row "colmap.exe" $false "not found. Run scripts\install-colmap.ps1"; exit 1 }
$source = if ($env:COLMAP_BIN -and $env:COLMAP_BIN -notin @("colmap", "colmap.exe", "auto")) { "override (COLMAP_BIN)" } elseif ($exe -like "$(Get-ColmapDir)*") { "bundled" } else { "PATH" }
Row "colmap.exe" $true "$exe  [$source]"
$dlls = @(Get-ChildItem (Split-Path -Parent $exe) -Filter *.dll -ErrorAction SilentlyContinue).Count
Row "bundled DLLs" ($dlls -ge 50) "$dlls DLL files next to colmap.exe"
$vc = Get-MissingVcRuntime
Row "Visual C++ runtime" ($vc.Count -eq 0) $(if ($vc.Count -eq 0) { "present in System32" } else { "MISSING: " + ($vc -join ", ") + "  -> scripts\install-colmap.ps1 -InstallVcRuntime" })

# start the executable: this is what actually proves the DLLs load
$r = Invoke-Native "`"$exe`" help"
$code = $r.Code
if ($code -eq -1073741515 -or $code -eq 3221225781) { Row "starts" $false "exit 0xC0000135: a DLL could not be loaded (usually the Visual C++ runtime)" }
elseif ($code -ne 0) { Row "starts" $false "exit code $code. Output: $($r.Output.Substring(0, [Math]::Min(300, $r.Output.Length)))" }
else {
    $banner = ($r.Output -split "`r?`n" | Where-Object { $_ -match "(?i)colmap" } | Select-Object -First 1)
    Row "starts" $true "$banner"
    $cuda = if ($r.Output -match "(?i)without\s+cuda") { "NO (CPU-only build, as expected)" } elseif ($r.Output -match "(?i)with\s+cuda") { "yes" } else { "not stated in the banner (treated as CPU-only)" }
    Write-Host "         CUDA: $cuda"
    # the real option check: these are the options the pipeline passes, read from this binary's own help
    $need = @{
        "feature_extractor" = @("FeatureExtraction.use_gpu", "FeatureExtraction.max_image_size", "ImageReader.camera_model", "ImageReader.single_camera")
        "sequential_matcher" = @("FeatureMatching.use_gpu", "SequentialMatching.overlap")
        "exhaustive_matcher" = @("FeatureMatching.use_gpu")
        "mapper" = @("database_path", "image_path", "output_path")
        "model_converter" = @("input_path", "output_path", "output_type")
    }
    foreach ($cmd in $need.Keys) {
        $h = Invoke-Native "`"$exe`" $cmd -h"
        $missing = @($need[$cmd] | Where-Object { $h.Output -notmatch [regex]::Escape("--$_") -and $h.Output -notmatch [regex]::Escape("$_") })
        # older COLMAP spelled the extraction/matching options SiftExtraction.* / SiftMatching.*; the AI service accepts either, so only report
        if ($missing.Count -eq 0) { Row "options: $cmd" $true "all listed" }
        else {
            $alt = @($missing | ForEach-Object { $_ -replace "^FeatureExtraction", "SiftExtraction" -replace "^FeatureMatching", "SiftMatching" } | Where-Object { $h.Output -notmatch [regex]::Escape($_) })
            Row "options: $cmd" ($alt.Count -eq 0) $(if ($alt.Count -eq 0) { "listed under the older Sift* names" } else { "NOT listed: " + ($alt -join ", ") })
        }
    }
    Write-Host "         patch_match_stereo / stereo_fusion need CUDA: unavailable in this build; dense geometry uses the Open3D depth-fusion path." -ForegroundColor DarkGray
}
# what the running AI service reports, if it is up
try {
    $port = if ($env:AI_PORT) { $env:AI_PORT } else { "8000" }
    $s = Invoke-RestMethod -Uri "http://localhost:$port/colmap/status" -TimeoutSec 20
    Row "AI service view" ([bool]$s.start.started) "version $($s.version), source $($s.location.source), error: $($s.error)"
} catch { Write-Host "         (AI service not running; skipped its /colmap/status check)" -ForegroundColor DarkGray }
if ($bad -gt 0) { Write-Host "`n$bad check(s) failed." -ForegroundColor Red; exit 1 }
Write-Host "`nCOLMAP is ready." -ForegroundColor Green
exit 0
