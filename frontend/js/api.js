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
  try {
    const response = await fetch(buildUrl(path, options.params), {
      method: options.method || "GET",
      headers: options.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
      body: options.body instanceof FormData ? options.body : options.body ? JSON.stringify(options.body) : undefined,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      return {
        success: false,
        error_message: data.detail || data.error_message || `请求失败: ${response.status}`,
        status: response.status,
        status_text: response.statusText,
        data,
      };
    }
    return {
      ...data,
      status: response.status,
      status_text: response.statusText,
    };
  } catch (error) {
    return {
      success: false,
      error_message: error.message || "请求失败，请确认后端服务是否已经启动。",
      status: 0,
    };
  }
}

export async function chatWithAgent(message, debug = false, sessionId = null) {
  return requestJson("/api/agent/chat", {
    method: "POST",
    body: { message, debug, session_id: sessionId || undefined },
  });
}

export async function analyzeFile(file, metadata = {}, sessionId = null) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("message", metadata.message || "请分析这个 Raman CSV 文件");
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

export async function listHistory(params = {}) {
  return requestJson("/api/history", { params });
}

export async function getHistoryDetail(taskId) {
  return requestJson(`/api/history/${encodeURIComponent(taskId)}`);
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
