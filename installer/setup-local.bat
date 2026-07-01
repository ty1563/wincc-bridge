@echo off
setlocal
title WinCC Bridge LOCAL Setup (Win 7/8/10/11)
echo ==================================================================
echo    WinCC Bridge LOCAL - Setup
echo    (may nay chay WinCC + co internet: KHONG can SSH remote)
echo ==================================================================
set "DEST=%USERPROFILE%\wincc-bridge"
set "ZIP=%~dp0wincc-bridge-local.zip"
if not exist "%ZIP%" (
  echo [LOI] Khong thay "%ZIP%"
  echo Dat setup-local.bat canh file wincc-bridge-local.zip roi chay lai.
  pause
  exit /b 1
)

REM Don thu muc cu (neu co) - lan cai dau tren may WinCC an toan
if exist "%DEST%" (
  echo Don cai cu: %DEST%
  rmdir /s /q "%DEST%" 2>nul
)
mkdir "%DEST%"

REM ============================================================
REM Unzip bang VBScript Shell.Application - KHONG can PowerShell 5.0
REM (Win 7 mac dinh PS 2.0 khong co Expand-Archive)
REM ============================================================
set "VBS=%TEMP%\wincc_unzip.vbs"
if exist "%VBS%" del "%VBS%"
>>"%VBS%"  echo Set fso = CreateObject("Scripting.FileSystemObject")
>>"%VBS%"  echo zip = fso.GetAbsolutePathName(WScript.Arguments(0))
>>"%VBS%"  echo dst = fso.GetAbsolutePathName(WScript.Arguments(1))
>>"%VBS%"  echo If Not fso.FolderExists(dst) Then fso.CreateFolder(dst)
>>"%VBS%"  echo Set sh = CreateObject("Shell.Application")
>>"%VBS%"  echo Set src = sh.NameSpace(zip)
>>"%VBS%"  echo Set trg = sh.NameSpace(dst)
>>"%VBS%"  echo trg.CopyHere src.Items, 20
>>"%VBS%"  echo Do While trg.Items.Count ^< src.Items.Count
>>"%VBS%"  echo   WScript.Sleep 300
>>"%VBS%"  echo Loop
>>"%VBS%"  echo WScript.Sleep 500
echo Giai nen -^> %DEST%
cscript //nologo "%VBS%" "%ZIP%" "%DEST%"
del "%VBS%" 2>nul

if not exist "%DEST%\installer\setup-local.ps1" (
  echo [LOI] Giai nen that bai - khong tim thay installer\setup-local.ps1
  pause
  exit /b 1
)

echo Chay installer local...
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\installer\setup-local.ps1"
echo.
echo === Ket thuc setup. Bam phim de dong. ===
pause >nul
