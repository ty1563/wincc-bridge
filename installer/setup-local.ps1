# WinCC Bridge LOCAL installer - chay TRUC TIEP tren may WinCC (co internet + WinCC).
# Khong dung SSH: OLE-DB reader chay tai cho, service POST thang len n8n.
# TUONG THICH: Windows 7 SP1+ (PowerShell 2.0+), 8, 10, 11.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$SVC = "WinCCBridge"
$ProgressPreference = "SilentlyContinue"

# ---- TLS 1.2 (Win 7 mac dinh chi TLS 1.0 -> tai file HTTPS se loi) ----
try {
  $tls12 = [Net.SecurityProtocolType]::Tls12
} catch {
  $tls12 = 3072  # Tls12 const enum khi .NET cu chua co
}
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor $tls12 } catch {}

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    $m" -ForegroundColor Yellow }
function Err($m)  { Write-Host "[LOI] $m" -ForegroundColor Red }

# ============================================================
# Helper: Download file (PS 2.0+ compat, khong dung Invoke-WebRequest)
# ============================================================
function Download-File($url, $out) {
  try {
    $wc = New-Object System.Net.WebClient
    $wc.DownloadFile($url, $out)
    return $true
  } catch {
    Warn "Tai $url -> loi: $_"
    return $false
  }
}

# ============================================================
# Helper: Unzip (PS 2.0/3.0/4.0/5.0+ compat)
#   1. Expand-Archive neu co (PS 5.0+)
#   2. .NET ZipFile.ExtractToDirectory neu .NET 4.5+ san
#   3. Shell.Application COM (Windows XP+ luon co)
# ============================================================
function Expand-Zip($zip, $dst) {
  if (-not (Test-Path $dst)) { New-Item -ItemType Directory -Force $dst | Out-Null }
  if (Get-Command Expand-Archive -ErrorAction SilentlyContinue) {
    try { Expand-Archive -LiteralPath $zip -DestinationPath $dst -Force; return $true } catch { Warn "Expand-Archive loi: $_" }
  }
  try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $dst)
    return $true
  } catch { Warn ".NET ZipFile loi: $_ - thu Shell.Application" }
  try {
    $sh = New-Object -ComObject Shell.Application
    $src = $sh.NameSpace((Resolve-Path $zip).Path)
    $trg = $sh.NameSpace((Resolve-Path $dst).Path)
    $trg.CopyHere($src.Items(), 20)  # 4=no progress + 16=yes to all
    Start-Sleep 2
    return $true
  } catch { Err "Shell.Application loi: $_"; return $false }
}

Info "WinCC Bridge LOCAL setup | repo = $repo"

# --- Admin check ---
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Err "Can chay bang quyen Administrator."
  Write-Host "      Chuot phai setup-local.bat -> 'Run as administrator' roi chay lai." -ForegroundColor Yellow
  Read-Host "Enter de thoat"
  exit 1
}

# --- PowerShell version check (canh bao neu PS 2.0) ---
$psv = $PSVersionTable.PSVersion.Major
Info "PowerShell version = $psv"
if ($psv -lt 3) {
  Warn "PS 2.0 cu - se dung .NET WebClient de tai file. Neu tai HTTPS loi -> cai WMF 5.1: https://aka.ms/wmf51"
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

# ---------- 1) Python 3.11 64-bit (cho bridge service loop) ----------
Info "[1/6] Python 64-bit (cho service loop)"
$py = $null
foreach ($c in @("$env:LOCALAPPDATA\Programs\Python\Python311\python.exe", "$env:USERPROFILE\Python311\python.exe", "C:\Python311\python.exe")) {
  if (Test-Path $c) { $py = $c; break }
}
if (-not $py) {
  $g = Get-Command python -ErrorAction SilentlyContinue
  if ($g) {
    $v = & $g.Source -c "import sys;print(sys.version_info>=(3,9))"
    if ($v -eq "True") { $py = $g.Source }
  }
}
if (-not $py) {
  Warn "Cai Python 3.11.9 (per-user)..."
  $pyexe = "$env:TEMP\python-3.11.9-amd64.exe"
  if (-not (Download-File "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" $pyexe)) {
    Err "Khong tai duoc Python installer. Cai tay tu https://www.python.org roi chay lai setup."
    Read-Host "Enter de thoat"; exit 1
  }
  Start-Process $pyexe -ArgumentList "/quiet","InstallAllUsers=0","PrependPath=1","Include_pip=1","Include_test=0","TargetDir=$env:USERPROFILE\Python311" -Wait
  $py = "$env:USERPROFILE\Python311\python.exe"
}
if (-not (Test-Path $py)) { Err "Khong cai duoc Python 3.11"; Read-Host "Enter de thoat"; exit 1 }
Ok ("python = " + $py + " (" + (& $py --version) + ")")

# ---------- 2) git (tuy chon - OTA co fallback HTTP-zip) ----------
Info "[2/6] git (tuy chon - neu khong co, OTA dung HTTP-zip)"
$hasGit = [bool](Get-Command git -ErrorAction SilentlyContinue)
if ($hasGit) { Ok ("git = " + (git --version)) } else { Warn "Khong co git -> OTA dung HTTP-zip (van OK)" }

# ---------- 3) nssm ----------
Info "[3/6] nssm"
$nssm = "$repo\tools\nssm.exe"
if (-not (Test-Path $nssm)) {
  New-Item -ItemType Directory -Force "$repo\tools" | Out-Null
  $z = "$env:TEMP\nssm.zip"
  if (-not (Download-File "https://nssm.cc/release/nssm-2.24.zip" $z)) {
    Err "Khong tai duoc nssm.zip - kiem tra mang."
    Read-Host "Enter de thoat"; exit 1
  }
  $nssmDir = "$env:TEMP\nssm"
  if (Test-Path $nssmDir) { Remove-Item -Recurse -Force $nssmDir -ErrorAction SilentlyContinue }
  if (-not (Expand-Zip $z $nssmDir)) { Err "Giai nen nssm loi"; Read-Host "Enter"; exit 1 }
  Copy-Item "$nssmDir\nssm-2.24\win64\nssm.exe" $nssm -Force
}
if (-not (Test-Path $nssm)) { Err "nssm khong co"; Read-Host "Enter de thoat"; exit 1 }
Ok "nssm = $nssm"

# ---------- 4) Cau hinh (webhook + Python 32-bit) ----------
Info "[4/6] Cau hinh LOCAL"
$defWebhook = "https://n8n.svnagentic.site/webhook/e54059c6-41f1-4854-be96-1d79f8d78797?user=1"
$webhook = Read-Host "  n8n webhook URL (Enter = mac dinh)"; if (-not $webhook) { $webhook = $defWebhook }

# --- Tram (station) ---
# Ten tram giup n8n phan biet Dakrosa1 / Dakrosa2 / ... Payload luon co field 'station'.
$stationName = Read-Host "  Ten tram (Enter = Dakrosa1)"; if (-not $stationName) { $stationName = "Dakrosa1" }
# PROJECT_LIKE mac dinh suy tu ten tram: LIKE 'CC[_]<ten>[_]%R'
$defProjLike = "CC[_]$stationName[_]%R"
$projLike = Read-Host "  WinCC project pattern (Enter = $defProjLike)"; if (-not $projLike) { $projLike = $defProjLike }
$catFallback = Read-Host "  Catalog fallback (Enter = de trong, reader tu do)"; if (-not $catFallback) { $catFallback = "" }

$py32 = $null
foreach ($c in @(
  "C:\Python311x86\python.exe",
  "C:\Python310x86\python.exe",
  "C:\Python39x86\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python311-32\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python310-32\python.exe",
  "$env:USERPROFILE\Python311x86\python.exe"
)) { if (Test-Path $c) { $py32 = $c; break } }
if (-not $py32) { $py32 = "C:\Python311x86\python.exe" }
$py32Input = Read-Host "  Python 32-bit (Enter = $py32)"
if ($py32Input) { $py32 = $py32Input }
if (-not (Test-Path $py32)) {
  Warn "Chua thay Python 32-bit tai '$py32' - service se bao loi khi collect."
  Warn "Cai: https://www.python.org/downloads/windows/ -> 'Windows installer (32-bit)' 3.11 -> pip install pywin32"
}
$reader = "$repo\box\oledb_reader.py"

# ---------- 5) Viet config.local.toml (mode=local, UTF-8 khong BOM) ----------
Info "[5/6] config.local.toml (mode=local)"
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

# ---------- 6) Dang ky NSSM service (auto-start, LocalSystem) ----------
Info "[6/6] Dang ky service $SVC (auto-start)"
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
