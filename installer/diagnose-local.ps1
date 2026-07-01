# WinCC Bridge LOCAL diagnose - quet toan bo may -> COPY VAO CLIPBOARD (khong tao file).
# PS 2.0 compat (Win 7). Paste (Ctrl+V) vao chat de gui ho tro.

$ErrorActionPreference = "Continue"

# --- PS 2.0 compat: $PSScriptRoot chi co tu PS 3.0 ---
$scriptPath = $MyInvocation.MyCommand.Definition
$scriptDir  = Split-Path -Parent $scriptPath
$repo       = Split-Path -Parent $scriptDir
if (-not (Test-Path "$repo\bridge")) { $repo = "$env:USERPROFILE\wincc-bridge" }

# Gom output vao list roi copy 1 lan (khong ghi file txt).
$script:OUT = New-Object System.Collections.ArrayList
function W($m) { [void]$script:OUT.Add([string]$m) }
function Hdr($t) { W ""; W ("================= " + $t + " ================="); }
function Try-Run($block) { try { & $block } catch { W ("EXCEPTION: " + $_.ToString()) } }

Write-Host "==> Diagnose bat dau, doi ~30s..." -ForegroundColor Cyan

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
      # PS 2.0: Connection.Execute().Fields(0) loi -> dung Recordset.Open + Fields.Item(0)
      $rs = New-Object -ComObject ADODB.Recordset
      $rs.Open("SELECT name FROM sys.databases WHERE name NOT IN ('master','tempdb','model','msdb') ORDER BY create_date DESC", $c, 0, 1)
      $names = @()
      while (-not $rs.EOF) { $names += [string]$rs.Fields.Item(0).Value; $rs.MoveNext() }
      $rs.Close()
      W ("    Total DB (loai system): " + $names.Count)
      # Nhom theo suffix de nhan biet Runtime/TagLogging/AlarmLogging/Backup
      $rDbs = @($names | Where-Object { $_ -match "R$" -and $_ -notmatch "_ALG_|_TLG_" })
      $tlgF = @($names | Where-Object { $_ -match "TLG_F|_TLG_?F_" })
      $tlgS = @($names | Where-Object { $_ -match "TLG_S|_TLG_?S_" })
      $alg  = @($names | Where-Object { $_ -match "_ALG_" })
      $ccDb = @($names | Where-Object { $_ -match "^CC[_]" })
      if ($rDbs.Count) { W ("    Runtime DB (*R):   " + $rDbs.Count + " -> " + ($rDbs -join ', ')) }
      else            { W ("    Runtime DB (*R):   0  <-- THIEU") }
      if ($tlgF.Count) { W ("    TagLog Fast:       " + $tlgF.Count + " -> " + ($tlgF -join ', ')) }
      else            { W ("    TagLog Fast:       0  <-- THIEU: khong archive tag values!") }
      if ($tlgS.Count) { W ("    TagLog Slow:       " + $tlgS.Count + " -> " + ($tlgS -join ', ')) }
      else            { W ("    TagLog Slow:       0") }
      if ($ccDb.Count) { W ("    CC_ config/RT DB:  " + $ccDb.Count + " -> " + ($ccDb -join ', ')) }
      else            { W ("    CC_ config/RT DB:  0  <-- KHONG co project DB nao ten CC_*") }
      W ("    AlarmLog archive:  " + $alg.Count)
      W ("    === TAT CA " + $names.Count + " DB ===")
      $names | ForEach-Object { W ("      " + $_) }
      $c.Close()
      $ok = $true
      break
    } catch {
      $em = $_.Exception.Message
      W ("  [" + $prov + "] FAIL: " + $em.Substring(0, [Math]::Min(150, $em.Length)))
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
  } else { W "Service WinCCBridge KHONG co" }
}

Hdr "10. Bridge repo + version.txt"
if (Test-Path $repo) {
  Try-Run { W ("version.txt: " + (Get-Content "$repo\version.txt" -ErrorAction SilentlyContinue)) }
  Try-Run {
    if (Test-Path "$repo\.git") {
      Push-Location $repo
      W ("git HEAD: " + (git rev-parse --short HEAD 2>&1))
      Pop-Location
    }
  }
} else { W ("Repo khong ton tai: " + $repo) }

Hdr "11. config.local.toml"
if (Test-Path "$repo\config.local.toml") {
  W (Get-Content "$repo\config.local.toml" | Out-String).TrimEnd()
} else { W "KHONG co config.local.toml" }

Hdr "12. logs\service.log (25 dong cuoi)"
if (Test-Path "$repo\logs\service.log") {
  Try-Run { W ((Get-Content "$repo\logs\service.log" -Tail 25 | Out-String).TrimEnd()) }
} else { W "KHONG co service.log" }

# ============================================================
# 13. Test OLE-DB reader truc tiep (neu co Python 32-bit)
# ============================================================
Hdr "13. Test reader (chay oledb_reader.py truc tiep)"
if ($py32Found -and (Test-Path "$repo\box\oledb_reader.py")) {
  Try-Run {
    $env:WINCC_STATION_NAME = "diagnose-test"
    W "Chay reader (timeout 60s)..."
    $outF = "$env:TEMP\wincc-reader-out.txt"
    $errF = "$env:TEMP\wincc-reader-err.txt"
    $p = Start-Process -FilePath $py32Found -ArgumentList "`"$repo\box\oledb_reader.py`"" `
         -NoNewWindow -PassThru -RedirectStandardOutput $outF -RedirectStandardError $errF
    if (-not $p.WaitForExit(60000)) { $p.Kill(); W "READER TIMEOUT (>60s)" }
    W "--- STDOUT ---"
    if (Test-Path $outF) { W (Get-Content $outF | Out-String).TrimEnd(); Remove-Item $outF -Force -ErrorAction SilentlyContinue }
    W "--- STDERR ---"
    if (Test-Path $errF) { W (Get-Content $errF | Out-String).TrimEnd(); Remove-Item $errF -Force -ErrorAction SilentlyContinue }
  }
} else { W ("Skip - py32=" + $py32Found + ", reader exists=" + (Test-Path "$repo\box\oledb_reader.py")) }

# ============================================================
# 14. WinCC project dang mo (command line cua process)
# ============================================================
Hdr "14. WinCC project dang mo"
Try-Run {
  $found = $false
  foreach ($pname in @("WinCCExplorer.exe", "PdlRt.exe", "CCCwrun.exe", "CCAgent.exe")) {
    $procs = Get-WmiObject Win32_Process -Filter ("Name='" + $pname + "'") -ErrorAction SilentlyContinue
    foreach ($x in $procs) {
      if ($x.CommandLine) { W ($pname + ": " + $x.CommandLine); $found = $true }
    }
  }
  if (-not $found) { W "Khong lay duoc CommandLine (can Admin)" }
}
# .mcp files (project WinCC) - CHI quet cac thu muc pho bien (KHONG recurse toan o -> treo)
Try-Run {
  W ""
  W "File .mcp o cac thu muc pho bien:"
  $seen = $false
  $projRoots = @("C:\", "D:\", "C:\Projects", "D:\Projects", "C:\WinCC_Projects", "D:\WinCC_Projects",
                 "$env:PUBLIC\Documents", "$env:USERPROFILE\Documents")
  foreach ($root in $projRoots) {
    if (Test-Path $root) {
      # Chi quet 2 cap dau (root + subfolder truc tiep), KHONG recurse sau -> nhanh
      Get-ChildItem -Path $root -Filter "*.mcp" -ErrorAction SilentlyContinue |
        ForEach-Object { W ("  " + $_.FullName + "  (sua: " + $_.LastWriteTime + ")"); $seen = $true }
      Get-ChildItem -Path $root -ErrorAction SilentlyContinue | Where-Object { $_.PSIsContainer } | Select-Object -First 40 | ForEach-Object {
        Get-ChildItem -Path $_.FullName -Filter "*.mcp" -ErrorAction SilentlyContinue |
          ForEach-Object { W ("  " + $_.FullName + "  (sua: " + $_.LastWriteTime + ")"); $seen = $true }
      }
    }
  }
  if (-not $seen) { W "  (khong thay .mcp o thu muc pho bien - xem CommandLine o tren)" }
}

# ============================================================
# 15. WinCC registry - project active + version
# ============================================================
Hdr "15. WinCC registry"
foreach ($k in @(
  "HKLM:\SOFTWARE\Wow6432Node\Siemens\WinCC\Setup",
  "HKLM:\SOFTWARE\Siemens\WinCC\Setup"
)) {
  if (Test-Path $k) {
    W ("[" + $k + "]")
    Try-Run { W ((Get-ItemProperty $k | Select-Object * -ExcludeProperty PS* | Format-List | Out-String).Trim()) }
  }
}

W ""
W "=== KET THUC diagnose ==="

# ============================================================
# COPY VAO CLIPBOARD (khong tao file txt)
# ============================================================
$text = ($script:OUT -join "`r`n")
$copied = $false
# Cach 1: Set-Clipboard (PS 5.0+)
if (Get-Command Set-Clipboard -ErrorAction SilentlyContinue) {
  try { Set-Clipboard -Value $text; $copied = $true } catch {}
}
# Cach 2: clip.exe (Win 7+ luon co) - dung temp file de tranh truncate khi pipe
if (-not $copied) {
  try {
    $tmp = "$env:TEMP\wincc-diag-clip.txt"
    [System.IO.File]::WriteAllText($tmp, $text, (New-Object System.Text.UTF8Encoding $false))
    cmd /c "clip < `"$tmp`""
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    $copied = $true
  } catch {}
}

Write-Host ""
if ($copied) {
  Write-Host "==========================================================" -ForegroundColor Green
  Write-Host "  DA COPY toan bo ket qua vao CLIPBOARD!" -ForegroundColor Green
  Write-Host "  -> Paste (Ctrl+V) vao chat de gui ho tro." -ForegroundColor Green
  Write-Host "==========================================================" -ForegroundColor Green
} else {
  Write-Host "Khong copy duoc clipboard - in ra man hinh, boi den chuot roi copy:" -ForegroundColor Yellow
  Write-Host ""
  Write-Host $text
}
Write-Host ""
