const API_BASE_URL =
  window.location.port === "5173" ? "http://127.0.0.1:8000" : window.location.origin;

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
    const response = await fetch(buildUrl(path, options.params), {
      method: options.method || "GET",
      headers: options.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
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

export async function sendAgentChat({ message = "", sessionId = null, userId = "default_user", debug = false, file = null, metadata = {} }) {
  const timeoutMs = Number(metadata.timeoutMs || (file ? 120000 : 60000));
  if (file) {
    const formData = new FormData();
    formData.append("message", message || "请分析这个文件");
    formData.append("user_id", userId || "default_user");
    formData.append("debug", String(Boolean(debug)));
    formData.append("file", file);
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
  return requestJson("/api/agent/skills", { timeoutMs: 8000 });
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
  return requestJson(`/api/agent/skills/${encodeURIComponent(skillName)}/enabled`, {
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
  return requestJson(`/api/agent/skills/${encodeURIComponent(skillName)}/actions/${encodeURIComponent(actionName)}/enabled`, {
    method: "PATCH",
    body: { enabled: Boolean(enabled) },
    timeoutMs: 8000,
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
