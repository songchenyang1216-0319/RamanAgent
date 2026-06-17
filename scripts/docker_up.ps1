$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$composeFile = if ($args -contains "--dev") { "docker-compose.dev.yml" } else { "docker-compose.yml" }
docker compose -f $composeFile up -d --build
Write-Host "RamanAgent is starting at http://127.0.0.1:8000/app"
