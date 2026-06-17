$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$env:PYTHONDONTWRITEBYTECODE = "1"
$env:VECTOR_DB_PROVIDER = if ($env:VECTOR_DB_PROVIDER) { $env:VECTOR_DB_PROVIDER } else { "mock" }
$env:EMBEDDING_PROVIDER = if ($env:EMBEDDING_PROVIDER) { $env:EMBEDDING_PROVIDER } else { "mock" }
$env:OCR_PROVIDER = if ($env:OCR_PROVIDER) { $env:OCR_PROVIDER } else { "none" }
$env:PDF_EXPORT_PROVIDER = if ($env:PDF_EXPORT_PROVIDER) { $env:PDF_EXPORT_PROVIDER } else { "none" }
$env:LLM_PLANNER_MODE = if ($env:LLM_PLANNER_MODE) { $env:LLM_PLANNER_MODE } else { "mock" }
$env:TOOL_CALLING_MODE = if ($env:TOOL_CALLING_MODE) { $env:TOOL_CALLING_MODE } else { "json" }

python -B scripts/check_env_safety.py
python -B scripts/rag_smoke_test.py
Get-ChildItem -Path backend\api,backend\agent\planning,backend\tasks,backend\repositories,backend\tool_runtime,backend\tool_runtime\adapters,backend\mcp,backend\security,raman_core\methanol -Filter *.py | ForEach-Object {
  python -B -m py_compile $_.FullName
}
python -B -c "import backend.main; print('backend.main ok')"
python -B -c "from fastapi.testclient import TestClient; from backend.main import app; c=TestClient(app); assert c.get('/health').json()['status']=='ok'; chat=c.post('/api/agent/chat', json={'message':'你好'}); assert chat.status_code == 200; stream=c.post('/api/agent/chat/stream', json={'message':'你好'}); assert stream.status_code == 200; text=stream.text; assert 'event: start' in text and 'event: final' in text and 'event: done' in text; assert c.get('/api/raman/algorithms').status_code == 200; assert c.get('/api/raman/pipeline/templates').status_code == 200; assert c.get('/api/tools').status_code == 200; assert c.get('/api/mcp/status').status_code == 200; assert c.get('/api/agent/confirmations').status_code == 200; print('api smoke ok')"
python -B -c "from backend.agent.planning.function_calling_adapter import FunctionCallingAdapter; from backend.agent.planning.tool_catalog import ToolCatalog; from backend.mcp.mcp_registry import MCPRegistry; from backend.security.sandbox_policy import SandboxPolicy; catalog=ToolCatalog(); assert FunctionCallingAdapter.to_openai_tools(catalog); assert MCPRegistry().status()['available'] in (True, False); assert SandboxPolicy.for_uploaded_skill().allow_network is False; print('tool runtime smoke ok')"
node --check frontend/app.js
Get-ChildItem frontend/js -Filter *.js | ForEach-Object {
  node --check $_.FullName
}

Write-Host "smoke_check passed"
