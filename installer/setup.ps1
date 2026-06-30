# WinCC Bridge installer - chay tren MAY TRAM (cung LAN voi may WinCC).
# Cai Python/git/nssm, hoi secrets, tao SSH key, dang ky NSSM service auto-start.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$SVC = "WinCCBridge"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    $m" -ForegroundColor Yellow }

Info "WinCC Bridge setup | repo = $repo"

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
Ok ("python = " + $py + " (" + (& $py --version) + ")")

# ---------- 2) git ----------
Info "[2/8] git"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Warn "Cai Git for Windows..."
  $rel = Invoke-RestMethod "https://api.github.com/repos/git-for-windows/git/releases/latest" -UseBasicParsing
  $asset = $rel.assets | Where-Object { $_.name -match '64-bit\.exe$' } | Select-Object -First 1
  $gitexe = "$env:TEMP\$($asset.name)"
  Invoke-WebRequest $asset.browser_download_url -OutFile $gitexe -UseBasicParsing
  Start-Process $gitexe -ArgumentList "/VERYSILENT","/NORESTART","/SP-" -Wait
  $env:Path += ";$env:ProgramFiles\Git\cmd"
}
Ok ("git = " + (git --version))

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
Ok "nssm = $nssm"

# ---------- 4) Hoi secrets ----------
Info "[4/8] Cau hinh (nhap thong tin)"
$webhook = Read-Host "  n8n webhook URL"
$ghtoken = Read-Host "  GitHub read-only token (PAT, de OTA git pull private repo)"
$wincHost = Read-Host "  IP may WinCC (Enter = 169.254.172.61)"; if (-not $wincHost) { $wincHost = "169.254.172.61" }
$wincUser = Read-Host "  User may WinCC (Enter = dell)"; if (-not $wincUser) { $wincUser = "dell" }

# ---------- 5) SSH key + alias winccbox ----------
Info "[5/8] SSH key"
$sshDir = "$env:USERPROFILE\.ssh"; if (-not (Test-Path $sshDir)) { New-Item -ItemType Directory $sshDir | Out-Null }
$key = "$sshDir\winccbox_ed25519"
if (-not (Test-Path $key)) { & ssh-keygen -t ed25519 -f $key -N '""' -C "wincc-bridge" *> $null; Ok "Da tao key moi" } else { Ok "Dung key san co" }
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
@"
[webhook]
url = "$webhook"

[winccbox]
target = "winccbox"
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
"@ | Set-Content -Path $cfgLocal -Encoding utf8
Ok $cfgLocal

# ---------- 7) git tracking (OTA) + day reader sang box ----------
Info "[7/8] Git tracking + dong bo box-side"
$remote = "https://$ghtoken@github.com/ty1563/wincc-bridge.git"
if (-not (Test-Path "$repo\.git")) {
  git -C $repo init -q
  git -C $repo add -A
  git -C $repo -c user.email=bridge@local -c user.name=bridge commit -qm bootstrap | Out-Null
  git -C $repo remote add origin $remote
} else { git -C $repo remote set-url origin $remote }
git -C $repo fetch -q origin main
git -C $repo reset --hard -q origin/main
Ok "repo dong bo origin/main"
# day reader moi sang box (neu ssh thong)
$boxDir = "C:/Users/$wincUser/wincc-bridge/box"
& ssh -o BatchMode=yes -o ConnectTimeout=10 winccbox "powershell -NoProfile -Command \"New-Item -ItemType Directory -Force '$boxDir' | Out-Null\"" 2>$null | Out-Null
& scp -q -o BatchMode=yes "$repo\box\oledb_reader.py" "winccbox:$boxDir/oledb_reader.py" 2>$null
Ok "da day oledb_reader.py sang box"

# ---------- 8) Dang ky NSSM service (auto-start) ----------
Info "[8/8] Dang ky service $SVC (auto-start)"
& $nssm stop $SVC 2>$null | Out-Null
& $nssm remove $SVC confirm 2>$null | Out-Null
& $nssm install $SVC $py "$repo\bridge\service.py"
& $nssm set $SVC AppDirectory $repo
& $nssm set $SVC Start SERVICE_AUTO_START
& $nssm set $SVC AppStdout "$repo\logs\service.log"
& $nssm set $SVC AppStderr "$repo\logs\service.log"
& $nssm set $SVC AppRotateFiles 1
& $nssm set $SVC AppRotateBytes 5242880
New-Item -ItemType Directory -Force "$repo\logs" | Out-Null
# Chay service duoi tai khoan user hien tai de truy cap ~/.ssh + git
Write-Host ""
Warn "Service can chay duoi tai khoan cua ban (de dung SSH key + git)."
$pwd = Read-Host "  Nhap mat khau Windows cua ban (de service auto-start khi chua dang nhap)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwd)
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
if ($plain) { & $nssm set $SVC ObjectName ".\$env:USERNAME" $plain | Out-Null }
& $nssm start $SVC
Start-Sleep 3
$st = (& $nssm status $SVC)
Ok "service status: $st"
Write-Host ""
Write-Host "HOAN TAT. Log: $repo\logs\service.log" -ForegroundColor Green
Write-Host "Lenh huu ich: `"$nssm`" status $SVC | restart $SVC | stop $SVC" -ForegroundColor DarkGray
