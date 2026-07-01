@echo off
setlocal
title WinCC Bridge - Diagnose Local (Win 7/8/10/11)
echo =================================================================
echo    WinCC Bridge - Diagnose LOCAL
echo    (quet toan bo may - SQL / WinCC / Python / Bridge -^> 1 file)
echo =================================================================
set "SCRIPT=%~dp0diagnose-local.ps1"
if not exist "%SCRIPT%" (
  echo [LOI] Khong thay %SCRIPT%
  echo Dat diagnose-local.bat canh file diagnose-local.ps1 roi chay lai.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
pause
