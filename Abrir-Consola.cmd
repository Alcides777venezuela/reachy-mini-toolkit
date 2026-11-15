@echo off
title Reachy Console - Iniciando
echo ============================================
echo   Reachy Console (voz + vision + 22 tools)
echo ============================================
echo.

rem 1) Arranca consola (:8090) y puente MCP (:8091) si no estan
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"

rem 2) Espera a que la consola responda
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0esperar-web.ps1" -Puerto 8090

rem 3) Abre el navegador
start "" "http://127.0.0.1:8090"

echo.
echo Esta ventana se cerrara en 4 segundos (la consola sigue en segundo plano).
ping -n 5 127.0.0.1 >nul
exit
