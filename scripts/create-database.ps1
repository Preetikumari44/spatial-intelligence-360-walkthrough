# One-time helper: creates the application role and database if they do not exist. It never drops or truncates anything.
. "$PSScriptRoot\_common.ps1"
Import-ProjectEnv
if (-not $env:DB_PASSWORD) { Fail "DB_PASSWORD is not set in .env" }
$db = Get-DbParts
$psql = Find-Psql
if (-not $psql) { Fail "psql.exe not found. Install PostgreSQL or add its bin folder to PATH." }
if (-not (Test-PortListening $db.Port)) { Fail "PostgreSQL is not listening on port $($db.Port). Run scripts\start-database.ps1 first." }

$secure = Read-Host "Password of the PostgreSQL superuser 'postgres' (set during installation)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

function Run-Sql([string]$sql) {
    $r = Invoke-Native "`"$psql`" -h $($db.Host) -p $($db.Port) -U postgres -d postgres -tAc `"$sql`""
    if ($r.Code -ne 0) { Fail "psql failed: $($r.Output)" }
    return $r.Output
}
$user = $env:DB_USER
if ($user -notmatch "^[A-Za-z_][A-Za-z0-9_]*$" -or $db.Name -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") { Fail "DB_USER and the database name may only contain letters, digits and underscores" }
$pw = $env:DB_PASSWORD.Replace("'", "''")

if ((Run-Sql "select 1 from pg_roles where rolname='$user'") -eq "1") { Write-Ok "Role '$user' already exists (password left unchanged)" }
else { Run-Sql "create role $user login password '$pw'" | Out-Null; Write-Ok "Created role '$user'" }

if ((Run-Sql "select 1 from pg_database where datname='$($db.Name)'") -eq "1") { Write-Ok "Database '$($db.Name)' already exists (left untouched)" }
else { Run-Sql "create database $($db.Name) owner $user" | Out-Null; Write-Ok "Created database '$($db.Name)'" }
Write-Host "Tables are created by the backend's Flyway migration on its first start."

exit 0
