import {
  clearAgentSession,
  checkCurrentModel,
  getCurrentRamanModel,
  getConversationMessages,
  getConversationTasks,
  getCurrentLlmModel,
  getModelProviders,
  getProviderModels,
  getTaskTrace,
  getAgentSession,
  getWorkspaceContext,
  getWorkspaceFiles,
  loadSkills as fetchSkills,
  deleteSkill as requestDeleteSkill,
  sendAgentChat,
  setActionEnabled as requestSetActionEnabled,
  setSkillEnabled as requestSetSkillEnabled,
  switchLlmModel,
  refreshLlmModels,
  toAssetUrl,
  uploadSkillZip as requestUploadSkillZip,
} from "./js/api.js";

const STORAGE_KEYS = {
  sessionId: "multiskill-agent.sessionId",
  legacySessionId: "ramanagent.sessionId",
};
const RESPONSE_FIELD_KEYS = {
  professionalAnalysis: "professional_analysis",
};
const DEBUG_LOGS = false;

const state = {
  sessionId: loadSessionId(),
  currentModel: null,
  llmModelsPayload: { current: null, providers: [], selectedProviderId: "", models: [] },
  workspacePayload: { files: null, context: null, tasks: null, messages: null },
  workspaceOpen: false,
  userId: "default_user",
  selectedFile: null,
  skillsPayload: null,
  expandedSkillNames: new Set(),
  chatBusy: false,
  typingNode: null,
  initialized: false,
  modelListOpen: false,
  refreshingDashboard: false,
  uploadingSkill: false,
  toastTimer: null,
};

const $ = (id) => document.getElementById(id);

function debugLog(...args) {
  if (DEBUG_LOGS) {
    console.log(...args);
  }
}

function loadSessionId() {
  try {
    return (
      localStorage.getItem(STORAGE_KEYS.sessionId)
      || localStorage.getItem(STORAGE_KEYS.legacySessionId)
      || ""
    );
  } catch {
    return "";
  }
}

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatDurationMs(value) {
  const num = Number(value);
  if (!Number.isFinite(num) || num <= 0) {
    return "";
  }
  if (num < 1000) {
    return `${Math.round(num)} ms`;
  }
  return `${(num / 1000).toFixed(num >= 10000 ? 0 : 1)} s`;
}

function showToast(message, type = "info") {
  if (!message) {
    return;
  }
  let node = document.getElementById("globalToast");
  if (!node) {
    node = document.createElement("div");
    node.id = "globalToast";
    node.className = "global-toast";
    document.body.appendChild(node);
  }
  node.className = `global-toast ${type}`.trim();
  node.textContent = message;
  node.classList.add("visible");
  if (state.toastTimer) {
    window.clearTimeout(state.toastTimer);
  }
  state.toastTimer = window.setTimeout(() => {
    node.classList.remove("visible");
  }, 2400);
}

function renderInlineMarkdown(text) {
  const placeholders = [];
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, (_, code) => {
    placeholders.push(code);
    return `%%CODE_${placeholders.length - 1}%%`;
  });
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[\s(])_([^_\n]+)_(?=$|[\s).,;!?])/g, "$1<em>$2</em>");
  html = html.replace(/%%CODE_(\d+)%%/g, (_, index) => `<code>${placeholders[Number(index)] ?? ""}</code>`);
  return html;
}

function isTableDividerLine(line) {
  const cells = String(line || "")
    .trim()
    .split("|")
    .map((part) => part.trim())
    .filter(Boolean);
  if (!cells.length) {
    return false;
  }
  return cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function renderMarkdownTable(lines, startIndex) {
  const headerLine = lines[startIndex];
  const dividerLine = lines[startIndex + 1];
  if (!headerLine || !dividerLine || !headerLine.includes("|") || !isTableDividerLine(dividerLine)) {
    return null;
  }
  const rows = [];
  let index = startIndex;
  while (index < lines.length) {
    const line = lines[index];
    if (!line || !line.includes("|")) {
      break;
    }
    rows.push(line);
    index += 1;
  }
  const splitRow = (line) =>
    String(line || "")
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim());
  const headers = splitRow(rows[0]).map((cell) => renderInlineMarkdown(cell));
  const bodyRows = rows.slice(2).map((row) => splitRow(row).map((cell) => renderInlineMarkdown(cell)));
  const bodyHtml = bodyRows
    .map((cells) => `<tr>${cells.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
    .join("");
  return {
    html: `
      <div class="markdown-table-wrap">
        <table class="markdown-table">
          <thead><tr>${headers.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead>
          <tbody>${bodyHtml}</tbody>
        </table>
      </div>
    `,
    nextIndex: index,
  };
}

function renderMarkdown(text) {
  const source = String(text ?? "").replace(/\r\n/g, "\n");
  if (!source.trim()) {
    return "";
  }

  const lines = source.split("\n");
  const blocks = [];
  let index = 0;

  const flushParagraph = (paragraphLines) => {
    if (!paragraphLines.length) {
      return;
    }
    const content = paragraphLines.join(" ").trim();
    if (content) {
      blocks.push(`<p>${renderInlineMarkdown(content)}</p>`);
    }
    paragraphLines.length = 0;
  };

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (/^```/.test(trimmed) || /^~~~/.test(trimmed)) {
      const fence = trimmed.slice(0, 3);
      const language = trimmed.slice(3).trim();
      const codeLines = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith(fence)) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push(`
        <pre class="markdown-code-block${language ? ` language-${escapeHtml(language)}` : ""}"><code>${escapeHtml(codeLines.join("\n"))}</code></pre>
      `);
      continue;
    }

    if (/^#{1,6}\s+/.test(trimmed)) {
      const level = Math.min(6, trimmed.match(/^#{1,6}/)[0].length);
      const content = trimmed.replace(/^#{1,6}\s+/, "").trim();
      blocks.push(`<h${level}>${renderInlineMarkdown(content)}</h${level}>`);
      index += 1;
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push("<hr />");
      index += 1;
      continue;
    }

    if (/^>\s?/.test(trimmed)) {
      const quoteLines = [];
      while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(`<blockquote>${renderMarkdown(quoteLines.join("\n"))}</blockquote>`);
      continue;
    }

    const table = renderMarkdownTable(lines, index);
    if (table) {
      blocks.push(table.html);
      index = table.nextIndex;
      continue;
    }

    if (/^(\d+\.\s+|[-*+]\s+)/.test(trimmed)) {
      const ordered = /^\d+\.\s+/.test(trimmed);
      const items = [];
      while (index < lines.length && /^(\d+\.\s+|[-*+]\s+)/.test(lines[index].trim())) {
        const itemText = lines[index].trim().replace(/^(\d+\.\s+|[-*+]\s+)/, "");
        items.push(itemText);
        index += 1;
      }
      blocks.push(
        `<${ordered ? "ol" : "ul"}>${items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`,
      );
      continue;
    }

    const paragraphLines = [];
    while (index < lines.length) {
      const current = lines[index];
      const currentTrimmed = current.trim();
      if (!currentTrimmed) {
        break;
      }
      if (
        /^#{1,6}\s+/.test(currentTrimmed)
        || /^```/.test(currentTrimmed)
        || /^~~~/.test(currentTrimmed)
        || /^(-{3,}|\*{3,}|_{3,})$/.test(currentTrimmed)
        || /^>\s?/.test(currentTrimmed)
        || /^(\d+\.\s+|[-*+]\s+)/.test(currentTrimmed)
        || (current.includes("|") && isTableDividerLine(lines[index + 1] || ""))
      ) {
        break;
      }
      paragraphLines.push(currentTrimmed);
      index += 1;
    }
    flushParagraph(paragraphLines);
    if (paragraphLines.length === 0 && index < lines.length && !lines[index].trim()) {
      index += 1;
    }
  }

  return `<div class="markdown-body">${blocks.join("")}</div>`;
}

function renderMarkdownWithCollapse(text, { threshold = 1600, label = "展开全文" } = {}) {
  const source = String(text ?? "");
  if (!source) {
    return "";
  }
  if (source.length <= threshold) {
    return renderMarkdown(source);
  }
  return `
    <details class="markdown-collapse">
      <summary>${escapeHtml(label)}</summary>
      <div class="markdown-full">${renderMarkdown(source)}</div>
    </details>
  `;
}

function buildNowText() {
  const now = new Date();
  return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
}

function persistSessionId(sessionId) {
  state.sessionId = sessionId || "";
  try {
    if (state.sessionId) {
      localStorage.setItem(STORAGE_KEYS.sessionId, state.sessionId);
      localStorage.removeItem(STORAGE_KEYS.legacySessionId);
    } else {
      localStorage.removeItem(STORAGE_KEYS.sessionId);
      localStorage.removeItem(STORAGE_KEYS.legacySessionId);
    }
  } catch {
    // ignore
  }
  const target = $("sessionIdText");
  if (target) {
    target.textContent = state.sessionId || "未创建";
  }
}

function setChatStatus(text) {
  const node = $("chatStatus");
  if (node) {
    node.textContent = text || "";
  }
}

function autoResizeTextarea() {
  const textarea = $("messageInput");
  if (!textarea) {
    return;
  }
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
}

function getChatRequestTimeout({ hasFile, message }) {
  if (hasFile) {
    return 120000;
  }
  const text = String(message || "").toLowerCase();
  if (
    text.includes("联网") ||
    text.includes("搜索") ||
    text.includes("查一下") ||
    text.includes("查一查") ||
    text.includes("最新") ||
    text.includes("新闻") ||
    text.includes("github")
  ) {
    return 90000;
  }
  if (
    text.includes("预处理") ||
    text.includes("预测") ||
    text.includes("分析") ||
    text.includes("画图") ||
    text.includes("基线") ||
    text.includes("去噪")
  ) {
    return 120000;
  }
  return 60000;
}

function formatResponseError(response = {}) {
  const message = response.message || "请求没有完成";
  const errorMessage = response.error_message || response.llm_error || "后端没有返回具体错误。";
  const suggestion = response.suggestion || "";
  const errorCode = response.error_code ? `（${response.error_code}）` : "";
  if (response.error_code === "REQUEST_TIMEOUT" || String(errorMessage).includes("请求超时")) {
    return `${message}${errorCode}：${errorMessage} 可以稍后查看最近记录或刷新工作区。`;
  }
  return `${message}${errorCode}：${errorMessage}${suggestion ? ` 建议：${suggestion}` : ""}`;
}

function scrollToBottom() {
  const container = $("chatMessages");
  if (!container) {
    return;
  }
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  });
}

function setBusy(isBusy, hint = "正在处理中...") {
  state.chatBusy = isBusy;
  const sendButton = $("sendButton");
  const fileButton = $("fileButton");
  const messageInput = $("messageInput");
  const chatDebug = $("chatDebug");
  if (sendButton) {
    sendButton.disabled = isBusy;
  }
  if (fileButton) {
    fileButton.disabled = isBusy;
  }
  if (messageInput) {
    messageInput.disabled = isBusy;
  }
  if (chatDebug) {
    chatDebug.disabled = isBusy;
  }
  setChatStatus(isBusy ? hint : state.sessionId ? `当前会话：${state.sessionId}` : "可以直接提问，或上传任意文件后发送。");
}

function appendMessage(role, html, type = "text", meta = buildNowText()) {
  const container = $("chatMessages");
  if (!container) {
    return null;
  }

  const row = document.createElement("div");
  row.className = `message-row ${role} ${type === "error" ? "error" : ""}`.trim();
  row.innerHTML = `
    <article class="message-bubble">
      <div class="message-meta">
        <span class="message-role">${role === "user" ? "用户" : role === "assistant" ? "Assistant" : "系统"}</span>
        <span class="message-time">${escapeHtml(meta)}</span>
      </div>
      <div class="message-content">${html}</div>
    </article>
  `;
  container.appendChild(row);
  scrollToBottom();
  return row;
}

function escapeOrFallback(value, fallback = "") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

const MODEL_CATEGORY_LABELS = {
  text_chat: "文本对话",
  vision_understanding: "视觉理解",
  image_edit: "图像编辑",
  ocr: "OCR",
  embedding: "向量检索",
  audio: "音频",
  unknown: "待确认",
};

function normalizeModelCategories(model = {}) {
  const supported = Array.isArray(model.supported_categories)
    ? model.supported_categories.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  if (supported.length) {
    return supported;
  }
  switch (String(model.model_type || "").trim()) {
    case "vision":
      return ["text_chat", "vision_understanding"];
    case "image_edit":
      return ["image_edit"];
    case "ocr":
      return ["ocr"];
    case "embedding":
      return ["embedding"];
    case "audio":
      return ["audio"];
    case "text":
      return ["text_chat"];
    default:
      return model.supports_vision ? ["text_chat", "vision_understanding"] : ["unknown"];
  }
}

function buildModelCategoryBadge(category, labelOverride = "") {
  const key = String(category || "").trim();
  const label = String(labelOverride || "").trim() || MODEL_CATEGORY_LABELS[key] || key || "待确认";
  const className = key === "vision_understanding" ? "ok" : key === "unknown" ? "warn" : "";
  return `<span class="model-badge ${className}">${escapeHtml(label)}</span>`;
}

function buildModelCategorySummary(model = {}) {
  const categories = normalizeModelCategories(model);
  const backendLabels = Array.isArray(model.supported_category_labels)
    ? model.supported_category_labels.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const labels = backendLabels.length === categories.length && backendLabels.length ? backendLabels : categories.map((category) => MODEL_CATEGORY_LABELS[category] || category || "待确认");
  const summary = escapeOrFallback(model.category_summary || labels.join(" / "), "待确认");
  const sourceMap = {
    explicit: "规则确认",
    heuristic: "自动识别",
    default: "默认推断",
  };
  const statusMap = {
    confirmed: "已确认",
    default: "待确认",
  };
  const status = statusMap[String(model.category_status || "").trim()] || "待确认";
  const source = sourceMap[String(model.category_source || "").trim()] || "";
  const reason = escapeOrFallback(model.category_reason || "", "");
  return {
    chips: categories.map((category, index) => buildModelCategoryBadge(category, labels[index] || "")).join(""),
    summary,
    status,
    source,
    reason,
  };
}

function resolveAssistantModelInfo(message = {}, fallback = {}) {
  const raw = message.llm_model_info || fallback.llm_model_info || message.model_info || fallback.model_info || {};
  const providerDisplayName = escapeOrFallback(raw.provider_display_name || raw.provider_name || raw.provider || "");
  const modelDisplayName = escapeOrFallback(raw.model_display_name || raw.model_name || raw.model || "");
  const displayName = escapeOrFallback(raw.display_name || (providerDisplayName && modelDisplayName ? `${providerDisplayName} · ${modelDisplayName}` : ""), "");
  return {
    provider: escapeOrFallback(raw.provider || ""),
    provider_display_name: providerDisplayName,
    model: escapeOrFallback(raw.model || ""),
    model_display_name: modelDisplayName,
    model_type: escapeOrFallback(raw.model_type || "", ""),
    display_name: displayName,
    available: raw.available,
    reason: escapeOrFallback(raw.reason || ""),
  };
}

function buildAssistantModelBadge(message = {}, fallback = {}) {
  const modelInfo = resolveAssistantModelInfo(message, fallback);
  if (!modelInfo.display_name) {
    return "";
  }
  return `<div class="assistant-model-badge">由 ${escapeHtml(modelInfo.display_name)} 生成</div>`;
}

function buildAssistantSourceBadge(message = {}, fallback = {}) {
  if (!message) {
    return "";
  }
  const toolInfo = (message.tool_info && typeof message.tool_info === "object" ? message.tool_info : null)
    || (fallback.tool_info && typeof fallback.tool_info === "object" ? fallback.tool_info : null)
    || {};
  const source = escapeOrFallback(toolInfo.source || message.source || fallback.source, "");
  const toolName = escapeOrFallback(message.tool_used || fallback.tool_used || "", "");
  const rawSkillName = escapeOrFallback(toolInfo.skill || message.skill_name || message.analysis?.skill_name, "");
  const skillName = rawSkillName === "web-search" ? "联网搜索" : rawSkillName;
  const actionName = escapeOrFallback(toolInfo.action || message.action_name || message.analysis?.action_name, "");
  const skillMode = escapeOrFallback(message.skill_mode || message.analysis?.skill_mode || fallback.skill_mode, "");
  const routeInfo = message.route_info || fallback.route_info || {};
  const route = escapeOrFallback(routeInfo.route, "");
  const reason = escapeOrFallback(routeInfo.reason, "");
  const fileName = escapeOrFallback(toolInfo.filename || message.saved_file || message.file_name || message.analysis?.details?.saved_file || "", "");
  const imageType = escapeOrFallback(toolInfo.image_type || "", "");
  const tableRows = toolInfo.rows;
  const tableColumns = toolInfo.columns;
  const sheetName = escapeOrFallback(toolInfo.sheet_name || "", "");
  const mode = escapeOrFallback(toolInfo.mode || "", "");
  const success = toolInfo.success !== undefined ? Boolean(toolInfo.success) : (message.success !== undefined ? Boolean(message.success) : fallback.success);
  const errorMessage = escapeOrFallback(toolInfo.error || message.error_message || message.llm_error || message.analysis?.details?.error_message || "", "");
  const durationMs = Number(message.elapsed_ms || message.client_elapsed_ms || message.analysis?.details?.duration_ms || message.data?.duration_ms || fallback.client_elapsed_ms || 0);

  const summaryParts = [];
  if (skillName && actionName) {
    summaryParts.push(`已调用 Skill：${skillName} · ${actionName}`);
  } else if (skillName) {
    summaryParts.push(`已调用 Skill：${skillName}`);
  } else if (toolName) {
    summaryParts.push(`已调用工具：${toolName}`);
  }

  if (!summaryParts.length) {
    return "";
  }

  const detailRows = [];
  if (source) {
    detailRows.push(["来源", source]);
  }
  if (skillName) {
    detailRows.push(["Skill", skillName]);
  }
  if (actionName) {
    detailRows.push(["Action", actionName]);
  }
  if (imageType) {
    detailRows.push(["Image Type", imageType]);
  }
  if (skillMode) {
    const modeLabel = skillMode === "prompt_only" ? "提示词型" : skillMode === "executable" ? "可执行型" : skillMode;
    detailRows.push(["模式", modeLabel]);
  }
  if (mode) {
    detailRows.push(["Mode", mode]);
  }
  if (fileName) {
    detailRows.push(["文件", fileName]);
  }
  if (tableRows !== undefined && tableRows !== null && tableRows !== "") {
    detailRows.push(["行数", String(tableRows)]);
  }
  if (tableColumns !== undefined && tableColumns !== null && tableColumns !== "") {
    detailRows.push(["列数", String(tableColumns)]);
  }
  if (sheetName) {
    detailRows.push(["Sheet", sheetName]);
  }
  if (Number.isFinite(durationMs) && durationMs > 0) {
    detailRows.push(["耗时", formatDurationMs(durationMs)]);
  }
  if (typeof success === "boolean") {
    detailRows.push(["成功", success ? "是" : "否"]);
  }
  if (route) {
    detailRows.push(["Route", route]);
  }
  if (reason) {
    detailRows.push(["原因", reason]);
  }
  if (errorMessage) {
    detailRows.push(["错误", errorMessage]);
  }

  return `
    <details class="skill-trace-banner" data-skill-trace>
      <summary class="skill-trace-summary">
        <span class="skill-trace-title">${escapeHtml(summaryParts.join(" "))}</span>
        <span class="skill-trace-toggle"><span class="when-closed">展开详情</span><span class="when-open">收起详情</span></span>
      </summary>
      <div class="skill-trace-details">
        ${detailRows
          .map(
            ([label, value]) => `
              <div class="skill-trace-item">
                <span>${escapeHtml(label)}</span>
                <strong>${escapeHtml(value)}</strong>
              </div>
            `,
          )
          .join("")}
      </div>
    </details>
  `;
}

function renderWebSearchSources(payload = {}) {
  const items = Array.isArray(payload.data?.items) ? payload.data.items : [];
  if (payload.intent !== "web_search" || !items.length) {
    return "";
  }
  const provider = escapeOrFallback(payload.data?.used_provider || payload.data?.provider || "", "");
  const query = escapeOrFallback(payload.data?.query || payload.message || "", "");
  return `
    <div class="web-search-sources">
      <strong>联网搜索来源</strong>
      ${provider ? `<div class="web-search-meta">搜索提供商：${provider}</div>` : ""}
      ${query ? `<div class="web-search-meta">搜索关键词：${query}</div>` : ""}
      ${items
        .slice(0, 5)
        .map(
          (item) => `
            <a href="${escapeHtml(item.url || "#")}" target="_blank" rel="noopener noreferrer">
              <span>${escapeHtml(item.title || "未命名结果")}</span>
              ${item.snippet ? `<small>${escapeHtml(item.snippet)}</small>` : ""}
            </a>
          `,
        )
        .join("")}
    </div>
  `;
}

function isImageFileLike(fileOrName) {
  const name = typeof fileOrName === "string" ? fileOrName : fileOrName?.name || "";
  return /\.(png|jpg|jpeg|webp|bmp|tif|tiff)$/i.test(String(name || ""));
}

function appendFileCard(file) {
  if (!file) {
    return;
  }
  if (isImageFileLike(file)) {
    const previewUrl = URL.createObjectURL(file);
    appendMessage(
      "user",
      `
        <div class="file-card image-card">
          <img src="${previewUrl}" alt="${escapeHtml(file.name)}" class="chat-upload-thumb" />
          <div class="file-card-body">
            <strong>图片</strong>
            <span>${escapeHtml(file.name)}</span>
          </div>
        </div>
      `,
      "text",
    );
    return;
  }
  appendMessage(
    "user",
    `<div class="file-card"><strong>文件</strong><span>${escapeHtml(file.name)}</span></div>`,
    "text",
  );
}

function renderTypingMessage(text = "正在处理，请稍候...") {
  removeTypingMessage();
  state.typingNode = appendMessage(
    "assistant",
    `<p>${escapeHtml(text)}</p><div class="typing-dots"><span></span><span></span><span></span></div>`,
    "text",
    "处理中",
  );
}

function removeTypingMessage() {
  if (state.typingNode) {
    state.typingNode.remove();
    state.typingNode = null;
  }
}

function renderWelcomeMessage() {
  const container = $("chatMessages");
  if (!container) {
    return;
  }
  container.innerHTML = "";
  appendMessage(
    "system",
    [
      "<p>欢迎使用多功能 Agent 工作台。</p>",
      "<p>你可以直接提问，也可以点击左下角的 <strong>+</strong> 上传任意文件，然后继续发送处理请求。</p>",
      "<p>当前支持通过 Skills 扩展能力，其中 Raman 光谱处理是一个独立 Skill。</p>",
      "<p>常见用法：<span class=\"inline-chip\">最近记录</span> <span class=\"inline-chip\">模型列表</span> <span class=\"inline-chip\">Skills 管理</span></p>",
    ].join(""),
    "text",
    state.sessionId ? `已恢复 ${state.sessionId}` : "新会话",
  );
}

function truncateText(value, limit = 240) {
  const text = String(value ?? "").trim();
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, Math.max(0, limit - 12))}……[已截断]`;
}

function formatCompactJson(value, limit = 1200) {
  if (value === null || value === undefined || value === "") {
    return "";
  }
  let text = "";
  try {
    text = JSON.stringify(value, null, 2);
  } catch {
    text = String(value);
  }
  return truncateText(text, limit);
}

function renderSessionMemorySummary(payload) {
  const summary = truncateText(payload?.summary || "", 220) || "暂无摘要";
  const lastAnalysis = payload?.last_analysis ? formatCompactJson(payload.last_analysis, 600) : "暂无最近分析";
  const taskState = payload?.task_state_view ? formatCompactJson(payload.task_state_view, 700) : formatCompactJson(payload.task_state, 700);
  appendMessage(
    "system",
    `
      <div class="memory-summary-card">
        <p><strong>会话 ID：</strong>${escapeHtml(payload?.session_id || state.sessionId || "未创建")}</p>
        <p><strong>摘要：</strong>${escapeHtml(summary)}</p>
        <p><strong>消息数：</strong>${escapeHtml(String(payload?.message_count ?? 0))}</p>
        <details>
          <summary>查看简要记忆</summary>
          <div class="analysis-detail-json">${escapeHtml(lastAnalysis)}</div>
          <div class="analysis-detail-json">${escapeHtml(taskState)}</div>
        </details>
      </div>
    `,
    "text",
    buildNowText(),
  );
}

function clearChatWindow() {
  const container = $("chatMessages");
  if (container) {
    container.innerHTML = "";
  }
  removeTypingMessage();
  renderWelcomeMessage();
}

async function handleNewSession() {
  persistSessionId("");
  state.selectedFile = null;
  const fileInput = $("fileInput");
  if (fileInput) {
    fileInput.value = "";
  }
  renderSelectedFileChip(null);
  clearChatWindow();
  setChatStatus("已切换为新会话，下一次发送时后端会自动创建新的 session。");
}

async function handleClearSessionMemory() {
  const sessionId = state.sessionId;
  if (!sessionId) {
    window.alert("当前还没有可清空的 session，请先发送一次消息或新建会话。");
    return;
  }
  try {
    const response = await clearAgentSession(sessionId);
    if (!response.success) {
      throw new Error(response.error_message || "清空记忆失败");
    }
    state.selectedFile = null;
    const fileInput = $("fileInput");
    if (fileInput) {
      fileInput.value = "";
    }
    renderSelectedFileChip(null);
    clearChatWindow();
    setChatStatus(`当前会话记忆已清空：${sessionId}`);
    window.alert(response.message || "当前会话记忆已清空。");
  } catch (error) {
    console.error("清空会话记忆失败：", error);
    window.alert(`清空会话记忆失败：${error.message || "未知错误"}`);
  }
}

async function handleInspectSession() {
  const sessionId = state.sessionId;
  if (!sessionId) {
    window.alert("当前还没有 session，请先发送一次消息。");
    return;
  }
  try {
    const response = await getAgentSession(sessionId);
    if (!response.success) {
      throw new Error(response.error_message || "读取记忆失败");
    }
    renderSessionMemorySummary(response);
    setChatStatus(`已查看当前会话记忆：${sessionId}`);
  } catch (error) {
    console.error("查看会话记忆失败：", error);
    window.alert(`查看会话记忆失败：${error.message || "未知错误"}`);
  }
}

function getSkillIcon(category, source) {
  if (source === "uploaded") return "⬆";
  const text = String(category || "");
  if (text.includes("数据")) return "文";
  if (text.includes("预处理")) return "净";
  if (text.includes("基线")) return "线";
  if (text.includes("去噪")) return "稳";
  if (text.includes("模型")) return "模";
  if (text.includes("可视化")) return "图";
  if (text.includes("报告")) return "报";
  if (text.includes("系统")) return "系";
  if (text.includes("对话")) return "聊";
  return "技";
}

function renderSkillsButton(payload = state.skillsPayload) {
  const target = $("skillsButtonCount");
  if (!target) {
    return;
  }
  const total = Number(payload?.total || 0);
  target.textContent = total > 0 ? `${total} 个` : "0 个";
}

function renderSkillsButtonError(error) {
  console.error("加载 Skills 失败：", error);
  const target = $("skillsButtonCount");
  if (target) {
    target.textContent = "失败";
  }
  renderSkillsPanel({
    total: 0,
    enabled_count: 0,
    available_count: 0,
    skills: [],
    error: error?.message || String(error || "Skill 列表加载失败"),
  });
}

function renderSkillToggleButton(skill) {
  const canToggle = Boolean(skill.available) && skill.source !== "uploaded";
  const nextEnabled = !skill.enabled;
  return `
    <button
      type="button"
      class="skill-toggle-button"
      data-toggle-skill-enabled="${escapeHtml(skill.name || "")}"
      data-next-enabled="${String(nextEnabled)}"
      ${canToggle ? "" : "disabled"}
    >
      ${skill.enabled ? "禁用" : "启用"}
    </button>
  `;
}

function renderSkillDeleteButton(skill) {
  if (skill.source !== "uploaded") {
    return "";
  }
  return `
    <button
      type="button"
      class="skill-toggle-button small danger"
      data-delete-skill="${escapeHtml(skill.name || "")}"
    >
      删除
    </button>
  `;
}

function renderActionToggleButton(skillName, action) {
  const canToggle = action.available || !action.enabled;
  const nextEnabled = !action.enabled;
  return `
    <button
      type="button"
      class="skill-toggle-button small"
      data-toggle-action-enabled="${escapeHtml(skillName || "")}"
      data-action-name="${escapeHtml(action.name || "")}"
      data-next-enabled="${String(nextEnabled)}"
      ${canToggle ? "" : "disabled"}
    >
      ${action.enabled ? "禁用" : "启用"}
    </button>
  `;
}

function renderActionSourceLine(action) {
  return `
    <div class="skill-source-line">
      <span class="skill-source-badge">${escapeHtml(action.skill_name || "")}</span>
    </div>
  `;
}

function renderSkillActions(actions = []) {
  if (!actions.length) {
    return `<div class="skills-empty">当前没有可展示的子能力。</div>`;
  }
  return actions
    .map(
      (action) => `
        <div class="skill-action-item">
          <h4>${escapeHtml(action.display_name || action.name || "未命名 action")}</h4>
          <p class="skill-action-tech">${escapeHtml(action.name || "")}</p>
          <p class="skill-action-desc">${escapeHtml(action.description || "暂无描述")}</p>
          ${renderActionSourceLine(action)}
          <div class="skill-statuses">
            <span class="skill-status ${action.enabled ? "success" : "warning"}">${action.enabled ? "已启用" : "未启用"}</span>
            <span class="skill-status ${action.available ? "success" : "error"}">${action.available ? "可用" : "不可用"}</span>
            <span class="skill-status">${escapeHtml(action.status || "unknown")}</span>
          </div>
          <div class="skill-action-toolbar">
            ${renderActionToggleButton(action.skill_name || "", action)}
          </div>
          ${action.available ? "" : `<div class="skill-action-unavailable">不可用原因：${escapeHtml(action.unavailable_reason || "未提供")}</div>`}
        </div>
      `,
    )
    .join("");
}

function renderSkillCard(skill) {
  const actions = Array.isArray(skill.actions) ? skill.actions : [];
  const expanded = state.expandedSkillNames.has(skill.name);
  const actionsWithSkillName = actions.map((action) => ({ ...action, skill_name: skill.name }));
  const sourceText = skill.source === "uploaded" ? "uploaded" : "builtin";
  return `
    <article class="skill-card" data-skill-name="${escapeHtml(skill.name || "")}">
      <div class="skill-card-header">
        <div class="skill-card-title">
          <span class="skill-icon">${getSkillIcon(skill.category, skill.source)}</span>
          <div class="skill-title-block">
            <h3>${escapeHtml(skill.display_name || skill.name || "未命名 Skill")}</h3>
            <p class="skill-technical-name">${escapeHtml(skill.name || "")}</p>
          </div>
        </div>
        <div class="skill-card-toolbar">
          ${renderSkillToggleButton(skill)}
          ${renderSkillDeleteButton(skill)}
        </div>
      </div>
      <p class="skill-description">${escapeHtml(skill.description || "暂无描述")}</p>
      <div class="skill-tags">
        <span class="skill-tag">${escapeHtml(skill.category || "未分类")}</span>
        <span class="skill-tag">source: ${escapeHtml(sourceText)}</span>
        <span class="skill-tag">${skill.requires_file ? "需要文件" : "无需文件"}</span>
        ${(skill.supported_file_types || []).length
          ? skill.supported_file_types.map((item) => `<span class="skill-tag">${escapeHtml(item)}</span>`).join("")
          : '<span class="skill-tag">通用</span>'}
        <span class="skill-tag">${escapeHtml(skill.version || "v1")}</span>
      </div>
      <div class="skill-statuses">
        <span class="skill-status ${skill.enabled ? "success" : "warning"}">${skill.enabled ? "已启用" : "未启用"}</span>
        <span class="skill-status ${skill.available ? "success" : "error"}">${skill.available ? "可用" : "待加载"}</span>
        <span class="skill-status">包含 ${actions.length} 个子能力</span>
      </div>
      ${
        skill.uploaded_at
          ? `<div class="skill-upload-meta">上传时间：${escapeHtml(skill.uploaded_at)}${skill.upload_status ? ` · 状态：${escapeHtml(skill.upload_status)}` : ""}</div>`
          : ""
      }
      ${skill.available ? "" : `<div class="skill-unavailable">不可用原因：${escapeHtml(skill.unavailable_reason || "未提供")}</div>`}
      <p class="skill-usage">${escapeHtml(skill.usage || "暂无使用说明")}</p>
      <button type="button" class="skill-actions-toggle" data-toggle-skill="${escapeHtml(skill.name || "")}">
        ${expanded ? "收起子能力" : "查看子能力"}
      </button>
      ${expanded ? `<div class="skill-actions">${renderSkillActions(actionsWithSkillName)}</div>` : ""}
    </article>
  `;
}

function renderSkillsPanel(payload) {
  const stats = $("skillsPanelStats");
  const body = $("skillsPanelBody");
  if (!stats || !body) {
    return;
  }

  if (!payload || !Array.isArray(payload.skills)) {
    stats.innerHTML = "";
    body.innerHTML = `<div class="skills-empty">Skill 列表加载失败，请检查后端 /api/agent/skills 接口。</div>`;
    return;
  }

  stats.innerHTML = `
    <div class="skills-panel-stat"><span>已安装</span><strong>${Number(payload.total || 0)}</strong></div>
    <div class="skills-panel-stat"><span>已启用</span><strong>${Number(payload.enabled_count || 0)}</strong></div>
    <div class="skills-panel-stat"><span>可用</span><strong>${Number(payload.available_count || 0)}</strong></div>
  `;

  const contentHtml = payload.skills.length
    ? payload.skills.map((skill) => renderSkillCard(skill)).join("")
    : `<div class="skills-empty">当前没有可展示的大 Skill。</div>`;
  body.innerHTML = payload.error
    ? `<div class="skills-empty">${escapeHtml(payload.error)}</div>${contentHtml}`
    : contentHtml;

  body.querySelectorAll("[data-toggle-skill]").forEach((button) => {
    button.addEventListener("click", () => toggleSkillActions(button.dataset.toggleSkill || ""));
  });
  body.querySelectorAll("[data-toggle-skill-enabled]").forEach((button) => {
    button.addEventListener("click", () => {
      toggleSkillEnabled(button.dataset.toggleSkillEnabled || "", button.dataset.nextEnabled === "true");
    });
  });
  body.querySelectorAll("[data-delete-skill]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteSkillItem(button.dataset.deleteSkill || "");
    });
  });
  body.querySelectorAll("[data-toggle-action-enabled]").forEach((button) => {
    button.addEventListener("click", () => {
      toggleActionEnabled(
        button.dataset.toggleActionEnabled || "",
        button.dataset.actionName || "",
        button.dataset.nextEnabled === "true",
      );
    });
  });
}

function openSkillsPanel() {
  const panel = $("skillsPanel");
  if (!panel) {
    return;
  }
  panel.classList.remove("hidden");
  panel.setAttribute("aria-hidden", "false");
}

function closeSkillsPanel() {
  const panel = $("skillsPanel");
  if (!panel) {
    return;
  }
  panel.classList.add("hidden");
  panel.setAttribute("aria-hidden", "true");
}

function openModelList() {
  const popover = $("modelListPopover");
  if (!popover) {
    return;
  }
  state.modelListOpen = true;
  renderModelList(state.llmModelsPayload);
  popover.classList.remove("hidden");
  popover.setAttribute("aria-hidden", "false");
}

function closeModelList() {
  const popover = $("modelListPopover");
  if (!popover) {
    return;
  }
  state.modelListOpen = false;
  popover.classList.add("hidden");
  popover.setAttribute("aria-hidden", "true");
}

function toggleSkillActions(skillName) {
  if (!skillName) {
    return;
  }
  if (state.expandedSkillNames.has(skillName)) {
    state.expandedSkillNames.delete(skillName);
  } else {
    state.expandedSkillNames.add(skillName);
  }
  renderSkillsPanel(state.skillsPayload);
}

async function refreshSkillsPanel() {
  await loadSkillsSafely();
}

async function toggleSkillEnabled(skillName, enabled) {
  try {
    const response = await requestSetSkillEnabled(skillName, enabled);
    if (!response.success) {
      throw new Error(response.error_message || "切换 Skill 状态失败");
    }
    await refreshSkillsPanel();
  } catch (error) {
    console.error("切换 Skill 状态失败：", error);
    window.alert(`切换 Skill 状态失败：${error.message || "未知错误"}`);
  }
}

async function toggleActionEnabled(skillName, actionName, enabled) {
  try {
    const response = await requestSetActionEnabled(skillName, actionName, enabled);
    if (!response.success) {
      throw new Error(response.error_message || "切换子能力状态失败");
    }
    state.expandedSkillNames.add(skillName);
    await refreshSkillsPanel();
  } catch (error) {
    console.error("切换子能力状态失败：", error);
    window.alert(`切换子能力状态失败：${error.message || "未知错误"}`);
  }
}

async function deleteSkillItem(skillName) {
  if (!skillName) {
    return;
  }
  const confirmed = window.confirm(
    `确定要删除 Skill「${skillName}」吗？删除后会清理上传包、解压目录和记录，并且无法恢复。`,
  );
  if (!confirmed) {
    return;
  }

  try {
    const response = await requestDeleteSkill(skillName);
    if (!response.success) {
      throw new Error(response.error_message || "删除 Skill 失败");
    }
    state.expandedSkillNames.delete(skillName);
    window.alert(response.message || "Skill 已删除");
    await refreshSkillsPanel();
  } catch (error) {
    console.error("删除 Skill 失败：", error);
    window.alert(`删除 Skill 失败：${error.message || "未知错误"}`);
  }
}

function renderSelectedFileChip(file) {
  const chip = $("selectedFileChip");
  if (!chip) {
    console.warn("找不到 selectedFileChip，跳过文件 chip 渲染");
    return;
  }

  if (!file) {
    chip.classList.add("hidden");
    chip.innerHTML = "";
    return;
  }

  chip.classList.remove("hidden");
  chip.innerHTML = `
    <span class="file-chip-name">已选择：${escapeHtml(file.name)}</span>
    <button id="removeSelectedFileButton" type="button" class="file-chip-remove" aria-label="移除已选文件">×</button>
  `;

  const removeBtn = $("removeSelectedFileButton");
  if (removeBtn) {
    removeBtn.addEventListener("click", () => {
      state.selectedFile = null;
      const fileInput = $("fileInput");
      if (fileInput) {
        fileInput.value = "";
      }
      renderSelectedFileChip(null);
    });
  }
}

function handleFileSelect(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) {
    return;
  }

  state.selectedFile = file;
  debugLog("已选择文件：", file.name);
  renderSelectedFileChip(file);
}

async function handleSkillZipSelect(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) {
    return;
  }
  const lowerName = file.name.toLowerCase();
  if (!lowerName.endsWith(".zip")) {
    window.alert("请上传 zip 格式的 Skill 压缩包");
    event.target.value = "";
    return;
  }
  await uploadSkillZip(file);
  event.target.value = "";
}

async function uploadSkillZip(file) {
  if (state.uploadingSkill) {
    return;
  }
  state.uploadingSkill = true;
  const uploadBtn = $("uploadSkillBtn");
  const originalText = uploadBtn?.textContent || "上传 Skill";
  if (uploadBtn) {
    uploadBtn.disabled = true;
    uploadBtn.textContent = "上传中...";
  }
  try {
    const response = await requestUploadSkillZip(file);
    if (!response.success) {
      throw new Error(response.error_message || "Skill 上传失败");
    }
    debugLog("Skill 上传成功：", response);
    window.alert(`${response.message || "Skill 上传成功"}${response.reload_required ? "，请刷新 Skills 列表查看待加载状态。" : ""}`);
    await loadSkillsSafely();
  } catch (error) {
    console.error("Skill 上传失败：", error);
    window.alert(`Skill 上传失败：${error.message || "未知错误"}`);
  } finally {
    state.uploadingSkill = false;
    if (uploadBtn) {
      uploadBtn.disabled = false;
      uploadBtn.textContent = originalText;
    }
  }
}

function renderDetailRows(title, details) {
  return Object.entries(details || {})
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(
      ([key, value]) => `
        <div class="detail-item">
          <span>${escapeHtml(title ? `${title} · ${key}` : key)}</span>
          <strong>${escapeHtml(typeof value === "object" ? JSON.stringify(value, null, 2) : String(value))}</strong>
        </div>
      `,
    )
    .join("");
}

function renderPlots(plots) {
  const items = (plots || [])
    .map((url, index) => {
      const normalizedUrl = typeof url === "string" ? url : url?.url;
      const title = typeof url === "string" ? `图谱 ${index + 1}` : url?.title || `图谱 ${index + 1}`;
      const assetUrl = toAssetUrl(normalizedUrl);
      if (!assetUrl) {
        return "";
      }
      return `
        <figure class="figure-tile">
          <img src="${escapeHtml(assetUrl)}" alt="plot-${index + 1}" />
          <figcaption>${escapeHtml(title)}</figcaption>
        </figure>
      `;
    })
    .filter(Boolean);
  return items.length ? `<div class="analysis-figures">${items.join("")}</div>` : "";
}

function renderListSection(title, items = [], emptyText = "当前未提供。") {
  const list = Array.isArray(items) ? items.filter(Boolean) : [];
  return `
    <section class="explanation-card">
      <h4>${escapeHtml(title)}</h4>
      ${
        list.length
          ? `<ul class="analysis-list compact">${list.map((item) => `<li>${renderInlineMarkdown(String(item))}</li>`).join("")}</ul>`
          : `<div class="analysis-empty">${escapeHtml(emptyText)}</div>`
      }
    </section>
  `;
}

function renderNarrativeBlock(text, { collapse = false, threshold = 1200 } = {}) {
  const content = String(text ?? "").trim();
  if (!content) {
    return "";
  }
  if (collapse) {
    return `
      <section class="analysis-summary markdown-summary">
        ${renderMarkdownWithCollapse(content, { threshold, label: "展开全文" })}
      </section>
    `;
  }
  return `
    <section class="analysis-summary markdown-summary">
      ${renderMarkdown(content)}
    </section>
  `;
}

function renderEvidenceSection(structured = {}) {
  const evidence = structured?.confidence_analysis?.evidence_items || [];
  return `
    <section class="explanation-card">
      <h4>关键判断依据</h4>
      ${
        evidence.length
          ? `<div class="detail-list">${evidence
              .map(
                (item) => `
                  <div class="detail-item">
                    <span>${escapeHtml(item.label || "指标")}</span>
                    <strong>${escapeHtml(item.value || "未提供")}</strong>
                  </div>
                `,
              )
              .join("")}</div>`
          : `<div class="analysis-empty">当前未提供关键判断依据。</div>`
      }
    </section>
  `;
}

function renderSpectralFeaturesSection(structured = {}) {
  const features = structured?.spectral_features || [];
  return `
    <section class="explanation-card">
      <h4>光谱特征说明</h4>
      ${
        features.length
          ? `<div class="feature-list">${features
              .map(
                (item) => `
                  <div class="feature-item">
                    <strong>${escapeHtml(item.wavenumber !== undefined && item.wavenumber !== null ? `${Number(item.wavenumber).toFixed(1)} cm^-1` : "未提供峰位")}</strong>
                    <span>${escapeHtml(item.label || "未标注")}</span>
                  </div>
                `,
              )
              .join("")}</div>`
          : `<div class="analysis-empty">当前未提供明确峰位说明。</div>`
      }
    </section>
  `;
}

function renderMetricGrid(metrics = {}) {
  const entries = Object.entries(metrics).filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (!entries.length) {
    return "";
  }
  return `
    <div class="detail-list">
      ${entries
        .map(
          ([key, value]) => `
            <div class="detail-item">
              <span>${escapeHtml(key)}</span>
              <strong>${escapeHtml(String(value))}</strong>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderPreprocessingResult(message) {
  const analysis = message?.analysis || {};
  const steps = Array.isArray(analysis.steps) ? analysis.steps : [];
  const warnings = Array.isArray(analysis.warnings) ? analysis.warnings : [];
  const plots = Array.isArray(analysis.plots) ? analysis.plots : [];
  const rawPlot = plots.find((item) => item?.kind === "raw");
  const processedPlot = plots.find((item) => item?.kind === "processed");
  const overlayPlot = plots.find((item) => item?.kind === "overlay");
  return `
    <div class="analysis-card">
      <div class="analysis-summary report-title">
        <p><strong>光谱预处理完成</strong></p>
        ${renderNarrativeBlock(message?.content || analysis.summary || "预处理完成。")}
      </div>
      ${
        steps.length
          ? `
            <div class="analysis-summary">
              <p><strong>处理步骤</strong></p>
              <ul class="analysis-list">
                ${steps.map((step) => `<li>${renderInlineMarkdown(step)}</li>`).join("")}
              </ul>
            </div>
          `
          : ""
      }
      <div class="preprocess-grid">
        <section class="figure-panel">
          <h4>处理前</h4>
          ${
            rawPlot?.url
              ? `<figure class="figure-tile"><img src="${escapeHtml(toAssetUrl(rawPlot.url))}" alt="raw-spectrum" /><figcaption>${escapeHtml(rawPlot.description || rawPlot.title || "原始光谱图")}</figcaption></figure>`
              : `<div class="analysis-empty">当前没有可展示的原始光谱图。</div>`
          }
        </section>
        <section class="figure-panel">
          <h4>处理后</h4>
          ${
            processedPlot?.url
              ? `<figure class="figure-tile"><img src="${escapeHtml(toAssetUrl(processedPlot.url))}" alt="processed-spectrum" /><figcaption>${escapeHtml(processedPlot.description || processedPlot.title || "预处理后光谱图")}</figcaption></figure>`
              : `<div class="analysis-empty">当前没有可展示的预处理后光谱图。</div>`
          }
        </section>
      </div>
      <section class="figure-panel overlay">
        <h4>前后叠加对比</h4>
        ${
          overlayPlot?.url
            ? `<figure class="figure-tile"><img src="${escapeHtml(toAssetUrl(overlayPlot.url))}" alt="overlay-spectrum" /><figcaption>${escapeHtml(overlayPlot.description || overlayPlot.title || "预处理前后叠加对比图")}</figcaption></figure>`
            : `<div class="analysis-empty">当前没有可展示的叠加对比图。</div>`
        }
      </section>
      ${
        analysis.output_file
          ? `
            <div class="detail-item">
              <span>输出文件</span>
              <strong>${escapeHtml(analysis.output_file)}</strong>
            </div>
          `
          : ""
      }
      ${renderMetricGrid(analysis.metrics || {})}
      ${renderPlots(analysis.plots || [])}
      ${warnings.length ? `<div class="analysis-summary soft"><p><strong>注意事项</strong></p><ul class="analysis-list compact">${warnings.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ul></div>` : ""}
    </div>
  `;
}

function renderPredictionResult(message) {
  const analysis = message?.analysis || {};
  const details = analysis.details || {};
  const confidence = details.confidence || {};
  const disagreement = details.model_disagreement || {};
  const structured = details.structured_explanation || {};
  const cards = [];
  if (analysis.predicted_value !== null && analysis.predicted_value !== undefined && analysis.predicted_value !== "") {
    cards.push(`
      <div class="analysis-block">
        <span>预测浓度</span>
        <strong>${escapeHtml(String(analysis.predicted_value))} ${escapeHtml(analysis.unit || "")}</strong>
      </div>
    `);
  }
  if (analysis.model_name || analysis.model_version) {
    cards.push(`
      <div class="analysis-block">
        <span>模型名称</span>
        <strong>${escapeHtml(analysis.model_name || analysis.model_version)}</strong>
      </div>
    `);
  }
  if (confidence.status) {
    cards.push(`
      <div class="analysis-block">
        <span>置信度</span>
        <strong>${escapeHtml(confidence.status)}</strong>
      </div>
    `);
  }
  if (disagreement.message) {
    cards.push(`
      <div class="analysis-block">
        <span>模型一致性</span>
        <strong>${escapeHtml(disagreement.message)}</strong>
      </div>
    `);
  }
  if (details.sample_file) {
    cards.push(`
      <div class="analysis-block">
        <span>样品文件</span>
        <strong>${escapeHtml(details.sample_file)}</strong>
      </div>
    `);
  }
  return `
    <div class="analysis-card">
      ${cards.length ? `<div class="analysis-hero">${cards.join("")}</div>` : ""}
      <div class="explanation-grid">
        ${renderListSection("结果摘要", structured.summary || [message?.content || analysis.summary || "预测完成。"], "当前未提供结果摘要。")}
        <section class="explanation-card">
          <h4>模型对比</h4>
          <div class="detail-list">
            ${structured?.model_comparison?.svr_prediction !== undefined ? `<div class="detail-item"><span>SVR</span><strong>${escapeHtml(String(structured.model_comparison.svr_prediction))}</strong></div>` : ""}
            ${structured?.model_comparison?.rf_prediction !== undefined ? `<div class="detail-item"><span>RF</span><strong>${escapeHtml(String(structured.model_comparison.rf_prediction))}</strong></div>` : ""}
            ${structured?.model_comparison?.absolute_difference !== undefined ? `<div class="detail-item"><span>绝对差异</span><strong>${escapeHtml(String(structured.model_comparison.absolute_difference))}</strong></div>` : ""}
            ${structured?.model_comparison?.relative_difference !== undefined ? `<div class="detail-item"><span>相对差异</span><strong>${escapeHtml(String(structured.model_comparison.relative_difference))}</strong></div>` : ""}
          </div>
        </section>
        ${renderEvidenceSection(structured)}
        ${renderSpectralFeaturesSection(structured)}
        ${renderListSection("风险提示", structured.risks || [], "当前未提供明显风险提示。")}
        ${renderListSection("建议", structured.suggestions || [], "当前未提供额外建议。")}
      </div>
      <div class="analysis-summary soft">
        <p><strong>补充说明</strong></p>
        ${renderNarrativeBlock(structured.explanation_text || message?.content || analysis.summary || "预测完成。")}
      </div>
      ${renderPlots(analysis.plots || [])}
    </div>
  `;
}

function renderUploadedSkillResult(message) {
  const analysis = message?.analysis || {};
  const details = analysis.details || {};
  const summary = analysis.summary || message?.content || details.analysis_summary || "文件分析完成。";
  const keyPoints = Array.isArray(details.key_points) ? details.key_points : [];
  const warnings = Array.isArray(details.warnings) ? details.warnings : [];
  const actionItems = Array.isArray(details.action_items) ? details.action_items : [];
  const findings = Array.isArray(details.findings) ? details.findings : [];
  const metadata = details.metadata && typeof details.metadata === "object" ? details.metadata : {};
  const entities = details.entities && typeof details.entities === "object" ? details.entities : {};
  const documentType = String(details.document_type || details.task_type || details.file_type || "").trim();
  const fieldCandidates = [
    ...(Array.isArray(entities.variables_or_fields) ? entities.variables_or_fields : []),
    ...(Array.isArray(details.key_fields) ? details.key_fields : []),
  ].filter(Boolean);
  return `
    <div class="analysis-card">
      <div class="analysis-summary report-title">
        <p><strong>文件分析结果</strong></p>
        ${renderNarrativeBlock(summary, { collapse: true, threshold: 1000 })}
      </div>
      ${
        documentType
          ? `<div class="skill-result-block markdown-summary"><strong>文档类型：</strong>${escapeHtml(documentType)}</div>`
          : ""
      }
      ${
        metadata.line_count || metadata.char_count
          ? `
            <div class="detail-list">
              ${metadata.line_count ? `<div class="detail-item"><span>行数</span><strong>${escapeHtml(String(metadata.line_count))}</strong></div>` : ""}
              ${metadata.char_count ? `<div class="detail-item"><span>字符数</span><strong>${escapeHtml(String(metadata.char_count))}</strong></div>` : ""}
            </div>
          `
          : ""
      }
      ${
        fieldCandidates.length
          ? `
            <section class="explanation-card">
              <h4>关键字段</h4>
              <ul class="analysis-list compact">
                ${fieldCandidates.slice(0, 10).map((item) => `<li>${renderInlineMarkdown(String(item))}</li>`).join("")}
              </ul>
            </section>
          `
          : ""
      }
      ${
        findings.length
          ? `
            <section class="explanation-card">
              <h4>主要内容</h4>
              <div class="detail-list">
                ${findings.slice(0, 6).map((finding) => {
                  const label = finding.label || finding.title || finding.name || "内容";
                  const value = finding.value || finding.description || finding.detail || finding.text || finding.summary || "";
                  return `<div class="detail-item"><span>${escapeHtml(String(label))}</span><strong>${renderInlineMarkdown(String(value || "未提供"))}</strong></div>`;
                }).join("")}
              </div>
            </section>
          `
          : ""
      }
      ${
        keyPoints.length
          ? `
            <section class="explanation-card">
              <h4>关键要点</h4>
              <ul class="analysis-list compact">
                ${keyPoints.map((item) => `<li>${renderInlineMarkdown(String(item))}</li>`).join("")}
              </ul>
            </section>
          `
          : ""
      }
      ${
        actionItems.length
          ? `
            <section class="explanation-card">
              <h4>建议</h4>
              <ul class="analysis-list compact">
                ${actionItems.map((item) => `<li>${renderInlineMarkdown(String(item))}</li>`).join("")}
              </ul>
            </section>
          `
          : ""
      }
      ${
        warnings.length
          ? `
            <section class="analysis-summary soft">
              <p><strong>注意事项</strong></p>
              <ul class="analysis-list compact">
                ${warnings.map((item) => `<li>${renderInlineMarkdown(String(item))}</li>`).join("")}
              </ul>
            </section>
          `
          : ""
      }
      ${
        message?.content && String(message.content).trim() && String(message.content).trim() !== String(summary).trim()
          ? `<details class="markdown-collapse"><summary>展开全文</summary>${renderNarrativeBlock(message.content, { collapse: false })}</details>`
          : ""
      }
    </div>
  `;
}

function renderModelStatusResult(message) {
  const analysis = message?.analysis || {};
  const details = analysis.details || {};
  return `
    <div class="analysis-card">
      <div class="analysis-summary">
        <p><strong>模型状态检查</strong></p>
        ${renderNarrativeBlock(message?.content || analysis.summary || "模型状态已更新。")}
      </div>
      <div class="detail-list">
        ${(analysis.model_name || analysis.model_version) ? `<div class="detail-item"><span>当前模型</span><strong>${escapeHtml(analysis.model_name || analysis.model_version)}</strong></div>` : ""}
        ${analysis.model_file_status ? `<div class="detail-item"><span>模型文件状态</span><strong>${escapeHtml(analysis.model_file_status)}</strong></div>` : ""}
        ${analysis.health_status ? `<div class="detail-item"><span>健康状态</span><strong>${escapeHtml(analysis.health_status)}</strong></div>` : ""}
        ${details.loadable !== null && details.loadable !== undefined ? `<div class="detail-item"><span>可加载性</span><strong>${details.loadable ? "可加载" : "加载失败"}</strong></div>` : ""}
      </div>
    </div>
  `;
}

function renderReportResult(message) {
  const analysis = message?.analysis || {};
  return `
    <div class="analysis-card">
      <div class="analysis-summary report-title">
        <p><strong>报告生成结果</strong></p>
        ${renderNarrativeBlock(message?.content || analysis.summary || "报告已生成。")}
      </div>
      <div class="detail-list">
        ${analysis.report_path ? `<div class="detail-item"><span>报告路径</span><strong>${escapeHtml(analysis.report_path)}</strong></div>` : ""}
        ${analysis.export_status ? `<div class="detail-item"><span>导出状态</span><strong>${escapeHtml(analysis.export_status)}</strong></div>` : ""}
        ${analysis.report_preview ? `<div class="detail-item"><span>摘要</span><strong>${escapeHtml(analysis.report_preview)}</strong></div>` : ""}
      </div>
    </div>
  `;
}

function renderGenericAnalysisResult(message) {
  const analysis = message?.analysis || {};
  return `
    <div class="analysis-card">
      <div class="analysis-summary report-title">
        ${renderNarrativeBlock(message?.content || analysis.summary || "处理完成。", { collapse: true, threshold: 900 })}
      </div>
      ${renderDetailRows("", analysis.details || {})}
    </div>
  `;
}

function renderAssistantResponse(payload) {
  const messages = Array.isArray(payload?.messages) && payload.messages.length
    ? payload.messages
    : [
        {
          role: "assistant",
          type: payload?.success === false ? "error" : "text",
          content: payload?.success === false
            ? (payload?.error_message || payload?.reply || "处理失败。")
            : (payload?.reply || payload?.message || ""),
          skill_name: payload?.skill_name,
          action_name: payload?.action_name,
          result_kind: "generic",
          skill_mode: payload?.skill_mode,
        },
      ];
  messages.forEach((message) => {
    const modelBadge = buildAssistantModelBadge(message, payload);
    if (message.type === "analysis") {
      const kind = message.result_kind || message.analysis?.result_kind || "generic";
      const traceBanner = buildAssistantSourceBadge(message, payload);
      if (kind === "preprocessing") {
        appendMessage("assistant", `${modelBadge}${traceBanner}${renderPreprocessingResult(message)}`, "analysis");
        return;
      }
      if (kind === "prediction") {
        appendMessage("assistant", `${modelBadge}${traceBanner}${renderPredictionResult(message)}`, "analysis");
        return;
      }
      if (kind === "model_status") {
        appendMessage("assistant", `${modelBadge}${traceBanner}${renderModelStatusResult(message)}`, "analysis");
        return;
      }
      if (kind === "report") {
        appendMessage("assistant", `${modelBadge}${traceBanner}${renderReportResult(message)}`, "analysis");
        return;
      }
      if (kind === "uploaded_skill") {
        appendMessage("assistant", `${modelBadge}${traceBanner}${renderUploadedSkillResult(message)}`, "analysis");
        return;
      }
      appendMessage("assistant", `${modelBadge}${traceBanner}${renderGenericAnalysisResult(message)}`, "analysis");
      return;
    }
    if (message.type === "error") {
      appendMessage("assistant", `${modelBadge}${buildAssistantSourceBadge(message, payload)}<p class="error-message">${renderInlineMarkdown(message.content || "分析失败。")}</p>`, "error");
      return;
    }
    appendMessage("assistant", `${modelBadge}${buildAssistantSourceBadge(message, payload)}${renderMarkdown(message.content || "")}${renderWebSearchSources(payload)}`, "text");
  });
}

function renderModelList(payload = {}) {
  const body = $("modelListBody");
  if (!body) {
    return;
  }
  const providers = Array.isArray(payload?.providers) ? payload.providers : [];
  const models = Array.isArray(payload?.models) ? payload.models : [];
  const current = payload?.current || {};
  const selectedProviderId = payload?.selectedProviderId || current.provider_id || "";
  const currentDisplay = current.provider_name && current.model_id
    ? `${current.provider_name} / ${current.model_id}`
    : "未选择";
  if (!providers.length) {
    body.innerHTML = `<div class="model-list-empty">当前没有可展示的模型。</div>`;
    return;
  }
  body.innerHTML = `
    <div class="model-current-summary">
      <span>当前平台</span>
      <strong>${escapeHtml(current.provider_name || "未选择")}</strong>
      <span>当前模型</span>
      <strong>${escapeHtml(current.model_id || "未选择")}</strong>
    </div>
    <div class="provider-model-grid">
      <section class="model-provider-column">
        ${providers
          .map((provider) => `
            <button
              type="button"
              class="provider-list-item ${provider.provider_id === selectedProviderId ? "active" : ""}"
              data-provider-select="${escapeHtml(provider.provider_id || "")}"
            >
              <strong>${escapeHtml(provider.display_name || provider.provider_id || "平台")}</strong>
              <span>${provider.configured || provider.provider_id === "ollama" ? "可用" : "未配置"}</span>
              ${provider.reason ? `<p class="model-list-reason">${escapeHtml(provider.reason)}</p>` : ""}
            </button>
          `)
          .join("")}
      </section>
      <section class="model-provider-group">
        <div class="model-provider-head">${escapeHtml(providers.find((item) => item.provider_id === selectedProviderId)?.display_name || "请选择平台")}</div>
        <div class="model-provider-list">
          ${models.length
            ? models
              .map((model) => {
                  const selected = Boolean(model.selected);
                  const categorySummary = buildModelCategorySummary(model);
                  return `
                    <button
                      type="button"
                      class="model-list-item ${selected ? "selected" : ""}"
                      data-provider="${escapeHtml(selectedProviderId)}"
                      data-model="${escapeHtml(model.id || "")}"
                    >
                      <div class="model-list-title">
                        <strong>${escapeHtml(model.display_name || model.id || "未命名模型")}</strong>
                        <span class="model-list-check">${selected ? "√" : ""}</span>
                      </div>
                      <div class="model-list-meta">
                        <span class="model-badge">${escapeHtml(model.id || "")}</span>
                        ${categorySummary.chips}
                        <span class="model-badge ${categorySummary.status === "已确认" ? "ok" : "warn"}">${escapeHtml(categorySummary.status)}</span>
                      </div>
                      <p class="model-list-summary">
                        分类：${escapeHtml(categorySummary.summary)}
                        ${categorySummary.source ? ` · 来源：${escapeHtml(categorySummary.source)}` : ""}
                      </p>
                    </button>
                  `;
                })
                .join("")
            : `<div class="model-list-empty">当前平台下没有可展示的模型。</div>`}
        </div>
      </section>
    </div>
  `;

  body.querySelectorAll("[data-provider-select]").forEach((button) => {
    button.addEventListener("click", async () => {
      const selectedProvider = providers.find((item) => item.provider_id === (button.dataset.providerSelect || ""));
      if (selectedProvider && !selectedProvider.configured && selectedProvider.provider_id !== "ollama") {
        showToast(
          `当前平台 API Key 未配置，请先在 .env 中填写 ${selectedProvider.api_key_env || "对应 API Key"}`,
          "info",
        );
      }
      await loadProviderModelsSafely(button.dataset.providerSelect || "");
    });
  });
  body.querySelectorAll("[data-provider][data-model]").forEach((button) => {
    button.addEventListener("click", async () => {
      await switchModel(button.dataset.provider || "", button.dataset.model || "");
    });
  });
}

function renderWorkspacePanel() {
  const body = $("workspacePanelBody");
  if (!body) {
    return;
  }
  const files = state.workspacePayload.files || {};
  const context = state.workspacePayload.context || {};
  const tasks = Array.isArray(state.workspacePayload.tasks?.tasks) ? state.workspacePayload.tasks.tasks : [];
  const taskTraces = state.workspacePayload.taskTraces || {};
  const messages = Array.isArray(state.workspacePayload.messages?.messages) ? state.workspacePayload.messages.messages : [];
  const renderFileList = (items = [], emptyText) => {
    if (!items.length) {
      return `<div class="workspace-empty">${escapeHtml(emptyText)}</div>`;
    }
    return `
      <div class="workspace-file-list">
        ${items
          .map(
            (item) => `
              <div class="workspace-file-item">
                <strong>${escapeHtml(item.original_name || item.filename || "未命名文件")}</strong>
                <span>${escapeHtml(item.mime_type || "unknown")} · ${escapeHtml(String(item.size || 0))} bytes</span>
              </div>
            `,
          )
          .join("")}
      </div>
    `;
  };
  const renderTasks = () => {
    if (!tasks.length) {
      return `<div class="workspace-empty">当前会话还没有任务执行记录。</div>`;
    }
    return `
      <div class="workspace-task-list">
        ${tasks
          .slice()
          .reverse()
          .map(
            (task) => `
              <article class="workspace-task-card ${task.status === "failed" ? "failed" : ""}">
                <div class="workspace-task-head">
                  <strong>${escapeHtml(task.intent || "unknown")}</strong>
                  <span>${escapeHtml(task.status || "unknown")}</span>
                </div>
                ${task.selected_skill ? `<p>已选择 Skill：${escapeHtml(task.selected_skill)}</p>` : ""}
                ${task.selected_ability ? `<p>已执行能力：${escapeHtml(task.selected_ability)}</p>` : ""}
                ${
                  Array.isArray(taskTraces[task.task_id]?.steps) && taskTraces[task.task_id].steps.length
                    ? `<div class="workspace-step-list">${taskTraces[task.task_id].steps
                        .map((step) => `<div><span>${escapeHtml(step.status || "")}</span><strong>${escapeHtml(step.name || "")}</strong></div>`)
                        .join("")}</div>`
                    : ""
                }
                ${
                  Array.isArray(taskTraces[task.task_id]?.skill_runs) && taskTraces[task.task_id].skill_runs.length
                    ? `<div class="workspace-skillrun-list">${taskTraces[task.task_id].skill_runs
                        .map(
                          (run) => `
                            <div class="workspace-skillrun-card ${run.status === "failed" ? "failed" : ""}">
                              <strong>${escapeHtml(run.skill_name || "Skill")}</strong>
                              <span>${escapeHtml(run.ability_name || "default")} · ${escapeHtml(run.status || "")}</span>
                              ${run.raw_result_summary ? `<p>${escapeHtml(run.raw_result_summary)}</p>` : ""}
                            </div>
                          `,
                        )
                        .join("")}</div>`
                    : ""
                }
                ${
                  Array.isArray(task.output_files) && task.output_files.length
                    ? `<p>已生成结果：${task.output_files.map((item) => escapeHtml(item.filename || item.path || "output")).join("、")}</p>`
                    : ""
                }
                ${task.error_message ? `<p class="error-message">失败原因：${escapeHtml(task.error_message)}</p><p>建议操作：检查输入文件、API Key 或 Skill 配置后重试。</p>` : ""}
              </article>
            `,
          )
          .join("")}
      </div>
    `;
  };
  body.innerHTML = `
    <section class="workspace-section">
      <h3>上下文</h3>
      <div class="workspace-context-card">
        <p><strong>会话：</strong>${escapeHtml(state.sessionId || "未创建")}</p>
        <p><strong>活跃文件：</strong>${escapeHtml(String((context.active_files || []).length || 0))}</p>
        <details>
          <summary>查看摘要</summary>
          ${renderMarkdownWithCollapse(context.context_summary || "暂无上下文摘要。", { threshold: 600, label: "展开摘要" })}
        </details>
      </div>
    </section>
    <section class="workspace-section">
      <h3>Uploads</h3>
      ${renderFileList(files.uploads || [], "还没有上传文件。")}
    </section>
    <section class="workspace-section">
      <h3>Outputs</h3>
      ${renderFileList(files.outputs || [], "还没有输出文件。")}
    </section>
    <section class="workspace-section">
      <h3>任务执行记录</h3>
      ${renderTasks()}
    </section>
    <section class="workspace-section">
      <h3>最近消息</h3>
      ${
        messages.length
          ? `<div class="workspace-message-list">${messages
              .slice()
              .reverse()
              .map((item) => `<div class="workspace-message-item"><span>${escapeHtml(item.role || "")}</span><p>${escapeHtml(item.content || "")}</p></div>`)
              .join("")}</div>`
          : `<div class="workspace-empty">暂无消息日志。</div>`
      }
    </section>
  `;
}

async function refreshWorkspacePanel() {
  if (!state.sessionId) {
    renderWorkspacePanel();
    return;
  }
  const [files, context, tasks, messages] = await Promise.all([
    getWorkspaceFiles(state.sessionId, state.userId),
    getWorkspaceContext(state.sessionId, state.userId),
    getConversationTasks(state.sessionId, state.userId),
    getConversationMessages(state.sessionId, state.userId, 20),
  ]);
  const taskItems = Array.isArray(tasks?.tasks) ? tasks.tasks : [];
  const traceResults = await Promise.allSettled(taskItems.slice(-8).map((task) => getTaskTrace(task.task_id)));
  const taskTraces = {};
  traceResults.forEach((result) => {
    if (result.status === "fulfilled" && result.value?.success && result.value.task?.task_id) {
      taskTraces[result.value.task.task_id] = result.value;
    }
  });
  state.workspacePayload = { files, context, tasks, messages, taskTraces };
  renderWorkspacePanel();
}

async function openWorkspacePanel() {
  state.workspaceOpen = true;
  $("workspacePanel")?.classList.remove("hidden");
  $("workspacePanel")?.setAttribute("aria-hidden", "false");
  await refreshWorkspacePanel();
}

function closeWorkspacePanel() {
  state.workspaceOpen = false;
  $("workspacePanel")?.classList.add("hidden");
  $("workspacePanel")?.setAttribute("aria-hidden", "true");
}

async function switchModel(provider, model) {
  if (!provider || !model) {
    return;
  }
  try {
    debugLog("开始切换大模型：", provider, model);
    const targetProvider = (state.llmModelsPayload.providers || []).find((item) => item.provider_id === provider);
    if (targetProvider && !targetProvider.configured && provider !== "ollama") {
      throw new Error(`当前平台 API Key 未配置，请先在 .env 中填写 ${targetProvider.api_key_env || "对应 API Key"}`);
    }
    const response = await switchLlmModel(provider, model, state.sessionId || null, state.userId);
    if (!response.success) {
      throw new Error(response.error_message || "切换模型失败");
    }
    await Promise.allSettled([loadLlmModelsSafely(provider)]);
    renderModelList(state.llmModelsPayload);
    $("topLlmModel").textContent = `${response.provider_name || provider} / ${response.model_id || model}`;
    showToast(`已切换到：${response.provider_name || provider} / ${response.model_id || model}`, "success");
    debugLog("大模型切换完成：", response);
  } catch (error) {
    console.error("切换模型失败：", error);
    showToast(`切换失败：${error.message || "未知错误"}`, "error");
  }
}

function bindComposerEvents() {
  const fileButton = $("fileButton");
  const fileInput = $("fileInput");
  const sendButton = $("sendButton");
  const messageInput = $("messageInput");

  if (!fileButton) {
    console.error("找不到 fileButton，无法绑定上传按钮事件");
    return;
  }
  if (!fileInput) {
    console.error("找不到 fileInput，无法打开文件选择窗口");
    return;
  }

  fileButton.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    debugLog("点击了 + 上传按钮");
    fileInput.click();
  });

  fileInput.addEventListener("change", handleFileSelect);

  if (sendButton) {
    sendButton.addEventListener("click", (event) => {
      event.preventDefault();
      sendChatMessage();
    });
  }

  if (messageInput) {
    messageInput.addEventListener("input", autoResizeTextarea);
    messageInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendChatMessage();
      }
    });
  }
}

function bindPageEvents() {
  $("newSessionBtn")?.addEventListener("click", handleNewSession);
  $("clearMemoryBtn")?.addEventListener("click", handleClearSessionMemory);
  $("inspectMemoryBtn")?.addEventListener("click", handleInspectSession);

  $("skillsButton")?.addEventListener("click", openSkillsPanel);
  $("skillsManageBtn")?.addEventListener("click", openSkillsPanel);
  $("closeSkillsPanelBtn")?.addEventListener("click", closeSkillsPanel);
  $("skillsPanelBackdrop")?.addEventListener("click", closeSkillsPanel);
  $("refreshSkillsBtn")?.addEventListener("click", refreshSkillsPanel);
  $("uploadSkillBtn")?.addEventListener("click", () => $("skillZipInput")?.click());
  $("skillZipInput")?.addEventListener("change", handleSkillZipSelect);
  $("workspaceButton")?.addEventListener("click", openWorkspacePanel);
  $("closeWorkspacePanelBtn")?.addEventListener("click", closeWorkspacePanel);
  $("workspacePanelBackdrop")?.addEventListener("click", closeWorkspacePanel);
  $("refreshWorkspaceBtn")?.addEventListener("click", async () => {
    await refreshWorkspacePanel();
    showToast("已刷新工作区", "info");
  });

  $("modelListBtn")?.addEventListener("click", (event) => {
    event.stopPropagation();
    if (state.modelListOpen) {
      closeModelList();
    } else {
      openModelList();
    }
  });
  $("closeModelListBtn")?.addEventListener("click", closeModelList);
  $("refreshModelListBtn")?.addEventListener("click", async () => {
    const response = await refreshLlmModels();
    if (!response.success) {
      showToast(response.message || response.error_message || "刷新失败", "error");
    }
    await loadLlmModelsSafely();
    if (state.modelListOpen) {
      renderModelList(state.llmModelsPayload);
    }
    showToast(response.message || "已刷新大模型列表", "info");
  });
  $("recentExperimentBtn")?.addEventListener("click", () => sendChatMessage("最近记录"));
  $("refreshDashboardBtn")?.addEventListener("click", refreshDashboard);

  document.addEventListener("click", (event) => {
    const wrap = document.querySelector(".model-menu-wrap");
    if (state.modelListOpen && wrap && !wrap.contains(event.target)) {
      closeModelList();
    }
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeSkillsPanel();
      closeWorkspacePanel();
      closeModelList();
    }
  });
}

async function loadRamanStatus() {
  const currentModelResponse = await getCurrentRamanModel();
  if (!currentModelResponse.success) {
    throw new Error(currentModelResponse.error_message || "获取当前模型失败");
  }

  state.currentModel = currentModelResponse.data || {};
  $("backendStatus").textContent = "已连接";
  $("topRamanModel").textContent = state.currentModel.model_version || "未知";

  const artifactResponse = await checkCurrentModel(state.currentModel.model_version);
  if (!artifactResponse.success) {
    $("topArtifactStatus").textContent = artifactResponse.error_message || "异常";
    return;
  }

  const missingFiles = (artifactResponse.data || {}).missing_files || [];
  $("topArtifactStatus").textContent = missingFiles.length ? `缺失 ${missingFiles.length} 个` : "正常";
}

async function loadRamanStatusSafely() {
  try {
    await loadRamanStatus();
  } catch (error) {
    console.error("加载状态失败：", error);
    $("backendStatus").textContent = "连接异常";
    $("topRamanModel").textContent = "加载失败";
    $("topArtifactStatus").textContent = "检查失败";
  }
}

async function loadLlmModels() {
  return loadLlmModelsSafely();
}

async function loadProviderModelsSafely(providerId) {
  try {
    const targetProviderId = providerId || state.llmModelsPayload.selectedProviderId || state.llmModelsPayload.current?.provider_id || "sensenova";
    const modelsResponse = await getProviderModels(targetProviderId, state.sessionId || null, state.userId);
    if (!modelsResponse.success) {
      throw new Error(modelsResponse.error_message || "加载平台模型失败");
    }
    state.llmModelsPayload.selectedProviderId = targetProviderId;
    state.llmModelsPayload.models = Array.isArray(modelsResponse.items) ? modelsResponse.items : [];
    renderModelList(state.llmModelsPayload);
  } catch (error) {
    console.error("加载平台模型失败：", error);
    showToast(`加载模型失败：${error.message || "未知错误"}`, "error");
  }
}

async function loadLlmModelsSafely(preferredProviderId = "") {
  try {
    const [providersResponse, currentResponse] = await Promise.all([
      getModelProviders(),
      getCurrentLlmModel(state.sessionId || null, state.userId),
    ]);
    if (!providersResponse.success) {
      throw new Error(providersResponse.error_message || "加载平台列表失败");
    }
    if (!currentResponse.success) {
      throw new Error(currentResponse.error_message || "加载当前模型失败");
    }
    const providers = Array.isArray(providersResponse.items) ? providersResponse.items : [];
    const current = currentResponse;
    const selectedProviderId = preferredProviderId || current.provider_id || providers[0]?.provider_id || "sensenova";
    const modelsResponse = await getProviderModels(selectedProviderId, state.sessionId || null, state.userId);
    if (!modelsResponse.success) {
      throw new Error(modelsResponse.error_message || "加载模型列表失败");
    }
    state.llmModelsPayload = {
      providers,
      current,
      selectedProviderId,
      models: Array.isArray(modelsResponse.items) ? modelsResponse.items : [],
    };
    renderModelList(state.llmModelsPayload);
    $("topLlmModel").textContent = `${current.provider_name || "未知平台"} / ${current.model_id || "未知模型"}`;
  } catch (error) {
    console.error("加载模型列表失败：", error);
    const body = $("modelListBody");
    if (body) {
      body.innerHTML = `<div class="model-list-empty">${escapeHtml(error.message || "模型列表加载失败")}</div>`;
    }
  }
}

async function loadSkills() {
  const response = await fetchSkills();
  if (!response.success) {
    throw new Error(response.error_message || "加载 Skills 失败");
  }
  state.skillsPayload = response;
  renderSkillsButton(response);
  renderSkillsPanel(response);
}

async function loadSkillsSafely() {
  const target = $("skillsButtonCount");
  if (target) {
    target.textContent = "加载中";
  }

  try {
    await loadSkills();
  } catch (error) {
    state.skillsPayload = null;
    renderSkillsButtonError(error);
  }
}

async function refreshDashboard() {
  if (state.refreshingDashboard) {
    return;
  }
  state.refreshingDashboard = true;
  const button = $("refreshDashboardBtn");
  const originalText = button?.textContent || "刷新";
  if (button) {
    button.disabled = true;
    button.textContent = "刷新中...";
  }
  debugLog("开始刷新工作台信息");
  const results = await Promise.allSettled([loadRamanStatusSafely(), loadLlmModelsSafely(), loadSkillsSafely()]);
  if (state.workspaceOpen) {
    await refreshWorkspacePanel();
  }
  results.forEach((result, index) => {
    if (result.status === "rejected") {
      console.error(`刷新任务 ${index + 1} 失败：`, result.reason);
    }
  });
  if (state.modelListOpen) {
    renderModelList(state.llmModelsPayload);
  }
  debugLog("工作台刷新完成");
  state.refreshingDashboard = false;
  if (button) {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function sendChatMessage(presetMessage = "") {
  if (state.chatBusy) {
    return;
  }

  const input = $("messageInput");
  const message = (presetMessage || input?.value || "").trim();
  const selectedFile = state.selectedFile;
  const timeoutMs = getChatRequestTimeout({ hasFile: Boolean(selectedFile), message });

  if (!message && !selectedFile) {
    setChatStatus("请输入消息，或者先选择一个文件。");
    return;
  }

  appendMessage("user", `<p>${escapeHtml(message || "请分析这个文件")}</p>`, "text");
  if (selectedFile) {
    appendFileCard(selectedFile);
  }

  if (input) {
    input.value = "";
    autoResizeTextarea();
  }

  setBusy(true, selectedFile ? "正在上传文件并分析..." : "正在思考...");
  renderTypingMessage(selectedFile ? "正在分析文件内容，可能需要几十秒，请稍候..." : "正在处理，请稍候...");

  try {
    const requestStartedAt = performance.now();
    const currentLlm = state.llmModelsPayload.current || {};
    const response = await sendAgentChat({
      message,
      sessionId: state.sessionId || "",
      userId: state.userId,
      debug: $("chatDebug")?.checked || false,
      file: selectedFile,
      metadata: {
        remarks: "",
        timeoutMs,
        providerId: currentLlm.provider_id || undefined,
        modelId: currentLlm.model_id || undefined,
      },
    });
    response.client_elapsed_ms = Math.round(performance.now() - requestStartedAt);

    removeTypingMessage();
    setBusy(false);

    if (response.conversation_id || response.session_id) {
      state.sessionId = response.conversation_id || response.session_id;
      persistSessionId(state.sessionId);
    }

    const treatAsSuccess = response.success === true || (response.reply && !response.error_message);
    if (!treatAsSuccess) {
      console.error("发送消息失败：", response);
      const friendlyMessage = escapeHtml(formatResponseError(response));
      appendMessage("assistant", `<p class="error-message">${friendlyMessage}</p>`, "error");
      return;
    }

    renderAssistantResponse(response);
    const responseModelInfo = response.model_info || response.llm_model_info || {};
    const usedProviderId = response.provider_id || responseModelInfo.provider || responseModelInfo.provider_id;
    const usedModelId = response.model_id || responseModelInfo.model || responseModelInfo.model_id;
    const usedProviderName = responseModelInfo.provider_display_name || responseModelInfo.provider_name || usedProviderId;
    if (usedProviderId && usedModelId) {
      state.llmModelsPayload.current = {
        ...(state.llmModelsPayload.current || {}),
        provider_id: usedProviderId,
        provider_name: usedProviderName,
        model_id: usedModelId,
        model_name: responseModelInfo.model_display_name || responseModelInfo.model_name || usedModelId,
      };
      $("topLlmModel").textContent = `${usedProviderName || "未知平台"} / ${usedModelId}`;
    }
    state.selectedFile = null;
    const fileInput = $("fileInput");
    if (fileInput) {
      fileInput.value = "";
    }
    renderSelectedFileChip(null);
    if (input) {
      input.value = "";
    }
    autoResizeTextarea();
    loadRamanStatusSafely();
    if (state.workspaceOpen) {
      refreshWorkspacePanel();
    }
  } catch (error) {
    removeTypingMessage();
    setBusy(false);
    console.error("发送消息失败：", error);
    appendMessage("assistant", `<p class="error-message">发送失败：${escapeHtml(error.message || "未知错误")}</p>`, "error");
  }
}

function restoreSessionIfNeeded() {
  persistSessionId(state.sessionId);
}

function initApp() {
  if (state.initialized) {
    return;
  }
  state.initialized = true;

  bindComposerEvents();
  bindPageEvents();
  restoreSessionIfNeeded();
  renderWelcomeMessage();
  autoResizeTextarea();
  setChatStatus(state.sessionId ? `当前会话：${state.sessionId}` : "可以直接提问，或上传任意文件后发送。");
  loadLlmModelsSafely();
  loadRamanStatusSafely();
  loadSkillsSafely();
}

initApp();
