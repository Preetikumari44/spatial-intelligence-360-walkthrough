# Removes old demo/test uploads and generated results so you can start with a new video.
#   .\scripts\clean-demo-data.ps1             REPORT ONLY (changes nothing)
#   .\scripts\clean-demo-data.ps1 -Execute    backs up, asks you to type CLEAN, then deletes
# Never touches: users, schema, migrations, source code, models, tools\colmap, .env.
# Stop the backend and AI service first (scripts\stop-all.ps1) so no file is in use.
param([switch]$Execute, [string]$KeepProjects = "")
. "$PSScriptRoot\_common.ps1"
Import-ProjectEnv

$psql = Find-Psql
if (-not $psql) { Fail "psql.exe not found. Install PostgreSQL or add its bin folder to PATH." }
$pgDump = Join-Path (Split-Path $psql) "pg_dump.exe"
$db = Get-DbParts
$store = if ($env:STORAGE_ROOT) { $env:STORAGE_ROOT } else { Join-Path $script:Root "data\storage" }
$env:PGPASSWORD = $env:DB_PASSWORD
try {
    Write-Step "Database report (read-only)"
    & $psql -h $db.Host -p $db.Port -U $env:DB_USER -d $db.Name -f (Join-Path $PSScriptRoot "sql\report_demo_data.sql")
    if ($LASTEXITCODE -ne 0) { Fail "Report failed. Is PostgreSQL running?" }

    Write-Step "Storage folders that would be removed"
    foreach ($sub in "projects", "jobs", "videos") {
        $p = Join-Path $store $sub
        if (Test-Path $p) { Get-ChildItem $p -Force | Where-Object { $_.Name -ne ".gitkeep" } | ForEach-Object { Write-Host ("  {0}\{1}" -f $sub, $_.Name) } }
    }
    if (-not $Execute) { Write-Ok "Report only. Nothing was changed. Re-run with -Execute to clean."; return }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $bk = Join-Path $script:Root "backups\$stamp"
    New-Item -ItemType Directory -Force -Path $bk | Out-Null
    Write-Step "Backing up database to $bk"
    & $pgDump -h $db.Host -p $db.Port -U $env:DB_USER -Fc -f (Join-Path $bk "spatial.dump") $db.Name
    if ($LASTEXITCODE -ne 0) { Fail "pg_dump failed. Nothing was deleted." }
    Write-Step "Backing up storage folders"
    foreach ($sub in "projects", "jobs", "videos") {
        $p = Join-Path $store $sub
        if (Test-Path $p) { Copy-Item $p (Join-Path $bk "storage-$sub") -Recurse -Force }
    }

    $ans = Read-Host "Type CLEAN to delete all projects, uploads and generated results (users are kept)"
    if ($ans -ne "CLEAN") { Fail "Cancelled. Nothing was deleted." }

    Write-Step "Cleaning database rows"
    & $psql -h $db.Host -p $db.Port -U $env:DB_USER -d $db.Name -v "keep=$KeepProjects" -f (Join-Path $PSScriptRoot "sql\clean_demo_data.sql")
    if ($LASTEXITCODE -ne 0) { Fail "Database cleanup failed and was rolled back. Files were not touched." }

    Write-Step "Removing files"
    foreach ($sub in "projects", "jobs", "videos") {
        $p = Join-Path $store $sub
        New-Item -ItemType Directory -Force -Path $p | Out-Null
        Get-ChildItem $p -Force | Where-Object { $_.Name -ne ".gitkeep" -and ($KeepProjects -eq "" -or $KeepProjects -notmatch $_.Name) } |
            Remove-Item -Recurse -Force
    }
    Write-Ok "Done. Backup kept in $bk. Start the services and upload a new video."
} finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}
