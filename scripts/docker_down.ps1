$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$composeFile = if ($args -contains "--dev") { "docker-compose.dev.yml" } else { "docker-compose.yml" }
docker compose -f $composeFile down
