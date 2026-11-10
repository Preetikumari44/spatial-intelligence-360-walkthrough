# Real end-to-end check of authentication against the RUNNING services (nothing is mocked).
#   scripts\test-auth.ps1
# Needs: backend running (scripts\start-backend.ps1). psql is optional (used to confirm the user row and BCrypt hash).
# It registers one throw-away account (test-auth-<random>@example.com). That account is left in the database
# (nothing is deleted from your data); the throw-away project it creates is deleted again.
. "$PSScriptRoot\_common.ps1"
Import-ProjectEnv
$api = "http://localhost:$($env:BACKEND_PORT)"
$origin = "http://localhost:$($env:FRONTEND_PORT)"
$script:pass = 0; $script:fail = 0
function Check([string]$name, [bool]$ok, [string]$detail = "") {
    if ($ok) { $script:pass++; Write-Ok "$name $detail" } else { $script:fail++; Write-Host "[ FAIL ] $name $detail" -ForegroundColor Red }
}
function Call([string]$method, [string]$path, $body = $null, [string]$token = $null, [hashtable]$extra = @{}) {
    $h = @{ Origin = $origin }
    foreach ($key in $extra.Keys) { $h[$key] = $extra[$key] }
    if ($token) { $h["Authorization"] = "Bearer $token" }
    $p = @{ Uri = "$api$path"; Method = $method; Headers = $h; UseBasicParsing = $true; TimeoutSec = 30 }
    if ($null -ne $body) { $p["Body"] = ($body | ConvertTo-Json); $p["ContentType"] = "application/json" }
    try { $r = Invoke-WebRequest @p; return @{ Code = [int]$r.StatusCode; Body = $r.Content; Headers = $r.Headers } }
    catch {
        $resp = $_.Exception.Response
        if ($null -eq $resp) { return @{ Code = 0; Body = $_.Exception.Message; Headers = @{} } }
        $txt = ""; try { $txt = (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd() } catch {}
        return @{ Code = [int]$resp.StatusCode; Body = $txt; Headers = $resp.Headers }
    }
}
function Json($r) { try { $r.Body | ConvertFrom-Json } catch { $null } }

$email = "test-auth-$([guid]::NewGuid().ToString('N').Substring(0,8))@example.com"
$pw = "Correct-Horse-9"

# 0. Reachability and CORS (what the browser needs before it will even send the request)
$h = Call GET "/actuator/health"
Check "Backend health" ($h.Code -eq 200) "(HTTP $($h.Code)) $api/actuator/health"
if ($h.Code -ne 200) { Fail "Backend is not reachable at $api. Run scripts\start-backend.ps1 and read .run\logs\backend.*.log" }
foreach ($o in @("http://localhost:$($env:FRONTEND_PORT)", "http://127.0.0.1:$($env:FRONTEND_PORT)")) {
    $pf = Call OPTIONS "/api/auth/login" $null $null @{ Origin = $o; "Access-Control-Request-Method" = "POST"; "Access-Control-Request-Headers" = "content-type,authorization" }
    $acao = "$($pf.Headers['Access-Control-Allow-Origin'])"
    Check "CORS preflight from $o" ($pf.Code -in 200, 204 -and $acao -eq $o) "(HTTP $($pf.Code), Access-Control-Allow-Origin='$acao')"
}
$pfPut = Call OPTIONS "/api/nodes/00000000-0000-0000-0000-000000000000/room" $null $null @{ "Access-Control-Request-Method" = "PUT" }
Check "CORS allows PUT" ("$($pfPut.Headers['Access-Control-Allow-Methods'])" -match "PUT") ""

# 1. Register
$r = Call POST "/api/auth/register" @{ email = $email; password = $pw; displayName = "Auth Test" }
$reg = Json $r
Check "1. Register new account" ($r.Code -in 200, 201 -and $reg.token) "(HTTP $($r.Code))"
# 2. Saved in PostgreSQL, hashed with BCrypt
$psql = Find-Psql
if ($psql) {
    $db = Get-DbParts
    $env:PGPASSWORD = $env:DB_PASSWORD
    $row = & $psql -h $db.Host -p $db.Port -U $env:DB_USER -d $db.Name -tAc "select email || '|' || left(password_hash, 4) from users where email = '$email'" 2>&1 | Out-String
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    Check "2. User row exists in PostgreSQL with a BCrypt hash" ($row.Trim() -match "^$([regex]::Escape($email))\|\`$2[aby]\`$") "($($row.Trim()))"
} else { Write-Warn2 "2. psql not found: could not read the users table directly (the /me call below still proves it was saved)" }
# 3. Sign in
$r = Call POST "/api/auth/login" @{ email = $email; password = $pw }
$login = Json $r
Check "3. Sign in with the correct password" ($r.Code -eq 200 -and $login.token) "(HTTP $($r.Code))"
# 4. Wrong password
$r = Call POST "/api/auth/login" @{ email = $email; password = "wrong-password-1" }
Check "4. Wrong password is rejected with 401" ($r.Code -eq 401) "(HTTP $($r.Code): $($r.Body))"
# 5. Duplicate e-mail
$r = Call POST "/api/auth/register" @{ email = $email.ToUpper(); password = $pw; displayName = "Dup" }
Check "5. Duplicate e-mail is rejected with 409" ($r.Code -eq 409) "(HTTP $($r.Code): $($r.Body))"
$r = Call POST "/api/auth/register" @{ email = "not-an-email"; password = "short" }
Check "   Invalid input is rejected with 400" ($r.Code -eq 400) "(HTTP $($r.Code): $($r.Body))"
# 6. Session validity (what a browser refresh does)
$r = Call GET "/api/auth/me" $null $login.token
Check "6. Token is valid on /api/auth/me" ($r.Code -eq 200 -and (Json $r).email -eq $email) "(HTTP $($r.Code))"
# 7. No token / bad token
$r = Call GET "/api/projects"
Check "7. Protected API without a token returns 401" ($r.Code -eq 401) "(HTTP $($r.Code))"
$r = Call GET "/api/projects" $null "not.a.token"
Check "   Protected API with a bad token returns 401" ($r.Code -eq 401) "(HTTP $($r.Code))"
# 8. Services
try { $ai = Invoke-RestMethod -Uri "http://localhost:$($env:AI_PORT)/health" -TimeoutSec 5; Check "8. Python AI service" ($ai.status -eq "ok") "(/health: $($ai.status))" }
catch { Check "8. Python AI service" $false "(no answer on port $($env:AI_PORT))" }
# 10. Upload connectivity with the new account
$r = Call POST "/api/projects" @{ name = "auth-test-project"; propertyType = "Apartment" } $login.token
$proj = Json $r
Check "10a. Create project" ($r.Code -in 200, 201 -and $proj.id) "(HTTP $($r.Code))"
if ($proj.id) {
    $png = [Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    $tmp = Join-Path $env:TEMP "auth-test.png"; [IO.File]::WriteAllBytes($tmp, $png)
    $out = & curl.exe -s -o NUL -w "%{http_code}" -H "Authorization: Bearer $($login.token)" -F "files=@$tmp;type=image/png" "$api/api/projects/$($proj.id)/images"
    Check "10b. Image upload API reachable (accepted 200/201, or rejected with a clear 4xx because the 1x1 test image is tiny)" ($out -in "200", "201", "400", "415", "422") "(HTTP $out)"
    Remove-Item $tmp -ErrorAction SilentlyContinue
    $r = Call DELETE "/api/projects/$($proj.id)" $null $login.token
    Check "    Clean up test project" ($r.Code -in 200, 204) "(HTTP $($r.Code))"
}
Write-Host ""
Write-Host "Passed: $($script:pass)   Failed: $($script:fail)" -ForegroundColor $(if ($script:fail -eq 0) { "Green" } else { "Red" })
Write-Host "Not covered here (needs a browser): form validation messages, redirect to /login after sign-out, the page refresh itself. See docs\AUTH_TESTING_REPORT.md."
exit $script:fail
