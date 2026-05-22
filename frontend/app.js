import {
  checkCurrentModel,
  getAgentModels,
  getCurrentModel,
  loadSkills as fetchSkills,
  sendAgentChat,
  setActionEnabled as requestSetActionEnabled,
  setSkillEnabled as requestSetSkillEnabled,
  switchAgentModel,
  toAssetUrl,
  uploadSkillZip as requestUploadSkillZip,
} from "./js/api.js";

const STORAGE_KEYS = {
  sessionId: "ramanagent.sessionId",
};

const state = {
  sessionId: loadSessionId(),
  currentModel: null,
  modelsPayload: { current_model: "", models: [] },
  selectedFile: null,
  skillsPayload: null,
  expandedSkillNames: new Set(),
  chatBusy: false,
  typingNode: null,
  initialized: false,
  modelListOpen: false,
  refreshingDashboard: false,
  uploadingSkill: false,
};

const $ = (id) => document.getElementById(id);

function loadSessionId() {
  try {
    return localStorage.getItem(STORAGE_KEYS.sessionId) || "";
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

function buildNowText() {
  const now = new Date();
  return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
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
    return 90000;
  }
  const text = String(message || "").toLowerCase();
  if (
    text.includes("预处理") ||
    text.includes("预测") ||
    text.includes("分析") ||
    text.includes("画图") ||
    text.includes("基线") ||
    text.includes("去噪")
  ) {
    return 60000;
  }
  return 15000;
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
  setChatStatus(isBusy ? hint : state.sessionId ? `当前会话：${state.sessionId}` : "可以直接提问，或上传 CSV 后发送。");
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

function appendFileCard(file) {
  if (!file) {
    return;
  }
  appendMessage(
    "user",
    `<div class="file-card"><strong>CSV</strong><span>${escapeHtml(file.name)}</span></div>`,
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
      "<p>欢迎使用聊天式 RamanAgent。</p>",
      "<p>你可以直接提问，也可以点击左下角的 <strong>+</strong> 上传 CSV 光谱文件，然后继续发送分析请求。</p>",
      "<p>常见用法：<span class=\"inline-chip\">最近实验</span> <span class=\"inline-chip\">模型列表</span> <span class=\"inline-chip\">Skills 管理</span></p>",
    ].join(""),
    "text",
    state.sessionId ? `已恢复 ${state.sessionId}` : "新会话",
  );
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
        ${renderSkillToggleButton(skill)}
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

  const lowerName = file.name.toLowerCase();
  if (!lowerName.endsWith(".csv")) {
    window.alert("请上传 CSV 格式的光谱文件");
    event.target.value = "";
    state.selectedFile = null;
    renderSelectedFileChip(null);
    return;
  }

  state.selectedFile = file;
  console.log("已选择文件：", file.name);
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
    console.log("Skill 上传成功：", response);
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
          ? `<ul class="analysis-list compact">${list.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>`
          : `<div class="analysis-empty">${escapeHtml(emptyText)}</div>`
      }
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
      <div class="analysis-summary">
        <p><strong>光谱预处理完成</strong></p>
        <p>${escapeHtml(message?.content || analysis.summary || "预处理完成。")}</p>
      </div>
      ${
        steps.length
          ? `
            <div class="analysis-summary">
              <p><strong>处理步骤</strong></p>
              <ul class="analysis-list">
                ${steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}
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
      ${warnings.length ? `<div class="analysis-summary"><p><strong>提示：</strong>${escapeHtml(warnings.join("；"))}</p></div>` : ""}
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
        <p>${escapeHtml(structured.explanation_text || message?.content || analysis.summary || "预测完成。")}</p>
      </div>
      ${renderPlots(analysis.plots || [])}
    </div>
  `;
}

function renderUploadedSkillResult(message) {
  const analysis = message?.analysis || {};
  const details = analysis.details || {};
  const replyText = details.reply_text || message?.content || analysis.summary || "上传 Skill 已执行。";
  return `
    <div class="analysis-card">
      <div class="analysis-summary">
        <p><strong>上传 Skill 执行结果</strong></p>
      </div>
      <pre class="skill-result-block">${escapeHtml(replyText)}</pre>
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
        <p>${escapeHtml(message?.content || analysis.summary || "模型状态已更新。")}</p>
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
      <div class="analysis-summary">
        <p><strong>实验报告生成结果</strong></p>
        <p>${escapeHtml(message?.content || analysis.summary || "报告已生成。")}</p>
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
      <div class="analysis-summary">
        <p>${escapeHtml(message?.content || analysis.summary || "处理完成。")}</p>
      </div>
      ${renderDetailRows("", analysis.details || {})}
    </div>
  `;
}

function renderAssistantResponse(payload) {
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  messages.forEach((message) => {
    if (message.type === "analysis") {
      const kind = message.result_kind || message.analysis?.result_kind || "generic";
      if (kind === "preprocessing") {
        appendMessage("assistant", renderPreprocessingResult(message), "analysis");
        return;
      }
      if (kind === "prediction") {
        appendMessage("assistant", renderPredictionResult(message), "analysis");
        return;
      }
      if (kind === "model_status") {
        appendMessage("assistant", renderModelStatusResult(message), "analysis");
        return;
      }
      if (kind === "report") {
        appendMessage("assistant", renderReportResult(message), "analysis");
        return;
      }
      if (kind === "uploaded_skill") {
        appendMessage("assistant", renderUploadedSkillResult(message), "analysis");
        return;
      }
      appendMessage("assistant", renderGenericAnalysisResult(message), "analysis");
      return;
    }
    if (message.type === "error") {
      appendMessage("assistant", `<p class="error-message">${escapeHtml(message.content || "分析失败。")}</p>`, "error");
      return;
    }
    appendMessage("assistant", `<p>${escapeHtml(message.content || "")}</p>`, "text");
  });
}

function renderModelList(models = [], currentModel = "") {
  const body = $("modelListBody");
  if (!body) {
    return;
  }
  if (!models.length) {
    body.innerHTML = `<div class="model-list-empty">当前没有可展示的模型。</div>`;
    return;
  }
  body.innerHTML = models
    .map((model) => {
      const selected = model.name === currentModel;
      return `
        <button
          type="button"
          class="model-list-item ${selected ? "selected" : ""}"
          data-model-name="${escapeHtml(model.name || "")}"
          ${model.available ? "" : "disabled"}
        >
          <div class="model-list-main">
            <div class="model-list-title">
              <strong>${escapeHtml(model.display_name || model.name || "未命名模型")}</strong>
              <span class="model-list-check">${selected ? "√" : ""}</span>
            </div>
            <div class="model-list-meta">
              ${selected ? '<span class="model-badge">已选中</span>' : ""}
              <span class="model-badge ${model.available ? "ok" : "warn"}">${model.available ? "可用" : "不可用"}</span>
            </div>
            <p>${escapeHtml(model.description || "暂无描述")}</p>
          </div>
        </button>
      `;
    })
    .join("");

  body.querySelectorAll("[data-model-name]").forEach((button) => {
    button.addEventListener("click", async () => {
      await switchModel(button.dataset.modelName || "");
    });
  });
}

async function switchModel(modelName) {
  if (!modelName) {
    return;
  }
  try {
    console.log("开始切换模型：", modelName);
    const response = await switchAgentModel(modelName);
    if (!response.success) {
      throw new Error(response.error_message || "切换模型失败");
    }
    state.currentModel = { ...(state.currentModel || {}), model_version: response.current_model };
    $("topModelVersion").textContent = response.current_model || "未知";
    await Promise.allSettled([loadModelsSafely(), loadStatusSafely()]);
    renderModelList(state.modelsPayload.models || [], response.current_model || "");
    console.log("模型切换完成：", response);
  } catch (error) {
    console.error("切换模型失败：", error);
    window.alert(`切换模型失败：${error.message || "未知错误"}`);
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
    console.log("点击了 + 上传按钮");
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
  $("clearSessionBtn")?.addEventListener("click", () => {
    persistSessionId("");
    state.selectedFile = null;
    const fileInput = $("fileInput");
    if (fileInput) {
      fileInput.value = "";
    }
    renderSelectedFileChip(null);
    renderWelcomeMessage();
    setChatStatus("会话已清空。");
  });

  $("skillsButton")?.addEventListener("click", openSkillsPanel);
  $("skillsManageBtn")?.addEventListener("click", openSkillsPanel);
  $("closeSkillsPanelBtn")?.addEventListener("click", closeSkillsPanel);
  $("skillsPanelBackdrop")?.addEventListener("click", closeSkillsPanel);
  $("refreshSkillsBtn")?.addEventListener("click", refreshSkillsPanel);
  $("uploadSkillBtn")?.addEventListener("click", () => $("skillZipInput")?.click());
  $("skillZipInput")?.addEventListener("change", handleSkillZipSelect);

  $("modelListBtn")?.addEventListener("click", (event) => {
    event.stopPropagation();
    if (state.modelListOpen) {
      closeModelList();
    } else {
      openModelList();
    }
  });
  $("closeModelListBtn")?.addEventListener("click", closeModelList);
  $("recentExperimentBtn")?.addEventListener("click", () => sendChatMessage("最近实验"));
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
      closeModelList();
    }
  });
}

async function loadStatus() {
  const currentModelResponse = await getCurrentModel();
  if (!currentModelResponse.success) {
    throw new Error(currentModelResponse.error_message || "获取当前模型失败");
  }

  state.currentModel = currentModelResponse.data || {};
  $("backendStatus").textContent = "已连接";
  $("topModelVersion").textContent = state.currentModel.model_version || state.modelsPayload.current_model || "未知";

  const artifactResponse = await checkCurrentModel(state.currentModel.model_version);
  if (!artifactResponse.success) {
    $("topArtifactStatus").textContent = artifactResponse.error_message || "异常";
    return;
  }

  const missingFiles = (artifactResponse.data || {}).missing_files || [];
  $("topArtifactStatus").textContent = missingFiles.length ? `缺失 ${missingFiles.length} 个` : "正常";
}

async function loadStatusSafely() {
  try {
    await loadStatus();
  } catch (error) {
    console.error("加载状态失败：", error);
    $("backendStatus").textContent = "连接异常";
    $("topModelVersion").textContent = state.modelsPayload.current_model || "加载失败";
    $("topArtifactStatus").textContent = "检查失败";
  }
}

async function loadModels() {
  const response = await getAgentModels();
  if (!response.success) {
    throw new Error(response.error_message || "加载模型列表失败");
  }
  state.modelsPayload = response;
  renderModelList(response.models || [], response.current_model || "");
  if (response.current_model) {
    $("topModelVersion").textContent = response.current_model;
  }
}

async function loadModelsSafely() {
  try {
    await loadModels();
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
  console.log("开始刷新工作台信息");
  const results = await Promise.allSettled([loadStatusSafely(), loadModelsSafely(), loadSkillsSafely()]);
  results.forEach((result, index) => {
    if (result.status === "rejected") {
      console.error(`刷新任务 ${index + 1} 失败：`, result.reason);
    }
  });
  if (state.modelListOpen) {
    renderModelList(state.modelsPayload.models || [], state.modelsPayload.current_model || "");
  }
  console.log("工作台刷新完成");
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
    setChatStatus("请输入消息，或者先选择一个 CSV 文件。");
    return;
  }

  appendMessage("user", `<p>${escapeHtml(message || "请分析这个 CSV 光谱文件")}</p>`, "text");
  if (selectedFile) {
    appendFileCard(selectedFile);
  }

  if (input) {
    input.value = "";
    autoResizeTextarea();
  }

  setBusy(true, selectedFile ? "正在上传 CSV 并分析..." : "正在思考...");
  renderTypingMessage(selectedFile ? "正在进行光谱分析，可能需要几十秒，请稍候..." : "正在处理，请稍候...");

  try {
    const response = await sendAgentChat({
      message,
      sessionId: state.sessionId || "",
      debug: $("chatDebug")?.checked || false,
      file: selectedFile,
      metadata: { remarks: "", timeoutMs },
    });

    removeTypingMessage();
    setBusy(false);

    if (response.session_id) {
      persistSessionId(response.session_id);
    }

    if (!response.success) {
      console.error("发送消息失败：", response.error_message);
      const errorText = String(response.error_message || "未知错误");
      const friendlyMessage = errorText.includes("请求超时")
        ? `发送失败：${escapeHtml(errorText)}。当前任务可能仍在后台处理中，你可以稍后重试，已选择的文件会保留。`
        : `发送失败：${escapeHtml(errorText)}`;
      appendMessage("assistant", `<p class="error-message">${friendlyMessage}</p>`, "error");
      return;
    }

    renderAssistantResponse(response);
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
    loadStatusSafely();
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
  setChatStatus(state.sessionId ? `当前会话：${state.sessionId}` : "可以直接提问，或上传 CSV 后发送。");
  loadModelsSafely();
  loadStatusSafely();
  loadSkillsSafely();
}

initApp();
