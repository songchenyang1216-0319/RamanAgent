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
  const timeoutMs = Number(options.timeoutMs || 8000);
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
      return {
        success: false,
        error_message: data.detail || data.error_message || `请求失败: ${response.status}`,
        status: response.status,
        data,
      };
    }
    return { success: true, ...data, status: response.status };
  } catch (error) {
    clearTimeout(timer);
    return {
      success: false,
      error_message:
        error.name === "AbortError"
          ? `请求超时（${timeoutMs}ms），请稍后重试。`
          : error.message || "请求失败，请确认后端服务是否已经启动。",
      status: 0,
    };
  }
}

export async function sendAgentChat({ message = "", sessionId = null, debug = false, file = null, metadata = {} }) {
  const timeoutMs = Number(metadata.timeoutMs || 15000);
  if (file) {
    const formData = new FormData();
    formData.append("message", message || "请分析这个文件");
    formData.append("debug", String(Boolean(debug)));
    formData.append("file", file);
    if (sessionId) {
      formData.append("session_id", sessionId);
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
      debug,
      session_id: sessionId || undefined,
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
  });
}

export async function getCurrentModel() {
  return requestJson("/api/models/current");
}

export async function checkCurrentModel(modelVersion) {
  const version = modelVersion || "methanol_v1";
  return requestJson(`/api/models/${encodeURIComponent(version)}/check`);
}

export async function getAgentModels() {
  return requestJson("/api/agent/models", { timeoutMs: 8000 });
}

export async function switchAgentModel(modelName) {
  return requestJson("/api/agent/models/current", {
    method: "PATCH",
    body: { model_name: modelName },
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
