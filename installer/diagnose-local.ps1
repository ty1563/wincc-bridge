# WinCC Bridge LOCAL diagnose - quet toan bo may -> file log tren Desktop.
# PS 2.0 compat (Win 7). KHONG can Administrator (query read-only), nhung Admin
# se thay them SQL/service info.

$ErrorActionPreference = "Continue"

# --- PS 2.0 compat: $PSScriptRoot chi co tu PS 3.0 ---
$scriptPath = $MyInvocation.MyCommand.Definition
$scriptDir  = Split-Path -Parent $scriptPath
$repo       = Split-Path -Parent $scriptDir
if (-not (Test-Path "$repo\bridge")) { $repo = "$env:USERPROFILE\wincc-bridge" }

$stamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
$log   = "$env:USERPROFILE\Desktop\wincc-diagnose-$stamp.txt"

function W($m) { Add-Content -Path $log -Value $m -Encoding ASCII }
function Hdr($t) { W ""; W ("================= " + $t + " ================="); }
function Try-Run($block) { try { & $block } catch { W ("EXCEPTION: " + $_.ToString()) } }

Write-Host "==> Diagnose bat dau, log -> $log" -ForegroundColor Cyan
"" | Set-Content -Path $log -Encoding ASCII  # clear/create

W "=== WinCC Bridge LOCAL diagnose ==="
W ("Time    : " + (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"))
W ("Host    : " + $env:COMPUTERNAME)
W ("User    : " + $env:USERNAME)
W ("PS ver  : " + $PSVersionTable.PSVersion.ToString())
W ("Repo    : " + $repo)

# ============================================================
# 1. Windows
# ============================================================
Hdr "1. Windows"
Try-Run { W ((Get-WmiObject Win32_OperatingSystem | Select-Object Caption,Version,OSArchitecture,ServicePackMajorVersion | Format-List | Out-String).Trim()) }
Try-Run { W ((Get-WmiObject Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory | Format-List | Out-String).Trim()) }

# ============================================================
# 2. WinCC processes + install
# ============================================================
Hdr "2. WinCC processes"
Try-Run {
  $procs = Get-Process | Where-Object { $_.Name -match "^(WinCCExplorer|pdlrt|CCCwrun|ccagent|CCEServer|CCEsSrv|CCFAServer|CCPMon|CCUdrConfig|CCAlgRT|CCCAP|CCTLGRT)" }
  if ($procs) {
    W ($procs | Select-Object Name,Id,@{n='WS_MB';e={[int]($_.WorkingSet64/1MB)}} | Format-Table -AutoSize | Out-String).Trim()
  } else { W "KHONG thay process WinCC nao chay -> Runtime DANG TAT" }
}

Hdr "3. WinCC install"
foreach ($p in @("C:\Program Files (x86)\Siemens\WinCC", "C:\Program Files\Siemens\WinCC", "C:\Siemens\WinCC")) {
  if (Test-Path $p) { W ("Cai tai: " + $p); try { W ("  Ver dir: " + (Get-ChildItem $p -Directory | Select-Object -First 5 | ForEach-Object { $_.Name } | Out-String).Trim()) } catch {} }
}

# ============================================================
# 4. SQL Server services + instances
# ============================================================
Hdr "4. SQL Server services"
Try-Run {
  $svcs = Get-Service | Where-Object { $_.Name -like "MSSQL*" -or $_.Name -eq "SQLBrowser" }
  W ($svcs | Format-Table Name,DisplayName,Status,StartType -AutoSize | Out-String).Trim()
}

Hdr "5. SQL instances (registry)"
foreach ($k in @("HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL",
                 "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Microsoft SQL Server\Instance Names\SQL")) {
  if (Test-Path $k) {
    W ("[" + $k + "]")
    Try-Run { W ((Get-ItemProperty $k | Select-Object * -ExcludeProperty PS* | Format-List | Out-String).Trim()) }
  }
}

# ============================================================
# 6. OLE-DB providers registered
# ============================================================
Hdr "6. OLE-DB providers"
foreach ($clsid in @(
  "HKLM:\SOFTWARE\Classes\WinCCOLEDBProvider.1",
  "HKLM:\SOFTWARE\WOW6432Node\Classes\WinCCOLEDBProvider.1",
  "HKLM:\SOFTWARE\Classes\SQLOLEDB",
  "HKLM:\SOFTWARE\WOW6432Node\Classes\SQLOLEDB",
  "HKLM:\SOFTWARE\Classes\MSOLEDBSQL",
  "HKLM:\SOFTWARE\WOW6432Node\Classes\MSOLEDBSQL"
)) {
  W ("[" + $clsid + "]: " + (Test-Path $clsid))
}

# ============================================================
# 7. Databases tren tung SQL instance (query bang ADODB - khong can sqlcmd)
# ============================================================
Hdr "7. Databases tren cac SQL instance"
$dsnList = @(".\WINCC", ".\SQLEXPRESS", "$env:COMPUTERNAME\WINCC", "$env:COMPUTERNAME\SQLEXPRESS", ".")
foreach ($dsn in $dsnList) {
  W ""
  W ("--- " + $dsn + " ---")
  $ok = $false
  foreach ($prov in @("SQLOLEDB", "MSOLEDBSQL")) {
    try {
      $c = New-Object -ComObject ADODB.Connection
      $c.ConnectionTimeout = 5
      $c.CommandTimeout = 10
      $c.ConnectionString = "Provider=$prov;Data Source=$dsn;Initial Catalog=master;Integrated Security=SSPI;TrustServerCertificate=yes"
      $c.Open()
      W ("  [" + $prov + "] Open OK")
      $rs = $c.Execute("SELECT name FROM sys.databases WHERE name NOT IN ('master','tempdb','model','msdb') ORDER BY create_date DESC")
      $names = @()
      while (-not $rs.EOF) { $names += $rs.Fields(0).Value; $rs.MoveNext() }
      W ("    Total DB (loai system): " + $names.Count)
      # Nhom theo suffix de nhan biet Runtime/TagLogging/AlarmLogging/Backup
      $rDbs = $names | Where-Object { $_ -match "_R$|R$" -and $_ -notmatch "backup" }
      $tlgF = $names | Where-Object { $_ -match "TLG_F|_TLG_?F_" }
      $tlgS = $names | Where-Object { $_ -match "TLG_S|_TLG_?S_" }
      $alg  = $names | Where-Object { $_ -match "_ALG_" }
      W ("    Runtime DB (_R):   " + ($rDbs.Count) + (if ($rDbs.Count) { " -> " + ($rDbs -join ', ') } else { "  <-- THIEU: Runtime DANG TAT!" }))
      W ("    TagLog Fast:       " + ($tlgF.Count) + (if ($tlgF.Count) { " -> " + ($tlgF[0]) } else { "  <-- THIEU: khong archive tag" }))
      W ("    TagLog Slow:       " + ($tlgS.Count) + (if ($tlgS.Count) { " -> " + ($tlgS[0]) } else { "" }))
      W ("    AlarmLog archive:  " + ($alg.Count))
      W ("    First 10 DBs:")
      $names | Select-Object -First 10 | ForEach-Object { W ("      " + $_) }
      $c.Close()
      $ok = $true
      break
    } catch {
      W ("  [" + $prov + "] FAIL: " + $_.Exception.Message.Substring(0, [Math]::Min(150, $_.Exception.Message.Length)))
    }
  }
  if (-not $ok) { W "  -> Instance KHONG toi duoc voi ca 2 provider" }
}

# ============================================================
# 8. Python 32-bit + pywin32
# ============================================================
Hdr "8. Python 32-bit + pywin32"
$py32Cands = @(
  "C:\Python37x86\python.exe",
  "C:\Python311x86\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python37-32\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python311-32\python.exe",
  "$env:USERPROFILE\AppData\Local\Programs\Python\Python37-32\python.exe"
)
$py32Found = $null
foreach ($p in $py32Cands) { if (Test-Path $p) { $py32Found = $p; W ("Found: " + $p); break } }
if ($py32Found) {
  Try-Run { W ("Version: " + (& $py32Found --version 2>&1)) }
  Try-Run { W ("Bits: " + (& $py32Found -c "import struct; print(struct.calcsize('P')*8)")) }
  Try-Run { W ("pywin32: " + (& $py32Found -c "import win32com.client; print('OK')" 2>&1)) }
} else {
  W "KHONG thay Python 32-bit tai cac vi tri thong dung"
}

# ============================================================
# 9. Bridge service + config + version + log
# ============================================================
Hdr "9. WinCCBridge service"
Try-Run {
  $svc = Get-Service WinCCBridge -ErrorAction SilentlyContinue
  if ($svc) {
    W ($svc | Format-List Name,Status,StartType,DisplayName | Out-String).Trim()
    Try-Run { W ("Config: " + (sc.exe qc WinCCBridge | Out-String).Trim()) }
  } else { W "Service WinCCBridge KHONG co" }
}

Hdr "10. Bridge repo + version.txt"
if (Test-Path $repo) {
  Try-Run { W ("version.txt: " + (Get-Content "$repo\version.txt" -ErrorAction SilentlyContinue)) }
  Try-Run {
    if (Test-Path "$repo\.git") {
      Push-Location $repo
      W ("git HEAD: " + (git rev-parse --short HEAD 2>&1))
      W ("git log -3:")
      W ((git log --oneline -3 2>&1 | Out-String).Trim())
      Pop-Location
    }
  }
} else { W ("Repo khong ton tai: " + $repo) }

Hdr "11. config.local.toml"
if (Test-Path "$repo\config.local.toml") {
  W (Get-Content "$repo\config.local.toml" | Out-String).TrimEnd()
} else { W "KHONG co config.local.toml" }

Hdr "12. logs\service.log (30 dong cuoi)"
if (Test-Path "$repo\logs\service.log") {
  Try-Run { W ((Get-Content "$repo\logs\service.log" -Tail 30 | Out-String).TrimEnd()) }
} else { W "KHONG co service.log" }

# ============================================================
# 13. Test OLE-DB reader truc tiep (neu co Python 32-bit)
# ============================================================
Hdr "13. Test reader (chay oledb_reader.py truc tiep)"
if ($py32Found -and (Test-Path "$repo\box\oledb_reader.py")) {
  Try-Run {
    $env:WINCC_STATION_NAME = "diagnose-test"
    W "Chay reader (timeout 60s)..."
    $p = Start-Process -FilePath $py32Found -ArgumentList "`"$repo\box\oledb_reader.py`"" `
         -NoNewWindow -PassThru -RedirectStandardOutput "$env:TEMP\reader-out.txt" `
         -RedirectStandardError "$env:TEMP\reader-err.txt"
    if (-not $p.WaitForExit(60000)) { $p.Kill(); W "READER TIMEOUT (>60s)" }
    W "--- STDOUT ---"
    if (Test-Path "$env:TEMP\reader-out.txt") { W (Get-Content "$env:TEMP\reader-out.txt" | Out-String).TrimEnd() }
    W "--- STDERR ---"
    if (Test-Path "$env:TEMP\reader-err.txt") { W (Get-Content "$env:TEMP\reader-err.txt" | Out-String).TrimEnd() }
  }
} else { W ("Skip - py32=" + $py32Found + ", reader exists=" + (Test-Path "$repo\box\oledb_reader.py")) }

# ============================================================
# Footer + open
# ============================================================
W ""
W "=== KET THUC diagnose ==="
Write-Host ""
Write-Host "==> Log da luu: $log" -ForegroundColor Green
Write-Host "==> Gui file nay cho ho tro de phan tich." -ForegroundColor Yellow
Write-Host ""
Start-Process notepad.exe $log
