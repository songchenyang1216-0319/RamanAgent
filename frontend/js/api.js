const API_BASE_URL =
  window.location.port === "5173" ? "http://127.0.0.1:8000" : window.location.origin;
const AUTH_TOKEN_KEY = "ramanagent.authToken";

export function getAuthToken() {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setAuthToken(token) {
  try {
    if (token) {
      localStorage.setItem(AUTH_TOKEN_KEY, token);
    } else {
      localStorage.removeItem(AUTH_TOKEN_KEY);
    }
  } catch {
    // ignore
  }
}

export function clearAuthToken() {
  setAuthToken("");
}

function buildUrl(path, params = {}) {
  const url = new URL(path, API_BASE_URL);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  return url.toString();
}

async function requestJson(path, options = {}) {
  const timeoutMs = Number(options.timeoutMs || 60000);
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };
    const token = getAuthToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    const response = await fetch(buildUrl(path, options.params), {
      method: options.method || "GET",
      headers: Object.keys(headers).length ? headers : undefined,
      body: options.body instanceof FormData ? options.body : options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });
    clearTimeout(timer);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail || {};
      const detailPayload = typeof detail === "object" && detail !== null ? detail : { error_message: detail };
      return {
        success: false,
        error_code: detailPayload.error_code || data.error_code || `HTTP_${response.status}`,
        message: detailPayload.message || data.message || "请求失败",
        error_message: detailPayload.error_message || data.error_message || `请求失败: ${response.status}`,
        suggestion: detailPayload.suggestion || data.suggestion || "",
        status: response.status,
        data,
      };
    }
    if (Array.isArray(data)) {
      return { success: true, items: data, data, status: response.status };
    }
    return { success: true, ...data, status: response.status };
  } catch (error) {
    clearTimeout(timer);
    return {
      success: false,
      error_code: error.name === "AbortError" ? "REQUEST_TIMEOUT" : "NETWORK_ERROR",
      message: error.name === "AbortError" ? "请求超时" : "请求失败",
      error_message:
        error.name === "AbortError"
          ? `请求超时（${timeoutMs}ms），后端可能仍在处理。`
          : error.message || "请求失败，请确认后端服务是否已经启动。",
      suggestion:
        error.name === "AbortError"
          ? "可以稍后查看最近记录或刷新工作区；如果经常超时，请检查后端日志和模型接口响应时间。"
          : "请确认后端服务已启动，并检查浏览器控制台或网络连接。",
      status: 0,
    };
  }
}

export async function downloadBinary(path, { params = {}, fallbackName = "download.bin", timeoutMs = 30000 } = {}) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = {};
    const token = getAuthToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    const response = await fetch(buildUrl(path, params), {
      method: "GET",
      headers,
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const detail = data.detail || {};
      const detailPayload = typeof detail === "object" && detail !== null ? detail : { error_message: detail };
      return {
        success: false,
        error_code: detailPayload.error_code || data.error_code || `HTTP_${response.status}`,
        message: detailPayload.message || data.message || "下载失败",
        error_message: detailPayload.error_message || data.error_message || `下载失败: ${response.status}`,
        suggestion: detailPayload.suggestion || data.suggestion || "",
        status: response.status,
      };
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const matched = disposition.match(/filename\*?=(?:UTF-8''|")?([^\";]+)/i);
    const filename = decodeURIComponent((matched?.[1] || fallbackName).replace(/"/g, ""));
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename || fallbackName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.URL.revokeObjectURL(url);
    return { success: true, filename };
  } catch (error) {
    clearTimeout(timer);
    return {
      success: false,
      error_code: error.name === "AbortError" ? "REQUEST_TIMEOUT" : "NETWORK_ERROR",
      message: error.name === "AbortError" ? "下载超时" : "下载失败",
      error_message: error.name === "AbortError" ? `下载超时（${timeoutMs}ms）。` : error.message || "下载失败",
      status: 0,
    };
  }
}

export async function sendAgentChat({
  message = "",
  sessionId = null,
  userId = "default_user",
  debug = false,
  file = null,
  files = [],
  fileIds = [],
  knowledgeBaseIds = [],
  ragScope = "",
  metadata = {},
}) {
  const selectedFiles = Array.isArray(files) && files.length ? files : (file ? [file] : []);
  const timeoutMs = Number(metadata.timeoutMs || (selectedFiles.length ? 120000 : 60000));
  if (selectedFiles.length) {
    const formData = new FormData();
    formData.append("message", message || "请分析这个文件");
    formData.append("user_id", userId || "default_user");
    formData.append("debug", String(Boolean(debug)));
    if (selectedFiles.length === 1) {
      formData.append("file", selectedFiles[0]);
    } else {
      selectedFiles.forEach((item) => formData.append("files", item));
    }
    (fileIds || []).forEach((item) => formData.append("file_ids", item));
    (knowledgeBaseIds || []).forEach((item) => formData.append("knowledge_base_ids", item));
    if (ragScope) {
      formData.append("rag_scope", ragScope);
    }
    if (sessionId) {
      formData.append("session_id", sessionId);
      formData.append("conversation_id", sessionId);
    }
    if (metadata.providerId) {
      formData.append("provider_id", metadata.providerId);
    }
    if (metadata.modelId) {
      formData.append("model_id", metadata.modelId);
    }
    ["sample_name", "sample_type", "operator", "instrument", "laser_power", "integration_time", "remarks", "remark"].forEach(
      (field) => {
        if (metadata[field]) {
          formData.append(field, metadata[field]);
        }
      }
    );
    return requestJson("/api/agent/chat", {
      method: "POST",
      body: formData,
      timeoutMs,
    });
  }

  return requestJson("/api/agent/chat", {
    method: "POST",
    body: {
      message,
      user_id: userId || "default_user",
      provider_id: metadata.providerId || undefined,
      model_id: metadata.modelId || undefined,
      file_ids: fileIds || undefined,
      knowledge_base_ids: knowledgeBaseIds || undefined,
      rag_scope: ragScope || undefined,
      debug,
      session_id: sessionId || undefined,
      conversation_id: sessionId || undefined,
    },
    timeoutMs,
  });
}

export async function analyzeFile(file, metadata = {}, sessionId = null) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("message", metadata.message || "请分析这个文件");
  if (sessionId) {
    formData.append("session_id", sessionId);
    formData.append("conversation_id", sessionId);
  }
  ["sample_name", "sample_type", "operator", "instrument", "laser_power", "integration_time", "remarks"].forEach(
    (field) => {
      if (metadata[field]) {
        formData.append(field, metadata[field]);
      }
    }
  );
  return requestJson("/api/agent/analyze-file", {
    method: "POST",
    body: formData,
    timeoutMs: 120000,
  });
}

export async function getCurrentRamanModel() {
  return requestJson("/api/raman-models/current");
}

export async function checkCurrentModel(modelVersion) {
  const version = modelVersion || "methanol_v1";
  return requestJson(`/api/raman-models/${encodeURIComponent(version)}/check`);
}

export async function getModelProviders() {
  return requestJson("/api/models/providers", { timeoutMs: 8000 });
}

export async function getProviderModels(providerId, conversationId = null, userId = "default_user") {
  return requestJson(`/api/models/providers/${encodeURIComponent(providerId)}/models`, {
    params: {
      conversation_id: conversationId || undefined,
      user_id: userId || "default_user",
    },
    timeoutMs: 8000,
  });
}

export async function getCurrentLlmModel(conversationId = null, userId = "default_user") {
  return requestJson("/api/models/current", {
    params: {
      conversation_id: conversationId || undefined,
      user_id: userId || "default_user",
    },
    timeoutMs: 8000,
  });
}

export async function switchLlmModel(provider, model, conversationId = null, userId = "default_user") {
  return requestJson("/api/models/select", {
    method: "POST",
    body: {
      provider_id: provider,
      model_id: model,
      conversation_id: conversationId || undefined,
      user_id: userId || "default_user",
    },
    timeoutMs: 12000,
  });
}

export async function refreshLlmModels() {
  return requestJson("/api/models/refresh", {
    method: "POST",
    timeoutMs: 12000,
  });
}

export async function getAgentModels() {
  return getModelProviders();
}

export async function switchAgentModel(modelNameOrProvider, maybeModel) {
  if (maybeModel) {
    return switchLlmModel(modelNameOrProvider, maybeModel);
  }
  return requestJson("/api/agent/models/current", {
    method: "PATCH",
    body: { model_name: modelNameOrProvider },
    timeoutMs: 12000,
  });
}

export async function createAgentSession() {
  return requestJson("/api/agent/session/new", {
    method: "POST",
    timeoutMs: 8000,
  });
}

export async function getConversations({ userId = "default_user", query = "", limit = 80 } = {}) {
  return requestJson("/api/conversations", {
    params: {
      user_id: userId,
      q: query || undefined,
      limit,
    },
    timeoutMs: 8000,
  });
}

export async function createConversation({ userId = "default_user", title = "" } = {}) {
  return requestJson("/api/conversations", {
    method: "POST",
    body: {
      user_id: userId,
      title: title || undefined,
    },
    timeoutMs: 8000,
  });
}

export async function getConversation(conversationId, userId = "default_user") {
  if (!conversationId) {
    return { success: false, error_message: "conversationId 不能为空。" };
  }
  return requestJson(`/api/conversations/${encodeURIComponent(conversationId)}`, {
    params: { user_id: userId },
    timeoutMs: 8000,
  });
}

export async function renameConversation(conversationId, title) {
  if (!conversationId) {
    return { success: false, error_message: "conversationId 不能为空。" };
  }
  return requestJson(`/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "PATCH",
    body: { title },
    timeoutMs: 8000,
  });
}

export async function deleteConversation(conversationId) {
  if (!conversationId) {
    return { success: false, error_message: "conversationId 不能为空。" };
  }
  return requestJson(`/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
    timeoutMs: 8000,
  });
}

export async function getAgentSession(sessionId) {
  if (!sessionId) {
    return { success: false, error_message: "sessionId 不能为空。" };
  }
  return requestJson(`/api/agent/session/${encodeURIComponent(sessionId)}`, {
    timeoutMs: 8000,
  });
}

export async function clearAgentSession(sessionId) {
  if (!sessionId) {
    return { success: false, error_message: "sessionId 不能为空。" };
  }
  return requestJson(`/api/agent/session/${encodeURIComponent(sessionId)}/clear`, {
    method: "POST",
    timeoutMs: 8000,
  });
}

export async function getWorkspaceFiles(conversationId, userId = "default_user") {
  if (!conversationId) {
    return { success: false, error_message: "conversationId 不能为空。" };
  }
  return requestJson(`/api/workspaces/${encodeURIComponent(conversationId)}/files`, {
    params: { user_id: userId },
    timeoutMs: 8000,
  });
}

export async function getFiles({ userId = "default_user", workspaceId = "", projectId = "" } = {}) {
  return requestJson("/api/files", {
    params: {
      user_id: userId,
      workspace_id: workspaceId || undefined,
      project_id: projectId || undefined,
    },
    timeoutMs: 8000,
  });
}

export async function uploadWorkspaceFile(file, { userId = "default_user", conversationId = "", projectId = "" } = {}) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("user_id", userId || "default_user");
  if (conversationId) {
    formData.append("conversation_id", conversationId);
  }
  if (projectId) {
    formData.append("project_id", projectId);
  }
  return requestJson("/api/files/upload", {
    method: "POST",
    body: formData,
    timeoutMs: 30000,
  });
}

export async function convertFile({ fileId, targetFormat, conversationId, userId = "default_user" }) {
  return requestJson("/api/files/convert", {
    method: "POST",
    body: {
      file_id: fileId,
      target_format: targetFormat,
      conversation_id: conversationId,
      user_id: userId,
    },
    timeoutMs: 60000,
  });
}

export async function queryRag(payload) {
  return requestJson("/api/rag/query", {
    method: "POST",
    body: payload,
    timeoutMs: 90000,
  });
}

export async function getRagStatus({ conversationId = "", userId = "default_user" } = {}) {
  return requestJson("/api/rag/status", {
    params: { conversation_id: conversationId || undefined, user_id: userId },
    timeoutMs: 8000,
  });
}

export async function getRagHealth({ conversationId = "", userId = "default_user" } = {}) {
  return requestJson("/api/rag/health", {
    params: { conversation_id: conversationId || undefined, user_id: userId },
    timeoutMs: 8000,
  });
}

export async function rebuildAllRagIndexes({ userId = "default_user" } = {}) {
  return requestJson("/api/rag/rebuild-all", {
    method: "POST",
    body: { user_id: userId },
    timeoutMs: 120000,
  });
}

export async function listKnowledgeBases({ userId = "default_user", includeDisabled = true } = {}) {
  return requestJson("/api/knowledge-bases", {
    params: { user_id: userId, include_disabled: includeDisabled },
    timeoutMs: 8000,
  });
}

export async function createKnowledgeBase(payload) {
  return requestJson("/api/knowledge-bases", {
    method: "POST",
    body: payload,
    timeoutMs: 12000,
  });
}

export async function updateKnowledgeBase(knowledgeBaseId, payload) {
  return requestJson(`/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}`, {
    method: "PATCH",
    body: payload,
    timeoutMs: 12000,
  });
}

export async function deleteKnowledgeBase(knowledgeBaseId, userId = "default_user") {
  return requestJson(`/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}`, {
    method: "DELETE",
    params: { user_id: userId },
    timeoutMs: 12000,
  });
}

export async function setKnowledgeBaseEnabled(knowledgeBaseId, enabled, userId = "default_user") {
  return updateKnowledgeBase(knowledgeBaseId, { enabled: Boolean(enabled), user_id: userId });
}

export async function uploadKnowledgeBaseFile(knowledgeBaseId, file, userId = "default_user") {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("user_id", userId);
  return requestJson(`/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/files`, {
    method: "POST",
    body: formData,
    timeoutMs: 120000,
  });
}

export async function listKnowledgeBaseFiles(knowledgeBaseId, userId = "default_user") {
  return requestJson(`/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/files`, {
    params: { user_id: userId },
    timeoutMs: 8000,
  });
}

export async function deleteKnowledgeBaseFile(knowledgeBaseId, kbFileId, userId = "default_user") {
  return requestJson(`/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/files/${encodeURIComponent(kbFileId)}`, {
    method: "DELETE",
    params: { user_id: userId },
    timeoutMs: 12000,
  });
}

export async function rebuildKnowledgeBaseIndex(knowledgeBaseId, userId = "default_user") {
  return requestJson(`/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/rebuild-index`, {
    method: "POST",
    params: { user_id: userId },
    timeoutMs: 120000,
  });
}

export async function getKnowledgeBaseIndexStatus(knowledgeBaseId, userId = "default_user") {
  return requestJson(`/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/index-status`, {
    params: { user_id: userId },
    timeoutMs: 8000,
  });
}

export async function searchKnowledgeBase(knowledgeBaseId, query, { userId = "default_user", topK = 6 } = {}) {
  return requestJson(`/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/search`, {
    method: "POST",
    body: { query, user_id: userId, top_k: topK },
    timeoutMs: 60000,
  });
}

export async function bindConversationKnowledgeBase(conversationId, knowledgeBaseId, { userId = "default_user", enabled = true } = {}) {
  return requestJson(`/api/conversations/${encodeURIComponent(conversationId)}/knowledge-bases`, {
    method: "POST",
    body: { knowledge_base_id: knowledgeBaseId, enabled, user_id: userId },
    timeoutMs: 12000,
  });
}

export async function listConversationKnowledgeBases(conversationId, userId = "default_user") {
  return requestJson(`/api/conversations/${encodeURIComponent(conversationId)}/knowledge-bases`, {
    params: { user_id: userId },
    timeoutMs: 8000,
  });
}

export async function unbindConversationKnowledgeBase(conversationId, knowledgeBaseId, userId = "default_user") {
  return requestJson(`/api/conversations/${encodeURIComponent(conversationId)}/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}`, {
    method: "DELETE",
    params: { user_id: userId },
    timeoutMs: 12000,
  });
}

export async function deleteFile(fileId) {
  if (!fileId) {
    return { success: false, error_message: "fileId 不能为空。" };
  }
  return requestJson(`/api/files/${encodeURIComponent(fileId)}`, {
    method: "DELETE",
    timeoutMs: 8000,
  });
}

export async function downloadFileById(fileId) {
  if (!fileId) {
    return { success: false, error_message: "fileId 不能为空。" };
  }
  return downloadBinary(`/api/files/${encodeURIComponent(fileId)}/download`, {
    fallbackName: "file.bin",
  });
}

export async function previewFile(fileId) {
  if (!fileId) {
    return { success: false, error_message: "fileId 不能为空。" };
  }
  return requestJson(`/api/files/${encodeURIComponent(fileId)}/preview`, {
    timeoutMs: 8000,
  });
}

export async function activateFile(fileId, conversationId, userId = "default_user") {
  if (!fileId || !conversationId) {
    return { success: false, error_message: "fileId 和 conversationId 不能为空。" };
  }
  const formData = new FormData();
  formData.append("conversation_id", conversationId);
  formData.append("user_id", userId);
  return requestJson(`/api/files/${encodeURIComponent(fileId)}/activate`, {
    method: "POST",
    body: formData,
    timeoutMs: 8000,
  });
}

export async function runFileOcr(fileId, { conversationId = "", userId = "default_user", pageRange = "" } = {}) {
  return requestJson(`/api/files/${encodeURIComponent(fileId)}/ocr`, {
    method: "POST",
    body: {
      conversation_id: conversationId,
      user_id: userId,
      page_range: pageRange || undefined,
    },
    timeoutMs: 120000,
  });
}

export async function getWorkspaceContext(conversationId, userId = "default_user") {
  if (!conversationId) {
    return { success: false, error_message: "conversationId 不能为空。" };
  }
  return requestJson(`/api/workspaces/${encodeURIComponent(conversationId)}/context`, {
    params: { user_id: userId },
    timeoutMs: 8000,
  });
}

export async function getConversationTasks(conversationId, userId = "default_user") {
  if (!conversationId) {
    return { success: false, error_message: "conversationId 不能为空。" };
  }
  return requestJson(`/api/conversations/${encodeURIComponent(conversationId)}/tasks`, {
    params: { user_id: userId },
    timeoutMs: 8000,
  });
}

export async function getTaskTrace(taskId) {
  if (!taskId) {
    return { success: false, error_message: "taskId 不能为空。" };
  }
  return requestJson(`/api/tasks/${encodeURIComponent(taskId)}`, {
    timeoutMs: 8000,
  });
}

export async function getTasks({ userId = "default_user", workspaceId = "" } = {}) {
  return requestJson("/api/tasks", {
    params: {
      user_id: userId,
      workspace_id: workspaceId || undefined,
    },
    timeoutMs: 8000,
  });
}

export async function getTaskLogs(taskId) {
  if (!taskId) {
    return { success: false, error_message: "taskId 不能为空。" };
  }
  return requestJson(`/api/tasks/${encodeURIComponent(taskId)}/logs`, {
    timeoutMs: 8000,
  });
}

export async function getTaskResult(taskId) {
  if (!taskId) {
    return { success: false, error_message: "taskId 不能为空。" };
  }
  return requestJson(`/api/tasks/${encodeURIComponent(taskId)}/result`, {
    timeoutMs: 8000,
  });
}

export async function getConversationMessages(conversationId, userId = "default_user", limit = 20) {
  if (!conversationId) {
    return { success: false, error_message: "conversationId 不能为空。" };
  }
  return requestJson(`/api/conversations/${encodeURIComponent(conversationId)}/messages`, {
    params: { user_id: userId, limit },
    timeoutMs: 8000,
  });
}

export async function loadSkills() {
  return requestJson("/api/skills", { timeoutMs: 8000 });
}

export async function getUserMemory(userId = "default_user") {
  return requestJson("/api/memory", {
    params: { user_id: userId },
    timeoutMs: 8000,
  });
}

export async function updateUserMemory(payload, userId = "default_user") {
  return requestJson("/api/memory", {
    method: "PATCH",
    params: { user_id: userId },
    body: payload,
    timeoutMs: 8000,
  });
}

export async function clearUserMemory(userId = "default_user") {
  return requestJson("/api/memory", {
    method: "DELETE",
    params: { user_id: userId },
    timeoutMs: 8000,
  });
}

export async function getSkillLogs({ userId = "default_user", conversationId = "", limit = 30 } = {}) {
  return requestJson("/api/skills/logs", {
    params: {
      user_id: userId,
      conversation_id: conversationId || undefined,
      limit,
    },
    timeoutMs: 8000,
  });
}

export async function uploadSkillZip(file) {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson("/api/agent/skills/upload", {
    method: "POST",
    body: formData,
    timeoutMs: 30000,
  });
}

export async function setSkillEnabled(skillName, enabled) {
  return requestJson(`/api/skills/${encodeURIComponent(skillName)}/enabled`, {
    method: "PATCH",
    body: { enabled: Boolean(enabled) },
    timeoutMs: 8000,
  });
}

export async function deleteSkill(skillName) {
  return requestJson(`/api/agent/skills/${encodeURIComponent(skillName)}`, {
    method: "DELETE",
    timeoutMs: 8000,
  });
}

export async function setActionEnabled(skillName, actionName, enabled) {
  return requestJson(`/api/skills/${encodeURIComponent(skillName)}/actions/${encodeURIComponent(actionName)}/enabled`, {
    method: "PATCH",
    body: { enabled: Boolean(enabled) },
    timeoutMs: 8000,
  });
}

export async function registerUser(username, password) {
  return requestJson("/api/auth/register", {
    method: "POST",
    body: { username, password },
    timeoutMs: 12000,
  });
}

export async function loginUser(username, password) {
  return requestJson("/api/auth/login", {
    method: "POST",
    body: { username, password },
    timeoutMs: 12000,
  });
}

export async function logoutUser() {
  return requestJson("/api/auth/logout", {
    method: "POST",
    timeoutMs: 8000,
  });
}

export async function getAuthMe() {
  return requestJson("/api/auth/me", {
    timeoutMs: 8000,
  });
}

export async function getProjects() {
  return requestJson("/api/projects", { timeoutMs: 8000 });
}

export async function createProject(payload) {
  return requestJson("/api/projects", {
    method: "POST",
    body: payload,
    timeoutMs: 12000,
  });
}

export async function getProject(projectId) {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}`, {
    timeoutMs: 8000,
  });
}

export async function updateProject(projectId, payload) {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    body: payload,
    timeoutMs: 12000,
  });
}

export async function archiveProject(projectId) {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}`, {
    method: "DELETE",
    timeoutMs: 12000,
  });
}

export async function getProjectFiles(projectId) {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/files`, {
    timeoutMs: 8000,
  });
}

export async function getProjectTasks(projectId) {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/tasks`, {
    timeoutMs: 8000,
  });
}

export async function getProjectReports(projectId) {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/reports`, {
    timeoutMs: 8000,
  });
}

export async function attachProjectFile(projectId, fileId) {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/attach-file`, {
    method: "POST",
    body: { file_id: fileId },
    timeoutMs: 12000,
  });
}

export async function getReports(projectId = "") {
  return requestJson("/api/reports", {
    params: { project_id: projectId || undefined },
    timeoutMs: 8000,
  });
}

export async function getReport(reportId) {
  return requestJson(`/api/reports/${encodeURIComponent(reportId)}`, {
    timeoutMs: 8000,
  });
}

export async function exportReport(payload) {
  return requestJson("/api/reports/export", {
    method: "POST",
    body: payload,
    timeoutMs: 120000,
  });
}

export async function deleteReport(reportId) {
  return requestJson(`/api/reports/${encodeURIComponent(reportId)}`, {
    method: "DELETE",
    timeoutMs: 12000,
  });
}

export async function downloadReport(reportId, format = "markdown") {
  return downloadBinary(`/api/reports/${encodeURIComponent(reportId)}/download`, {
    params: { format },
    fallbackName: `report.${format === "markdown" ? "md" : format}`,
  });
}

export async function batchAnalyze(payload) {
  return requestJson("/api/methanol/batch-analyze", {
    method: "POST",
    body: payload,
    timeoutMs: 120000,
  });
}

export async function getBatchSummary(taskId) {
  return requestJson(`/api/methanol/batch-tasks/${encodeURIComponent(taskId)}/summary`, {
    timeoutMs: 8000,
  });
}

export async function downloadBatchCsv(taskId) {
  return downloadBinary(`/api/methanol/batch-tasks/${encodeURIComponent(taskId)}/download-csv`, {
    fallbackName: `batch_${taskId}.csv`,
  });
}

export function toAssetUrl(url) {
  if (!url || url === "#") {
    return "";
  }
  if (/^https?:\/\//i.test(url)) {
    return url;
  }
  return `${API_BASE_URL}${url.startsWith("/") ? url : `/${url}`}`;
}
