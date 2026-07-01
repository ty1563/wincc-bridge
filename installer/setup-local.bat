@echo off
setlocal
title WinCC Bridge LOCAL Setup (cai truc tiep tren may WinCC + internet)
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
echo Giai nen -^> %DEST%
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%DEST%' -Force"
if errorlevel 1 ( echo [LOI] Giai nen that bai & pause & exit /b 1 )
echo Chay installer local...
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\installer\setup-local.ps1"
echo.
echo === Ket thuc setup. Bam phim de dong. ===
pause >nul
