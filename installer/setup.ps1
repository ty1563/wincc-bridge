# WinCC Bridge installer - chay tren MAY TRAM (cung LAN voi may WinCC).
# Cai Python/git/nssm, hoi secrets, tao SSH key, dang ky NSSM service auto-start.
# EAP=Continue: cac lenh native (ssh/scp/nssm/git/icacls) in stderr binh thuong,
# khong de chung lam crash script. Cac buoc quan trong co check Test-Path rieng.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$SVC = "WinCCBridge"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    $m" -ForegroundColor Yellow }

Info "WinCC Bridge setup | repo = $repo"

# --- Can quyen Administrator (dang ky Windows service) ---
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Host "[LOI] Can chay bang quyen Administrator." -ForegroundColor Red
  Write-Host "      Chuot phai setup.bat -> 'Run as administrator' roi chay lai." -ForegroundColor Yellow
  Read-Host "Enter de thoat"
  exit 1
}

# --- Don service cu (neu co) truoc khi cai lai ---
if (Get-Service $SVC -ErrorAction SilentlyContinue) {
  Info "Don service cu '$SVC'..."
  & sc.exe stop $SVC 2>$null | Out-Null
  Start-Sleep 2
  & sc.exe delete $SVC 2>$null | Out-Null
  Start-Sleep 2
  Ok "da go service cu"
}

# ---------- 1) Python 3.11+ (64-bit) ----------
Info "[1/8] Python"
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

# ---------- 2) git (TUY CHON - OTA co fallback HTTP-zip neu khong co git) ----------
Info "[2/8] git (tuy chon)"
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
Info "[3/8] nssm"
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

# ---------- 4) Cau hinh (co default - repo public, khong can token) ----------
Info "[4/8] Cau hinh"
$defWebhook = "https://n8n.svnagentic.site/webhook/e54059c6-41f1-4854-be96-1d79f8d78797?user=1"
$webhook = Read-Host "  n8n webhook URL (Enter = mac dinh)"; if (-not $webhook) { $webhook = $defWebhook }
$wincHost = Read-Host "  IP may WinCC (Enter = 169.254.172.61)"; if (-not $wincHost) { $wincHost = "169.254.172.61" }
$wincUser = Read-Host "  User may WinCC (Enter = dell)"; if (-not $wincUser) { $wincUser = "dell" }

# ---------- 5) SSH key + alias winccbox ----------
Info "[5/8] SSH key"
$sshDir = "$env:USERPROFILE\.ssh"; if (-not (Test-Path $sshDir)) { New-Item -ItemType Directory $sshDir | Out-Null }
$key = "$sshDir\winccbox_ed25519"
if (-not (Test-Path $key)) { & ssh-keygen -t ed25519 -f $key -N '""' -C "wincc-bridge" *> $null; Ok "Da tao key moi" } else { Ok "Dung key san co" }
# Cho SYSTEM dung key (service chay LocalSystem). Dung SID (S-1-5-18=SYSTEM, S-1-5-32-544=Administrators) -> doc lap ngon ngu may.
& icacls $key /inheritance:r /grant "*S-1-5-18:F" /grant "*S-1-5-32-544:F" /grant "$($env:USERNAME):R" 2>$null | Out-Null
& icacls $key /setowner "*S-1-5-32-544" 2>$null | Out-Null
$cfgSsh = "$sshDir\config"
if (-not (Test-Path $cfgSsh) -or -not (Select-String -Path $cfgSsh -SimpleMatch "Host winccbox" -Quiet -ErrorAction SilentlyContinue)) {
@"

Host winccbox
    HostName $wincHost
    User $wincUser
    IdentityFile $key
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
"@ | Add-Content -Path $cfgSsh -Encoding ascii
}
$pub = Get-Content "$key.pub"
Write-Host ""
Warn "==> CAP QUYEN cho key: chay khoi nay tren MAY WinCC (PowerShell Admin), roi quay lai bam Enter:"
Write-Host "-----------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "`$pub = '$pub'"
Write-Host '$ak = "$env:ProgramData\ssh\administrators_authorized_keys"'
Write-Host 'if(-not(Test-Path $ak)){New-Item -ItemType File $ak|Out-Null}'
Write-Host 'if(-not(Select-String -Path $ak -SimpleMatch $pub -Quiet -ErrorAction SilentlyContinue)){Add-Content $ak -Value $pub -Encoding ascii}'
Write-Host 'icacls $ak /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null'
Write-Host "-----------------------------------------------------------" -ForegroundColor DarkGray
Read-Host "  (Da cap quyen key tren may WinCC? Enter de tiep tuc)"
Write-Host "  Test ssh winccbox..."
$t = & ssh -o BatchMode=yes -o ConnectTimeout=10 winccbox "echo ok" 2>$null
if ($t -eq "ok") { Ok "SSH winccbox OK" } else { Warn "SSH chua vao duoc - kiem tra lai key/IP (service van se retry)." }

# ---------- 6) Viet config.local.toml ----------
Info "[6/8] config.local.toml"
$cfgLocal = "$repo\config.local.toml"
$cfgBody = @"
[webhook]
url = "$webhook"

[winccbox]
host = "$wincHost"
user = "$wincUser"
key = "$($key -replace '\\','/')"
python32 = "C:/Users/$wincUser/Python311x86/python.exe"
reader = "C:/Users/$wincUser/wincc-bridge/box/oledb_reader.py"

[intervals]
snapshot_sec = 300
ota_sec = 900

[ota]
enabled = true
repo = "https://github.com/ty1563/wincc-bridge.git"
branch = "main"
"@
# UTF-8 KHONG BOM: tomllib (config.py) khong nuot duoc BOM ma PS5.1 '-Encoding utf8' them vao.
[System.IO.File]::WriteAllText($cfgLocal, $cfgBody, (New-Object System.Text.UTF8Encoding $false))
Ok $cfgLocal

# ---------- 7) git tracking (OTA) + day reader sang box ----------
Info "[7/8] Git tracking (neu co git) + dong bo box-side"
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
} else { Warn "Khong co git -> bo qua git tracking, OTA dung HTTP-zip" }
# day reader moi sang box (best-effort, dell@IP tuong minh)
$boxDir = "C:/Users/$wincUser/wincc-bridge/box"
$boxWin = ($boxDir -replace '/', '\')
$boxScpDir = "wincc-bridge/box"
$wb = "$wincUser@$wincHost"
& ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -i $key $wb "mkdir $boxWin" 2>$null
& scp -q -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i $key "$repo\box\oledb_reader.py" "${wb}:$boxScpDir/oledb_reader.py" 2>$null
if ($LASTEXITCODE -eq 0) { Ok "da day oledb_reader.py sang box" } else { Warn "Chua day reader sang box (box chua ket noi) - service se thu khi OTA" }

# ---------- 8) Dang ky NSSM service (auto-start) ----------
Info "[8/8] Dang ky service $SVC (auto-start)"
$ErrorActionPreference = "Continue"   # nssm in stderr - dung de no lam crash script
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
# --- Tu restart khi crash/exit (gom ca OTA exit) ---
& $nssm set $SVC AppExit Default Restart 2>$null       # thoat bat ky -> restart
& $nssm set $SVC AppRestartDelay 5000 2>$null          # cho 5s roi restart
& $nssm set $SVC AppThrottle 10000 2>$null             # neu chet <10s -> coi la loi, gian restart
# --- Windows SCM recovery: neu chinh service crash -> tu restart (stop tay thi khong) ---
& sc.exe failure $SVC reset= 86400 actions= restart/5000/restart/5000/restart/60000 2>$null | Out-Null
# Service chay duoi LocalSystem - KHONG can mat khau Windows.
# Dung SSH key tuong minh (-i); key da cap quyen SYSTEM o buoc 5 nen SYSTEM ssh duoc.
& $nssm set $SVC ObjectName "LocalSystem" 2>$null | Out-Null
& $nssm start $SVC 2>$null
Start-Sleep 3
$st = (& $nssm status $SVC 2>$null)
Ok "service status: $st"
Write-Host ""
Info "Chan doan he thong (diagnose) - kiem tra + doan loi:"
try { & $py "$repo\bridge\diagnose.py" } catch { Warn "diagnose loi: $_" }
Write-Host ""
Write-Host "HOAN TAT. Log: $repo\logs\service.log | $repo\logs\diagnose.log" -ForegroundColor Green
Write-Host "Lenh huu ich: `"$nssm`" status $SVC | restart $SVC | stop $SVC" -ForegroundColor DarkGray
