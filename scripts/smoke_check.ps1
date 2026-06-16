$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$env:PYTHONDONTWRITEBYTECODE = "1"
$env:VECTOR_DB_PROVIDER = if ($env:VECTOR_DB_PROVIDER) { $env:VECTOR_DB_PROVIDER } else { "mock" }
$env:EMBEDDING_PROVIDER = if ($env:EMBEDDING_PROVIDER) { $env:EMBEDDING_PROVIDER } else { "mock" }
$env:OCR_PROVIDER = if ($env:OCR_PROVIDER) { $env:OCR_PROVIDER } else { "none" }
$env:PDF_EXPORT_PROVIDER = if ($env:PDF_EXPORT_PROVIDER) { $env:PDF_EXPORT_PROVIDER } else { "none" }

python -B scripts/check_env_safety.py
python -B scripts/rag_smoke_test.py
python -B -c "import backend.main; print('backend.main ok')"
python -B -c "from fastapi.testclient import TestClient; from backend.main import app; c=TestClient(app); r=c.post('/api/agent/chat/stream', json={'message':'你好'}); assert r.status_code == 200; text=r.text; assert 'event: start' in text and 'event: final' in text and 'event: done' in text; print('agent stream ok')"
node --check frontend/app.js
Get-ChildItem frontend/js -Filter *.js | ForEach-Object {
  node --check $_.FullName
}

Write-Host "smoke_check passed"
