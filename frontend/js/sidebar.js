import {
  createConversation,
  deleteConversation,
  getConversations,
  renameConversation,
} from "./api.js";

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function shortDate(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function initConversationSidebar({
  getState,
  setSessionId,
  renderConversationMessages,
  clearForNewConversation,
  showToast,
  refreshWorkspace,
}) {
  const listNode = document.getElementById("conversationList");
  const searchInput = document.getElementById("conversationSearch");
  const newButtons = [
    document.getElementById("sidebarNewSessionBtn"),
    document.getElementById("newSessionBtn"),
  ].filter(Boolean);

  async function refreshConversations(query = searchInput?.value || "") {
    if (!listNode) {
      return;
    }
    const state = getState();
    listNode.innerHTML = '<div class="conversation-empty">正在加载聊天记录...</div>';
    const response = await getConversations({ userId: state.userId || "default_user", query, limit: 100 });
    if (!response.success) {
      listNode.innerHTML = `<div class="conversation-empty error">${escapeHtml(response.error_message || "加载失败")}</div>`;
      return;
    }
    const conversations = response.conversations || [];
    if (!conversations.length) {
      listNode.innerHTML = '<div class="conversation-empty">还没有聊天记录</div>';
      return;
    }
    listNode.innerHTML = conversations
      .map((item) => {
        const id = item.conversation_id || item.session_id;
        const active = id && id === state.sessionId ? "active" : "";
        return `
          <div class="conversation-item ${active}" data-conversation-id="${escapeHtml(id)}">
            <button class="conversation-open" type="button">
              <span class="conversation-title">${escapeHtml(item.title || "新聊天")}</span>
              <span class="conversation-meta">${escapeHtml(shortDate(item.updated_at))} · ${Number(item.message_count || 0)} 条</span>
            </button>
            <div class="conversation-actions">
              <button type="button" data-action="rename" title="重命名">改</button>
              <button type="button" data-action="delete" title="删除">删</button>
            </div>
          </div>
        `;
      })
      .join("");
  }

  async function createNewConversation() {
    const state = getState();
    const response = await createConversation({ userId: state.userId || "default_user" });
    if (!response.success) {
      showToast?.(response.error_message || "新建聊天失败", "error");
      return;
    }
    const conversation = response.conversation || {};
    const id = conversation.conversation_id || conversation.session_id;
    setSessionId(id || "");
    clearForNewConversation?.();
    await refreshConversations();
    showToast?.("已新建聊天", "success");
  }

  async function openConversation(conversationId) {
    if (!conversationId) {
      return;
    }
    setSessionId(conversationId);
    await renderConversationMessages?.(conversationId);
    await refreshWorkspace?.();
    await refreshConversations();
  }

  async function renameCurrent(conversationId) {
    const title = window.prompt("新的聊天标题");
    if (!title || !title.trim()) {
      return;
    }
    const response = await renameConversation(conversationId, title.trim());
    if (!response.success) {
      showToast?.(response.error_message || "重命名失败", "error");
      return;
    }
    await refreshConversations();
  }

  async function deleteCurrent(conversationId) {
    const confirmed = window.confirm("确定删除这个聊天吗？消息会被软删除，不会影响其他会话。");
    if (!confirmed) {
      return;
    }
    const response = await deleteConversation(conversationId);
    if (!response.success) {
      showToast?.(response.error_message || "删除失败", "error");
      return;
    }
    const state = getState();
    if (state.sessionId === conversationId) {
      setSessionId("");
      clearForNewConversation?.();
    }
    await refreshConversations();
  }

  listNode?.addEventListener("click", async (event) => {
    const item = event.target.closest("[data-conversation-id]");
    if (!item) {
      return;
    }
    const conversationId = item.getAttribute("data-conversation-id");
    const actionButton = event.target.closest("[data-action]");
    if (actionButton?.dataset.action === "rename") {
      await renameCurrent(conversationId);
      return;
    }
    if (actionButton?.dataset.action === "delete") {
      await deleteCurrent(conversationId);
      return;
    }
    await openConversation(conversationId);
  });

  searchInput?.addEventListener("input", () => {
    window.clearTimeout(searchInput._conversationTimer);
    searchInput._conversationTimer = window.setTimeout(() => refreshConversations(), 180);
  });

  newButtons.forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      createNewConversation();
    });
  });

  return { refreshConversations, createNewConversation, openConversation };
}
