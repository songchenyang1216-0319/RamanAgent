import {
  analyzeFile,
  chatWithAgent,
  checkCurrentModel,
  getCurrentModel,
  getHistoryDetail,
  listHistory,
  toAssetUrl,
} from "./js/api.js";

const STORAGE_KEYS = {
  sessionId: "ramanagent.sessionId",
};

const state = {
  currentModel: null,
  latestAnalysis: null,
  sessionId: loadSessionId(),
  chatBusy: false,
  analysisBusy: false,
  figureModalUrl: "",
  figureModalTitle: "",
};

const $ = (id) => document.getElementById(id);

function loadSessionId() {
  try {
    return localStorage.getItem(STORAGE_KEYS.sessionId) || "";
  } catch {
    return "";
  }
}

function persistSessionId(sessionId) {
  state.sessionId = sessionId || "";
  try {
    if (state.sessionId) {
      localStorage.setItem(STORAGE_KEYS.sessionId, state.sessionId);
    } else {
      localStorage.removeItem(STORAGE_KEYS.sessionId);
    }
  } catch {
    // ignore storage failures
  }
  renderSessionState();
}

function formatNumber(value, digits = 4) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) {
    return "未提供";
  }
  return Number(value).toFixed(digits);
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) {
    return "未提供";
  }
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdown(markdownText) {
  const escaped = escapeHtml(markdownText || "未生成解释。");
  const lines = escaped.split(/\r?\n/);
  const parts = [];
  let inList = false;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      if (inList) {
        parts.push("</ul>");
        inList = false;
      }
      continue;
    }
    if (line.startsWith("### ")) {
      if (inList) {
        parts.push("</ul>");
        inList = false;
      }
      parts.push(`<h3>${line.slice(4).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")}</h3>`);
      continue;
    }
    if (line.startsWith("## ")) {
      if (inList) {
        parts.push("</ul>");
        inList = false;
      }
      parts.push(`<h2>${line.slice(3).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")}</h2>`);
      continue;
    }
    if (line.startsWith("- ")) {
      if (!inList) {
        parts.push("<ul>");
        inList = true;
      }
      parts.push(`<li>${line.slice(2).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")}</li>`);
      continue;
    }
    if (inList) {
      parts.push("</ul>");
      inList = false;
    }
    parts.push(`<p>${line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")}</p>`);
  }

  if (inList) {
    parts.push("</ul>");
  }
  return parts.join("");
}

function renderList(items, emptyText = "暂无") {
  if (!Array.isArray(items) || items.length === 0) {
    return `<p class="muted">${escapeHtml(emptyText)}</p>`;
  }
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function renderKeyValue(container, rows) {
  container.innerHTML = rows
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? "未提供")}</strong></div>`)
    .join("");
}

function renderJsonDetails(title, value) {
  return `<details><summary>${escapeHtml(title)}</summary><pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre></details>`;
}

function setBadge(element, text, type = "neutral") {
  element.textContent = text;
  element.className = `badge ${type}`;
}

function setError(message) {
  $("errorText").textContent = message || "";
}

function setChatStatus(message) {
  $("chatStatus").textContent = message || "";
}

function setAnalysisProgress(message) {
  $("analysisProgress").textContent = message || "";
}

function setHistoryStatus(message) {
  $("historyStatus").textContent = message || "";
}

function renderSessionState() {
  $("sessionIdText").textContent = state.sessionId || "未创建";
}

function normalizeErrorMessage(message, context = "") {
  const text = `${message || ""} ${context || ""}`.toLowerCase();
  if (text.includes("siliconflow_api_key") || text.includes("未配置") || text.includes("api key")) {
    return "当前大模型服务还没有配置好，所以页面会自动切换到本地兜底回复。";
  }
  if (text.includes("csv") || text.includes("文件格式") || text.includes("只支持")) {
    return "文件格式可能不对，请确认上传的是 `.csv` 文件，而且内容是两列光谱数据。";
  }
  if (text.includes("缺少模型") || text.includes("模型文件") || text.includes("工件")) {
    return "模型文件还没准备完整，当前分析暂时无法继续。可以先检查模型文件是否齐全。";
  }
  if (text.includes("failed to fetch") || text.includes("network") || text.includes("后端") || text.includes("连接")) {
    return "后端暂时没有连上，请确认服务已经启动后再试一次。";
  }
  if (!message) {
    return "请求失败了，请稍后重试。";
  }
  return String(message);
}

function createChatMessage(role, title, content, meta = "", extra = "") {
  return `
    <div class="chat-head">
      <span class="chat-role">${escapeHtml(title)}</span>
      ${meta ? `<span class="muted">${escapeHtml(meta)}</span>` : ""}
    </div>
    <div class="chat-content">${content}</div>
    ${extra}
  `;
}

function appendChatMessage(role, title, content, meta = "", extra = "") {
  const message = document.createElement("div");
  message.className = `chat-message ${role}`;
  message.innerHTML = createChatMessage(role, title, content, meta, extra);
  $("chatMessages").appendChild(message);
  $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
  return message;
}

function replaceChatMessage(node, role, title, content, meta = "", extra = "") {
  if (!node) {
    return appendChatMessage(role, title, content, meta, extra);
  }
  node.className = `chat-message ${role}`;
  node.innerHTML = createChatMessage(role, title, content, meta, extra);
  $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
  return node;
}

function renderChatPayload(response) {
  const metaParts = [
    response.category ? `category: ${response.category}` : "",
    response.intent ? `intent: ${response.intent}` : "",
    response.tool_used ? `tool: ${response.tool_used}` : "",
  ].filter(Boolean);

  const data = response.data || {};
  const dataSection = renderChatData(data);
  const nextAction = response.next_action ? `<p class="muted">${escapeHtml(response.next_action)}</p>` : "";
  const note = response.llm_note ? `<p class="muted">${escapeHtml(response.llm_note)}</p>` : "";
  const debugHtml = response._debug_html || "";

  return `
    <p>${escapeHtml(response.reply || "")}</p>
    <div class="chat-meta">${escapeHtml(metaParts.join(" · "))}</div>
    ${dataSection}
    ${nextAction}
    ${note}
    ${debugHtml}
  `;
}

function renderChatData(data) {
  if (!data || (typeof data === "object" && Object.keys(data).length === 0)) {
    return "";
  }
  if (data.model_version) {
    return `
      <div class="compact-data">
        <strong>${escapeHtml(data.model_version)}</strong>
        <span>${escapeHtml(data.model_name || data.task || "")}</span>
        <span>${escapeHtml((data.algorithm || []).join(", "))}</span>
      </div>
    `;
  }
  if (data.final_prediction !== undefined || data.fusion_prediction !== undefined) {
    return `
      <div class="compact-data">
        <strong>融合预测值：${escapeHtml(formatNumber(data.final_prediction ?? data.fusion_prediction))}</strong>
        <span>SVR：${escapeHtml(formatNumber(data.svr_prediction))} · RF：${escapeHtml(formatNumber(data.rf_prediction))}</span>
      </div>
    `;
  }
  if (Array.isArray(data.items)) {
    return `
      <div class="compact-data">
        ${data.items
          .slice(0, 3)
          .map((item) => `<span>${escapeHtml(item.sample_file || item.task_id || "")} ${escapeHtml(formatNumber(item.final_prediction ?? item.fusion_prediction))}</span>`)
          .join("")}
      </div>
    `;
  }
  if (data.missing_files) {
    return `<div class="compact-data"><strong>缺失 ${data.missing_files.length} 个文件</strong><span>${escapeHtml(data.message || "")}</span></div>`;
  }
  return renderJsonDetails("核心数据", data);
}

function setChatBusy(isBusy, text = "正在思考...") {
  state.chatBusy = isBusy;
  $("sendChatBtn").disabled = isBusy;
  $("chatInput").disabled = isBusy;
  $("chatDebug").disabled = isBusy;
  setChatStatus(isBusy ? text : state.sessionId ? `当前会话：${state.sessionId}` : "尚未创建会话");
}

function setAnalysisBusy(isBusy, text = "正在分析...") {
  state.analysisBusy = isBusy;
  $("analyzeBtn").disabled = isBusy;
  $("csvFile").disabled = isBusy;
  setAnalysisProgress(isBusy ? text : "");
}

function normalizeFigureValue(value, fallbackLabel, index) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  if (typeof value === "string") {
    return { label: fallbackLabel || `图谱 ${index + 1}`, url: value };
  }
  if (Array.isArray(value)) {
    return value.flatMap((item, childIndex) => {
      const normalized = normalizeFigureValue(item, `${fallbackLabel || "图谱"}-${childIndex + 1}`, childIndex);
      return Array.isArray(normalized) ? normalized.filter(Boolean) : normalized ? [normalized] : [];
    });
  }
  if (typeof value === "object") {
    return {
      label: value.label || value.name || fallbackLabel || `图谱 ${index + 1}`,
      url: value.url || value.href || value.path || value.value || "",
    };
  }
  return { label: fallbackLabel || `图谱 ${index + 1}`, url: String(value) };
}

function flattenFigureEntries(source) {
  if (!source) {
    return [];
  }
  if (Array.isArray(source)) {
    return source.flatMap((item, index) => {
      const normalized = normalizeFigureValue(item, `图谱 ${index + 1}`, index);
      return Array.isArray(normalized) ? normalized.filter(Boolean) : normalized ? [normalized] : [];
    });
  }
  if (typeof source === "object") {
    return Object.entries(source).flatMap(([key, value], index) => {
      if (Array.isArray(value)) {
        return value.flatMap((item, childIndex) => {
          const normalized = normalizeFigureValue(item, `${key}-${childIndex + 1}`, childIndex);
          return Array.isArray(normalized) ? normalized.filter(Boolean) : normalized ? [normalized] : [];
        });
      }
      const normalized = normalizeFigureValue(value, key, index);
      return Array.isArray(normalized) ? normalized.filter(Boolean) : normalized ? [normalized] : [];
    });
  }
  return [];
}

function normalizeFigureEntries(payload) {
  return flattenFigureEntries(payload.figure_urls || payload.web_urls?.figures || payload.result?.figure_urls || payload.result?.figures || {});
}

function openFigureModal(url, title) {
  state.figureModalUrl = url;
  state.figureModalTitle = title || "图谱预览";
  $("figureModalTitle").textContent = state.figureModalTitle;
  $("figureModalImage").src = url;
  $("figureModalOpenLink").href = url;
  $("figureModal").classList.remove("hidden");
}

function closeFigureModal() {
  $("figureModal").classList.add("hidden");
  $("figureModalImage").src = "";
  $("figureModalOpenLink").href = "#";
  state.figureModalUrl = "";
  state.figureModalTitle = "";
}

function renderAnalysisSnapshot(payload) {
  const result = payload.result || {};
  const professional = payload.professional_analysis || {};
  const summary = professional.professional_summary || {};
  const quality = professional.quality_analysis || {};
  const baseline = professional.baseline_analysis || {};
  const ood = summary.ood_risk || professional.ood_risk || {};
  const risks = (summary.risks || []).slice(0, 3);

  const qualityLabel = quality.overall_quality || quality.quality_level || "未评估";
  const confidenceText = result.confidence?.status || "未提供";
  const predictionText = `${formatNumber(result.final_prediction ?? result.fusion_prediction)} ${result.unit || ""}`.trim();
  const oodText = ood.level ? `${ood.level} / ${formatNumber(ood.score, 2)}` : "未评估";

  $("analysisSnapshot").innerHTML = [
    ["融合预测值", predictionText || "未提供"],
    ["可信度", confidenceText],
    ["光谱质量", `${qualityLabel}${quality.score !== undefined ? ` · ${formatNumber(quality.score, 2)}` : ""}`],
    ["基线状态", baseline.baseline_level || "未提供"],
    ["OOD 风险", oodText],
    ["关键风险", risks.length ? risks.join("；") : "暂无明显风险"],
  ]
    .map(([label, value]) => `<div class="snapshot-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");
}

function renderPrediction(result) {
  const disagreement = result.model_disagreement || {};
  const confidence = result.confidence || {};
  const unit = result.unit || "%";
  $("predictionCards").innerHTML = [
    ["融合预测值", `${formatNumber(result.final_prediction ?? result.fusion_prediction)} ${unit}`],
    ["SVR 预测值", `${formatNumber(result.svr_prediction)} ${unit}`],
    ["RF 预测值", `${formatNumber(result.rf_prediction)} ${unit}`],
    ["模型一致性", disagreement.warning ? "需要关注" : "一致性较好"],
    ["绝对差异", formatNumber(disagreement.absolute_difference)],
    ["相对差异", formatPercent(disagreement.relative_difference)],
    ["可信度", confidence.status || "未提供"],
    ["近邻距离", formatNumber(confidence.knn_distance)],
  ]
    .map(([label, value]) => `<div class="metric-card"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");
  $("pipelineText").textContent = Array.isArray(result.pipeline) ? result.pipeline.join(" → ") : "";
}

function renderProfessionalAnalysis(analysis = {}) {
  const summary = analysis.professional_summary || {};
  const quality = analysis.quality_analysis || {};
  const qualityMetrics = quality.metrics || {};
  const baseline = analysis.baseline_analysis || {};
  const baselineMetrics = baseline.metrics || {};
  const peaks = (analysis.peak_analysis || {}).peaks || [];
  const similar = (analysis.similarity_analysis || {}).similar_records || [];

  const summaryLevel = summary.overall_level || "未生成";
  setBadge(
    $("overallLevel"),
    summaryLevel,
    summaryLevel === "poor" ? "error" : summaryLevel === "acceptable" ? "warning" : "success"
  );
  $("professionalSummary").innerHTML = `
    <h3>结论</h3>
    <p>${escapeHtml(summary.conclusion || "当前未生成综合结论。")}</p>
    <h3>关键发现</h3>
    ${renderList(summary.key_findings || summary.key_evidence, "当前未生成关键发现")}
    <h3>风险</h3>
    ${renderList(summary.risks, "暂无明显风险")}
    <h3>建议</h3>
    ${renderList(summary.suggestions, "暂无额外建议")}
  `;

  renderKeyValue($("qualityBox"), [
    ["质量等级", quality.overall_quality || quality.quality_level],
    ["质量分", formatNumber(quality.score, 2)],
    ["估计信噪比", formatNumber(qualityMetrics.estimated_snr)],
    ["基线漂移分", formatNumber(qualityMetrics.baseline_drift_score)],
    ["峰尖锐度", formatNumber(qualityMetrics.peak_sharpness_score)],
    ["异常点比例", formatPercent(qualityMetrics.outlier_ratio)],
  ]);

  renderKeyValue($("baselineBox"), [
    ["基线等级", baseline.baseline_level],
    ["回归适用", baseline.regression_suitability],
    ["漂移评分", formatNumber(baselineMetrics.baseline_drift_score)],
    ["负峰风险", baseline.negative_peak_risk ? "是" : "否"],
    ["峰形削弱", baseline.peak_weakening_risk ? "是" : "否"],
    ["过校正风险", baseline.over_subtraction_risk ? "是" : "否"],
  ]);

  $("peaksTable").innerHTML = peaks.length
    ? `<table><thead><tr><th>rank</th><th>峰位</th><th>强度</th><th>prominence</th><th>说明</th></tr></thead><tbody>${peaks
        .slice(0, 8)
        .map((peak) => {
          const annotation = (peak.knowledge_annotations || []).find((item) => item.confidence !== "unknown");
          const label = annotation ? `${annotation.label}${annotation.possible_mode ? ` · ${annotation.possible_mode}` : ""}` : "未匹配内置知识库";
          return `<tr><td>${peak.rank}</td><td>${formatNumber(peak.wavenumber)}</td><td>${formatNumber(peak.intensity)}</td><td>${formatNumber(peak.prominence)}</td><td>${escapeHtml(label)}</td></tr>`;
        })
        .join("")}</tbody></table>`
    : `<p class="muted">当前未生成主要峰分析。</p>`;

  $("similarRecords").innerHTML = similar.length
    ? `<table><thead><tr><th>样品</th><th>预测值</th><th>差异</th><th>时间</th></tr></thead><tbody>${similar
        .map(
          (item) =>
            `<tr><td>${escapeHtml(item.sample_file || "")}</td><td>${formatNumber(item.final_prediction)}</td><td>${formatNumber(item.difference)}</td><td>${escapeHtml(item.created_at || "")}</td></tr>`
        )
        .join("")}</tbody></table>`
    : `<p class="muted">暂无预测浓度接近的历史记录。</p>`;
}

function renderModelInfo(modelInfo = {}) {
  const training = modelInfo.training_data || {};
  const artifactCheck = modelInfo.artifact_check || {};
  const missingCount = (artifactCheck.missing_files || []).length;
  const fallbackCount = (artifactCheck.fallback_files || []).length;
  renderKeyValue($("modelInfoBox"), [
    ["模型版本", modelInfo.model_version],
    ["模型名称", modelInfo.model_name],
    ["目标任务", modelInfo.task || modelInfo.target],
    ["单位", modelInfo.unit],
    ["算法组成", (modelInfo.algorithm || []).join(", ")],
    ["样本数量", training.sample_count],
    ["浓度范围", Array.isArray(training.concentration_range) ? training.concentration_range.join(" - ") : "未提供"],
    ["模型文件", missingCount ? `缺失 ${missingCount} 个` : fallbackCount ? `兼容加载 ${fallbackCount} 个` : "检查通过"],
  ]);
}

function renderExperimentInfo(metadata = {}) {
  renderKeyValue($("experimentInfoBox"), [
    ["样品名", metadata.sample_name],
    ["样品类型", metadata.sample_type],
    ["操作人", metadata.operator],
    ["仪器", metadata.instrument],
    ["激光功率", metadata.laser_power],
    ["积分时间", metadata.integration_time],
    ["备注", metadata.remarks],
  ]);
}

function renderFiguresAndReport(payload) {
  const entries = normalizeFigureEntries(payload);
  const reportView = payload.web_urls?.report_view ? toAssetUrl(payload.web_urls.report_view) : "";
  const reportDownload = payload.web_urls?.report_download ? toAssetUrl(payload.web_urls.report_download) : "";
  const reportHtml = `${reportView ? `<a href="${escapeHtml(reportView)}" target="_blank" rel="noopener noreferrer">查看报告</a>` : ""}${reportDownload ? `<a href="${escapeHtml(reportDownload)}" target="_blank" rel="noopener noreferrer">下载报告</a>` : ""}`;
  $("reportLinks").innerHTML = payload.report
    ? reportHtml || `<span class="muted">报告已生成，但当前没有可访问的链接。</span>`
    : `<span class="muted">暂无报告</span>`;

  if (!entries.length) {
    $("figureGrid").innerHTML = `<div class="history-empty">暂无图谱数据。</div>`;
    return;
  }

  $("figureGrid").innerHTML = entries
    .map((entry, index) => {
      const url = toAssetUrl(entry.url);
      return `
        <figure class="figure-card">
          <button type="button" data-figure-url="${escapeHtml(url)}" data-figure-title="${escapeHtml(entry.label || `图谱 ${index + 1}`)}">
            ${url ? `<img src="${escapeHtml(url)}" alt="${escapeHtml(entry.label || `图谱 ${index + 1}`)}" />` : `<div class="empty-figure">暂无图像</div>`}
          </button>
          <figcaption>
            <span>${escapeHtml(entry.label || `图谱 ${index + 1}`)}</span>
            ${url ? `<a class="figure-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">新窗口</a>` : ""}
          </figcaption>
        </figure>
      `;
    })
    .join("");

  $("figureGrid").querySelectorAll("button[data-figure-url]").forEach((button) => {
    button.addEventListener("click", () => {
      openFigureModal(button.dataset.figureUrl, button.dataset.figureTitle);
    });
  });
}

function renderAnalysisPayload(payload) {
  state.latestAnalysis = payload;
  persistSessionId(payload.session_id || state.sessionId);
  renderAnalysisSnapshot(payload);
  renderPrediction(payload.result || {});
  renderProfessionalAnalysis(payload.professional_analysis || {});
  renderModelInfo(payload.model_info || state.currentModel || {});
  renderExperimentInfo(payload.experiment_metadata || {});
  renderFiguresAndReport(payload);
  $("llmExplanation").innerHTML = renderMarkdown(payload.llm_explanation || "未生成解释。");
  setBadge($("historyTaskBadge"), payload.history?.task_id ? `task ${payload.history.task_id.slice(0, 8)}` : "分析完成", "success");
}

function buildMetadata() {
  return {
    message: "请分析这个 Raman CSV 文件",
    sample_name: $("sampleName").value.trim(),
    sample_type: $("sampleType").value.trim(),
    operator: $("operatorName").value.trim(),
    instrument: $("instrument").value.trim(),
    laser_power: $("laserPower").value.trim(),
    integration_time: $("integrationTime").value.trim(),
    remarks: $("remarks").value.trim(),
  };
}

async function sendChat(message) {
  const text = (message || $("chatInput").value).trim();
  if (!text || state.chatBusy) {
    return;
  }
  $("chatInput").value = "";
  appendChatMessage("user", "你", `<p>${escapeHtml(text)}</p>`, `session ${state.sessionId || "new"}`);
  setChatBusy(true, "正在思考...");
  const loadingBubble = appendChatMessage("agent", "Agent", `<p class="muted">正在思考，请稍等...</p>`, "加载中");

  const debug = $("chatDebug").checked;
  const response = await chatWithAgent(text, debug, state.sessionId || null);
  setChatBusy(false);

  if (!response.success) {
    const friendly = normalizeErrorMessage(response.error_message, text);
    replaceChatMessage(
      loadingBubble,
      "agent",
      "Agent",
      `<p>${escapeHtml(friendly)}</p>`,
      "错误",
      response.error_message ? `<p class="muted">${escapeHtml(response.error_message)}</p>` : ""
    );
    return;
  }

  persistSessionId(response.session_id || state.sessionId);
  const debugHtml = debug
    ? `${response.tool_result ? renderJsonDetails("tool_result", response.tool_result) : ""}${response.available_tools ? renderJsonDetails("available_tools", response.available_tools) : ""}${response.raw_intent ? renderJsonDetails("raw_intent", response.raw_intent) : ""}${response.llm_raw_response ? renderJsonDetails("llm_raw_response", response.llm_raw_response) : ""}`
    : "";
  replaceChatMessage(
    loadingBubble,
    "agent",
    "Agent",
    renderChatPayload({ ...response, _debug_html: debugHtml }),
  );
}

function setUploadStatus(stage, text) {
  setBadge($("analysisStatus"), stage, stage === "失败" ? "error" : stage === "分析完成" ? "success" : "warning");
  setAnalysisProgress(text);
}

async function submitAnalysis() {
  const file = $("csvFile").files[0];
  setError("");
  if (!file) {
    setError("请先选择 CSV 文件。");
    return;
  }
  if (!file.name.toLowerCase().endsWith(".csv")) {
    setError("当前只支持 CSV 文件。");
    return;
  }

  setAnalysisBusy(true, "正在上传文件...");
  setUploadStatus("上传中", "正在上传 CSV 文件...");
  const loadingTimer = setTimeout(() => {
    if (state.analysisBusy) {
      setUploadStatus("分析中", "文件已上传，正在进行光谱分析和报告生成...");
    }
  }, 700);

  const response = await analyzeFile(file, buildMetadata(), state.sessionId || null);
  clearTimeout(loadingTimer);
  setAnalysisBusy(false);

  if (!response.success) {
    setUploadStatus("失败", "");
    const friendly = normalizeErrorMessage(response.error_message, file.name);
    setError(friendly);
    appendChatMessage("agent", "Agent", `<p>${escapeHtml(friendly)}</p>`, "分析失败");
    return;
  }

  persistSessionId(response.session_id || state.sessionId);
  setUploadStatus("分析完成", "分析已完成，下面是结果概览。");
  renderAnalysisPayload(response);
  setError("");
  await refreshHistory();
}

function historyFilters() {
  return {
    limit: 10,
    keyword: $("historyKeyword").value.trim(),
    model_version: $("historyModelVersion").value.trim(),
    min_prediction: $("historyMinPrediction").value,
    max_prediction: $("historyMaxPrediction").value,
    quality_level: $("historyQualityLevel").value.trim(),
    baseline_level: $("historyBaselineLevel").value.trim(),
  };
}

function renderHistoryItems(items) {
  if (!Array.isArray(items) || items.length === 0) {
    $("historyList").innerHTML = `<div class="history-empty">暂无历史记录。</div>`;
    return;
  }

  $("historyList").innerHTML = items
    .map(
      (item) => `
        <button class="history-row" data-task-id="${escapeHtml(item.task_id)}" type="button">
          <span><strong>${escapeHtml(item.sample_file || item.sample_name || "未命名样品")}</strong><em>${escapeHtml((item.task_id || "").slice(0, 8))}</em></span>
          <span>${escapeHtml(formatNumber(item.fusion_prediction))} ${escapeHtml(item.unit || "")}</span>
          <span><span class="tag">${escapeHtml(item.model_version || "未知模型")}</span></span>
          <span><span class="tag">${escapeHtml(item.quality_level || "未评估")}</span></span>
          <span><span class="tag">${escapeHtml(item.baseline_level || "未评估")}</span></span>
          <span>${escapeHtml(item.created_at || "")}</span>
        </button>
      `
    )
    .join("");

  $("historyList").querySelectorAll(".history-row").forEach((row) => {
    row.addEventListener("click", () => loadHistoryDetail(row.dataset.taskId));
  });
}

async function refreshHistory() {
  setHistoryStatus("加载中...");
  const response = await listHistory(historyFilters());
  if (!response.success) {
    $("historyList").innerHTML = `<div class="history-empty">${escapeHtml(normalizeErrorMessage(response.error_message, "历史记录加载失败"))}</div>`;
    setHistoryStatus("加载失败");
    return;
  }
  renderHistoryItems(response.items || []);
  setHistoryStatus(`已加载 ${response.items?.length || 0} 条`);
}

function renderHistoryDetailCard(label, value) {
  return `<div class="history-detail-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? "未提供")}</strong></div>`;
}

function historyDetailHtml(item) {
  const result = item.result || {};
  const confidence = result.confidence || {};
  const report = item.report || {};
  const webUrls = item.web_urls || {};
  const figureUrls = webUrls.figures || {};

  const figureLinks = Object.entries(figureUrls || {})
    .map(([key, value]) => {
      const url = toAssetUrl(value);
      return url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(key)}</a>` : "";
    })
    .filter(Boolean)
    .join("");

  return `
    <div class="history-detail-grid">
      ${renderHistoryDetailCard("文件名", item.sample_file || result.sample_file)}
      ${renderHistoryDetailCard("时间", item.created_at)}
      ${renderHistoryDetailCard("预测值", `${formatNumber(item.fusion_prediction ?? result.fusion_prediction)} ${item.unit || result.unit || ""}`.trim())}
      ${renderHistoryDetailCard("可信度", item.confidence_status || confidence.status)}
      ${renderHistoryDetailCard("模型版本", item.model_version)}
      ${renderHistoryDetailCard("质量/基线", `${item.quality_level || "未评估"} / ${item.baseline_level || "未评估"}`)}
    </div>
    <div class="link-row">
      ${report.report_file ? `<a href="${escapeHtml(toAssetUrl(`/static/reports/${report.report_file}`))}" target="_blank" rel="noopener noreferrer">查看报告</a>` : ""}
      ${figureLinks}
    </div>
    <details>
      <summary>查看完整详情 JSON</summary>
      <pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre>
    </details>
  `;
}

async function loadHistoryDetail(taskId) {
  if (!taskId) {
    return;
  }
  setHistoryStatus(`正在查看 ${taskId.slice(0, 8)}...`);
  const response = await getHistoryDetail(taskId);
  if (!response.success) {
    $("historyDetail").classList.remove("hidden");
    $("historyDetail").innerHTML = `<p class="error-text">${escapeHtml(normalizeErrorMessage(response.error_message, "历史详情加载失败"))}</p>`;
    setHistoryStatus("查看失败");
    return;
  }
  const item = response.item || response.data || {};
  $("historyDetail").classList.remove("hidden");
  $("historyDetail").innerHTML = `
    <h3>${escapeHtml(item.sample_file || "历史详情")}</h3>
    <p class="muted">task_id: ${escapeHtml(item.task_id || taskId)}</p>
    <div class="panel-actions">
      <button id="renderHistoryBtn" class="secondary-action" type="button">渲染到结果区</button>
      ${item.report_file ? `<a href="${escapeHtml(toAssetUrl(`/static/reports/${item.report_file}`))}" target="_blank" rel="noopener noreferrer">查看报告</a>` : ""}
    </div>
    ${historyDetailHtml(item)}
  `;
  const renderButton = $("renderHistoryBtn");
  if (renderButton) {
    renderButton.addEventListener("click", () => renderAnalysisPayload(normalizeHistoryDetail(item)));
  }
  setHistoryStatus("已加载详情");
}

function normalizeHistoryDetail(item) {
  return {
    session_id: state.sessionId,
    result: item.result || {
      sample_file: item.sample_file,
      final_prediction: item.fusion_prediction,
      fusion_prediction: item.fusion_prediction,
      svr_prediction: item.svr_prediction,
      rf_prediction: item.rf_prediction,
      unit: item.unit,
      confidence: { status: item.confidence_status, knn_distance: item.knn_distance, threshold: item.confidence_threshold },
      model_disagreement: {
        absolute_difference: item.model_abs_diff,
        relative_difference: item.model_rel_diff,
        warning: Boolean(item.model_warning),
        message: item.model_message,
      },
      pipeline: item.pipeline_text ? item.pipeline_text.split(" → ") : [],
    },
    professional_analysis: item.professional_analysis || {},
    model_info: item.model_info || {},
    experiment_metadata: item.experiment_metadata || {},
    llm_explanation: item.llm_explanation,
    report: item.report || { report_file: item.report_file, report_path: item.report_path },
    web_urls: item.web_urls || {
      figures: {
        raw: item.raw_figure_url,
        preprocessed: item.preprocessed_figure_url,
        cdae: item.cdae_figure_url,
        final: item.final_figure_url,
      },
      report_view: item.report_file ? `/static/reports/${item.report_file}` : "",
      report_download: item.report_file ? `/api/files/reports/${item.report_file}/download` : "",
    },
  };
}

async function loadModelInfo() {
  const response = await getCurrentModel();
  if (!response.success) {
    setBadge($("backendStatus"), "异常", "error");
    $("modelInfoBox").innerHTML = `<p class="error-text">${escapeHtml(normalizeErrorMessage(response.error_message, "模型信息加载失败"))}</p>`;
    return;
  }
  setBadge($("backendStatus"), "已连接", "success");
  state.currentModel = response.data || {};
  $("topModelVersion").textContent = state.currentModel.model_version || "未知";
  renderModelInfo(state.currentModel);
  const check = await checkCurrentModel(state.currentModel.model_version);
  const data = check.data || {};
  const missingCount = (data.missing_files || []).length;
  setBadge($("topArtifactStatus"), missingCount ? "有缺失" : "正常", missingCount ? "warning" : "success");
}

async function checkModelFiles() {
  const response = await checkCurrentModel(state.currentModel?.model_version);
  const data = response.data || {};
  const missing = data.missing_files || [];
  setBadge($("topArtifactStatus"), missing.length ? "有缺失" : "正常", missing.length ? "warning" : "success");
  appendChatMessage(
    "agent",
    "Agent",
    `<p>${escapeHtml(missing.length ? `模型文件检查完成，缺失 ${missing.length} 个文件。` : "模型文件检查完成，核心文件齐全。")}</p>${renderJsonDetails("检查结果", data)}`,
    "模型检查"
  );
}

function addWelcomeMessages() {
  $("chatMessages").innerHTML = "";
  appendChatMessage(
    "system",
    "系统",
    `<p>你好，我是 RamanAgent。你可以直接问基础问题、聊几句，也可以上传 CSV 做拉曼分析。</p><p class="muted">当前会话会保存在本地浏览器，刷新后可继续沿用同一个 session_id。</p>`,
    state.sessionId ? `已恢复 ${state.sessionId}` : "新会话"
  );
}

function clearCurrentSession() {
  persistSessionId("");
  state.latestAnalysis = null;
  $("chatInput").value = "";
  setError("");
  addWelcomeMessages();
  setChatStatus("已清空当前会话");
}

function bindEvents() {
  $("sendChatBtn").addEventListener("click", () => sendChat());
  $("chatInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      sendChat();
    }
  });
  document.querySelectorAll(".quick-actions button").forEach((button) => {
    button.addEventListener("click", () => sendChat(button.dataset.question));
  });
  $("csvFile").addEventListener("change", () => {
    $("fileName").textContent = $("csvFile").files[0]?.name || "选择 CSV 光谱文件";
  });
  $("analyzeBtn").addEventListener("click", submitAnalysis);
  $("checkModelBtn").addEventListener("click", checkModelFiles);
  $("refreshHistoryBtn").addEventListener("click", refreshHistory);
  $("clearSessionBtn").addEventListener("click", clearCurrentSession);
  $("figureModalCloseBtn").addEventListener("click", closeFigureModal);
  $("figureModal").addEventListener("click", (event) => {
    if (event.target?.dataset?.closeModal === "true") {
      closeFigureModal();
    }
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeFigureModal();
    }
  });
  ["historyKeyword", "historyModelVersion", "historyMinPrediction", "historyMaxPrediction", "historyQualityLevel", "historyBaselineLevel"].forEach(
    (id) => {
      $(id).addEventListener("change", refreshHistory);
    }
  );
}

function init() {
  renderSessionState();
  setChatStatus(state.sessionId ? `当前会话：${state.sessionId}` : "尚未创建会话");
  addWelcomeMessages();
  bindEvents();
  loadModelInfo();
  refreshHistory();
}

init();
