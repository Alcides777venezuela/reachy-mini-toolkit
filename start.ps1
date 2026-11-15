# start.ps1 — Arranca los servicios locales del proyecto (idempotente)
# Uso:  .\start.ps1        (o clic derecho → Ejecutar con PowerShell)
#
#   Consola web  → http://127.0.0.1:8090
#   MCP bridge   → http://127.0.0.1:8091
#
# El Space de Hugging Face NO necesita esto: vive en la nube.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Test-Port([int]$port) {
    $r = netstat -ano | Select-String ":$port\s+.*LISTENING"
    return ($null -ne $r)
}

if (-not (Test-Port 8090)) {
    Write-Host "Arrancando consola web…"
    Start-Process -FilePath "python" -ArgumentList "server.py" -WorkingDirectory $root -WindowStyle Hidden
    Start-Sleep -Seconds 3
} else {
    Write-Host "Consola ya estaba arriba."
}

if (-not (Test-Port 8091)) {
    Write-Host "Arrancando puente MCP…"
    Start-Process -FilePath "python" -ArgumentList "mcp\mcp_http.py" -WorkingDirectory $root -WindowStyle Hidden
    Start-Sleep -Seconds 2
} else {
    Write-Host "Puente MCP ya estaba arriba."
}

Write-Host ""
Write-Host "Consola:    http://127.0.0.1:8090"
Write-Host "MCP local:  http://127.0.0.1:8091/gradio_api/mcp/schema"
Write-Host "MCP online: https://alcides777-reachy-mcp-tool.hf.space/gradio_api/mcp/schema"
