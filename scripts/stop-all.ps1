# Stops only the processes these scripts started (recorded in .run\*.pid). The PostgreSQL service and
# any unrelated program using the same ports are left alone.
. "$PSScriptRoot\_common.ps1"
Write-Step "Stopping project processes"
foreach ($n in "frontend", "backend", "ai") { Stop-Tracked $n }
Write-Host "PostgreSQL service left running (stop it from services.msc if you want to)."
