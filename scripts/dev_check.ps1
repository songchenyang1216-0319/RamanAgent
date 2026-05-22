$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Python version:"
python --version

Write-Host "Checking backend import..."
python -B -c "from backend.main import app; print(app.title)"

Write-Host "Checking required artifacts..."
python -B -c "from backend.model_registry.model_registry_service import ModelRegistryService; print(ModelRegistryService().check_model_artifacts())"

Write-Host "Running tests..."
python -m pytest -q
