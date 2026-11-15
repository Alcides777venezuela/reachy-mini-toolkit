# esperar-web.ps1 — espera a que un servicio web local responda
param([int]$Puerto = 8090, [int]$Intentos = 45)

$url = "http://127.0.0.1:$Puerto/"
Write-Host "Esperando a que el servicio responda en $url ..."

for ($i = 1; $i -le $Intentos; $i++) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) {
            Write-Host "Servicio listo." -ForegroundColor Green
            exit 0
        }
    } catch {
        # aun no responde
    }
    Start-Sleep -Seconds 2
}

Write-Host "El servicio tarda mas de lo normal." -ForegroundColor Yellow
exit 1
