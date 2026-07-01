# WinCC Bridge LOCAL installer - chay TRUC TIEP tren may WinCC (Win 7/8/10/11).
# Yeu cau CAI TRUOC (PowerShell 2.0/Win 7 khong tai duoc HTTPS moi):
#   1) Python 3.7+ x64  (Win 7 dung 3.7.9 - Python cuoi cung ho tro Win 7 chinh thuc)
#   2) Python 3.7+ x86  + `pip install pywin32`  (goi WinCCOLEDBProvider - COM 32-bit)
#      Tai: https://www.python.org/ftp/python/3.7.9/python-3.7.9.exe        (32-bit)
#           https://www.python.org/ftp/python/3.7.9/python-3.7.9-amd64.exe  (64-bit)
# nssm.exe da BUNDLED trong repo -> khong can tai.
# Config parser co fallback mini-TOML cho Python 3.7-3.10 (tomllib chi co tu 3.11).
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

# === PS 2.0 COMPAT: $PSScriptRoot chi co tu PS 3.0. Fallback bang $MyInvocation. ===
$scriptPath = $MyInvocation.MyCommand.Definition
$scriptDir  = Split-Path -Parent $scriptPath
$repo       = Split-Path -Parent $scriptDir
$SVC        = "WinCCBridge"

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    $m" -ForegroundColor Yellow }
function Err($m)  { Write-Host "[LOI] $m" -ForegroundColor Red }

Info "WinCC Bridge LOCAL setup | repo = $repo"

# --- PS version info ---
$psv = $PSVersionTable.PSVersion.Major
Info "PowerShell version = $psv"
if ($psv -lt 3) {
  Warn "PS 2.0 (Win 7 mac dinh) - installer khong tai file HTTPS, Python phai cai truoc."
}

# --- Admin check ---
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Err "Can chay bang quyen Administrator."
  Write-Host "      Chuot phai setup-local.bat -> 'Run as administrator' roi chay lai." -ForegroundColor Yellow
  Read-Host "Enter de thoat"
  exit 1
}

# --- Don service cu (neu co) ---
if (Get-Service $SVC -ErrorAction SilentlyContinue) {
  Info "Don service cu '$SVC'..."
  & sc.exe stop $SVC 2>$null | Out-Null
  Start-Sleep 2
  & sc.exe delete $SVC 2>$null | Out-Null
  Start-Sleep 2
  Ok "da go service cu"
}

# ---------- 1) Python 64-bit (bat buoc cai truoc) ----------
Info "[1/5] Kiem tra Python 3.7+ 64-bit (cho service loop)"
$py = $null
$cands = @(
  "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python38\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python37\python.exe",
  "$env:USERPROFILE\Python311\python.exe",
  "$env:USERPROFILE\Python37\python.exe",
  "C:\Python311\python.exe",
  "C:\Python310\python.exe",
  "C:\Python39\python.exe",
  "C:\Python38\python.exe",
  "C:\Python37\python.exe"
)
foreach ($c in $cands) { if (Test-Path $c) { $py = $c; break } }
if (-not $py) {
  $g = Get-Command python -ErrorAction SilentlyContinue
  if ($g) {
    $ok = & $g.Source -c "import sys;print(sys.version_info>=(3,7))"
    if ($ok -eq "True") { $py = $g.Source }
  }
}
if (-not $py) {
  Err "KHONG THAY Python 3.7+ 64-bit."
  Write-Host ""
  Write-Host "  Cach cai tren Win 7 (tren may co internet, roi copy sang):" -ForegroundColor Yellow
  Write-Host "    1. Tai: https://www.python.org/ftp/python/3.7.9/python-3.7.9-amd64.exe" -ForegroundColor Yellow
  Write-Host "       (3.7.9 la Python cuoi cung ho tro Win 7 chinh thuc)" -ForegroundColor Yellow
  Write-Host "    2. Copy sang may nay, chay installer, TICH 'Add Python to PATH'" -ForegroundColor Yellow
  Write-Host "    3. Chay lai setup-local.bat" -ForegroundColor Yellow
  Read-Host "Enter de thoat"
  exit 1
}
Ok ("python 64-bit = " + $py + " (" + (& $py --version) + ")")

# ---------- 2) git (tuy chon - OTA fallback HTTP-zip qua Python neu thieu) ----------
Info "[2/5] git (tuy chon)"
$hasGit = [bool](Get-Command git -ErrorAction SilentlyContinue)
if ($hasGit) { Ok ("git = " + (git --version)) } else { Warn "Khong co git -> OTA dung HTTP-zip qua Python (van OK)" }

# ---------- 3) nssm (BUNDLED trong repo) ----------
Info "[3/5] nssm"
$nssm = "$repo\tools\nssm.exe"
if (-not (Test-Path $nssm)) {
  Err "Khong tim thay nssm.exe (mong doi: $nssm). Bo zip bi loi - copy lai wincc-bridge-local.zip."
  Read-Host "Enter de thoat"; exit 1
}
Ok "nssm = $nssm (bundled)"

# ---------- 4) Cau hinh ----------
Info "[4/5] Cau hinh LOCAL"
$defWebhook = "https://n8n.svnagentic.site/webhook/e54059c6-41f1-4854-be96-1d79f8d78797?user=1"
$webhook = Read-Host "  n8n webhook URL (Enter = mac dinh)"
if (-not $webhook) { $webhook = $defWebhook }

# Ten tram
$stationName = Read-Host "  Ten tram (Enter = Dakrosa1)"
if (-not $stationName) { $stationName = "Dakrosa1" }
$defProjLike = "CC[_]$stationName[_]%R"
$projLike = Read-Host "  WinCC project pattern (Enter = $defProjLike)"
if (-not $projLike) { $projLike = $defProjLike }
$catFallback = Read-Host "  Catalog fallback (Enter = de trong, reader tu do)"
if (-not $catFallback) { $catFallback = "" }

# Python 32-bit (Win 7: dung 3.7.9 x86)
$py32 = $null
$cands32 = @(
  "C:\Python37x86\python.exe",
  "C:\Python38x86\python.exe",
  "C:\Python39x86\python.exe",
  "C:\Python310x86\python.exe",
  "C:\Python311x86\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python37-32\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python38-32\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python39-32\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python310-32\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python311-32\python.exe",
  "$env:USERPROFILE\Python37x86\python.exe",
  "$env:USERPROFILE\Python311x86\python.exe"
)
foreach ($c in $cands32) { if (Test-Path $c) { $py32 = $c; break } }
if (-not $py32) { $py32 = "C:\Python37x86\python.exe" }
$py32Input = Read-Host "  Python 32-bit (Enter = $py32)"
if ($py32Input) { $py32 = $py32Input }
if (-not (Test-Path $py32)) {
  Warn "CHUA thay Python 32-bit tai '$py32' - service se bao loi khi collect."
  Warn "  Win 7: tai https://www.python.org/ftp/python/3.7.9/python-3.7.9.exe  (32-bit)"
  Warn "  Sau khi cai: '$py32 -m pip install pywin32'"
}
$reader = "$repo\box\oledb_reader.py"

# ---------- 5) Viet config + dang ky service ----------
Info "[5/5] config.local.toml + service $SVC"
$cfgLocal = "$repo\config.local.toml"
$cfgBody = @"
[webhook]
url = "$webhook"

[station]
name = "$stationName"
project_like = "$projLike"
catalog_fallback = "$catFallback"

[winccbox]
mode = "local"
python32 = "$($py32 -replace '\\','/')"
reader = "$($reader -replace '\\','/')"

[intervals]
snapshot_sec = 300
ota_sec = 900

[ota]
enabled = true
repo = "https://github.com/ty1563/wincc-bridge.git"
branch = "main"
"@
[System.IO.File]::WriteAllText($cfgLocal, $cfgBody, (New-Object System.Text.UTF8Encoding $false))
Ok $cfgLocal

# --- Git tracking (OTA) neu co git ---
if ($hasGit) {
  Info "Git tracking (OTA)"
  $remote = "https://github.com/ty1563/wincc-bridge.git"
  if (-not (Test-Path "$repo\.git")) {
    git -C $repo init -q
    git -C $repo add -A
    git -C $repo -c user.email=bridge@local -c user.name=bridge commit -qm bootstrap | Out-Null
    git -C $repo remote add origin $remote
  } else { git -C $repo remote set-url origin $remote }
  git -C $repo fetch -q origin main
  git -C $repo reset --hard -q origin/main
  Ok "git tracking origin/main"
}

New-Item -ItemType Directory -Force "$repo\logs" | Out-Null
if (Get-Service $SVC -ErrorAction SilentlyContinue) {
  & $nssm stop $SVC 2>$null
  & $nssm remove $SVC confirm 2>$null
  Start-Sleep 1
}
& $nssm install $SVC $py "$repo\bridge\service.py" 2>$null
& $nssm set $SVC AppDirectory $repo 2>$null
& $nssm set $SVC Start SERVICE_AUTO_START 2>$null
& $nssm set $SVC AppStdout "$repo\logs\service.log" 2>$null
& $nssm set $SVC AppStderr "$repo\logs\service.log" 2>$null
& $nssm set $SVC AppRotateFiles 1 2>$null
& $nssm set $SVC AppRotateBytes 5242880 2>$null
& $nssm set $SVC AppExit Default Restart 2>$null
& $nssm set $SVC AppRestartDelay 5000 2>$null
& $nssm set $SVC AppThrottle 10000 2>$null
& sc.exe failure $SVC reset= 86400 actions= restart/5000/restart/5000/restart/60000 2>$null | Out-Null
& $nssm set $SVC ObjectName "LocalSystem" 2>$null | Out-Null
& $nssm start $SVC 2>$null
Start-Sleep 3
$st = (& $nssm status $SVC 2>$null)
Ok "service status: $st"

Write-Host ""
Info "Chan doan he thong (diagnose):"
try { & $py "$repo\bridge\diagnose.py" } catch { Warn "diagnose loi: $_" }
Write-Host ""
Info "Ping dau tien -> webhook (kiem tra ca pipeline ngay bay gio):"
try { & $py "$repo\bridge\service.py" --once } catch { Warn "ping loi: $_" }
Write-Host ""
Write-Host "HOAN TAT LOCAL SETUP. Log: $repo\logs\service.log | $repo\logs\diagnose.log" -ForegroundColor Green
Write-Host "Lenh huu ich: `"$nssm`" status $SVC | restart $SVC | stop $SVC" -ForegroundColor DarkGray
