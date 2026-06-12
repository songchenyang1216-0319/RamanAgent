import {
  bindConversationKnowledgeBase,
  createKnowledgeBase,
  deleteKnowledgeBase,
  deleteKnowledgeBaseFile,
  getKnowledgeBaseIndexStatus,
  getRagHealth,
  listConversationKnowledgeBases,
  listKnowledgeBaseFiles,
  listKnowledgeBases,
  rebuildAllRagIndexes,
  rebuildKnowledgeBaseIndex,
  searchKnowledgeBase,
  setKnowledgeBaseEnabled,
  unbindConversationKnowledgeBase,
  updateKnowledgeBase,
  uploadKnowledgeBaseFile,
} from "./api.js";

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatBytes(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num) || num <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = num;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function shortDate(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value || "");
  }
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function statusClass(value) {
  const status = String(value || "").toLowerCase();
  if (["indexed", "success", "ready"].includes(status)) {
    return "success";
  }
  if (["failed", "error", "deleted"].includes(status)) {
    return "error";
  }
  if (["pending", "running", "processing"].includes(status)) {
    return "warning";
  }
  return "";
}

function normalizeKbs(response) {
  return Array.isArray(response?.knowledge_bases) ? response.knowledge_bases : [];
}

function normalizeFiles(response) {
  return Array.isArray(response?.files) ? response.files : [];
}

export function initKnowledgeBasePanel({
  getState,
  showToast,
  onWorkspaceChanged,
} = {}) {
  const panel = document.getElementById("knowledgeBasePanel");
  const body = document.getElementById("knowledgeBasePanelBody");
  const fileInput = document.getElementById("knowledgeBaseFileInput");
  const state = {
    open: false,
    selectedKnowledgeBaseId: "",
    knowledgeBases: [],
    conversationKnowledgeBases: [],
    filesByKb: {},
    indexStatusByKb: {},
    ragHealth: null,
    busy: false,
  };

  function currentUserId() {
    return getState?.().userId || "default_user";
  }

  function currentConversationId() {
    return getState?.().sessionId || "";
  }

  function setBusy(value) {
    state.busy = Boolean(value);
    render();
  }

  function selectedKb() {
    return state.knowledgeBases.find((item) => item.knowledge_base_id === state.selectedKnowledgeBaseId) || state.knowledgeBases[0] || null;
  }

  function isBound(knowledgeBaseId) {
    return state.conversationKnowledgeBases.some((item) => item.knowledge_base_id === knowledgeBaseId);
  }

  function renderKbList() {
    if (!state.knowledgeBases.length) {
      return `<div class="kb-empty">还没有知识库。点击“新建知识库”开始沉淀长期资料。</div>`;
    }
    return `
      <div class="kb-list">
        ${state.knowledgeBases.map((item) => {
          const id = item.knowledge_base_id;
          const active = id === state.selectedKnowledgeBaseId ? "active" : "";
          const bound = isBound(id);
          const indexStatus = state.indexStatusByKb[id] || {};
          return `
            <button type="button" class="kb-list-item ${active}" data-kb-select="${escapeHtml(id)}">
              <span class="kb-list-title">${escapeHtml(item.name || id)}</span>
              <span class="kb-list-meta">
                ${escapeHtml(item.visibility || "private")} · ${item.enabled ? "启用" : "禁用"}${bound ? " · 已绑定" : ""}
              </span>
              <span class="kb-list-meta">
                ${escapeHtml(String(indexStatus.chunk_count ?? item.chunk_count ?? 0))} chunks · ${escapeHtml(indexStatus.status || "unknown")}
              </span>
            </button>
          `;
        }).join("")}
      </div>
    `;
  }

  function renderKbFiles(kb) {
    const files = normalizeFiles(state.filesByKb[kb.knowledge_base_id]);
    if (!files.length) {
      return `<div class="kb-empty">这个知识库还没有文件。上传 PDF、DOCX、MD、CSV、XLSX 等资料后会自动解析并索引。</div>`;
    }
    return `
      <div class="kb-file-list">
        ${files.map((file) => `
          <article class="kb-file-card">
            <div>
              <strong>${escapeHtml(file.original_filename || file.filename || file.kb_file_id)}</strong>
              <span>${escapeHtml(file.file_type || file.mime_type || "unknown")} · ${formatBytes(file.size)} · ${escapeHtml(shortDate(file.updated_at || file.created_at))}</span>
              ${file.rag_index_error ? `<small class="kb-error">索引错误：${escapeHtml(file.rag_index_error)}</small>` : ""}
            </div>
            <div class="kb-file-status">
              <span class="kb-status ${statusClass(file.processing_status)}">${escapeHtml(file.processing_status || "unknown")}</span>
              <span class="kb-status ${statusClass(file.rag_index_status)}">${escapeHtml(file.rag_index_status || "unknown")}</span>
            </div>
            <div class="kb-card-actions">
              <button type="button" data-kb-delete-file="${escapeHtml(file.kb_file_id)}">删除文件</button>
            </div>
          </article>
        `).join("")}
      </div>
    `;
  }

  function renderSelectedKb(kb) {
    if (!kb) {
      return `
        <section class="kb-detail">
          <div class="kb-empty">请选择或创建一个知识库。</div>
        </section>
      `;
    }
    const bound = isBound(kb.knowledge_base_id);
    const indexStatus = state.indexStatusByKb[kb.knowledge_base_id] || {};
    const ragHealth = state.ragHealth || {};
    return `
      <section class="kb-detail">
        <div class="kb-detail-head">
          <div>
            <h3>${escapeHtml(kb.name || "未命名知识库")}</h3>
            <p>${escapeHtml(kb.description || "暂无描述。")}</p>
          </div>
          <div class="kb-card-actions">
            <button type="button" data-kb-edit="${escapeHtml(kb.knowledge_base_id)}">编辑</button>
            <button type="button" data-kb-toggle="${escapeHtml(kb.knowledge_base_id)}">${kb.enabled ? "禁用" : "启用"}</button>
            <button type="button" data-kb-delete="${escapeHtml(kb.knowledge_base_id)}">删除</button>
          </div>
        </div>

        <div class="kb-stats">
          <div><span>绑定状态</span><strong>${bound ? "已绑定当前会话" : "未绑定"}</strong></div>
          <div><span>索引状态</span><strong>${escapeHtml(indexStatus.status || "unknown")}</strong></div>
          <div><span>文件数</span><strong>${escapeHtml(String(indexStatus.file_count ?? normalizeFiles(state.filesByKb[kb.knowledge_base_id]).length))}</strong></div>
          <div><span>Chunks</span><strong>${escapeHtml(String(indexStatus.chunk_count ?? 0))}</strong></div>
        </div>

        <div class="kb-health-card">
          <strong>RAG 健康</strong>
          <span>${escapeHtml(ragHealth.embedding?.embedding_provider || ragHealth.embedding_provider || "unknown")} / ${escapeHtml(ragHealth.vector_store?.vector_provider || ragHealth.vector_store?.provider || "unknown")}</span>
          ${
            ragHealth.production_warnings?.length
              ? `<p class="kb-error">${escapeHtml(ragHealth.production_warnings.join("；"))}</p>`
              : `<p>当前 RAG 配置未发现阻塞性问题。</p>`
          }
        </div>

        <div class="kb-card-actions kb-primary-actions">
          <button type="button" data-kb-bind="${escapeHtml(kb.knowledge_base_id)}">${bound ? "重新绑定" : "绑定到当前会话"}</button>
          ${bound ? `<button type="button" data-kb-unbind="${escapeHtml(kb.knowledge_base_id)}">解绑当前会话</button>` : ""}
          <button type="button" data-kb-upload="${escapeHtml(kb.knowledge_base_id)}">上传文件</button>
          <button type="button" data-kb-rebuild="${escapeHtml(kb.knowledge_base_id)}">重建索引</button>
        </div>

        <form class="kb-search-form" data-kb-search-form="${escapeHtml(kb.knowledge_base_id)}">
          <input name="query" placeholder="在这个知识库里搜索，例如：甲醇预测流程" />
          <button type="submit">搜索</button>
        </form>
        <div id="kbSearchResults" class="kb-search-results"></div>

        <h4>文件</h4>
        ${renderKbFiles(kb)}
      </section>
    `;
  }

  function render() {
    if (!body) {
      return;
    }
    const kb = selectedKb();
    body.innerHTML = `
      ${state.busy ? `<div class="kb-busy">正在处理，请稍候...</div>` : ""}
      <div class="kb-layout">
        <aside class="kb-sidebar">
          <div class="kb-sidebar-head">
            <strong>知识库</strong>
            <span>${state.knowledgeBases.length} 个可访问</span>
          </div>
          ${renderKbList()}
        </aside>
        ${renderSelectedKb(kb)}
      </div>
    `;
    bindBodyEvents();
  }

  async function refresh({ keepSelection = true } = {}) {
    if (!body) {
      return;
    }
    body.innerHTML = `<div class="kb-empty">正在加载知识库...</div>`;
    const userId = currentUserId();
    const conversationId = currentConversationId();
    const [kbResponse, boundResponse, healthResponse] = await Promise.all([
      listKnowledgeBases({ userId, includeDisabled: true }),
      conversationId ? listConversationKnowledgeBases(conversationId, userId) : Promise.resolve({ success: true, knowledge_bases: [] }),
      getRagHealth({ conversationId, userId }),
    ]);
    if (!kbResponse.success) {
      body.innerHTML = `<div class="kb-empty error">${escapeHtml(kbResponse.error_message || "加载知识库失败")}</div>`;
      return;
    }
    state.knowledgeBases = normalizeKbs(kbResponse);
    state.conversationKnowledgeBases = normalizeKbs(boundResponse);
    state.ragHealth = healthResponse.success ? healthResponse : null;
    if (!keepSelection || !state.knowledgeBases.some((item) => item.knowledge_base_id === state.selectedKnowledgeBaseId)) {
      state.selectedKnowledgeBaseId = state.knowledgeBases[0]?.knowledge_base_id || "";
    }
    await loadSelectedKbDetails();
    render();
  }

  async function loadSelectedKbDetails() {
    const kb = selectedKb();
    if (!kb) {
      return;
    }
    const userId = currentUserId();
    const [files, status] = await Promise.all([
      listKnowledgeBaseFiles(kb.knowledge_base_id, userId),
      getKnowledgeBaseIndexStatus(kb.knowledge_base_id, userId),
    ]);
    state.filesByKb[kb.knowledge_base_id] = files;
    state.indexStatusByKb[kb.knowledge_base_id] = status.success ? status.index_status || status : {};
  }

  function openPanel() {
    state.open = true;
    panel?.classList.remove("hidden");
    panel?.setAttribute("aria-hidden", "false");
    refresh({ keepSelection: true });
  }

  function closePanel() {
    state.open = false;
    panel?.classList.add("hidden");
    panel?.setAttribute("aria-hidden", "true");
  }

  async function createKb() {
    const name = window.prompt("知识库名称");
    if (!name || !name.trim()) {
      return;
    }
    const description = window.prompt("知识库描述（可选）") || "";
    setBusy(true);
    const response = await createKnowledgeBase({
      user_id: currentUserId(),
      name: name.trim(),
      description,
      visibility: "private",
    });
    setBusy(false);
    if (!response.success) {
      showToast?.(response.error_message || "创建知识库失败", "error");
      return;
    }
    state.selectedKnowledgeBaseId = response.knowledge_base?.knowledge_base_id || response.knowledge_base_id || "";
    showToast?.("知识库已创建", "success");
    await refresh({ keepSelection: true });
  }

  async function editKb(knowledgeBaseId) {
    const kb = state.knowledgeBases.find((item) => item.knowledge_base_id === knowledgeBaseId);
    if (!kb) {
      return;
    }
    const name = window.prompt("新的知识库名称", kb.name || "");
    if (name === null) {
      return;
    }
    const description = window.prompt("新的知识库描述", kb.description || "");
    setBusy(true);
    const response = await updateKnowledgeBase(knowledgeBaseId, {
      user_id: currentUserId(),
      name: name.trim() || kb.name,
      description: description ?? kb.description ?? "",
    });
    setBusy(false);
    if (!response.success) {
      showToast?.(response.error_message || "更新知识库失败", "error");
      return;
    }
    showToast?.("知识库已更新", "success");
    await refresh({ keepSelection: true });
  }

  async function toggleKb(knowledgeBaseId) {
    const kb = state.knowledgeBases.find((item) => item.knowledge_base_id === knowledgeBaseId);
    if (!kb) {
      return;
    }
    setBusy(true);
    const response = await setKnowledgeBaseEnabled(knowledgeBaseId, !kb.enabled, currentUserId());
    setBusy(false);
    if (!response.success) {
      showToast?.(response.error_message || "启停知识库失败", "error");
      return;
    }
    showToast?.(!kb.enabled ? "知识库已启用" : "知识库已禁用", "success");
    await refresh({ keepSelection: true });
  }

  async function removeKb(knowledgeBaseId) {
    if (!window.confirm("确定删除这个知识库吗？这会软删除知识库并移除向量索引。")) {
      return;
    }
    setBusy(true);
    const response = await deleteKnowledgeBase(knowledgeBaseId, currentUserId());
    setBusy(false);
    if (!response.success) {
      showToast?.(response.error_message || "删除知识库失败", "error");
      return;
    }
    state.selectedKnowledgeBaseId = "";
    showToast?.("知识库已删除", "success");
    await refresh({ keepSelection: false });
    await onWorkspaceChanged?.();
  }

  async function bindKb(knowledgeBaseId) {
    const conversationId = currentConversationId();
    if (!conversationId) {
      showToast?.("请先新建或打开一个聊天，再绑定知识库。", "error");
      return;
    }
    setBusy(true);
    const response = await bindConversationKnowledgeBase(conversationId, knowledgeBaseId, {
      userId: currentUserId(),
      enabled: true,
    });
    setBusy(false);
    if (!response.success) {
      showToast?.(response.error_message || "绑定知识库失败", "error");
      return;
    }
    showToast?.("知识库已绑定到当前会话", "success");
    await refresh({ keepSelection: true });
    await onWorkspaceChanged?.();
  }

  async function unbindKb(knowledgeBaseId) {
    const conversationId = currentConversationId();
    if (!conversationId) {
      return;
    }
    setBusy(true);
    const response = await unbindConversationKnowledgeBase(conversationId, knowledgeBaseId, currentUserId());
    setBusy(false);
    if (!response.success) {
      showToast?.(response.error_message || "解绑知识库失败", "error");
      return;
    }
    showToast?.("知识库已从当前会话解绑", "success");
    await refresh({ keepSelection: true });
    await onWorkspaceChanged?.();
  }

  async function rebuildKb(knowledgeBaseId) {
    setBusy(true);
    const response = await rebuildKnowledgeBaseIndex(knowledgeBaseId, currentUserId());
    setBusy(false);
    if (!response.success) {
      showToast?.(response.error_message || "重建索引失败", "error");
      return;
    }
    showToast?.(`索引重建完成：${response.total ?? response.results?.length ?? 0} 个文件`, "success");
    await refresh({ keepSelection: true });
  }

  async function rebuildAllRag() {
    if (!window.confirm("确定重建当前用户的全部会话 RAG 和知识库索引吗？数据较多时可能需要一段时间。")) {
      return;
    }
    setBusy(true);
    const response = await rebuildAllRagIndexes({ userId: currentUserId() });
    setBusy(false);
    if (!response.success) {
      showToast?.(response.error_message || "全量重建 RAG 失败", "error");
      return;
    }
    showToast?.(`全量重建完成：会话 ${response.conversation_total || 0}，知识库 ${response.knowledge_base_total || 0}`, "success");
    await refresh({ keepSelection: true });
  }

  function uploadKbFiles(knowledgeBaseId) {
    if (!fileInput) {
      return;
    }
    state.selectedKnowledgeBaseId = knowledgeBaseId;
    fileInput.value = "";
    fileInput.click();
  }

  async function handleFileInput() {
    const kb = selectedKb();
    const files = Array.from(fileInput?.files || []);
    if (!kb || !files.length) {
      return;
    }
    setBusy(true);
    const results = [];
    for (const file of files) {
      // 串行上传，避免 Windows 文件锁和后端 SQLite 写入冲突。
      results.push(await uploadKnowledgeBaseFile(kb.knowledge_base_id, file, currentUserId()));
    }
    setBusy(false);
    const failed = results.filter((item) => !item.success);
    if (failed.length) {
      showToast?.(`上传完成，但 ${failed.length} 个文件失败`, "error");
    } else {
      showToast?.(`已上传 ${results.length} 个文件并触发索引`, "success");
    }
    await refresh({ keepSelection: true });
  }

  async function deleteKbFile(kbFileId) {
    const kb = selectedKb();
    if (!kb || !kbFileId) {
      return;
    }
    if (!window.confirm("确定删除这个知识库文件吗？相关 chunks 和向量索引会一并移除。")) {
      return;
    }
    setBusy(true);
    const response = await deleteKnowledgeBaseFile(kb.knowledge_base_id, kbFileId, currentUserId());
    setBusy(false);
    if (!response.success) {
      showToast?.(response.error_message || "删除知识库文件失败", "error");
      return;
    }
    showToast?.("知识库文件已删除", "success");
    await refresh({ keepSelection: true });
  }

  async function runSearch(form) {
    const kbId = form.getAttribute("data-kb-search-form") || "";
    const resultNode = document.getElementById("kbSearchResults");
    const formData = new FormData(form);
    const query = String(formData.get("query") || "").trim();
    if (!query || !resultNode) {
      return;
    }
    resultNode.innerHTML = `<div class="kb-empty">正在搜索...</div>`;
    const response = await searchKnowledgeBase(kbId, query, { userId: currentUserId(), topK: 8 });
    if (!response.success) {
      resultNode.innerHTML = `<div class="kb-empty error">${escapeHtml(response.error_message || "搜索失败")}</div>`;
      return;
    }
    const chunks = response.chunks || response.retrieved_chunks || response.results || [];
    resultNode.innerHTML = chunks.length
      ? chunks.map((item, index) => `
          <article class="kb-search-result">
            <strong>[${index + 1}] ${escapeHtml(item.filename || item.source_name || item.chunk_id || "片段")}</strong>
            <span>${escapeHtml([item.page ? `页 ${item.page}` : "", item.sheet ? `Sheet ${item.sheet}` : "", item.score ? `score ${Number(item.score).toFixed(3)}` : ""].filter(Boolean).join(" · "))}</span>
            <p>${escapeHtml(item.text || item.preview || "")}</p>
          </article>
        `).join("")
      : `<div class="kb-empty">没有检索到相关片段。</div>`;
  }

  function bindBodyEvents() {
    body?.querySelectorAll("[data-kb-select]").forEach((button) => {
      button.addEventListener("click", async () => {
        state.selectedKnowledgeBaseId = button.getAttribute("data-kb-select") || "";
        await loadSelectedKbDetails();
        render();
      });
    });
    body?.querySelectorAll("[data-kb-edit]").forEach((button) => button.addEventListener("click", () => editKb(button.dataset.kbEdit || "")));
    body?.querySelectorAll("[data-kb-toggle]").forEach((button) => button.addEventListener("click", () => toggleKb(button.dataset.kbToggle || "")));
    body?.querySelectorAll("[data-kb-delete]").forEach((button) => button.addEventListener("click", () => removeKb(button.dataset.kbDelete || "")));
    body?.querySelectorAll("[data-kb-bind]").forEach((button) => button.addEventListener("click", () => bindKb(button.dataset.kbBind || "")));
    body?.querySelectorAll("[data-kb-unbind]").forEach((button) => button.addEventListener("click", () => unbindKb(button.dataset.kbUnbind || "")));
    body?.querySelectorAll("[data-kb-upload]").forEach((button) => button.addEventListener("click", () => uploadKbFiles(button.dataset.kbUpload || "")));
    body?.querySelectorAll("[data-kb-rebuild]").forEach((button) => button.addEventListener("click", () => rebuildKb(button.dataset.kbRebuild || "")));
    body?.querySelectorAll("[data-kb-delete-file]").forEach((button) => button.addEventListener("click", () => deleteKbFile(button.dataset.kbDeleteFile || "")));
    body?.querySelectorAll("[data-kb-search-form]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        runSearch(form);
      });
    });
  }

  document.getElementById("knowledgeBaseButton")?.addEventListener("click", openPanel);
  document.getElementById("sidebarKnowledgeBaseBtn")?.addEventListener("click", openPanel);
  document.getElementById("closeKnowledgeBasePanelBtn")?.addEventListener("click", closePanel);
  document.getElementById("knowledgeBasePanelBackdrop")?.addEventListener("click", closePanel);
  document.getElementById("refreshKnowledgeBaseBtn")?.addEventListener("click", () => refresh({ keepSelection: true }));
  document.getElementById("createKnowledgeBaseBtn")?.addEventListener("click", createKb);
  document.getElementById("rebuildAllRagBtn")?.addEventListener("click", rebuildAllRag);
  fileInput?.addEventListener("change", handleFileInput);

  return {
    open: openPanel,
    close: closePanel,
    refresh,
    isOpen: () => state.open,
  };
}
