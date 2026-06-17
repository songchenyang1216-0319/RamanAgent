import {
  activateFile,
  activateTrainedRamanModel,
  archiveProject,
  attachProjectFile,
  batchAnalyze,
  cancelTask,
  clearAuthToken,
  createProject,
  createRamanDataset,
  checkCurrentModel,
  deleteFile as requestDeleteFile,
  deleteReport as requestDeleteReport,
  downloadBatchCsv,
  downloadFileById,
  downloadReport,
  approveAgentConfirmation,
  executeToolAction,
  exportReport,
  getAuditLogs,
  getAuthMe,
  getCurrentRamanModel,
  getConversationMessages,
  getFiles,
  getCurrentLlmModel,
  getRamanAlgorithms,
  getRamanDatasets,
  getRamanPipelineHistory,
  getRamanPipelineTemplates,
  getModelProviders,
  getProjects,
  getReports,
  getTaskLogs,
  getTaskResult,
  getTaskArtifacts,
  getToolCatalog,
  getTrainedRamanModels,
  getProviderModels,
  getReport,
  getSkillLogs,
  getTasks,
  getBatchSummary,
  rejectAgentConfirmation,
  previewFile,
  getProjectFiles,
  getProjectReports,
  getProjectTasks,
  loginUser,
  loadSkills as fetchSkills,
  deleteSkill as requestDeleteSkill,
  logoutUser,
  sendAgentChat,
  sendAgentChatStream,
  setAuthToken,
  setActionEnabled as requestSetActionEnabled,
  setSkillEnabled as requestSetSkillEnabled,
  switchLlmModel,
  refreshLlmModels,
  runRamanBenchmark,
  runRamanPipeline,
  runRamanTraining,
  toAssetUrl,
  registerUser,
  runFileOcr,
  streamTaskEvents,
  uploadWorkspaceFile,
  uploadSkillZip as requestUploadSkillZip,
  validateRamanPipeline,
  validateToolAction,
} from "./js/api.js";
import { initConversationSidebar } from "./js/sidebar.js";
import { renderArtifacts } from "./js/artifact-renderer.js";
import { initKnowledgeBasePanel } from "./js/knowledge-base-panel.js";

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
  workspacePayload: { files: null, context: null, tasks: null, messages: null, knowledgeBases: null, conversationKnowledgeBases: null, ragStatus: null },
  workspaceOpen: false,
  userId: "default_user",
  selectedFile: null,
  selectedFiles: [],
  skillsPayload: null,
  skillLogsPayload: { logs: [] },
  expandedSkillNames: new Set(),
  chatBusy: false,
  typingNode: null,
  streamAbortController: null,
  activeStreamNode: null,
  useStreaming: true,
  initialized: false,
  modelListOpen: false,
  uploadingSkill: false,
  toastTimer: null,
  authToken: "",
  currentUser: null,
  authBusy: false,
  projectsPayload: { projects: [] },
  reportsPayload: { reports: [] },
  dashboardFilesPayload: { files: [] },
  dashboardTasksPayload: { tasks: [] },
  selectedProjectId: "",
  selectedBatchFileIds: new Set(),
  conversationSidebar: null,
  knowledgeBasePanel: null,
  ramanPipelineOpen: false,
  ramanPipelinePayload: { algorithms: [], templates: [], history: [] },
  ramanPipelineSteps: [],
  selectedPipelineTemplate: "basic_preprocessing",
  ramanPipelineResult: null,
  ramanPipelineBusy: false,
  toolCatalogPayload: { tools: {} },
  auditLogsPayload: { logs: [] },
  ramanLabPayload: { datasets: [], models: [], lastBenchmark: null, lastTraining: null },
  taskEventAbortController: null,
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
  const sidebarUser = $("sidebarUserLabel");
  if (sidebarUser) {
    sidebarUser.textContent = state.currentUser?.username || state.userId || "default_user";
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
    return `${message}${errorCode}：${errorMessage} 可以稍后在左侧聊天记录中重新打开会话，或到工作区文件查看上传文件。`;
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
  const stopStreamButton = $("stopStreamButton");
  const fileButton = $("fileButton");
  const messageInput = $("messageInput");
  if (sendButton) {
    sendButton.disabled = isBusy;
  }
  if (stopStreamButton) {
    stopStreamButton.classList.toggle("hidden", !isBusy || !state.streamAbortController);
    stopStreamButton.disabled = !isBusy || !state.streamAbortController;
  }
  if (fileButton) {
    fileButton.disabled = isBusy;
  }
  if (messageInput) {
    messageInput.disabled = isBusy;
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

function appendStreamingAssistantMessage() {
  const row = appendMessage(
    "assistant",
    `
      <div class="agent-stream-card">
        <details class="agent-stream-thinking" data-stream-thinking open>
          <summary class="agent-stream-thinking-summary" data-stream-thinking-summary>正在分析问题...</summary>
          <div class="agent-trace" data-stream-trace></div>
        </details>
        <div class="assistant-stream-answer markdown-body" data-stream-answer>
          <span class="muted-text">正在等待响应...</span>
        </div>
      </div>
    `,
    "text",
    "流式处理中",
  );
  const context = {
    row,
    thinkingNode: row?.querySelector("[data-stream-thinking]") || null,
    thinkingSummaryNode: row?.querySelector("[data-stream-thinking-summary]") || null,
    traceNode: row?.querySelector("[data-stream-trace]") || null,
    answerNode: row?.querySelector("[data-stream-answer]") || null,
    answerText: "",
    finalResponse: null,
    receivedAnyEvent: false,
    receivedFinal: false,
  };
  state.activeStreamNode = row;
  return context;
}

function updateStreamThinkingSummary(streamContext, text = "") {
  if (!streamContext?.thinkingSummaryNode) {
    return;
  }
  streamContext.thinkingSummaryNode.textContent = text || "查看处理过程";
}

function finalizeStreamThinking(streamContext, eventPayload = {}) {
  if (!streamContext?.thinkingNode) {
    return;
  }
  const elapsedMs = Number(eventPayload?.data?.elapsed_ms || 0);
  updateStreamThinkingSummary(
    streamContext,
    elapsedMs > 0 ? `已处理 ${formatDurationMs(elapsedMs)}，查看过程` : "已完成，查看过程",
  );
  streamContext.thinkingNode.open = false;
}

function getStreamTraceText(eventName, eventPayload = {}) {
  const content = String(eventPayload.content || summarizeStreamEventData(eventPayload.data) || "").trim();
  const data = eventPayload.data || {};
  const route = String(data.route_type || data.route || "").trim();
  const skillName = String(data.skill_name || "").trim();
  const toolName = String(data.tool_name || "").trim();
  const actionName = String(data.action_name || "").trim();
  if (eventName === "final") {
    return "已生成最终答复。";
  }
  if (eventName === "done") {
    return "本次处理已结束。";
  }
  if (eventName === "error") {
    return content || "处理过程中出现错误。";
  }
  if (eventName === "start") {
    return "我已收到你的消息，开始整理请求。";
  }
  if (eventName === "status") {
    return content || "我正在推进当前步骤。";
  }
  if (eventName === "planner") {
    return content || "我正在判断这次该走哪条处理路径。";
  }
  if (eventName === "tool_start") {
    const target = [skillName ? `Skill ${skillName}` : "", toolName ? `工具 ${toolName}` : "", actionName ? `动作 ${actionName}` : ""]
      .filter(Boolean)
      .join("，");
    return target ? `我准备调用${target}。` : (content || "我准备调用合适的工具。");
  }
  if (eventName === "tool_progress") {
    return content || "工具正在处理中。";
  }
  if (eventName === "tool_result") {
    return content || "工具已经执行完成。";
  }
  return content || (route ? `当前处理路径：${route}。` : "处理中。");
}

function appendStreamTrace(streamContext, eventPayload = {}) {
  const traceNode = streamContext?.traceNode;
  if (!traceNode || eventPayload.visible === false) {
    return;
  }
  const eventName = String(eventPayload.event || "status");
  if (eventName === "delta") {
    return;
  }
  updateStreamThinkingSummary(streamContext, "正在分析问题...");
  const item = document.createElement("div");
  item.className = `trace-item trace-${eventName}`;
  const cardHtml = buildStreamTraceCardHtml(eventName, eventPayload);
  if (cardHtml) {
    item.innerHTML = cardHtml;
    wireStreamTraceCardActions(item, eventPayload);
  } else {
    item.textContent = getStreamTraceText(eventName, eventPayload);
  }
  traceNode.appendChild(item);
  scrollToBottom();
}

function buildStreamTraceCardHtml(eventName, eventPayload = {}) {
  const data = eventPayload.data || {};
  const confirmation = data.confirmation_payload || data.confirmation || data.response?.confirmation_payload || null;
  if (confirmation) {
    return `
      <div class="tool-trace-card confirmation-card">
        <div class="tool-trace-card-head">
          <strong>需要确认</strong>
          <span>${escapeHtml(confirmation.danger_level || "high")}</span>
        </div>
        <div class="tool-trace-card-body">
          <div>${escapeHtml(confirmation.message || "该操作需要你确认后才能继续。")}</div>
          <div class="tool-trace-meta">${escapeHtml([confirmation.tool_name, confirmation.action_name].filter(Boolean).join("."))}</div>
        </div>
        <div class="inline-actions">
          <button class="pill-button small ghost" type="button" data-confirm-approve="${escapeHtml(confirmation.confirmation_id || "")}">批准</button>
          <button class="pill-button small ghost" type="button" data-confirm-reject="${escapeHtml(confirmation.confirmation_id || "")}">拒绝</button>
        </div>
      </div>
    `;
  }
  const toolName = String(data.tool_name || data.response?.tool_name || "").trim();
  const actionName = String(data.action_name || data.response?.action_name || "").trim();
  const source = String(data.source || data.tool_source || data.response?.source || "").trim();
  const errorCode = String(data.error_code || data.response?.error_code || "").trim();
  if (["tool_start", "tool_progress", "tool_result"].includes(eventName) || toolName || actionName) {
    const isMcp = source === "mcp" || toolName.startsWith("mcp_");
    return `
      <div class="tool-trace-card ${isMcp ? "mcp-tool-card" : ""}">
        <div class="tool-trace-card-head">
          <strong>${escapeHtml(toolName || "工具调用")}</strong>
          <span>${escapeHtml(actionName || eventName)}</span>
        </div>
        <div class="tool-trace-card-body">
          <div>${escapeHtml(getStreamTraceText(eventName, eventPayload))}</div>
          ${errorCode ? `<div class="tool-trace-meta error-message">${escapeHtml(errorCode)}</div>` : ""}
          ${isMcp ? `<div class="tool-trace-meta">MCP 工具来源：${escapeHtml(source || "mcp")}</div>` : ""}
        </div>
      </div>
    `;
  }
  if (eventName === "sandbox_log" || data.sandbox) {
    return `
      <div class="tool-trace-card sandbox-log-card">
        <div class="tool-trace-card-head">
          <strong>Sandbox</strong>
          <span>${escapeHtml(data.status || "log")}</span>
        </div>
        <pre>${escapeHtml(eventPayload.content || data.message || "沙盒执行日志")}</pre>
      </div>
    `;
  }
  return "";
}

function wireStreamTraceCardActions(item, eventPayload = {}) {
  item.querySelectorAll("[data-confirm-approve]").forEach((button) => {
    button.addEventListener("click", async () => {
      const confirmationId = button.dataset.confirmApprove || "";
      const response = await approveAgentConfirmation(confirmationId);
      showToast(response.success ? "已批准该操作，请重新发送或继续执行原请求。" : (response.error_message || "批准失败"), response.success ? "success" : "error");
      button.disabled = true;
      item.querySelectorAll("[data-confirm-reject]").forEach((target) => { target.disabled = true; });
    });
  });
  item.querySelectorAll("[data-confirm-reject]").forEach((button) => {
    button.addEventListener("click", async () => {
      const confirmationId = button.dataset.confirmReject || "";
      const response = await rejectAgentConfirmation(confirmationId);
      showToast(response.success ? "已拒绝该操作。" : (response.error_message || "拒绝失败"), response.success ? "success" : "error");
      button.disabled = true;
      item.querySelectorAll("[data-confirm-approve]").forEach((target) => { target.disabled = true; });
    });
  });
}

function summarizeStreamEventData(data = {}) {
  if (!data || typeof data !== "object") {
    return "";
  }
  if (data.route) return `路径：${data.route}`;
  if (data.plan_type) return `计划：${data.plan_type}`;
  if (data.tool_name || data.action_name) return [data.tool_name, data.action_name].filter(Boolean).join(".");
  if (data.algorithm_id) return `算法：${data.algorithm_id}`;
  return "";
}

function appendStreamAnswer(streamContext, chunk = "") {
  if (!streamContext?.answerNode || !chunk) {
    return;
  }
  streamContext.answerText += chunk;
  streamContext.answerNode.innerHTML = renderMarkdown(streamContext.answerText || "");
  scrollToBottom();
}

function replaceStreamAnswer(streamContext, text = "") {
  if (!streamContext?.answerNode) {
    return;
  }
  streamContext.answerText = text;
  streamContext.answerNode.innerHTML = renderMarkdown(text || "");
  scrollToBottom();
}

function parseSseMessage(rawMessage) {
  const lines = String(rawMessage || "").split(/\r?\n/);
  let eventName = "";
  const dataLines = [];
  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  });
  const dataText = dataLines.join("\n").trim();
  if (!dataText) {
    return null;
  }
  const payload = JSON.parse(dataText);
  if (eventName && !payload.event) {
    payload.event = eventName;
  }
  return payload;
}

async function readSseStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const messages = buffer.split(/\n\n|\r\n\r\n/);
    buffer = messages.pop() || "";
    for (const message of messages) {
      const payload = parseSseMessage(message);
      if (payload) {
        onEvent(payload);
      }
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    const payload = parseSseMessage(buffer);
    if (payload) {
      onEvent(payload);
    }
  }
}

function handleStreamEvent(streamContext, eventPayload) {
  if (!streamContext || !eventPayload) {
    return;
  }
  streamContext.receivedAnyEvent = true;
  const eventName = String(eventPayload.event || "");
  if (eventPayload.conversation_id || eventPayload.session_id) {
    state.sessionId = eventPayload.conversation_id || eventPayload.session_id;
    persistSessionId(state.sessionId);
  }
  if (eventName === "delta") {
    appendStreamAnswer(streamContext, eventPayload.content || "");
    return;
  }
  if (eventName === "final") {
    streamContext.receivedFinal = true;
    streamContext.finalResponse = eventPayload.data?.response || null;
    const finalText = eventPayload.content || streamContext.finalResponse?.reply || streamContext.finalResponse?.llm_explanation || streamContext.finalResponse?.error_message || streamContext.answerText;
    if (finalText && finalText !== streamContext.answerText) {
      replaceStreamAnswer(streamContext, finalText);
    }
    appendStreamTrace(streamContext, eventPayload);
    finalizeStreamThinking(streamContext, eventPayload);
    return;
  }
  if (eventName === "error") {
    const errorText = eventPayload.content || "流式处理失败。";
    if (!streamContext.answerText) {
      streamContext.answerNode.innerHTML = `<p class="error-message">${escapeHtml(errorText)}</p>`;
    }
    appendStreamTrace(streamContext, eventPayload);
    updateStreamThinkingSummary(streamContext, "处理失败，查看过程");
    return;
  }
  appendStreamTrace(streamContext, eventPayload);
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

function renderRagSources(payload = {}) {
  const citations = Array.isArray(payload.citations)
    ? payload.citations
    : (Array.isArray(payload.data?.citations) ? payload.data.citations : []);
  if (payload.route !== "rag" && !citations.length) {
    return "";
  }
  const scopeLabel = {
    conversation: "会话文件 RAG",
    knowledge_base: "知识库 RAG",
    mixed: "混合 RAG",
  }[payload.rag_scope || payload.data?.rag_scope] || "RAG";
  const retrievalMode = payload.retrieval_mode || payload.data?.retrieval_mode || "unknown";
  const rerank = payload.rerank || payload.data?.rerank || payload.rag?.rerank || payload.data?.rag?.rerank || {};
  const rerankLabel = rerank.provider
    ? ` · rerank:${rerank.applied ? "on" : "off"}/${rerank.provider}`
    : "";
  const items = citations.slice(0, 6).map((item, index) => {
    const title = item.knowledge_base_name
      ? `${item.knowledge_base_name} / ${item.filename || "资料"}`
      : (item.filename || item.file_id || item.chunk_id || "来源");
    const location = [item.page ? `页 ${item.page}` : "", item.sheet ? `Sheet ${item.sheet}` : "", item.section || ""]
      .filter(Boolean)
      .join(" · ");
    return `
      <li>
        <strong>[${index + 1}] ${escapeHtml(title)}</strong>
        ${location ? `<span>${escapeHtml(location)}</span>` : ""}
        ${item.preview ? `<small>${escapeHtml(item.preview)}</small>` : ""}
      </li>
    `;
  }).join("");
  return `
    <details class="rag-sources" open>
      <summary>${escapeHtml(scopeLabel)} · ${escapeHtml(retrievalMode)}${escapeHtml(rerankLabel)} · ${citations.length} 个引用</summary>
      ${items ? `<ol>${items}</ol>` : "<p>没有返回可展示的引用片段。</p>"}
    </details>
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
      "<p>常见用法：<span class=\"inline-chip\">模型列表</span> <span class=\"inline-chip\">工作区文件</span> <span class=\"inline-chip\">Skills 管理</span></p>",
    ].join(""),
    "text",
    state.sessionId ? `已恢复 ${state.sessionId}` : "新会话",
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

function clearForNewConversation() {
  state.selectedFile = null;
  state.selectedFiles = [];
  const fileInput = $("fileInput");
  if (fileInput) {
    fileInput.value = "";
  }
  renderSelectedFileChip([]);
  clearChatWindow();
  setChatStatus("已创建新聊天，可以直接提问或上传文件。");
}

async function renderConversationMessages(conversationId) {
  if (!conversationId) {
    clearForNewConversation();
    return;
  }
  const response = await getConversationMessages(conversationId, state.userId, 200);
  if (!response.success) {
    showToast(response.error_message || "加载聊天消息失败", "error");
    return;
  }
  const container = $("chatMessages");
  if (container) {
    container.innerHTML = "";
  }
  removeTypingMessage();
  const messages = response.messages || [];
  if (!messages.length) {
    renderWelcomeMessage();
    setChatStatus(`当前会话：${conversationId}`);
    return;
  }
  messages.forEach((message) => {
    const role = message.role === "assistant" ? "assistant" : message.role === "system" ? "system" : "user";
    appendMessage(role, `<div class="markdown-body">${renderMarkdown(message.content || "")}</div>`, "text", message.created_at || buildNowText());
  });
  setChatStatus(`已恢复会话：${conversationId}`);
}

async function handleNewSession() {
  persistSessionId("");
  state.selectedFile = null;
  state.selectedFiles = [];
  const fileInput = $("fileInput");
  if (fileInput) {
    fileInput.value = "";
  }
  renderSelectedFileChip([]);
  clearChatWindow();
  setChatStatus("已切换为新会话，下一次发送时后端会自动创建新的 session。");
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
  return `
    <label class="skill-switch ${canToggle ? "" : "disabled"}">
      <input
        type="checkbox"
        data-toggle-skill-enabled="${escapeHtml(skill.name || "")}"
        ${skill.enabled ? "checked" : ""}
        ${canToggle ? "" : "disabled"}
      />
      <span class="skill-switch-slider"></span>
      <span class="skill-switch-text">${skill.enabled ? "已启用" : "已禁用"}</span>
    </label>
  `;
}

function renderSkillLogsSection(logs = []) {
  if (!Array.isArray(logs) || !logs.length) {
    return `
      <section class="workspace-section">
        <h3>Skill 执行日志</h3>
        <div class="workspace-empty">当前范围内还没有 Skill 执行日志。</div>
      </section>
    `;
  }
  return `
    <section class="workspace-section">
      <h3>Skill 执行日志</h3>
      <div class="workspace-task-list">
        ${logs.map((log) => `
          <article class="workspace-task-card ${log.status === "failed" ? "failed" : ""}">
            <div class="workspace-task-head">
              <strong>${escapeHtml(log.skill_name || "Skill")}</strong>
              <span>${escapeHtml(log.status || "unknown")}</span>
            </div>
            <p>能力：${escapeHtml(log.capability || log.ability_name || "default")}</p>
            <p>输入摘要：${escapeHtml(log.input_summary || "无")}</p>
            <p>开始时间：${escapeHtml(log.started_at || "未记录")}</p>
            <p>结束时间：${escapeHtml(log.ended_at || log.finished_at || "未记录")}</p>
            <p>耗时：${escapeHtml(formatDurationMs(log.duration_ms) || "未记录")}</p>
            ${log.error_message ? `<p class="error-message">错误原因：${escapeHtml(log.error_message)}</p>` : ""}
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

function renderFilePreviewSnippet(file) {
  const preview = file.preview || {};
  if (!preview.success) {
    return "";
  }
  if (preview.preview_type === "image") {
    const assetUrl = toAssetUrl(preview.preview_url);
    return assetUrl ? `<img class="workspace-inline-preview" src="${escapeHtml(assetUrl)}" alt="${escapeHtml(file.filename || "preview")}" />` : "";
  }
  if (preview.content) {
    return `<pre class="workspace-preview-text">${escapeHtml(preview.content)}</pre>`;
  }
  return "";
}

async function ensureFilePreview(fileId) {
  if (!fileId) {
    return null;
  }
  const existing = (state.workspacePayload.filePreviewMap || {})[fileId];
  if (existing) {
    return existing;
  }
  const response = await previewFile(fileId);
  state.workspacePayload.filePreviewMap = state.workspacePayload.filePreviewMap || {};
  state.workspacePayload.filePreviewMap[fileId] = response;
  return response;
}

async function handleFileAction(action, fileId) {
  if (!fileId) {
    return;
  }
  try {
    if (action === "delete") {
      const response = await requestDeleteFile(fileId);
      if (!response.success) {
        throw new Error(response.error_message || "删除文件失败");
      }
      showToast(response.message || "文件已删除", "success");
      await refreshWorkspacePanel();
      return;
    }
    if (action === "preview") {
      await ensureFilePreview(fileId);
      renderWorkspacePanel();
      return;
    }
    if (action === "analyze") {
      if (!state.sessionId) {
        throw new Error("当前还没有会话，无法指定分析文件。");
      }
      const response = await activateFile(fileId, state.sessionId, state.userId);
      if (!response.success) {
        throw new Error(response.error_message || "切换当前分析文件失败");
      }
      showToast("已切换到该文件，开始继续分析", "info");
      sendChatMessage("继续分析这个文件");
    }
    if (action === "ocr") {
      if (!state.sessionId) {
        throw new Error("当前还没有会话，无法写入 OCR 结果。");
      }
      showToast("正在执行 OCR，这可能需要一会儿", "info");
      const response = await runFileOcr(fileId, { conversationId: state.sessionId, userId: state.userId });
      if (!response.success) {
        throw new Error(response.suggestion ? `${response.error_message || "OCR 失败"}；建议：${response.suggestion}` : response.error_message || "OCR 失败");
      }
      showToast(response.message || "OCR 完成", "success");
      await refreshWorkspacePanel();
    }
  } catch (error) {
    console.error("文件操作失败：", error);
    showToast(`文件操作失败：${error.message || "未知错误"}`, "error");
  }
}

function renderFileActionButtons(item) {
  const downloadUrl = toAssetUrl(item.download_url || `/api/files/${encodeURIComponent(item.file_id || "")}/download`);
  const type = String(item.file_type || item.mime_type || item.filename || "").toLowerCase();
  const canOcr = type.includes("pdf") || /\.(png|jpg|jpeg|webp|bmp|gif|tif|tiff)$/i.test(String(item.filename || item.original_filename || ""));
  return `
    <div class="workspace-file-actions">
      <button type="button" class="skill-toggle-button small" data-preview-file="${escapeHtml(item.file_id || "")}">预览</button>
      <a class="skill-toggle-button small link-button" href="${escapeHtml(downloadUrl)}" target="_blank" rel="noreferrer">下载</a>
      <button type="button" class="skill-toggle-button small" data-analyze-file="${escapeHtml(item.file_id || "")}">分析</button>
      ${canOcr ? `<button type="button" class="skill-toggle-button small" data-ocr-file="${escapeHtml(item.file_id || "")}">OCR</button>` : ""}
      <button type="button" class="skill-toggle-button small danger" data-delete-file="${escapeHtml(item.file_id || "")}">删除</button>
    </div>
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
  const skillLogsHtml = renderSkillLogsSection(state.skillLogsPayload.logs || []);
  body.innerHTML = payload.error
    ? `<div class="skills-empty">${escapeHtml(payload.error)}</div>${contentHtml}${skillLogsHtml}`
    : `${contentHtml}${skillLogsHtml}`;

  body.querySelectorAll("[data-toggle-skill]").forEach((button) => {
    button.addEventListener("click", () => toggleSkillActions(button.dataset.toggleSkill || ""));
  });
  body.querySelectorAll("[data-toggle-skill-enabled]").forEach((button) => {
    button.addEventListener("change", () => {
      toggleSkillEnabled(button.dataset.toggleSkillEnabled || "", button.checked);
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

function renderSelectedFileChip(fileOrFiles) {
  const chip = $("selectedFileChip");
  if (!chip) {
    console.warn("找不到 selectedFileChip，跳过文件 chip 渲染");
    return;
  }

  const files = Array.isArray(fileOrFiles)
    ? fileOrFiles
    : fileOrFiles
      ? [fileOrFiles]
      : [];

  if (!files.length) {
    chip.classList.add("hidden");
    chip.innerHTML = "";
    return;
  }

  chip.classList.remove("hidden");
  chip.innerHTML = `
    ${files
      .map(
        (file, index) => `
          <span class="file-chip-name" title="${escapeHtml(file.name)}">
            ${escapeHtml(file.name)}
            <button type="button" class="file-chip-remove" data-remove-file-index="${index}" aria-label="移除已选文件">×</button>
          </span>
        `,
      )
      .join("")}
  `;

  chip.querySelectorAll("[data-remove-file-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.getAttribute("data-remove-file-index"));
      state.selectedFiles = state.selectedFiles.filter((_, currentIndex) => currentIndex !== index);
      state.selectedFile = state.selectedFiles[0] || null;
      const fileInput = $("fileInput");
      if (fileInput && !state.selectedFiles.length) {
        fileInput.value = "";
      }
      renderSelectedFileChip(state.selectedFiles);
    });
  });
}

function handleFileSelect(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) {
    return;
  }

  state.selectedFiles = files;
  state.selectedFile = files[0] || null;
  debugLog("已选择文件：", files.map((file) => file.name).join(", "));
  renderSelectedFileChip(files);
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
  const artifactsHtml = renderArtifacts(payload?.artifacts || []);
  const ragSourcesHtml = renderRagSources(payload || {});
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
        appendMessage("assistant", `${modelBadge}${traceBanner}${renderPreprocessingResult(message)}${artifactsHtml}`, "analysis");
        return;
      }
      if (kind === "prediction") {
        appendMessage("assistant", `${modelBadge}${traceBanner}${renderPredictionResult(message)}${artifactsHtml}`, "analysis");
        return;
      }
      if (kind === "model_status") {
        appendMessage("assistant", `${modelBadge}${traceBanner}${renderModelStatusResult(message)}${artifactsHtml}`, "analysis");
        return;
      }
      if (kind === "report") {
        appendMessage("assistant", `${modelBadge}${traceBanner}${renderReportResult(message)}${artifactsHtml}`, "analysis");
        return;
      }
      if (kind === "uploaded_skill") {
        appendMessage("assistant", `${modelBadge}${traceBanner}${renderUploadedSkillResult(message)}${artifactsHtml}`, "analysis");
        return;
      }
      appendMessage("assistant", `${modelBadge}${traceBanner}${renderGenericAnalysisResult(message)}${artifactsHtml}`, "analysis");
      return;
    }
    if (message.type === "error") {
      appendMessage("assistant", `${modelBadge}${buildAssistantSourceBadge(message, payload)}<p class="error-message">${renderInlineMarkdown(message.content || "分析失败。")}</p>`, "error");
      return;
    }
    appendMessage("assistant", `${modelBadge}${buildAssistantSourceBadge(message, payload)}${renderMarkdown(message.content || "")}${renderWebSearchSources(payload)}${ragSourcesHtml}${artifactsHtml}`, "text");
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
  const previewMap = state.workspacePayload.filePreviewMap || {};
  const files = (Array.isArray(state.workspacePayload.files?.files) ? state.workspacePayload.files.files : []).map((item) => ({
    ...item,
    preview: previewMap[item.file_id] || null,
  }));
  const uploadedFiles = files.filter((item) => {
    const source = String(item.source || item.file_source || item.kind || "upload").toLowerCase();
    return !source || source === "upload" || source === "uploaded" || source === "workspace";
  });
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
                <strong>${escapeHtml(item.original_filename || item.original_name || item.filename || "未命名文件")}</strong>
                <span>${escapeHtml(item.file_type || item.mime_type || "unknown")} · ${escapeHtml(String(item.size || 0))} bytes · ${escapeHtml(item.upload_time || "未知时间")}</span>
                ${renderFileActionButtons(item)}
                ${renderFilePreviewSnippet(item)}
              </div>
            `,
          )
          .join("")}
      </div>
    `;
  };
  body.innerHTML = `
    <section class="workspace-section">
      <h3>上传文件</h3>
      ${renderFileList(uploadedFiles, "当前会话还没有上传文件。")}
    </section>
  `;

  body.querySelectorAll("[data-preview-file]").forEach((button) => {
    button.addEventListener("click", () => handleFileAction("preview", button.dataset.previewFile || ""));
  });
  body.querySelectorAll("[data-delete-file]").forEach((button) => {
    button.addEventListener("click", () => handleFileAction("delete", button.dataset.deleteFile || ""));
  });
  body.querySelectorAll("[data-analyze-file]").forEach((button) => {
    button.addEventListener("click", () => handleFileAction("analyze", button.dataset.analyzeFile || ""));
  });
  body.querySelectorAll("[data-ocr-file]").forEach((button) => {
    button.addEventListener("click", () => handleFileAction("ocr", button.dataset.ocrFile || ""));
  });
}

async function refreshWorkspacePanel() {
  if (!state.sessionId) {
    renderWorkspacePanel();
    return;
  }
  const files = await getFiles({ userId: state.userId, workspaceId: state.sessionId });
  state.workspacePayload = {
    files,
    filePreviewMap: state.workspacePayload.filePreviewMap || {},
  };
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
  const stopStreamButton = $("stopStreamButton");
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

  if (stopStreamButton) {
    stopStreamButton.addEventListener("click", (event) => {
      event.preventDefault();
      if (state.streamAbortController) {
        state.streamAbortController.abort();
      }
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

function getPipelineAlgorithmMap() {
  const algorithms = Array.isArray(state.ramanPipelinePayload.algorithms) ? state.ramanPipelinePayload.algorithms : [];
  return new Map(algorithms.map((item) => [item.algorithm_id, item]));
}

function clonePipelineSteps(steps = []) {
  return (Array.isArray(steps) ? steps : []).map((step) => ({
    algorithm_id: String(step.algorithm_id || ""),
    params: { ...(step.params || {}) },
  })).filter((step) => step.algorithm_id);
}

function applyPipelineTemplate(templateId) {
  const templates = Array.isArray(state.ramanPipelinePayload.templates) ? state.ramanPipelinePayload.templates : [];
  const template = templates.find((item) => item.template_id === templateId);
  if (!template) {
    return;
  }
  state.selectedPipelineTemplate = templateId;
  state.ramanPipelineSteps = clonePipelineSteps(template.steps || []);
  state.ramanPipelineResult = null;
}

async function loadRamanPipelineData() {
  const [algorithmsResponse, templatesResponse, historyResponse] = await Promise.all([
    getRamanAlgorithms(),
    getRamanPipelineTemplates(),
    getRamanPipelineHistory(12),
  ]);
  if (!algorithmsResponse.success) {
    throw new Error(algorithmsResponse.error_message || "算法库加载失败");
  }
  if (!templatesResponse.success) {
    throw new Error(templatesResponse.error_message || "模板加载失败");
  }
  state.ramanPipelinePayload = {
    algorithms: Array.isArray(algorithmsResponse.algorithms) ? algorithmsResponse.algorithms : [],
    templates: Array.isArray(templatesResponse.templates) ? templatesResponse.templates : [],
    history: Array.isArray(historyResponse.history) ? historyResponse.history : [],
  };
  if (!state.ramanPipelineSteps.length) {
    applyPipelineTemplate(state.selectedPipelineTemplate || state.ramanPipelinePayload.templates[0]?.template_id || "");
  }
}

function renderAlgorithmLibrary() {
  const algorithms = Array.isArray(state.ramanPipelinePayload.algorithms) ? state.ramanPipelinePayload.algorithms : [];
  if (!algorithms.length) {
    return `<div class="pipeline-empty">算法库还没有加载。</div>`;
  }
  const groups = algorithms.reduce((acc, algorithm) => {
    const key = algorithm.category || "未分类";
    acc[key] = acc[key] || [];
    acc[key].push(algorithm);
    return acc;
  }, {});
  return Object.entries(groups).map(([category, items]) => `
    <section class="pipeline-library-group">
      <h3>${escapeHtml(category)}</h3>
      <div class="pipeline-algorithm-list">
        ${items.map((algorithm) => `
          <article class="pipeline-algorithm-item ${algorithm.available ? "" : "unavailable"}">
            <div>
              <strong>${escapeHtml(algorithm.display_name || algorithm.algorithm_id)}</strong>
              <span>${escapeHtml(algorithm.algorithm_id)}</span>
              <p>${escapeHtml(algorithm.description || "")}</p>
              ${algorithm.available ? "" : `<div class="pipeline-warning">${escapeHtml(algorithm.unavailable_reason || "当前不可用")}</div>`}
            </div>
            <button class="mini-ghost-button" type="button" data-add-pipeline-algorithm="${escapeHtml(algorithm.algorithm_id)}" ${algorithm.available ? "" : "disabled"}>添加</button>
          </article>
        `).join("")}
      </div>
    </section>
  `).join("");
}

function renderPipelineSteps() {
  const algorithmMap = getPipelineAlgorithmMap();
  const steps = Array.isArray(state.ramanPipelineSteps) ? state.ramanPipelineSteps : [];
  if (!steps.length) {
    return `<div class="pipeline-empty">还没有步骤。可以选择模板，或从算法库添加算法。</div>`;
  }
  return steps.map((step, index) => {
    const algorithm = algorithmMap.get(step.algorithm_id) || {};
    const paramsText = JSON.stringify(step.params || {}, null, 2);
    return `
      <article class="pipeline-step-card" data-step-index="${index}" data-algorithm-id="${escapeHtml(step.algorithm_id)}">
        <div class="pipeline-step-head">
          <div>
            <span>步骤 ${index + 1}</span>
            <strong>${escapeHtml(algorithm.display_name || step.algorithm_id)}</strong>
            <small>${escapeHtml(step.algorithm_id)}</small>
          </div>
          <div class="inline-actions">
            <button class="mini-ghost-button" type="button" data-move-pipeline-step="${index}" data-direction="-1">上移</button>
            <button class="mini-ghost-button" type="button" data-move-pipeline-step="${index}" data-direction="1">下移</button>
            <button class="mini-ghost-button" type="button" data-remove-pipeline-step="${index}">移除</button>
          </div>
        </div>
        <label class="pipeline-param-editor">
          <span>参数 JSON</span>
          <textarea class="form-textarea" data-pipeline-step-params="${index}" rows="4">${escapeHtml(paramsText)}</textarea>
        </label>
      </article>
    `;
  }).join("");
}

function renderPipelineResult() {
  const result = state.ramanPipelineResult;
  if (!result) {
    return `<div class="pipeline-empty">运行后会在这里显示每一步状态、图谱、warning 和 error。</div>`;
  }
  const steps = Array.isArray(result.steps) ? result.steps : [];
  const warnings = Array.isArray(result.warnings) ? result.warnings : [];
  const artifacts = Array.isArray(result.artifacts) ? result.artifacts : [];
  const images = artifacts.filter((item) => item.type === "image" && item.url);
  const tables = artifacts.filter((item) => item.type === "table");
  return `
    <div class="pipeline-result-summary ${result.success ? "success" : "failed"}">
      <strong>${escapeHtml(result.message || (result.success ? "运行完成" : "运行失败"))}</strong>
      <span>Run ID：${escapeHtml(result.run_id || "")} · 耗时：${escapeHtml(formatDurationMs(result.elapsed_ms) || "")}</span>
      ${result.error_message ? `<div class="pipeline-error">${escapeHtml(result.error_message)}</div>` : ""}
    </div>
    ${warnings.length ? `<div class="pipeline-warning">${warnings.map(escapeHtml).join("；")}</div>` : ""}
    <div class="pipeline-step-result-list">
      ${steps.map((step) => `
        <article class="pipeline-step-result ${step.status === "success" ? "success" : "failed"}">
          <div>
            <strong>${escapeHtml(step.display_name || step.algorithm_id)}</strong>
            <span>${escapeHtml(step.status || "")} · ${escapeHtml(formatDurationMs(step.elapsed_ms) || "")} · 输入 ${escapeHtml(String(step.input_shape?.points ?? 0))} 点 / 输出 ${escapeHtml(String(step.output_shape?.points ?? 0))} 点</span>
          </div>
          ${step.warning ? `<div class="pipeline-warning">${escapeHtml(step.warning)}</div>` : ""}
          ${step.error_message ? `<div class="pipeline-error">${escapeHtml(step.error_message)}</div>` : ""}
        </article>
      `).join("")}
    </div>
    ${images.length ? `
      <div class="pipeline-figure-grid">
        ${images.map((image) => `
          <figure class="pipeline-figure">
            <img src="${escapeHtml(toAssetUrl(image.url))}" alt="${escapeHtml(image.title || "Pipeline 图谱")}" />
            <figcaption>${escapeHtml(image.title || "")}</figcaption>
          </figure>
        `).join("")}
      </div>
    ` : ""}
    ${tables.length ? `
      <div class="pipeline-table-list">
        ${tables.map((table) => `
          <details class="pipeline-table-card">
            <summary>${escapeHtml(table.title || "表格")} · ${escapeHtml(String((table.rows || []).length))} 行预览</summary>
            <pre>${escapeHtml(JSON.stringify(table.rows || [], null, 2))}</pre>
          </details>
        `).join("")}
      </div>
    ` : ""}
  `;
}

function renderPipelineHistory() {
  const history = Array.isArray(state.ramanPipelinePayload.history) ? state.ramanPipelinePayload.history : [];
  if (!history.length) {
    return `<div class="pipeline-empty">暂无运行历史。</div>`;
  }
  return history.slice(0, 8).map((item) => `
    <article class="pipeline-history-item ${item.success ? "success" : "failed"}">
      <strong>${escapeHtml(item.template_id || "custom_pipeline")}</strong>
      <span>${escapeHtml(item.created_at || "")} · ${escapeHtml(item.run_id || "")} · ${escapeHtml(item.success ? "成功" : "失败")}</span>
    </article>
  `).join("");
}

function readPipelineStepsFromDom() {
  const cards = Array.from(document.querySelectorAll(".pipeline-step-card"));
  const steps = [];
  for (const card of cards) {
    const index = Number(card.dataset.stepIndex || 0);
    const algorithmId = card.dataset.algorithmId || state.ramanPipelineSteps[index]?.algorithm_id || "";
    const textarea = card.querySelector(`[data-pipeline-step-params="${index}"]`);
    let params = {};
    try {
      params = textarea?.value?.trim() ? JSON.parse(textarea.value) : {};
    } catch {
      showToast(`第 ${index + 1} 步参数 JSON 不合法`, "error");
      return null;
    }
    steps.push({ algorithm_id: algorithmId, params });
  }
  state.ramanPipelineSteps = clonePipelineSteps(steps);
  return state.ramanPipelineSteps;
}

function bindRamanPipelinePanelEvents() {
  const body = $("ramanPipelinePanelBody");
  if (!body) {
    return;
  }
  $("pipelineTemplateSelect")?.addEventListener("change", (event) => {
    state.selectedPipelineTemplate = event.target?.value || "";
  });
  $("applyPipelineTemplateBtn")?.addEventListener("click", () => {
    applyPipelineTemplate($("pipelineTemplateSelect")?.value || state.selectedPipelineTemplate);
    renderRamanPipelinePanel();
  });
  $("clearPipelineStepsBtn")?.addEventListener("click", () => {
    state.ramanPipelineSteps = [];
    state.ramanPipelineResult = null;
    renderRamanPipelinePanel();
  });
  $("validatePipelineBtn")?.addEventListener("click", async () => {
    const steps = readPipelineStepsFromDom();
    if (!steps) {
      return;
    }
    const response = await validateRamanPipeline({ steps, template_id: state.selectedPipelineTemplate || undefined, save_history: false });
    state.ramanPipelineResult = {
      success: response.success,
      message: response.success ? "Pipeline 校验通过。" : "Pipeline 校验未通过。",
      run_id: "validate",
      elapsed_ms: 0,
      steps: steps.map((step) => ({
        display_name: getPipelineAlgorithmMap().get(step.algorithm_id)?.display_name || step.algorithm_id,
        algorithm_id: step.algorithm_id,
        status: response.errors?.length ? "failed" : "success",
        input_shape: {},
        output_shape: {},
      })),
      warnings: response.warnings || [],
      error_message: (response.errors || []).join("；"),
      artifacts: [],
    };
    renderRamanPipelinePanel();
  });
  $("runPipelineBtn")?.addEventListener("click", async () => {
    const file = $("pipelineFileInput")?.files?.[0] || null;
    if (!file) {
      showToast("请先选择一个 Raman CSV 文件", "error");
      return;
    }
    const steps = readPipelineStepsFromDom();
    if (!steps) {
      return;
    }
    state.ramanPipelineBusy = true;
    renderRamanPipelinePanel();
    const response = await runRamanPipeline({
      file,
      payload: {
        template_id: state.selectedPipelineTemplate || undefined,
        steps,
        sample_name: file.name,
        save_history: true,
      },
    });
    state.ramanPipelineBusy = false;
    state.ramanPipelineResult = response.success === false && !response.steps
      ? {
          success: false,
          message: "Raman Pipeline 运行失败。",
          run_id: "",
          elapsed_ms: 0,
          steps: [],
          artifacts: [],
          warnings: [],
          error_message: response.error_message || response.message || "运行失败",
        }
      : response;
    const historyResponse = await getRamanPipelineHistory(12);
    state.ramanPipelinePayload.history = Array.isArray(historyResponse.history) ? historyResponse.history : state.ramanPipelinePayload.history;
    renderRamanPipelinePanel();
  });
  body.querySelectorAll("[data-add-pipeline-algorithm]").forEach((button) => {
    button.addEventListener("click", () => {
      const algorithmId = button.dataset.addPipelineAlgorithm || "";
      const algorithm = getPipelineAlgorithmMap().get(algorithmId);
      state.ramanPipelineSteps.push({ algorithm_id: algorithmId, params: { ...(algorithm?.default_params || {}) } });
      renderRamanPipelinePanel();
    });
  });
  body.querySelectorAll("[data-remove-pipeline-step]").forEach((button) => {
    button.addEventListener("click", () => {
      readPipelineStepsFromDom();
      state.ramanPipelineSteps.splice(Number(button.dataset.removePipelineStep || 0), 1);
      renderRamanPipelinePanel();
    });
  });
  body.querySelectorAll("[data-move-pipeline-step]").forEach((button) => {
    button.addEventListener("click", () => {
      readPipelineStepsFromDom();
      const index = Number(button.dataset.movePipelineStep || 0);
      const direction = Number(button.dataset.direction || 0);
      const target = index + direction;
      if (target < 0 || target >= state.ramanPipelineSteps.length) {
        return;
      }
      const [item] = state.ramanPipelineSteps.splice(index, 1);
      state.ramanPipelineSteps.splice(target, 0, item);
      renderRamanPipelinePanel();
    });
  });
}

function renderRamanPipelinePanel() {
  const body = $("ramanPipelinePanelBody");
  if (!body) {
    return;
  }
  const templates = Array.isArray(state.ramanPipelinePayload.templates) ? state.ramanPipelinePayload.templates : [];
  body.innerHTML = `
    <div class="pipeline-toolbar">
      <label class="pipeline-template-select">
        <span>模板</span>
        <select id="pipelineTemplateSelect" class="form-select">
          ${templates.map((template) => `<option value="${escapeHtml(template.template_id)}" ${template.template_id === state.selectedPipelineTemplate ? "selected" : ""}>${escapeHtml(template.display_name || template.template_id)}</option>`).join("")}
        </select>
      </label>
      <input id="pipelineFileInput" class="form-input" type="file" accept=".csv,text/csv" />
      <button id="applyPipelineTemplateBtn" class="pill-button small" type="button">套用模板</button>
      <button id="validatePipelineBtn" class="pill-button small ghost" type="button">校验</button>
      <button id="runPipelineBtn" class="pill-button small" type="button" ${state.ramanPipelineBusy ? "disabled" : ""}>${state.ramanPipelineBusy ? "运行中..." : "运行"}</button>
      <button id="clearPipelineStepsBtn" class="pill-button small ghost" type="button">清空步骤</button>
    </div>
    <div class="pipeline-builder-grid">
      <section class="pipeline-panel-section">
        <div class="pipeline-section-head">
          <h3>算法库</h3>
          <span>${escapeHtml(String(state.ramanPipelinePayload.algorithms?.length || 0))} 个</span>
        </div>
        <div class="pipeline-library">${renderAlgorithmLibrary()}</div>
      </section>
      <section class="pipeline-panel-section">
        <div class="pipeline-section-head">
          <h3>Pipeline 步骤</h3>
          <span>${escapeHtml(String(state.ramanPipelineSteps.length))} 步</span>
        </div>
        <div class="pipeline-steps">${renderPipelineSteps()}</div>
      </section>
    </div>
    <section class="pipeline-panel-section">
      <div class="pipeline-section-head">
        <h3>运行结果</h3>
        <span>状态 / 中间图 / warning / error</span>
      </div>
      <div class="pipeline-result">${renderPipelineResult()}</div>
    </section>
    <section class="pipeline-panel-section">
      <div class="pipeline-section-head">
        <h3>历史记录</h3>
        <span>最近 8 条</span>
      </div>
      <div class="pipeline-history">${renderPipelineHistory()}</div>
    </section>
  `;
  bindRamanPipelinePanelEvents();
}

async function openRamanPipelinePanel() {
  state.ramanPipelineOpen = true;
  $("ramanPipelinePanel")?.classList.remove("hidden");
  $("ramanPipelinePanel")?.setAttribute("aria-hidden", "false");
  const body = $("ramanPipelinePanelBody");
  if (body) {
    body.innerHTML = `<div class="pipeline-empty">正在加载 Raman Pipeline...</div>`;
  }
  try {
    await loadRamanPipelineData();
    renderRamanPipelinePanel();
  } catch (error) {
    console.error("加载 Raman Pipeline 失败：", error);
    if (body) {
      body.innerHTML = `<div class="pipeline-error">加载失败：${escapeHtml(error.message || "未知错误")}</div>`;
    }
  }
}

function closeRamanPipelinePanel() {
  state.ramanPipelineOpen = false;
  $("ramanPipelinePanel")?.classList.add("hidden");
  $("ramanPipelinePanel")?.setAttribute("aria-hidden", "true");
}

function bindPageEvents() {
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
  $("ramanPipelineButton")?.addEventListener("click", openRamanPipelinePanel);
  $("closeRamanPipelinePanelBtn")?.addEventListener("click", closeRamanPipelinePanel);
  $("ramanPipelinePanelBackdrop")?.addEventListener("click", closeRamanPipelinePanel);

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
      closeRamanPipelinePanel();
      state.knowledgeBasePanel?.close();
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
  const [response, logsResponse] = await Promise.all([
    fetchSkills(),
    getSkillLogs({ userId: state.userId, conversationId: state.sessionId || "", limit: 20 }),
  ]);
  if (!response.success) {
    throw new Error(response.error_message || "加载 Skills 失败");
  }
  state.skillsPayload = response;
  state.skillLogsPayload = logsResponse?.success ? logsResponse : { logs: [] };
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

function setAuthUiVisible(isLoggedIn) {
  $("phase2Panels")?.classList.toggle("hidden", !isLoggedIn);
  ["workspaceButton", "skillsManageBtn", "skillsButton", "toolCatalogButton", "ramanLabButton", "auditLogsButton"].forEach((id) => {
    $(id)?.classList.toggle("hidden", !isLoggedIn);
  });
  const userBar = $("currentUserBar");
  if (userBar) {
    userBar.textContent = isLoggedIn && state.currentUser
      ? `当前用户：${state.currentUser.username} (${state.currentUser.role || "user"})`
      : "当前用户：未登录";
  }
  const sidebarUser = $("sidebarUserLabel");
  if (sidebarUser) {
    sidebarUser.textContent = isLoggedIn && state.currentUser ? state.currentUser.username : state.userId || "default_user";
  }
}

function renderAuthPanel() {
  const body = $("authPanelBody");
  if (!body) {
    return;
  }
  const current = state.currentUser;
  if (current) {
    body.innerHTML = `
      <div class="auth-card">
        <h3>当前登录状态</h3>
        <div class="entity-meta">
          <div>用户名：${escapeHtml(current.username || "")}</div>
          <div>角色：${escapeHtml(current.role || "user")}</div>
          <div>用户 ID：${escapeHtml(current.user_id || "")}</div>
        </div>
        <div class="inline-actions" style="margin-top: 12px;">
          <button id="logoutBtn" type="button" class="pill-button">退出登录</button>
        </div>
      </div>
    `;
    $("logoutBtn")?.addEventListener("click", handleLogout);
    return;
  }
  body.innerHTML = `
    <div class="auth-grid">
      <div class="auth-card">
        <h3>登录</h3>
        <form id="loginForm">
          <input class="form-input" name="username" placeholder="用户名" required />
          <input class="form-input" name="password" type="password" placeholder="密码" required />
          <button class="pill-button" type="submit">登录</button>
        </form>
      </div>
      <div class="auth-card">
        <h3>注册</h3>
        <form id="registerForm">
          <input class="form-input" name="username" placeholder="用户名" required />
          <input class="form-input" name="password" type="password" placeholder="密码（至少 6 位）" required />
          <button class="pill-button" type="submit">注册并登录</button>
        </form>
      </div>
    </div>
    <div class="panel-note">未登录时，项目中心、文件中心、任务中心、报告中心与 Skill 管理会隐藏。</div>
  `;
  $("loginForm")?.addEventListener("submit", handleLoginSubmit);
  $("registerForm")?.addEventListener("submit", handleRegisterSubmit);
}

function getCurrentProject() {
  const projects = Array.isArray(state.projectsPayload?.projects) ? state.projectsPayload.projects : [];
  return projects.find((item) => item.project_id === state.selectedProjectId) || null;
}

function renderProjectPanel() {
  const body = $("projectPanelBody");
  if (!body) {
    return;
  }
  const projects = Array.isArray(state.projectsPayload?.projects) ? state.projectsPayload.projects : [];
  const currentProject = getCurrentProject();
  body.innerHTML = `
    <div class="auth-card">
      <h3>新建项目</h3>
      <form id="createProjectForm">
        <input class="form-input" name="name" placeholder="项目名称，例如：甲醇浓度检测实验" required />
        <textarea class="form-textarea" name="description" placeholder="项目描述"></textarea>
        <button class="pill-button" type="submit">创建项目</button>
      </form>
    </div>
    ${
      currentProject
        ? `<div class="current-project-banner">当前项目：<strong>${escapeHtml(currentProject.name || "")}</strong><br />${escapeHtml(currentProject.description || "暂无描述")}</div>`
        : `<div class="panel-note">当前未选择项目。上传文件和导出报告时可以不绑定项目，或先创建一个项目再继续。</div>`
    }
    <div class="entity-list">
      ${
        projects.length
          ? projects.map((project) => `
            <article class="entity-card">
              <div class="entity-card-head">
                <div>
                  <h4>${escapeHtml(project.name || "")}</h4>
                  <div class="entity-meta">${escapeHtml(project.description || "暂无描述")}</div>
                </div>
                <div class="entity-tags">
                  <span class="entity-tag">文件 ${escapeHtml(String(project.file_count || 0))}</span>
                  <span class="entity-tag">任务 ${escapeHtml(String(project.task_count || 0))}</span>
                  <span class="entity-tag">报告 ${escapeHtml(String(project.report_count || 0))}</span>
                </div>
              </div>
              <div class="inline-actions">
                <button class="pill-button small" type="button" data-select-project="${escapeHtml(project.project_id || "")}">${project.project_id === state.selectedProjectId ? "已选中" : "设为当前项目"}</button>
                <button class="pill-button small ghost" type="button" data-archive-project="${escapeHtml(project.project_id || "")}">归档</button>
              </div>
            </article>
          `).join("")
          : `<div class="panel-note">当前还没有项目。</div>`
      }
    </div>
  `;
  $("createProjectForm")?.addEventListener("submit", handleCreateProject);
  body.querySelectorAll("[data-select-project]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.selectedProjectId = button.dataset.selectProject || "";
      await loadPhase2Data();
    });
  });
  body.querySelectorAll("[data-archive-project]").forEach((button) => {
    button.addEventListener("click", async () => {
      const projectId = button.dataset.archiveProject || "";
      if (!projectId) {
        return;
      }
      const response = await archiveProject(projectId);
      if (!response.success) {
        showToast(response.error_message || "归档项目失败", "error");
        return;
      }
      if (state.selectedProjectId === projectId) {
        state.selectedProjectId = "";
      }
      showToast("项目已归档", "success");
      await loadPhase2Data();
    });
  });
}

function renderFileCenter() {
  const body = $("fileCenterBody");
  if (!body) {
    return;
  }
  const files = Array.isArray(state.dashboardFilesPayload?.files) ? state.dashboardFilesPayload.files : [];
  const currentProject = getCurrentProject();
  body.innerHTML = `
    <div class="auth-card">
      <h3>上传到文件中心</h3>
      <form id="fileCenterUploadForm">
        <input id="dashboardFileInput" class="form-input" name="file" type="file" required />
        <div class="panel-note">上传时会自动绑定到当前项目：${escapeHtml(currentProject?.name || "未绑定项目")}</div>
        <button class="pill-button" type="submit">上传文件</button>
      </form>
    </div>
    <div class="selection-row">
      <label><input id="selectAllBatchFiles" type="checkbox" ${files.length && state.selectedBatchFileIds.size === files.length ? "checked" : ""} /> 全选当前列表</label>
      <button id="runBatchAnalyzeBtn" class="pill-button" type="button">批量分析选中文件</button>
      <span class="muted-text">已选 ${escapeHtml(String(state.selectedBatchFileIds.size))} 个文件</span>
    </div>
    <div class="entity-list">
      ${
        files.length
          ? `<table class="simple-table">
              <thead>
                <tr>
                  <th></th>
                  <th>文件名</th>
                  <th>类型</th>
                  <th>上传时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                ${files.map((file) => `
                  <tr>
                    <td><input type="checkbox" data-batch-file="${escapeHtml(file.file_id || "")}" ${state.selectedBatchFileIds.has(file.file_id) ? "checked" : ""} /></td>
                    <td>${escapeHtml(file.original_filename || file.filename || "")}</td>
                    <td>${escapeHtml(file.file_type || "")}</td>
                    <td>${escapeHtml(file.upload_time || "")}</td>
                    <td>
                      <div class="inline-actions">
                        <button class="pill-button small" type="button" data-preview-dashboard-file="${escapeHtml(file.file_id || "")}">预览</button>
                        <button class="pill-button small" type="button" data-download-dashboard-file="${escapeHtml(file.file_id || "")}">下载</button>
                        <button class="pill-button small" type="button" data-analyze-dashboard-file="${escapeHtml(file.file_id || "")}">分析</button>
                        <button class="pill-button small ghost" type="button" data-export-dashboard-file="${escapeHtml(file.file_id || "")}" data-export-format="markdown">导出 MD</button>
                        <button class="pill-button small ghost" type="button" data-export-dashboard-file="${escapeHtml(file.file_id || "")}" data-export-format="docx">导出 Word</button>
                        <button class="pill-button small ghost" type="button" data-export-dashboard-file="${escapeHtml(file.file_id || "")}" data-export-format="pdf">导出 PDF</button>
                        ${currentProject && file.project_id !== currentProject.project_id ? `<button class="pill-button small ghost" type="button" data-attach-dashboard-file="${escapeHtml(file.file_id || "")}">绑定当前项目</button>` : ""}
                        <button class="pill-button small ghost" type="button" data-delete-dashboard-file="${escapeHtml(file.file_id || "")}">删除</button>
                      </div>
                    </td>
                  </tr>
                `).join("")}
              </tbody>
            </table>`
          : `<div class="panel-note">当前没有文件。你可以先上传 Raman CSV，再做单文件或批量分析。</div>`
      }
    </div>
  `;
  $("fileCenterUploadForm")?.addEventListener("submit", handleDashboardUpload);
  $("selectAllBatchFiles")?.addEventListener("change", (event) => {
    const checked = Boolean(event.target?.checked);
    state.selectedBatchFileIds = checked ? new Set(files.map((item) => item.file_id)) : new Set();
    renderFileCenter();
  });
  $("runBatchAnalyzeBtn")?.addEventListener("click", handleBatchAnalyze);
  body.querySelectorAll("[data-batch-file]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const fileId = checkbox.dataset.batchFile || "";
      if (!fileId) {
        return;
      }
      if (checkbox.checked) {
        state.selectedBatchFileIds.add(fileId);
      } else {
        state.selectedBatchFileIds.delete(fileId);
      }
      renderFileCenter();
    });
  });
  body.querySelectorAll("[data-preview-dashboard-file]").forEach((button) => {
    button.addEventListener("click", () => handleFileAction("preview", button.dataset.previewDashboardFile || ""));
  });
  body.querySelectorAll("[data-download-dashboard-file]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await downloadFileById(button.dataset.downloadDashboardFile || "");
      if (!response.success) {
        showToast(response.error_message || "下载失败", "error");
      }
    });
  });
  body.querySelectorAll("[data-analyze-dashboard-file]").forEach((button) => {
    button.addEventListener("click", () => handleFileAction("analyze", button.dataset.analyzeDashboardFile || ""));
  });
  body.querySelectorAll("[data-delete-dashboard-file]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await requestDeleteFile(button.dataset.deleteDashboardFile || "");
      if (!response.success) {
        showToast(response.error_message || "删除失败", "error");
        return;
      }
      state.selectedBatchFileIds.delete(button.dataset.deleteDashboardFile || "");
      showToast("文件已删除", "success");
      await loadPhase2Data();
    });
  });
  body.querySelectorAll("[data-export-dashboard-file]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await exportReport({
        file_id: button.dataset.exportDashboardFile || "",
        project_id: state.selectedProjectId || undefined,
        formats: [button.dataset.exportFormat || "markdown"],
      }, { asyncTask: true });
      if (!response.success) {
        showToast(response.error_message || "导出报告失败", "error");
        return;
      }
      if (response.async_task) {
        showToast(`报告导出任务已创建：${response.task_id || ""}`, "success");
        await loadPhase2Data();
        return;
      }
      const warnings = Array.isArray(response.warnings) ? response.warnings : [];
      showToast(warnings.length ? warnings.join("；") : "报告导出完成", warnings.length ? "info" : "success");
      await loadPhase2Data();
    });
  });
  body.querySelectorAll("[data-attach-dashboard-file]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!state.selectedProjectId) {
        showToast("请先选择当前项目", "error");
        return;
      }
      const response = await attachProjectFile(state.selectedProjectId, button.dataset.attachDashboardFile || "");
      if (!response.success) {
        showToast(response.error_message || "绑定项目失败", "error");
        return;
      }
      showToast("文件已绑定到当前项目", "success");
      await loadPhase2Data();
    });
  });
}

function renderTaskCenter() {
  const body = $("taskCenterBody");
  if (!body) {
    return;
  }
  const tasks = Array.isArray(state.dashboardTasksPayload?.tasks) ? state.dashboardTasksPayload.tasks : [];
  body.innerHTML = tasks.length
    ? `<div class="entity-list">${tasks.map((task) => `
        <article class="entity-card">
          <div class="entity-card-head">
            <div>
              <h4>${escapeHtml(task.task_type || task.intent || "unknown")}</h4>
              <div class="entity-meta">状态：${escapeHtml(task.status || "")} · 进度：${escapeHtml(String(task.progress ?? ""))}% · 创建时间：${escapeHtml(task.created_at || "")}</div>
            </div>
            <div class="entity-tags">
              <span class="entity-tag">${escapeHtml(task.project_id || "未绑定项目")}</span>
            </div>
          </div>
          ${task.error_message ? `<div class="inline-error">错误原因：${escapeHtml(task.error_message)}</div>` : ""}
          ${task.result_summary?.failed_count ? `<div class="panel-note">批量摘要：成功 ${escapeHtml(String(task.result_summary.success_count || 0))}，失败 ${escapeHtml(String(task.result_summary.failed_count || 0))}</div>` : ""}
          <div class="inline-actions">
            <button class="pill-button small" type="button" data-task-logs="${escapeHtml(task.task_id || "")}">查看日志</button>
            <button class="pill-button small" type="button" data-task-result="${escapeHtml(task.task_id || "")}">查看结果</button>
            <button class="pill-button small ghost" type="button" data-task-artifacts="${escapeHtml(task.task_id || "")}">产物</button>
            <button class="pill-button small ghost" type="button" data-task-events="${escapeHtml(task.task_id || "")}">订阅事件</button>
            ${["pending", "running"].includes(String(task.status || "")) ? `<button class="pill-button small ghost" type="button" data-task-cancel="${escapeHtml(task.task_id || "")}">取消</button>` : ""}
            ${task.task_type === "raman_batch_analysis" ? `<button class="pill-button small ghost" type="button" data-task-batch-csv="${escapeHtml(task.task_id || "")}">下载批量 CSV</button>` : ""}
          </div>
        </article>
      `).join("")}</div>`
    : `<div class="panel-note">当前还没有任务记录。</div>`;
  body.querySelectorAll("[data-task-logs]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await getTaskLogs(button.dataset.taskLogs || "");
      if (!response.success) {
        showToast(response.error_message || "加载任务日志失败", "error");
        return;
      }
      const skillRuns = Array.isArray(response.skill_runs) ? response.skill_runs : [];
      const steps = Array.isArray(response.steps) ? response.steps : [];
      showToast(`任务日志：步骤 ${steps.length} 个，Skill 运行 ${skillRuns.length} 次`, "info");
    });
  });
  body.querySelectorAll("[data-task-result]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await getTaskResult(button.dataset.taskResult || "");
      if (!response.success) {
        showToast(response.error_message || "加载任务结果失败", "error");
        return;
      }
      if (response.result_file_id) {
        const downloadResponse = await downloadFileById(response.result_file_id);
        if (!downloadResponse.success) {
          showToast(downloadResponse.error_message || "下载结果失败", "error");
        }
        return;
      }
      if (response.result_summary) {
        showToast("任务结果已刷新到页面摘要中", "info");
        return;
      }
      showToast("当前任务还没有可下载结果", "info");
    });
  });
  body.querySelectorAll("[data-task-batch-csv]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await downloadBatchCsv(button.dataset.taskBatchCsv || "");
      if (!response.success) {
        showToast(response.error_message || "下载批量 CSV 失败", "error");
      }
    });
  });
  body.querySelectorAll("[data-task-artifacts]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await getTaskArtifacts(button.dataset.taskArtifacts || "");
      if (!response.success) {
        showToast(response.error_message || "加载任务产物失败", "error");
        return;
      }
      const artifacts = Array.isArray(response.artifacts) ? response.artifacts : [];
      showToast(artifacts.length ? `任务产物 ${artifacts.length} 个` : "当前任务暂无产物", artifacts.length ? "info" : "error");
    });
  });
  body.querySelectorAll("[data-task-cancel]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await cancelTask(button.dataset.taskCancel || "");
      if (!response.success) {
        showToast(response.error_message || "取消任务失败", "error");
        return;
      }
      showToast("任务已取消", "success");
      await loadPhase2Data();
    });
  });
  body.querySelectorAll("[data-task-events]").forEach((button) => {
    button.addEventListener("click", async () => {
      const taskId = button.dataset.taskEvents || "";
      if (!taskId) {
        return;
      }
      state.taskEventAbortController?.abort();
      const controller = new AbortController();
      state.taskEventAbortController = controller;
      let count = 0;
      showToast("开始订阅任务事件", "info");
      const response = await streamTaskEvents(
        taskId,
        (event) => {
          count += 1;
          const label = event.content || event.event || "任务事件";
          showToast(label, event.event === "task_failed" ? "error" : "info");
        },
        { signal: controller.signal },
      );
      if (!response.success) {
        showToast(response.error_message || "订阅任务事件失败", "error");
        return;
      }
      showToast(`任务事件流结束，共 ${count} 条`, "success");
      await loadPhase2Data();
    });
  });
}

function renderToolCatalogPanel() {
  const body = $("toolCatalogBody");
  if (!body) {
    return;
  }
  const toolsPayload = state.toolCatalogPayload || {};
  const tools = toolsPayload.tools && typeof toolsPayload.tools === "object" ? toolsPayload.tools : {};
  const entries = Object.entries(tools);
  body.innerHTML = `
    <div class="panel-note">工具目录来自后端 ToolCatalog，展示每个工具的动作、风险等级、确认要求和参数 Schema。</div>
    <div class="entity-list">
      ${
        entries.length
          ? entries.map(([toolName, tool]) => {
              const actions = tool.actions && typeof tool.actions === "object" ? Object.values(tool.actions) : [];
              return `
                <article class="entity-card">
                  <div class="entity-card-head">
                    <div>
                      <h4>${escapeHtml(tool.display_name || toolName)}</h4>
                      <div class="entity-meta">${escapeHtml(tool.description || "")}</div>
                    </div>
                    <div class="entity-tags">
                      <span class="entity-tag">${escapeHtml(tool.category || "tool")}</span>
                      <span class="entity-tag">${escapeHtml(tool.source || "builtin")}</span>
                      <span class="entity-tag">${escapeHtml(tool.danger_level || "low")}</span>
                      ${tool.available === false ? `<span class="entity-tag danger">unavailable</span>` : ""}
                      ${tool.requires_auth ? `<span class="entity-tag">auth</span>` : ""}
                    </div>
                  </div>
                  ${tool.available === false ? `<div class="inline-error">${escapeHtml(tool.unavailable_reason || "工具当前不可用。")}</div>` : ""}
                  <div class="tool-action-list">
                    ${actions.map((action) => {
                      const actionName = action.action_name || action.name || "";
                      const sideEffects = Array.isArray(action.side_effects) ? action.side_effects.filter(Boolean).join(", ") : "";
                      return `
                      <div class="tool-action-row">
                        <div>
                          <strong>${escapeHtml(action.display_name || actionName)}</strong>
                          <span>${escapeHtml(actionName)} · ${escapeHtml(action.danger_level || "low")} ${action.requires_confirmation ? "· 需确认" : ""}${action.supports_async_task ? " · async" : ""}</span>
                          ${sideEffects ? `<span>side_effects: ${escapeHtml(sideEffects)}</span>` : ""}
                        </div>
                        <div class="inline-actions">
                          <button class="pill-button small ghost" type="button" data-tool-validate="${escapeHtml(toolName)}" data-tool-action="${escapeHtml(actionName)}">校验</button>
                          <button class="pill-button small ghost" type="button" data-tool-execute="${escapeHtml(toolName)}" data-tool-action="${escapeHtml(actionName)}">${action.requires_confirmation ? "生成确认" : "试运行"}</button>
                        </div>
                      </div>
                    `;
                    }).join("")}
                  </div>
                </article>
              `;
            }).join("")
          : `<div class="panel-note">工具目录尚未加载。</div>`
      }
    </div>
  `;
  body.querySelectorAll("[data-tool-validate]").forEach((button) => {
    button.addEventListener("click", async () => {
      const toolName = button.dataset.toolValidate || "";
      const actionName = button.dataset.toolAction || "";
      const action = findToolAction(toolName, actionName);
      const response = await validateToolAction(toolName, actionName, action?.default_args || {});
      if (!response.success) {
        const errors = response.validation?.errors || [];
        showToast(errors.join("；") || response.error_message || "工具校验未通过", "error");
        return;
      }
      showToast("工具参数校验通过", "success");
    });
  });
  body.querySelectorAll("[data-tool-execute]").forEach((button) => {
    button.addEventListener("click", async () => {
      const toolName = button.dataset.toolExecute || "";
      const actionName = button.dataset.toolAction || "";
      const action = findToolAction(toolName, actionName);
      const response = await executeToolAction(toolName, actionName, action?.default_args || {});
      appendToolCatalogRuntimeNotice(response);
      const runtimeResult = response.response || {};
      const needsConfirm = runtimeResult.requires_confirmation || runtimeResult.status === "confirmation_required";
      showToast(
        needsConfirm ? "已生成确认请求" : (response.success ? "工具试运行完成" : (response.error_message || runtimeResult.error_message || "工具试运行失败")),
        response.success ? "success" : "error",
      );
    });
  });
}

function appendToolCatalogRuntimeNotice(response = {}) {
  const body = $("toolCatalogBody");
  const result = response.response || {};
  if (!body || !result) {
    return;
  }
  const confirmation = result.confirmation_payload || null;
  const notice = document.createElement("div");
  if (confirmation) {
    notice.className = "tool-trace-card confirmation-card";
    notice.innerHTML = `
      <div class="tool-trace-card-head">
        <strong>已生成确认请求</strong>
        <span>${escapeHtml(confirmation.danger_level || "high")}</span>
      </div>
      <div class="tool-trace-card-body">
        <div>${escapeHtml(confirmation.message || "")}</div>
        <div class="tool-trace-meta">${escapeHtml([confirmation.tool_name, confirmation.action_name].filter(Boolean).join("."))}</div>
      </div>
      <div class="inline-actions">
        <button class="pill-button small ghost" type="button" data-confirm-approve="${escapeHtml(confirmation.confirmation_id || "")}">批准</button>
        <button class="pill-button small ghost" type="button" data-confirm-reject="${escapeHtml(confirmation.confirmation_id || "")}">拒绝</button>
      </div>
    `;
    wireStreamTraceCardActions(notice, { data: { confirmation_payload: confirmation } });
  } else {
    notice.className = result.success === false ? "inline-error" : "panel-note";
    notice.textContent = result.summary || result.error_message || "工具执行已返回。";
  }
  body.prepend(notice);
}

function findToolAction(toolName, actionName) {
  const tools = state.toolCatalogPayload?.tools || {};
  const tool = tools[toolName] || {};
  const actions = tool.actions && typeof tool.actions === "object" ? Object.values(tool.actions) : [];
  return actions.find((action) => (action.action_name || action.name) === actionName) || null;
}

function renderAuditLogPanel() {
  const body = $("auditLogBody");
  if (!body) {
    return;
  }
  const logs = Array.isArray(state.auditLogsPayload?.logs) ? state.auditLogsPayload.logs : [];
  const failed = state.auditLogsPayload?.success === false;
  body.innerHTML = failed
    ? `<div class="inline-error">${escapeHtml(state.auditLogsPayload.error_message || "当前账号无权查看审计日志。")}</div>`
    : logs.length
      ? `<div class="entity-list">${logs.map((log) => `
          <article class="entity-card">
            <div class="entity-card-head">
              <div>
                <h4>${escapeHtml(log.action || "")}</h4>
                <div class="entity-meta">${escapeHtml(log.created_at || "")} · ${escapeHtml(log.user_id || "unknown")} · ${escapeHtml(log.resource_type || "")}:${escapeHtml(log.resource_id || "")}</div>
              </div>
              <div class="entity-tags">
                <span class="entity-tag">${escapeHtml(log.ip_address || "local")}</span>
              </div>
            </div>
          </article>
        `).join("")}</div>`
      : `<div class="panel-note">暂无审计日志，或当前账号不是管理员。</div>`;
}

function renderRamanLabPanel() {
  const body = $("ramanLabBody");
  if (!body) {
    return;
  }
  const datasets = Array.isArray(state.ramanLabPayload.datasets) ? state.ramanLabPayload.datasets : [];
  const models = Array.isArray(state.ramanLabPayload.models) ? state.ramanLabPayload.models : [];
  const selectedFiles = (state.dashboardFilesPayload.files || []).filter((file) => state.selectedBatchFileIds.has(file.file_id));
  body.innerHTML = `
    <div class="raman-lab-grid">
      <section class="auth-card">
        <h3>生成测试集</h3>
        <form id="createRamanDatasetForm">
          <input class="form-input" name="name" placeholder="测试集名称" required />
          <textarea class="form-textarea" name="description" placeholder="说明"></textarea>
          <button class="pill-button" type="submit">用已选文件创建</button>
        </form>
        <div class="panel-note">当前文件中心已选 ${escapeHtml(String(selectedFiles.length))} 个文件。</div>
      </section>
      <section class="auth-card">
        <h3>运行 Benchmark</h3>
        <label class="form-label">测试集</label>
        <select id="benchmarkDatasetSelect" class="form-select">
          ${datasets.map((dataset) => `<option value="${escapeHtml(dataset.dataset_id)}">${escapeHtml(dataset.name || dataset.dataset_id)}</option>`).join("")}
        </select>
        <button id="runBenchmarkBtn" class="pill-button" type="button">运行基础 Pipeline</button>
      </section>
      <section class="auth-card">
        <h3>训练候选模型</h3>
        <form id="runRamanTrainingForm">
          <select class="form-select" name="model_type">
            ${["SVR", "RandomForestRegressor", "PLSRegression", "Ridge", "Lasso", "LinearRegression", "KNNRegressor"].map((name) => `<option value="${name}">${name}</option>`).join("")}
          </select>
          <textarea class="form-textarea" name="features" rows="3" placeholder="features JSON，例如 [[1,2,3],[2,3,4]]"></textarea>
          <textarea class="form-textarea" name="targets" rows="3" placeholder="targets JSON，例如 [0.1,0.2]"></textarea>
          <button class="pill-button" type="submit">训练并注册</button>
        </form>
      </section>
    </div>
    <div class="entity-list">
      ${datasets.length ? datasets.map((dataset) => `
        <article class="entity-card">
          <div class="entity-card-head">
            <div>
              <h4>${escapeHtml(dataset.name || "未命名测试集")}</h4>
              <div class="entity-meta">${escapeHtml(dataset.dataset_id || "")} · 样本 ${escapeHtml(String(dataset.sample_count || 0))} · ${escapeHtml(dataset.target_name || "methanol")}</div>
            </div>
          </div>
        </article>
      `).join("") : `<div class="panel-note">还没有 Raman 测试集。</div>`}
      ${models.length ? models.map((model) => `
        <article class="entity-card">
          <div class="entity-card-head">
            <div>
              <h4>${escapeHtml(model.model_type || model.model_id || "候选模型")}</h4>
              <div class="entity-meta">${escapeHtml(model.model_id || "")} · ${escapeHtml(model.status || "")} · ${escapeHtml(model.created_at || "")}</div>
            </div>
            <button class="pill-button small ghost" type="button" data-activate-raman-model="${escapeHtml(model.model_id || "")}">设为候选激活</button>
          </div>
        </article>
      `).join("") : `<div class="panel-note">还没有训练注册模型。</div>`}
    </div>
    ${state.ramanLabPayload.lastBenchmark ? `<pre class="json-preview">${escapeHtml(JSON.stringify(state.ramanLabPayload.lastBenchmark, null, 2))}</pre>` : ""}
    ${state.ramanLabPayload.lastTraining ? `<pre class="json-preview">${escapeHtml(JSON.stringify(state.ramanLabPayload.lastTraining, null, 2))}</pre>` : ""}
  `;
  $("createRamanDatasetForm")?.addEventListener("submit", handleCreateRamanDataset);
  $("runBenchmarkBtn")?.addEventListener("click", handleRunRamanBenchmark);
  $("runRamanTrainingForm")?.addEventListener("submit", handleRunRamanTraining);
  body.querySelectorAll("[data-activate-raman-model]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await activateTrainedRamanModel(button.dataset.activateRamanModel || "");
      showToast(response.success ? "候选模型已激活" : (response.error_message || "激活失败"), response.success ? "success" : "error");
      await loadRamanLabData();
      renderRamanLabPanel();
    });
  });
}

async function loadToolCatalogData() {
  const response = await getToolCatalog();
  state.toolCatalogPayload = response?.success ? response : { tools: {} };
  renderToolCatalogPanel();
}

async function loadAuditLogData() {
  const response = await getAuditLogs({ limit: 30 });
  state.auditLogsPayload = response?.success ? response : response || { logs: [] };
  renderAuditLogPanel();
}

async function loadRamanLabData() {
  const [datasetsResponse, modelsResponse] = await Promise.all([
    getRamanDatasets(),
    getTrainedRamanModels(),
  ]);
  state.ramanLabPayload = {
    ...state.ramanLabPayload,
    datasets: datasetsResponse?.success && Array.isArray(datasetsResponse.datasets) ? datasetsResponse.datasets : [],
    models: modelsResponse?.success && Array.isArray(modelsResponse.models) ? modelsResponse.models : [],
  };
  renderRamanLabPanel();
}

async function handleCreateRamanDataset(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const selectedFiles = (state.dashboardFilesPayload.files || []).filter((file) => state.selectedBatchFileIds.has(file.file_id));
  if (!selectedFiles.length) {
    showToast("请先在文件中心选择文件", "error");
    return;
  }
  const response = await createRamanDataset({
    name: String(form.get("name") || ""),
    description: String(form.get("description") || ""),
    files: selectedFiles.map((file) => file.path || file.file_path || file.saved_file || "").filter(Boolean),
    sample_count: selectedFiles.length,
    target_type: "regression",
    target_name: "methanol",
  });
  if (!response.success) {
    showToast(response.error_message || "创建测试集失败", "error");
    return;
  }
  showToast("Raman 测试集已创建", "success");
  await loadRamanLabData();
}

async function handleRunRamanBenchmark() {
  const datasetId = $("benchmarkDatasetSelect")?.value || "";
  if (!datasetId) {
    showToast("请先创建或选择测试集", "error");
    return;
  }
  const response = await runRamanBenchmark({
    dataset_id: datasetId,
    pipelines: [{ template_id: "basic_preprocessing" }],
  });
  if (!response.success) {
    showToast(response.error_message || "Benchmark 运行失败", "error");
    return;
  }
  state.ramanLabPayload.lastBenchmark = response.benchmark || response;
  showToast("Benchmark 运行完成", "success");
  renderRamanLabPanel();
}

async function handleRunRamanTraining(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  let features = [];
  let targets = [];
  try {
    features = JSON.parse(String(form.get("features") || "[]"));
    targets = JSON.parse(String(form.get("targets") || "[]"));
  } catch {
    showToast("features 或 targets JSON 不合法", "error");
    return;
  }
  const response = await runRamanTraining({
    model_type: String(form.get("model_type") || "SVR"),
    target: "methanol",
    features,
    targets,
  });
  if (!response.success) {
    showToast(response.error_message || response.message || "训练失败", "error");
    state.ramanLabPayload.lastTraining = response;
    renderRamanLabPanel();
    return;
  }
  state.ramanLabPayload.lastTraining = response;
  showToast("候选模型训练完成并已注册", "success");
  await loadRamanLabData();
}

function renderReportCenter() {
  const body = $("reportCenterBody");
  if (!body) {
    return;
  }
  const reports = Array.isArray(state.reportsPayload?.reports) ? state.reportsPayload.reports : [];
  body.innerHTML = reports.length
    ? `<div class="entity-list">${reports.map((report) => `
        <article class="entity-card">
          <div class="entity-card-head">
            <div>
              <h4>${escapeHtml(report.title || "未命名报告")}</h4>
              <div class="entity-meta">项目：${escapeHtml(report.project_id || "未绑定")} · 文件：${escapeHtml(report.file_id || "未知")} · 时间：${escapeHtml(report.created_at || "")}</div>
            </div>
            <div class="entity-tags">
              <span class="entity-tag">${escapeHtml(report.status || "")}</span>
              <span class="entity-tag">${escapeHtml(report.report_type || "")}</span>
            </div>
          </div>
          ${report.error_message ? `<div class="inline-error">${escapeHtml(report.error_message)}</div>` : ""}
          <div class="inline-actions">
            ${report.markdown_path ? `<button class="pill-button small" type="button" data-report-download="${escapeHtml(report.report_id || "")}" data-report-format="markdown">Markdown</button>` : ""}
            ${report.html_path ? `<button class="pill-button small" type="button" data-report-download="${escapeHtml(report.report_id || "")}" data-report-format="html">HTML</button>` : ""}
            ${report.docx_path ? `<button class="pill-button small" type="button" data-report-download="${escapeHtml(report.report_id || "")}" data-report-format="docx">Word</button>` : ""}
            ${report.pdf_path ? `<button class="pill-button small" type="button" data-report-download="${escapeHtml(report.report_id || "")}" data-report-format="pdf">PDF</button>` : ""}
            <button class="pill-button small ghost" type="button" data-report-delete="${escapeHtml(report.report_id || "")}">删除</button>
          </div>
        </article>
      `).join("")}</div>`
    : `<div class="panel-note">当前还没有导出报告。</div>`;
  body.querySelectorAll("[data-report-download]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await downloadReport(button.dataset.reportDownload || "", button.dataset.reportFormat || "markdown");
      if (!response.success) {
        showToast(response.error_message || "下载报告失败", "error");
      }
    });
  });
  body.querySelectorAll("[data-report-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await requestDeleteReport(button.dataset.reportDelete || "");
      if (!response.success) {
        showToast(response.error_message || "删除报告失败", "error");
        return;
      }
      showToast("报告已删除", "success");
      await loadPhase2Data();
    });
  });
}

async function loadPhase2Data() {
  if (!state.currentUser) {
    setAuthUiVisible(false);
    renderProjectPanel();
    renderFileCenter();
    renderTaskCenter();
    renderToolCatalogPanel();
    renderRamanLabPanel();
    renderAuditLogPanel();
    renderReportCenter();
    return;
  }
  const projectId = state.selectedProjectId || "";
  const [projects, files, tasks, reports, tools, datasets, trainedModels, auditLogs] = await Promise.all([
    getProjects(),
    getFiles({ userId: state.userId, projectId }),
    getTasks({ userId: state.userId, workspaceId: "" }),
    getReports(projectId),
    getToolCatalog(),
    getRamanDatasets(),
    getTrainedRamanModels(),
    getAuditLogs({ limit: 30 }),
  ]);
  state.projectsPayload = projects?.success ? projects : { projects: [] };
  const projectList = Array.isArray(state.projectsPayload.projects) ? state.projectsPayload.projects : [];
  if (state.selectedProjectId && !projectList.some((item) => item.project_id === state.selectedProjectId)) {
    state.selectedProjectId = "";
  }
  state.dashboardFilesPayload = files?.success ? files : { files: [] };
  state.dashboardTasksPayload = tasks?.success ? tasks : { tasks: [] };
  state.reportsPayload = reports?.success ? reports : { reports: [] };
  state.toolCatalogPayload = tools?.success ? tools : { tools: {} };
  state.ramanLabPayload = {
    ...state.ramanLabPayload,
    datasets: datasets?.success && Array.isArray(datasets.datasets) ? datasets.datasets : [],
    models: trainedModels?.success && Array.isArray(trainedModels.models) ? trainedModels.models : [],
  };
  state.auditLogsPayload = auditLogs?.success ? auditLogs : auditLogs || { logs: [] };
  const visibleFileIds = new Set((state.dashboardFilesPayload.files || []).map((item) => item.file_id));
  state.selectedBatchFileIds = new Set([...state.selectedBatchFileIds].filter((fileId) => visibleFileIds.has(fileId)));
  setAuthUiVisible(true);
  renderProjectPanel();
  renderFileCenter();
  renderTaskCenter();
  renderToolCatalogPanel();
  renderRamanLabPanel();
  renderAuditLogPanel();
  renderReportCenter();
}

async function refreshAuthSession() {
  const response = await getAuthMe();
  if (!response.success) {
    state.currentUser = null;
    state.userId = "default_user";
    clearAuthToken();
    state.authToken = "";
    setAuthUiVisible(false);
    renderAuthPanel();
    state.conversationSidebar?.refreshConversations();
    return false;
  }
  state.currentUser = response.user || null;
  state.userId = state.currentUser?.user_id || "default_user";
  setAuthUiVisible(true);
  renderAuthPanel();
  state.conversationSidebar?.refreshConversations();
  return true;
}

async function handleLoginSubmit(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const response = await loginUser(String(form.get("username") || ""), String(form.get("password") || ""));
  if (!response.success) {
    showToast(response.error_message || "登录失败", "error");
    return;
  }
  setAuthToken(response.token || "");
  state.authToken = response.token || "";
  state.currentUser = response.user || null;
  state.userId = state.currentUser?.user_id || "default_user";
  showToast("登录成功", "success");
  renderAuthPanel();
  state.conversationSidebar?.refreshConversations();
  await loadPhase2Data();
}

async function handleRegisterSubmit(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const response = await registerUser(String(form.get("username") || ""), String(form.get("password") || ""));
  if (!response.success) {
    showToast(response.error_message || "注册失败", "error");
    return;
  }
  setAuthToken(response.token || "");
  state.authToken = response.token || "";
  state.currentUser = response.user || null;
  state.userId = state.currentUser?.user_id || "default_user";
  showToast("注册成功，已自动登录", "success");
  renderAuthPanel();
  state.conversationSidebar?.refreshConversations();
  await loadPhase2Data();
}

async function handleLogout() {
  await logoutUser();
  clearAuthToken();
  state.authToken = "";
  state.currentUser = null;
  state.userId = "default_user";
  state.selectedProjectId = "";
  state.selectedBatchFileIds = new Set();
  state.projectsPayload = { projects: [] };
  state.reportsPayload = { reports: [] };
  state.dashboardFilesPayload = { files: [] };
  state.dashboardTasksPayload = { tasks: [] };
  state.toolCatalogPayload = { tools: {} };
  state.auditLogsPayload = { logs: [] };
  state.ramanLabPayload = { datasets: [], models: [], lastBenchmark: null, lastTraining: null };
  setAuthUiVisible(false);
  renderAuthPanel();
  renderProjectPanel();
  renderFileCenter();
  renderTaskCenter();
  renderToolCatalogPanel();
  renderRamanLabPanel();
  renderAuditLogPanel();
  renderReportCenter();
  state.conversationSidebar?.refreshConversations();
  showToast("已退出登录", "success");
}

async function handleCreateProject(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const response = await createProject({
    name: String(form.get("name") || ""),
    description: String(form.get("description") || ""),
  });
  if (!response.success) {
    showToast(response.error_message || "创建项目失败", "error");
    return;
  }
  state.selectedProjectId = response.project?.project_id || "";
  showToast("项目已创建", "success");
  await loadPhase2Data();
}

async function handleDashboardUpload(event) {
  event.preventDefault();
  const file = $("dashboardFileInput")?.files?.[0];
  if (!file) {
    showToast("请先选择文件", "error");
    return;
  }
  const response = await uploadWorkspaceFile(file, {
    userId: state.userId,
    conversationId: state.sessionId || "dashboard-upload",
    projectId: state.selectedProjectId || "",
  });
  if (!response.success) {
    showToast(response.error_message || "上传文件失败", "error");
    return;
  }
  showToast("文件上传成功", "success");
  await loadPhase2Data();
}

async function handleBatchAnalyze() {
  const fileIds = [...state.selectedBatchFileIds];
  if (!fileIds.length) {
    showToast("请先选择至少一个文件", "error");
    return;
  }
  const response = await batchAnalyze(
    {
      file_ids: fileIds,
      project_id: state.selectedProjectId || undefined,
      options: {
        generate_report: true,
        export_formats: ["markdown"],
      },
    },
    { asyncTask: true },
  );
  if (!response.success) {
    showToast(response.error_message || "批量分析失败", "error");
    return;
  }
  if (response.async_task) {
    showToast(`批量分析任务已创建：${response.task_id || ""}`, "success");
    await loadPhase2Data();
    return;
  }
  const summary = response.summary || {};
  showToast(`批量分析完成：成功 ${summary.success_count || 0}，失败 ${summary.failed_count || 0}`, summary.failed_count ? "info" : "success");
  await loadPhase2Data();
}

function openDashboardCard(cardId) {
  const card = $(cardId);
  if (!card) {
    return;
  }
  card.open = true;
  card.scrollIntoView({ behavior: "smooth", block: "start" });
}

function bindPhase2Events() {
  $("refreshAuthBtn")?.addEventListener("click", async () => {
    await refreshAuthSession();
    if (state.currentUser) {
      await loadPhase2Data();
    }
  });
  $("refreshProjectsBtn")?.addEventListener("click", loadPhase2Data);
  $("refreshFilesBtn")?.addEventListener("click", loadPhase2Data);
  $("refreshTasksBtn")?.addEventListener("click", loadPhase2Data);
  $("refreshReportsBtn")?.addEventListener("click", loadPhase2Data);
  $("refreshToolsBtn")?.addEventListener("click", loadToolCatalogData);
  $("refreshRamanLabBtn")?.addEventListener("click", loadRamanLabData);
  $("refreshAuditLogsBtn")?.addEventListener("click", loadAuditLogData);
  $("toolCatalogButton")?.addEventListener("click", async () => {
    openDashboardCard("toolCatalogCard");
    if (!Object.keys(state.toolCatalogPayload?.tools || {}).length) {
      await loadToolCatalogData();
    }
  });
  $("ramanLabButton")?.addEventListener("click", async () => {
    openDashboardCard("ramanLabCard");
    if (!state.ramanLabPayload.datasets.length && !state.ramanLabPayload.models.length) {
      await loadRamanLabData();
    }
  });
  $("auditLogsButton")?.addEventListener("click", async () => {
    openDashboardCard("auditLogCard");
    if (!state.auditLogsPayload.logs.length) {
      await loadAuditLogData();
    }
  });
}

function buildChatRequestOptions(message, selectedFiles, timeoutMs) {
  const currentLlm = state.llmModelsPayload.current || {};
  return {
    message,
    sessionId: state.sessionId || "",
    userId: state.userId,
    debug: false,
    files: selectedFiles,
    metadata: {
      remarks: "",
      timeoutMs,
      providerId: currentLlm.provider_id || undefined,
      modelId: currentLlm.model_id || undefined,
    },
  };
}

function applyChatResponseSideEffects(response, { renderResponse = true } = {}) {
  if (response.conversation_id || response.session_id) {
    state.sessionId = response.conversation_id || response.session_id;
    persistSessionId(state.sessionId);
  }

  const treatAsSuccess = response.success === true || (response.reply && !response.error_message);
  if (!treatAsSuccess) {
    console.error("发送消息失败：", response);
    if (renderResponse) {
      const friendlyMessage = escapeHtml(formatResponseError(response));
      appendMessage("assistant", `<p class="error-message">${friendlyMessage}</p>`, "error");
    }
    return false;
  }

  if (renderResponse) {
    renderAssistantResponse(response);
  }
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
  state.selectedFiles = [];
  const fileInput = $("fileInput");
  if (fileInput) {
    fileInput.value = "";
  }
  renderSelectedFileChip([]);
  const input = $("messageInput");
  if (input) {
    input.value = "";
  }
  autoResizeTextarea();
  loadRamanStatusSafely();
  if (state.workspaceOpen) {
    refreshWorkspacePanel();
  }
  if (state.knowledgeBasePanel?.isOpen?.()) {
    state.knowledgeBasePanel.refresh();
  }
  state.conversationSidebar?.refreshConversations();
  return true;
}

async function sendChatMessageStreaming(requestOptions) {
  const controller = new AbortController();
  state.streamAbortController = controller;
  setBusy(true, requestOptions.files?.length ? "正在上传文件并流式分析..." : "正在流式生成...");
  const streamContext = appendStreamingAssistantMessage();
  try {
    const response = await sendAgentChatStream(requestOptions, { signal: controller.signal });
    await readSseStream(response, (eventPayload) => handleStreamEvent(streamContext, eventPayload));
    if (!streamContext.receivedFinal) {
      throw new Error("流式响应没有返回 final 事件。");
    }
    return streamContext.finalResponse || {
      success: true,
      reply: streamContext.answerText || "处理完成。",
      conversation_id: state.sessionId,
      session_id: state.sessionId,
    };
  } catch (error) {
    if (error.name === "AbortError") {
      appendStreamTrace(streamContext, { event: "done", content: "已停止生成。" });
      if (!streamContext.answerText) {
        replaceStreamAnswer(streamContext, "已停止生成。");
      }
      return {
        success: true,
        reply: streamContext.answerText || "已停止生成。",
        conversation_id: state.sessionId,
        session_id: state.sessionId,
        stopped: true,
      };
    }
    if (!streamContext.receivedAnyEvent) {
      streamContext.row?.remove();
      throw error;
    }
    appendStreamTrace(streamContext, { event: "error", content: error.message || "流式响应中断。" });
    if (!streamContext.answerText) {
      replaceStreamAnswer(streamContext, error.message || "流式响应中断。");
    }
    return {
      success: false,
      error_message: error.message || "流式响应中断。",
      reply: streamContext.answerText,
      conversation_id: state.sessionId,
      session_id: state.sessionId,
    };
  } finally {
    state.streamAbortController = null;
    setBusy(false);
  }
}

async function sendChatMessage(presetMessage = "") {
  if (state.chatBusy) {
    return;
  }

  const input = $("messageInput");
  const message = (presetMessage || input?.value || "").trim();
  const selectedFiles = state.selectedFiles?.length ? state.selectedFiles : (state.selectedFile ? [state.selectedFile] : []);
  const selectedFile = selectedFiles[0] || null;
  const timeoutMs = getChatRequestTimeout({ hasFile: Boolean(selectedFile), message });

  if (!message && !selectedFile) {
    setChatStatus("请输入消息，或者先选择一个文件。");
    return;
  }

  appendMessage("user", `<p>${escapeHtml(message || "请分析这个文件")}</p>`, "text");
  selectedFiles.forEach((file) => appendFileCard(file));

  if (input) {
    input.value = "";
    autoResizeTextarea();
  }

  const requestOptions = buildChatRequestOptions(message, selectedFiles, timeoutMs);

  try {
    const requestStartedAt = performance.now();
    if (state.useStreaming) {
      try {
        const streamedResponse = await sendChatMessageStreaming(requestOptions);
        streamedResponse.client_elapsed_ms = Math.round(performance.now() - requestStartedAt);
        applyChatResponseSideEffects(streamedResponse, { renderResponse: false });
        return;
      } catch (streamError) {
        console.warn("流式请求失败，回退普通聊天接口：", streamError);
        showToast("流式响应不可用，已回退普通响应。", "info");
      }
    }

    setBusy(true, selectedFile ? "正在上传文件并分析..." : "正在思考...");
    renderTypingMessage(selectedFile ? "正在分析文件内容，可能需要几十秒，请稍候..." : "正在处理，请稍候...");
    const response = await sendAgentChat(requestOptions);
    response.client_elapsed_ms = Math.round(performance.now() - requestStartedAt);

    removeTypingMessage();
    setBusy(false);

    applyChatResponseSideEffects(response, { renderResponse: true });
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
  bindPhase2Events();
  state.conversationSidebar = initConversationSidebar({
    getState: () => state,
    setSessionId: persistSessionId,
    renderConversationMessages,
    clearForNewConversation,
    showToast,
    refreshWorkspace: async () => {
      if (state.workspaceOpen) {
        await refreshWorkspacePanel();
      }
    },
  });
  state.knowledgeBasePanel = initKnowledgeBasePanel({
    getState: () => state,
    showToast,
    onWorkspaceChanged: async () => {
      if (state.workspaceOpen) {
        await refreshWorkspacePanel();
      }
    },
  });
  restoreSessionIfNeeded();
  renderWelcomeMessage();
  renderAuthPanel();
  setAuthUiVisible(false);
  autoResizeTextarea();
  setChatStatus(state.sessionId ? `当前会话：${state.sessionId}` : "可以直接提问，或上传任意文件后发送。");
  loadLlmModelsSafely();
  loadRamanStatusSafely();
  loadSkillsSafely();
  state.conversationSidebar?.refreshConversations();
  refreshAuthSession().then((loggedIn) => {
    if (loggedIn) {
      loadPhase2Data();
    }
  });
}

initApp();
