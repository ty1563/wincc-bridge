# WinCC Bridge LOCAL installer - chay TREN CHINH MAY WinCC (co internet + WinCC).
# Khong dung SSH: OLE-DB reader chay tai cho, service POST thang len n8n.
# Yeu cau:
#   - Windows PowerShell chay bang Administrator (dang ky Windows service)
#   - Python 32-bit cai san (dua ra o buoc [4] - de goi WinCCOLEDBProvider)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$SVC = "WinCCBridge"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    $m" -ForegroundColor Yellow }

Info "WinCC Bridge LOCAL setup | repo = $repo"

# --- Admin check ---
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Host "[LOI] Can chay bang quyen Administrator." -ForegroundColor Red
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

# ---------- 1) Python 3.11+ 64-bit (cho bridge service loop) ----------
Info "[1/6] Python 64-bit (cho service loop)"
$py = $null
foreach ($c in @("$env:LOCALAPPDATA\Programs\Python\Python311\python.exe", "$env:USERPROFILE\Python311\python.exe")) {
  if (Test-Path $c) { $py = $c; break }
}
if (-not $py) { $g = Get-Command python -ErrorAction SilentlyContinue; if ($g -and (& $g.Source -c "import sys;print(sys.version_info>=(3,11))") -eq "True") { $py = $g.Source } }
if (-not $py) {
  Warn "Cai Python 3.11.9 (per-user)..."
  $pyexe = "$env:TEMP\python-3.11.9-amd64.exe"
  Invoke-WebRequest "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $pyexe -UseBasicParsing
  Start-Process $pyexe -ArgumentList "/quiet","InstallAllUsers=0","PrependPath=1","Include_pip=1","Include_test=0","TargetDir=$env:USERPROFILE\Python311" -Wait
  $py = "$env:USERPROFILE\Python311\python.exe"
}
if (-not (Test-Path $py)) { Write-Host "[LOI] Khong cai duoc Python 3.11 - kiem tra mang/quyen" -ForegroundColor Red; Read-Host "Enter de thoat"; exit 1 }
Ok ("python = " + $py + " (" + (& $py --version) + ")")

# ---------- 2) git (tuy chon - OTA co fallback HTTP-zip) ----------
Info "[2/6] git (tuy chon)"
$hasGit = [bool](Get-Command git -ErrorAction SilentlyContinue)
if (-not $hasGit) {
  try {
    Warn "Thu cai Git for Windows..."
    $rel = Invoke-RestMethod "https://api.github.com/repos/git-for-windows/git/releases/latest" -UseBasicParsing
    $asset = $rel.assets | Where-Object { $_.name -match '64-bit\.exe$' } | Select-Object -First 1
    $gitexe = "$env:TEMP\$($asset.name)"
    Invoke-WebRequest $asset.browser_download_url -OutFile $gitexe -UseBasicParsing
    Start-Process $gitexe -ArgumentList "/VERYSILENT","/NORESTART","/SP-" -Wait
    $env:Path += ";$env:ProgramFiles\Git\cmd"
    $hasGit = [bool](Get-Command git -ErrorAction SilentlyContinue)
  } catch { Warn "Khong cai duoc git -> OTA dung HTTP-zip (van OK)" }
}
if ($hasGit) { Ok ("git = " + (git --version)) } else { Warn "Khong co git -> OTA dung HTTP-zip" }

# ---------- 3) nssm ----------
Info "[3/6] nssm"
$nssm = "$repo\tools\nssm.exe"
if (-not (Test-Path $nssm)) {
  New-Item -ItemType Directory -Force "$repo\tools" | Out-Null
  $z = "$env:TEMP\nssm.zip"
  Invoke-WebRequest "https://nssm.cc/release/nssm-2.24.zip" -OutFile $z -UseBasicParsing
  Expand-Archive $z "$env:TEMP\nssm" -Force
  Copy-Item "$env:TEMP\nssm\nssm-2.24\win64\nssm.exe" $nssm -Force
}
if (-not (Test-Path $nssm)) { Write-Host "[LOI] Khong tai duoc nssm" -ForegroundColor Red; Read-Host "Enter de thoat"; exit 1 }
Ok "nssm = $nssm"

# ---------- 4) Cau hinh (webhook + Python 32-bit + reader) ----------
Info "[4/6] Cau hinh LOCAL"
$defWebhook = "https://n8n.svnagentic.site/webhook/e54059c6-41f1-4854-be96-1d79f8d78797?user=1"
$webhook = Read-Host "  n8n webhook URL (Enter = mac dinh)"; if (-not $webhook) { $webhook = $defWebhook }

# Do tim Python 32-bit trong cac vi tri pho bien
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
  Warn "Cai tay: https://www.python.org/downloads/windows/ -> 'Windows installer (32-bit)' -> pip install pywin32"
}
$reader = "$repo\box\oledb_reader.py"

# ---------- 5) Viet config.local.toml (mode = local) ----------
Info "[5/6] config.local.toml (mode=local)"
$cfgLocal = "$repo\config.local.toml"
$cfgBody = @"
[webhook]
url = "$webhook"

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

# ---------- Git tracking (OTA) ----------
Info "Git tracking (OTA)"
$remote = "https://github.com/ty1563/wincc-bridge.git"
if ($hasGit) {
  if (-not (Test-Path "$repo\.git")) {
    git -C $repo init -q
    git -C $repo add -A
    git -C $repo -c user.email=bridge@local -c user.name=bridge commit -qm bootstrap | Out-Null
    git -C $repo remote add origin $remote
  } else { git -C $repo remote set-url origin $remote }
  git -C $repo fetch -q origin main
  git -C $repo reset --hard -q origin/main
  Ok "git tracking origin/main"
} else { Warn "Khong co git -> OTA dung HTTP-zip" }

# ---------- 6) Dang ky NSSM service (auto-start, LocalSystem) ----------
Info "[6/6] Dang ky service $SVC (auto-start)"
$ErrorActionPreference = "Continue"
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
