@echo off
setlocal
title WinCC Bridge Setup
echo ============================================
echo    WinCC Bridge - Setup
echo ============================================
set "DEST=%USERPROFILE%\wincc-bridge"
set "ZIP=%~dp0wincc-bridge.zip"
if not exist "%ZIP%" (
  echo [LOI] Khong thay "%ZIP%"
  echo Dat setup.bat canh file wincc-bridge.zip roi chay lai.
  pause
  exit /b 1
)
echo Giai nen -^> %DEST%
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%DEST%' -Force"
if errorlevel 1 ( echo [LOI] Giai nen that bai & pause & exit /b 1 )
echo Chay installer...
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\installer\setup.ps1"
echo.
echo === Ket thuc setup. Bam phim de dong. ===
pause >nul
