import { toAssetUrl } from "./api.js";

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function renderArtifacts(artifacts = []) {
  if (!Array.isArray(artifacts) || !artifacts.length) {
    return "";
  }
  return `
    <div class="artifact-grid">
      ${artifacts.map((artifact) => renderArtifactCard(artifact)).join("")}
    </div>
  `;
}

function renderArtifactCard(artifact = {}) {
  const type = String(artifact.type || artifact.file_type || "file").toLowerCase();
  const title = artifact.title || artifact.filename || artifact.name || "运行产物";
  const downloadUrl = toAssetUrl(artifact.download_url || artifact.url || artifact.preview_url || "");
  const previewUrl = toAssetUrl(artifact.preview_url || artifact.url || artifact.download_url || "");
  const meta = [type, artifact.mime_type, artifact.created_at].filter(Boolean).join(" · ");
  const imagePreview = type === "image" && previewUrl
    ? `<img class="artifact-image" src="${escapeHtml(previewUrl)}" alt="${escapeHtml(title)}" />`
    : "";
  const jsonPreview = type === "json" && artifact.data
    ? `<details><summary>查看 JSON</summary><pre>${escapeHtml(JSON.stringify(artifact.data, null, 2))}</pre></details>`
    : "";
  return `
    <article class="artifact-card">
      ${imagePreview}
      <div class="artifact-body">
        <strong>${escapeHtml(title)}</strong>
        ${meta ? `<span>${escapeHtml(meta)}</span>` : ""}
        ${jsonPreview}
        <div class="artifact-actions">
          ${previewUrl && type !== "image" ? `<a href="${escapeHtml(previewUrl)}" target="_blank" rel="noreferrer">预览</a>` : ""}
          ${downloadUrl ? `<a href="${escapeHtml(downloadUrl)}" target="_blank" rel="noreferrer" download>下载</a>` : ""}
        </div>
      </div>
    </article>
  `;
}
