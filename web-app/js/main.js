"use strict";

const API = "/api/v1";
const POLL_MS = 2500;
const FINAL_STAGES = new Set(["ready", "failed", "cancelled"]);
const LAST_NOTEBOOK_KEY = "argos.lastNotebook";

// ---------------------------------------------------------------------------
// Autentikasi
// ---------------------------------------------------------------------------

(function captureToken() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (token) {
        localStorage.setItem("access_token", token);
        window.history.replaceState({}, document.title, "/" + (window.location.hash || ""));
    }
})();

function getToken() { return localStorage.getItem("access_token"); }

if (!getToken()) window.location.href = "/login";

function logout() {
    localStorage.removeItem("access_token");
    window.location.href = "/login";
}

// ---------------------------------------------------------------------------
// API helper — semua error backend berbentuk {error: {code, message, request_id}}
// ---------------------------------------------------------------------------

class ApiError extends Error {
    constructor(message, code, requestId, status, details = {}, retryable = false) {
        super(message);
        this.code = code;
        this.requestId = requestId;
        this.status = status;
        this.details = details;      // mis. {conversation_id, message_id} saat chat gagal
        this.retryable = retryable;
    }
}

async function api(path, { method = "GET", json, form } = {}) {
    const headers = { Authorization: `Bearer ${getToken()}` };
    let body;
    if (json !== undefined) {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(json);
    } else if (form) {
        body = form;
    }

    let response;
    try {
        response = await fetch(`${API}${path}`, { method, headers, body });
    } catch {
        throw new ApiError("Tidak bisa terhubung ke server. Periksa koneksi Anda.", "NETWORK", null, 0);
    }

    if (response.status === 401) {
        logout();
        throw new ApiError("Sesi berakhir.", "UNAUTHENTICATED", null, 401);
    }
    if (response.status === 204) return null;

    const data = await response.json().catch(() => null);
    if (!response.ok) {
        const err = data && data.error;
        throw new ApiError(
            (err && err.message) || "Permintaan gagal diproses.",
            (err && err.code) || `HTTP_${response.status}`,
            (err && err.request_id) || response.headers.get("X-Request-ID"),
            response.status,
            (err && err.details) || {},
            Boolean(err && err.retryable),
        );
    }
    return data;
}

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);

const el = {
    notebookBtn: $("notebookBtn"),
    notebookTitle: $("notebookTitle"),
    notebookMenu: $("notebookMenu"),
    notebookMenuList: $("notebookMenuList"),
    sourceList: $("sourceList"),
    sourceCount: $("sourceCount"),
    historyList: $("historyList"),
    chatBox: $("chatBox"),
    chatInput: $("chatInput"),
    sendBtn: $("sendBtn"),
    micBtn: $("micBtn"),
    chatLoading: $("chatLoading"),
    welcome: $("welcomeScreen"),
    welcomeTitle: $("welcomeTitle"),
    welcomeSubtitle: $("welcomeSubtitle"),
    welcomeCta: $("welcomeCta"),
    welcomeSuggestions: $("welcomeSuggestions"),
    headerTitle: $("chatHeaderTitle"),
    headerScope: $("headerScope"),
    renameThreadBtn: $("renameThreadBtn"),
    deleteThreadBtn: $("deleteThreadBtn"),
    popover: $("citePopover"),
    toast: $("toast"),
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
    notebooks: [],
    notebook: null,          // detail notebook aktif (termasuk sources)
    conversations: [],
    conversationId: null,
    pollTimer: null,
    sending: false,
    citedVersion: null,      // versi yang sedang disorot oleh chip sitasi
    me: null,                // {id, email, is_admin} dari /users/me
};

// ---------------------------------------------------------------------------
// Utilitas tampilan
// ---------------------------------------------------------------------------

function h(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === "class") node.className = v;
        else if (k === "text") node.textContent = v;
        else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
        else if (k === "dataset") Object.assign(node.dataset, v);
        else node.setAttribute(k, v === true ? "" : v);
    }
    for (const child of children.flat()) {
        if (child === null || child === undefined || child === false) continue;
        node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
}

function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    return d.toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" });
}

function formatRelative(iso) {
    if (!iso) return "";
    // Waktu dari server tanpa zona = UTC
    const d = new Date(/Z|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
    if (isNaN(d)) return "";
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return "baru saja";
    if (diff < 3600) return `${Math.floor(diff / 60)} menit lalu`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} jam lalu`;
    if (diff < 604800) return `${Math.floor(diff / 86400)} hari lalu`;
    return formatDate(iso);
}

function formatSize(bytes) {
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}

let toastTimer = null;
function toast(message, kind = "info") {
    el.toast.textContent = message;
    el.toast.dataset.kind = kind;
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.toast.hidden = true; }, 4200);
}

function errorText(err) {
    return err.requestId ? `${err.message} (kode: ${err.requestId})` : err.message;
}

// ---------------------------------------------------------------------------
// Modal umum (konfirmasi / prompt / info)
// ---------------------------------------------------------------------------

const MODAL_ICONS = {
    edit: '<svg fill="none" height="22" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24" width="22"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
    danger: '<svg fill="none" height="22" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24" width="22"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>',
    info: '<svg fill="none" height="22" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24" width="22"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8"  y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>',
};

const modal = {
    root: $("appModal"), icon: $("modalIcon"), title: $("modalTitle"), sub: $("modalSubtitle"),
    input: $("modalInput"), cancel: $("modalCancelBtn"), confirm: $("modalConfirmBtn"),
    resolver: null, returnFocus: null,
};

function closeModal(value) {
    modal.root.hidden = true;
    document.removeEventListener("keydown", modalKeys);
    if (modal.returnFocus) modal.returnFocus.focus();
    if (modal.resolver) { const r = modal.resolver; modal.resolver = null; r(value); }
}

function modalKeys(e) {
    if (e.key === "Escape") { e.preventDefault(); closeModal(null); }
    else if (e.key === "Enter" && !modal.input.hidden && document.activeElement === modal.input) {
        e.preventDefault(); modal.confirm.click();
    } else if (e.key === "Tab") {
        trapFocus(e, modal.root);
    }
}

modal.cancel.addEventListener("click", () => closeModal(null));
modal.root.addEventListener("click", (e) => { if (e.target === modal.root) closeModal(null); });

function openModal({ title, subtitle = "", icon = "info", kind = "confirm", defaultValue = "",
                     placeholder = "", confirmLabel = "OK", cancelLabel = "Batal", danger = false }) {
    modal.returnFocus = document.activeElement;
    modal.icon.innerHTML = MODAL_ICONS[icon] || MODAL_ICONS.info;
    modal.title.textContent = title;
    modal.sub.textContent = subtitle;
    modal.sub.style.display = subtitle ? "" : "none";
    modal.input.hidden = kind !== "prompt";
    modal.input.value = defaultValue;
    modal.input.placeholder = placeholder;
    modal.confirm.textContent = confirmLabel;
    modal.cancel.textContent = cancelLabel;
    modal.cancel.style.display = kind === "alert" ? "none" : "";
    modal.confirm.classList.toggle("modal-btn--danger", danger);
    modal.confirm.classList.toggle("modal-btn--primary", !danger);
    modal.root.hidden = false;
    setTimeout(() => (kind === "prompt" ? (modal.input.focus(), modal.input.select()) : modal.confirm.focus()), 30);
    document.addEventListener("keydown", modalKeys);
    return new Promise((resolve) => {
        modal.resolver = resolve;
        modal.confirm.onclick = () => closeModal(kind === "prompt" ? modal.input.value : true);
    });
}

const modalAlert = (title, subtitle = "") => openModal({ title, subtitle, kind: "alert" });

function trapFocus(e, container) {
    const focusable = [...container.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]):not(.visually-hidden), [tabindex]:not([tabindex="-1"])'
    )].filter((n) => n.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

// ---------------------------------------------------------------------------
// Menu dropdown (user & notebook)
// ---------------------------------------------------------------------------

function setupMenu(button, menu) {
    const open = () => { menu.hidden = false; button.setAttribute("aria-expanded", "true"); button.classList.add("is-open"); };
    const close = () => { menu.hidden = true; button.setAttribute("aria-expanded", "false"); button.classList.remove("is-open"); };
    button.addEventListener("click", (e) => { e.stopPropagation(); menu.hidden ? open() : close(); });
    document.addEventListener("click", (e) => {
        if (!menu.hidden && !menu.contains(e.target) && !button.contains(e.target)) close();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { close(); button.focus(); } });
    return close;
}

setupMenu($("userPillBtn"), $("userMenu"));
const closeNotebookMenu = setupMenu(el.notebookBtn, el.notebookMenu);
$("logoutBtn").addEventListener("click", logout);

// ---------------------------------------------------------------------------
// Routing: #/nb/<notebook>  atau  #/nb/<notebook>/c/<conversation>
// ---------------------------------------------------------------------------

function parseRoute() {
    const m = (window.location.hash || "").match(/^#\/nb\/([\w-]+)(?:\/c\/([\w-]+))?$/);
    return m ? { notebookId: m[1], conversationId: m[2] || null } : { notebookId: null, conversationId: null };
}

function go(notebookId, conversationId = null) {
    const target = `#/nb/${notebookId}${conversationId ? `/c/${conversationId}` : ""}`;
    if (window.location.hash === target) handleRoute();
    else window.location.hash = target;
}

async function handleRoute() {
    let { notebookId, conversationId } = parseRoute();

    if (!notebookId) {
        notebookId = await defaultNotebookId();
        if (!notebookId) return;
        window.history.replaceState({}, document.title, `/#/nb/${notebookId}`);
    }

    if (!state.notebook || state.notebook.id !== notebookId) {
        const ok = await loadNotebook(notebookId);
        if (!ok) {
            localStorage.removeItem(LAST_NOTEBOOK_KEY);
            const fallback = await defaultNotebookId();
            if (fallback && fallback !== notebookId) go(fallback);
            return;
        }
    }

    await openConversation(conversationId);
}

window.addEventListener("hashchange", handleRoute);

async function defaultNotebookId() {
    try {
        state.notebooks = await api("/notebooks");
    } catch (err) {
        toast(errorText(err), "error");
        return null;
    }
    const last = localStorage.getItem(LAST_NOTEBOOK_KEY);
    if (last && state.notebooks.some((n) => n.id === last)) return last;
    if (state.notebooks.length) return state.notebooks[0].id;
    // Pengguna baru: langsung siapkan satu notebook agar bisa mulai menambah sumber.
    try {
        const nb = await api("/notebooks", { method: "POST", json: { title: "Notebook saya" } });
        state.notebooks = [nb];
        return nb.id;
    } catch (err) {
        toast(errorText(err), "error");
        return null;
    }
}

// ---------------------------------------------------------------------------
// Notebook
// ---------------------------------------------------------------------------

async function loadNotebook(notebookId) {
    try {
        const [detail, conversations] = await Promise.all([
            api(`/notebooks/${notebookId}`),
            api(`/notebooks/${notebookId}/conversations`),
        ]);
        state.notebook = detail;
        state.conversations = conversations;
        state.conversationId = null;
        localStorage.setItem(LAST_NOTEBOOK_KEY, notebookId);
        if (!state.notebooks.some((n) => n.id === notebookId)) {
            state.notebooks = await api("/notebooks").catch(() => state.notebooks);
        }
        renderNotebookSwitcher();
        renderSources();
        renderConversations();
        schedulePoll();
        return true;
    } catch (err) {
        if (err.status !== 404) toast(errorText(err), "error");
        return false;
    }
}

function renderNotebookSwitcher() {
    el.notebookTitle.textContent = state.notebook ? state.notebook.title : "Notebook";
    el.notebookMenuList.replaceChildren(
        ...state.notebooks.map((nb) =>
            h("button", {
                type: "button",
                class: "notebook-menu-item" + (state.notebook && nb.id === state.notebook.id ? " is-current" : ""),
                role: "menuitemradio",
                "aria-checked": state.notebook && nb.id === state.notebook.id ? "true" : "false",
                onclick: () => { closeNotebookMenu(); go(nb.id); },
            },
            h("span", { class: "notebook-menu-name", text: nb.title }),
            h("span", { class: "notebook-menu-meta", text: `${nb.source_count} sumber` })),
        ),
    );
}

$("newNotebookBtn").addEventListener("click", async () => {
    closeNotebookMenu();
    const title = await openModal({
        title: "Notebook baru", subtitle: "Satu notebook untuk satu topik riset, misalnya \"Harga MPV 2026\".",
        icon: "edit", kind: "prompt", placeholder: "Judul notebook", confirmLabel: "Buat notebook",
    });
    if (!title || !title.trim()) return;
    try {
        const nb = await api("/notebooks", { method: "POST", json: { title: title.trim() } });
        state.notebooks.unshift({ ...nb, source_count: 0 });
        go(nb.id);
    } catch (err) { modalAlert("Notebook tidak dibuat", errorText(err)); }
});

$("renameNotebookBtn").addEventListener("click", async () => {
    closeNotebookMenu();
    if (!state.notebook) return;
    const title = await openModal({
        title: "Ganti nama notebook", icon: "edit", kind: "prompt",
        defaultValue: state.notebook.title, placeholder: "Judul notebook", confirmLabel: "Simpan",
    });
    if (!title || !title.trim()) return;
    try {
        const nb = await api(`/notebooks/${state.notebook.id}`, { method: "PATCH", json: { title: title.trim() } });
        state.notebook.title = nb.title;
        const item = state.notebooks.find((n) => n.id === nb.id);
        if (item) item.title = nb.title;
        renderNotebookSwitcher();
    } catch (err) { modalAlert("Nama tidak disimpan", errorText(err)); }
});

$("deleteNotebookBtn").addEventListener("click", async () => {
    closeNotebookMenu();
    if (!state.notebook) return;
    const ok = await openModal({
        title: "Hapus notebook ini?",
        subtitle: "Semua percakapan di notebook ini ikut terhapus. Dokumen tetap tersimpan di Library.",
        icon: "danger", confirmLabel: "Hapus notebook", danger: true,
    });
    if (!ok) return;
    try {
        await api(`/notebooks/${state.notebook.id}`, { method: "DELETE" });
        const deletedId = state.notebook.id;
        localStorage.removeItem(LAST_NOTEBOOK_KEY);
        state.notebook = null;
        state.notebooks = state.notebooks.filter((n) => n.id !== deletedId);
        window.location.hash = "";  // memicu hashchange → handleRoute
    } catch (err) { modalAlert("Notebook tidak dihapus", errorText(err)); }
});

// ---------------------------------------------------------------------------
// Sumber
// ---------------------------------------------------------------------------

const STAGE_LABEL = {
    queued: "Menunggu giliran",
    parsing: "Membaca dokumen",
    vision: "Membaca gambar",
    indexing: "Mengindeks isi",
    extracting: "Mengekstrak data",
    failed: "Gagal diproses",
    cancelled: "Dibatalkan",
};

function stageText(s) {
    const base = STAGE_LABEL[s.stage] || s.stage;
    if (!FINAL_STAGES.has(s.stage) && s.progress_total > 0) return `${base} ${s.progress_done}/${s.progress_total}`;
    return base;
}

function sources() { return (state.notebook && state.notebook.sources) || []; }
function activeSources() { return sources().filter((s) => s.enabled && s.stage === "ready"); }
function pendingSources() { return sources().filter((s) => !FINAL_STAGES.has(s.stage)); }

function renderSources() {
    const list = sources();
    const max = state.notebook ? state.notebook.max_sources : 10;
    el.sourceCount.textContent = `${list.length}/${max}`;
    $("addSourceBtn").disabled = list.length >= max;

    if (!list.length) {
        el.sourceList.replaceChildren(
            h("li", { class: "source-empty" },
                h("p", { text: "Belum ada sumber. Tambahkan dokumen agar Argos bisa menjawab dari isinya." }),
                h("button", { type: "button", class: "btn-inline", text: "Tambah sumber", onclick: openSourceModal })),
        );
    } else {
        el.sourceList.replaceChildren(...list.map(renderSourceItem));
    }
    renderScope();
    renderWelcome();
}

function renderSourceItem(s) {
    const ready = s.stage === "ready";
    const processing = !FINAL_STAGES.has(s.stage);
    const failed = s.stage === "failed" || s.stage === "cancelled";
    const id = `src-${s.document_id}`;

    const meta = [];
    if (ready) {
        meta.push(h("span", { text: `Versi ${s.version_no}, ${formatDate(s.uploaded_at)}` }));
        if (s.archived) meta.push(h("span", { class: "source-warn", text: "Diarsipkan oleh pengunggah" }));
        if (s.warnings.length) meta.push(h("span", { class: "source-warn", text: s.warnings[0] }));
    } else if (processing) {
        meta.push(h("span", { class: "source-stage" }, h("span", { class: "spinner", "aria-hidden": "true" }), stageText(s)));
    } else {
        meta.push(h("span", { class: "source-error", text: s.error || stageText(s) }));
    }

    const item = h("li", {
        class: "source-item" + (ready && s.enabled ? " is-on" : "") + (failed ? " is-failed" : "")
            + (state.citedVersion === s.version_id ? " is-cited" : ""),
        dataset: { documentId: s.document_id, versionId: s.version_id },
    },
        h("input", {
            type: "checkbox", id, class: "source-check",
            checked: s.enabled, disabled: !ready && !processing,
            "aria-describedby": `${id}-meta`,
            onchange: (e) => toggleSource(s, e.target.checked),
        }),
        h("label", { for: id, class: "source-body" },
            h("span", { class: "source-name", text: s.display_name, title: s.display_name }),
            h("span", { class: "source-meta", id: `${id}-meta` }, ...meta)),
        h("button", {
            type: "button", class: "source-remove", title: "Lepas dari notebook",
            "aria-label": `Lepas ${s.display_name} dari notebook`, onclick: () => removeSource(s),
        }, iconX()),
    );

    if (s.update_available) {
        item.append(h("div", { class: "source-update" },
            h("span", { text: `Versi ${s.latest_version_no} tersedia` }),
            h("button", { type: "button", class: "btn-inline", text: "Pakai versi terbaru", onclick: () => updateSource(s) })));
    }
    return item;
}

async function patchSource(s, body) {
    try {
        state.notebook.sources = await api(`/notebooks/${state.notebook.id}/sources/${s.document_id}`, {
            method: "PATCH", json: body,
        });
        renderSources();
        schedulePoll();
    } catch (err) {
        toast(errorText(err), "error");
        renderSources();
    }
}

const toggleSource = (s, enabled) => patchSource(s, { enabled });
const updateSource = (s) => patchSource(s, { use_latest_version: true });

async function removeSource(s) {
    const processing = !FINAL_STAGES.has(s.stage);
    const ok = await openModal({
        title: `Lepas "${s.display_name}"?`,
        subtitle: processing
            ? "Dokumen ini masih diproses. Jika tidak dipakai notebook lain, prosesnya dihentikan. Dokumen tetap ada di Library."
            : "Sumber hanya dilepas dari notebook ini. Dokumen tetap ada di Library.",
        icon: "danger", confirmLabel: "Lepas sumber", danger: true,
    });
    if (!ok) return;
    try {
        state.notebook.sources = await api(`/notebooks/${state.notebook.id}/sources/${s.document_id}`, { method: "DELETE" });
        renderSources();
    } catch (err) { toast(errorText(err), "error"); }
}

function renderScope() {
    const active = activeSources().length;
    el.headerScope.textContent = active ? `Menjawab dari ${active} sumber` : "";
}

// Polling status sumber selama masih ada yang diproses
function schedulePoll() {
    clearTimeout(state.pollTimer);
    if (pendingSources().length && state.notebook) state.pollTimer = setTimeout(pollSources, POLL_MS);
}

async function pollSources() {
    if (!state.notebook) return;
    const notebookId = state.notebook.id;
    const before = new Map(sources().map((s) => [s.version_id, s.stage]));
    try {
        const detail = await api(`/notebooks/${notebookId}`);
        if (!state.notebook || state.notebook.id !== notebookId) return;
        state.notebook.sources = detail.sources;
        for (const s of detail.sources) {
            const prev = before.get(s.version_id);
            if (prev && !FINAL_STAGES.has(prev) && s.stage === "ready") toast(`"${s.display_name}" siap dipakai.`, "success");
            if (prev && !FINAL_STAGES.has(prev) && s.stage === "failed") toast(`"${s.display_name}" gagal diproses.`, "error");
        }
        renderSources();
    } catch { /* coba lagi pada putaran berikutnya */ }
    schedulePoll();
}

// ---------------------------------------------------------------------------
// Modal "Tambah sumber"
// ---------------------------------------------------------------------------

const LIMITS = { fileMb: 10, files: 5, batchMb: 30, ext: [".pdf", ".md"] };

const sm = {
    root: $("sourceModal"), slots: $("sourceModalSlots"), note: $("sourceModalNote"),
    submit: $("sourceModalSubmit"), cancel: $("sourceModalCancel"), close: $("sourceModalClose"),
    tabUpload: $("tabUpload"), tabLibrary: $("tabLibrary"),
    panelUpload: $("panelUpload"), panelLibrary: $("panelLibrary"),
    dropzone: $("dropzone"), input: $("uploadInput"), uploadList: $("uploadList"),
    search: $("librarySearch"), libraryList: $("libraryList"),
    tab: "upload", files: [], results: null, library: [], picked: new Set(), busy: false, returnFocus: null,
};

function remainingSlots() {
    return state.notebook ? state.notebook.max_sources - sources().length : 0;
}

function openSourceModal() {
    if (!state.notebook) return;
    if (remainingSlots() <= 0) {
        modalAlert("Notebook sudah penuh", `Satu notebook berisi maksimal ${state.notebook.max_sources} sumber. Lepas sumber yang tidak dipakai, lalu coba lagi.`);
        return;
    }
    sm.returnFocus = document.activeElement;
    sm.files = []; sm.results = null; sm.picked = new Set(); sm.busy = false;
    sm.input.value = ""; sm.search.value = "";
    sm.root.hidden = false;
    selectTab("upload");
    document.addEventListener("keydown", sourceModalKeys);
    setTimeout(() => sm.tabUpload.focus(), 30);
}

function closeSourceModal() {
    if (sm.busy) return;
    sm.root.hidden = true;
    document.removeEventListener("keydown", sourceModalKeys);
    if (sm.returnFocus) sm.returnFocus.focus();
    // File mirip yang belum diputuskan → dokumen terpisah (default, A §6.3).
    const undecided = (sm.results || []).filter((r) => r.status === "similar");
    sm.results = null;
    if (undecided.length) resolveUndecided(undecided);
}

async function resolveUndecided(results) {
    let added = 0;
    for (const r of results) {
        try {
            const out = await resolvePendingRequest(r.pending_id, "separate");
            state.notebook.sources = out.sources;
            added += 1;
        } catch (err) {
            toast(`${r.filename}: ${errorText(err)}`, "error");
        }
    }
    if (added) {
        renderSources();
        schedulePoll();
        toast(`${added} file yang mirip disimpan sebagai dokumen terpisah.`, "success");
    }
}

function resolvePendingRequest(pendingId, action) {
    return api(`/notebooks/${state.notebook.id}/sources/pending/${pendingId}/resolve`, {
        method: "POST", json: { action },
    });
}

function sourceModalKeys(e) {
    if (panel.root) return;  // panel kelola dokumen sedang terbuka di atasnya
    if (e.key === "Escape") { e.preventDefault(); closeSourceModal(); }
    else if (e.key === "Tab") trapFocus(e, sm.root);
}

sm.close.addEventListener("click", closeSourceModal);
sm.cancel.addEventListener("click", closeSourceModal);
sm.root.addEventListener("click", (e) => { if (e.target === sm.root) closeSourceModal(); });
$("addSourceBtn").addEventListener("click", openSourceModal);
$("attachBtn").addEventListener("click", openSourceModal);
el.welcomeCta.addEventListener("click", openSourceModal);

function selectTab(tab) {
    sm.tab = tab;
    const upload = tab === "upload";
    sm.tabUpload.setAttribute("aria-selected", String(upload));
    sm.tabLibrary.setAttribute("aria-selected", String(!upload));
    sm.tabUpload.tabIndex = upload ? 0 : -1;
    sm.tabLibrary.tabIndex = upload ? -1 : 0;
    sm.panelUpload.hidden = !upload;
    sm.panelLibrary.hidden = upload;
    if (!upload && !sm.library.length) loadLibrary();
    renderSourceModal();
}

sm.tabUpload.addEventListener("click", () => selectTab("upload"));
sm.tabLibrary.addEventListener("click", () => selectTab("library"));
for (const tab of [sm.tabUpload, sm.tabLibrary]) {
    tab.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
            const next = sm.tab === "upload" ? "library" : "upload";
            selectTab(next);
            (next === "upload" ? sm.tabUpload : sm.tabLibrary).focus();
        }
    });
}

// ── Upload ──

function validateFile(file) {
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!LIMITS.ext.includes(ext)) return "Format tidak didukung, gunakan PDF atau Markdown";
    if (file.size > LIMITS.fileMb * 1024 * 1024) return `Melebihi ${LIMITS.fileMb} MB`;
    if (file.size === 0) return "File kosong";
    return null;
}

function addFiles(fileList) {
    if (sm.results) { sm.files = []; sm.results = null; }
    for (const file of fileList) {
        if (sm.files.some((f) => f.file.name === file.name && f.file.size === file.size)) continue;
        sm.files.push({ file, error: validateFile(file) });
    }
    renderSourceModal();
}

sm.input.addEventListener("change", () => { addFiles(sm.input.files); sm.input.value = ""; });
sm.dropzone.addEventListener("dragover", (e) => { e.preventDefault(); sm.dropzone.classList.add("is-over"); });
sm.dropzone.addEventListener("dragleave", () => sm.dropzone.classList.remove("is-over"));
sm.dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    sm.dropzone.classList.remove("is-over");
    addFiles(e.dataTransfer.files);
});

function validUploads() { return sm.files.filter((f) => !f.error); }

function uploadProblems() {
    const valid = validUploads();
    const limit = Math.min(LIMITS.files, remainingSlots());
    if (valid.length > limit) {
        return limit < LIMITS.files
            ? `Notebook hanya punya ${limit} slot tersisa. Kurangi file.`
            : `Maksimal ${LIMITS.files} file sekaligus.`;
    }
    const total = valid.reduce((n, f) => n + f.file.size, 0);
    if (total > LIMITS.batchMb * 1024 * 1024) return `Total upload melebihi ${LIMITS.batchMb} MB.`;
    return null;
}

const RESULT_TEXT = {
    queued: "Diproses di background",
    existing: "Sudah ada di Library, langsung dipakai",
};

function resultRow(r) {
    if (r.status !== "similar") {
        return h("li", { class: `pick-item is-${r.status === "rejected" ? "error" : "ok"}` },
            fileIcon(),
            h("span", { class: "pick-name", text: r.filename }),
            h("span", { class: "pick-status", text: r.status === "rejected" ? r.error_message : (r.doneText || RESULT_TEXT[r.status]) }));
    }
    // Mirip dokumen Library: user memilih versi baru atau dokumen terpisah.
    const percent = Math.round((r.similarity || 0) * 100);
    const label = `Pilihan untuk ${r.filename}`;
    return h("li", { class: "pick-item is-similar" },
        fileIcon(),
        h("span", { class: "pick-name", text: r.filename }),
        h("span", { class: "pick-status", text: r.busy ? "Menyimpan…" : `${percent}% mirip` }),
        h("div", { class: "similar-choice", role: "group", "aria-label": label },
            h("p", { class: "similar-text" },
                r.candidateGone ? r.error_message : ["Isinya mirip dengan ", h("strong", { text: r.similar_document_name }),
                    " di Library. Simpan sebagai versi barunya?"]),
            h("div", { class: "similar-actions" },
                r.candidateGone ? null : h("button", {
                    type: "button", class: "similar-btn similar-btn--accent", disabled: r.busy,
                    onclick: () => resolveSimilar(r, "new_version"),
                }, "Jadikan versi baru"),
                h("button", {
                    type: "button", class: "similar-btn", disabled: r.busy,
                    onclick: () => resolveSimilar(r, "separate"),
                }, "Dokumen terpisah"))));
}

async function resolveSimilar(r, action) {
    r.busy = true;
    renderSourceModal(true);
    try {
        const out = await resolvePendingRequest(r.pending_id, action);
        const [res] = out.results;
        const name = r.similar_document_name;
        Object.assign(r, res, {
            busy: false,
            doneText: action === "new_version" ? `Disimpan sebagai versi baru ${name}` : "Disimpan sebagai dokumen baru",
        });
        state.notebook.sources = out.sources;
        renderSources();
        schedulePoll();
    } catch (err) {
        r.busy = false;
        if (err.code === "SIMILAR_DOCUMENT_GONE") {
            r.candidateGone = true;
            r.error_message = err.message;
        } else if (err.code === "PENDING_UPLOAD_NOT_FOUND") {
            Object.assign(r, { status: "rejected", error_message: err.message });
        } else {
            toast(errorText(err), "error");
        }
    }
    renderSourceModal(true);
    updateUploadNote();
}

function updateUploadNote() {
    if (!sm.results) return;
    const added = sm.results.filter((r) => r.status === "queued" || r.status === "existing").length;
    const waiting = sm.results.filter((r) => r.status === "similar").length;
    delete sm.note.dataset.kind;
    if (waiting) {
        sm.note.textContent = `${waiting} file mirip dokumen yang sudah ada. Pilih cara menyimpannya; `
            + "jika jendela ini ditutup, file disimpan sebagai dokumen terpisah.";
    } else {
        sm.note.textContent = added
            ? `${added} sumber ditambahkan. Anda bisa menutup jendela ini; proses berjalan di background.`
            : "Tidak ada file yang ditambahkan.";
    }
}

function renderUploadList() {
    if (sm.results) {
        sm.uploadList.replaceChildren(...sm.results.map(resultRow));
        return;
    }
    sm.uploadList.replaceChildren(...sm.files.map((f, i) =>
        h("li", { class: `pick-item${f.error ? " is-error" : ""}` },
            fileIcon(),
            h("span", { class: "pick-name", text: f.file.name }),
            h("span", { class: "pick-status", text: f.error || formatSize(f.file.size) }),
            h("button", {
                type: "button", class: "pick-remove", "aria-label": `Hapus ${f.file.name} dari daftar`,
                onclick: () => { sm.files.splice(i, 1); renderSourceModal(); },
            }, iconX())),
    ));
}

function reuseLine(stats) {
    // Hanya ditampilkan bila ada hasil versi sebelumnya yang dipakai ulang (Tahap 3).
    if (!stats) return null;
    const parts = [];
    if (stats.chunks_reused) parts.push(`${stats.chunks_reused} dari ${stats.chunks} potongan teks`);
    if (stats.units_cached) parts.push(`${stats.units_cached} dari ${stats.units} bagian analisis AI`);
    if (stats.images_cached) parts.push(`${stats.images_cached} dari ${stats.images} gambar`);
    if (!parts.length) return null;
    return h("span", { class: "version-reuse", text: `Dipakai ulang dari versi sebelumnya: ${parts.join(", ")}` });
}

async function submitUpload() {
    const valid = validUploads();
    const form = new FormData();
    valid.forEach((f) => form.append("files", f.file));
    sm.busy = true;
    renderSourceModal();
    try {
        const out = await api(`/notebooks/${state.notebook.id}/sources/upload`, { method: "POST", form });
        sm.results = out.results;
        state.notebook.sources = out.sources;
        renderSources();
        schedulePoll();
        updateUploadNote();
    } catch (err) {
        sm.note.textContent = errorText(err);
        sm.note.dataset.kind = "error";
    } finally {
        sm.busy = false;
        renderSourceModal(true);
    }
}

// ── Library ──

let searchTimer = null;
sm.search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadLibrary, 250);
});

async function loadLibrary() {
    const q = sm.search.value.trim();
    sm.libraryList.replaceChildren(h("li", { class: "pick-empty", text: "Memuat Library…" }));
    try {
        sm.library = await api(`/library/documents?limit=100${q ? `&q=${encodeURIComponent(q)}` : ""}`);
    } catch (err) {
        sm.library = [];
        sm.libraryList.replaceChildren(h("li", { class: "pick-empty", text: errorText(err) }));
        return;
    }
    renderSourceModal();
}

function renderLibraryList() {
    if (!sm.library.length) {
        sm.libraryList.replaceChildren(h("li", { class: "pick-empty",
            text: sm.search.value.trim() ? "Tidak ada dokumen yang cocok." : "Library masih kosong. Upload dokumen pertama Anda di tab Upload baru." }));
        return;
    }
    const inNotebook = new Set(sources().map((s) => s.document_id));
    sm.libraryList.replaceChildren(...sm.library.map((d) => {
        const already = inNotebook.has(d.id);
        const v = d.latest_version;
        const status = !v ? "" : v.stage === "ready" ? `Versi ${v.version_no}, ${formatDate(v.uploaded_at)}`
            : FINAL_STAGES.has(v.stage) ? STAGE_LABEL[v.stage] : "Sedang diproses";
        const id = `lib-${d.id}`;
        return h("li", { class: `pick-item library-item${already ? " is-disabled" : ""}` },
            h("input", {
                type: "checkbox", id, class: "source-check", disabled: already || (v && v.stage === "failed"),
                checked: already || sm.picked.has(d.id),
                onchange: (e) => { e.target.checked ? sm.picked.add(d.id) : sm.picked.delete(d.id); renderSourceModal(); },
            }),
            h("label", { for: id, class: "library-body" },
                h("span", { class: "pick-name", text: d.display_name }),
                h("span", { class: "pick-status",
                    text: already ? "Sudah ada di notebook ini" : [status, d.owner_name && `diunggah ${d.owner_name}`].filter(Boolean).join(", ") })),
            h("button", {
                type: "button", class: "btn-manage", text: "Kelola",
                "aria-label": `Kelola ${d.display_name}`, onclick: () => openDocumentManager(d.id),
            }));
    }));
}

async function submitLibrary() {
    sm.busy = true;
    renderSourceModal();
    try {
        state.notebook.sources = await api(`/notebooks/${state.notebook.id}/sources`, {
            method: "POST", json: { document_ids: [...sm.picked] },
        });
        renderSources();
        schedulePoll();
        sm.busy = false;
        toast(`${sm.picked.size} sumber ditambahkan.`, "success");
        closeSourceModal();
    } catch (err) {
        sm.busy = false;
        sm.note.textContent = errorText(err);
        sm.note.dataset.kind = "error";
        renderSourceModal(true);
    }
}

// ── Footer & tombol ──

function renderSourceModal(keepNote = false) {
    const left = remainingSlots();
    sm.slots.textContent = `${sources().length} dari ${state.notebook ? state.notebook.max_sources : 10} sumber terpakai`;
    $("dropzoneLimits").textContent =
        `PDF atau Markdown, maks. ${LIMITS.fileMb} MB per file, ${Math.min(LIMITS.files, Math.max(left, 0))} file sekaligus`;

    if (!keepNote) { sm.note.textContent = ""; delete sm.note.dataset.kind; }
    sm.cancel.disabled = sm.busy;
    sm.close.disabled = sm.busy;

    if (sm.tab === "upload") {
        renderUploadList();
        if (sm.results) {
            sm.submit.textContent = "Selesai";
            sm.submit.disabled = false;
            sm.submit.onclick = closeSourceModal;
            sm.cancel.hidden = true;
            return;
        }
        sm.cancel.hidden = false;
        const valid = validUploads().length;
        const problem = uploadProblems();
        if (problem && !keepNote) { sm.note.textContent = problem; sm.note.dataset.kind = "error"; }
        sm.submit.textContent = sm.busy ? "Mengunggah…" : valid ? `Tambah ${valid} file` : "Tambah";
        sm.submit.disabled = sm.busy || !valid || !!problem;
        sm.submit.onclick = submitUpload;
    } else {
        renderLibraryList();
        sm.cancel.hidden = false;
        const n = sm.picked.size;
        const over = n > left;
        if (over && !keepNote) { sm.note.textContent = `Notebook hanya punya ${left} slot tersisa.`; sm.note.dataset.kind = "error"; }
        sm.submit.textContent = sm.busy ? "Menambahkan…" : n ? `Tambah ${n} dokumen` : "Tambah";
        sm.submit.disabled = sm.busy || !n || over;
        sm.submit.onclick = submitLibrary;
    }
}

// ---------------------------------------------------------------------------
// Percakapan
// ---------------------------------------------------------------------------

function renderConversations() {
    if (!state.conversations.length) {
        el.historyList.replaceChildren(h("div", { class: "history-empty", text: "Belum ada percakapan di notebook ini." }));
        return;
    }
    el.historyList.replaceChildren(...state.conversations.map((c) =>
        h("button", {
            type: "button",
            class: "history-item" + (c.id === state.conversationId ? " active" : ""),
            "aria-current": c.id === state.conversationId ? "true" : null,
            onclick: () => { closeSidebarOnMobile(); go(state.notebook.id, c.id); },
        },
            h("span", { class: "history-item-content" },
                h("span", { class: "history-item-title", text: c.title || "Tanpa judul" }),
                h("span", { class: "history-item-subtitle", text: formatRelative(c.updated_at) }))),
    ));
}

async function refreshConversations() {
    if (!state.notebook) return;
    try {
        state.conversations = await api(`/notebooks/${state.notebook.id}/conversations`);
        renderConversations();
    } catch { /* daftar lama tetap ditampilkan */ }
}

async function openConversation(conversationId) {
    state.conversationId = conversationId;
    el.chatBox.replaceChildren();
    renderConversations();

    if (!conversationId) {
        showWelcome();
        return;
    }
    showChat();
    el.headerTitle.textContent = "Memuat…";
    try {
        const detail = await api(`/notebooks/${state.notebook.id}/conversations/${conversationId}`);
        if (state.conversationId !== conversationId) return;
        el.headerTitle.textContent = detail.title || "Tanpa judul";
        const last = detail.messages[detail.messages.length - 1];
        detail.messages.forEach((m) =>
            m.role === "user"
                // Hanya pesan terakhir yang bisa dikirim ulang (server menolak yang lain).
                ? appendUserMessage(m.content, { ...m, conversationId, canRetry: m === last })
                : appendBotMessage(m.content, m.citations || [], [], m));
        scrollToBottom();
    } catch (err) {
        if (err.status === 404) { go(state.notebook.id); return; }
        appendNotice(err.message, err.requestId);
    }
}

function showWelcome() {
    el.welcome.hidden = false;
    el.chatBox.hidden = true;
    el.headerTitle.textContent = "Chat baru";
    el.renameThreadBtn.hidden = true;
    el.deleteThreadBtn.hidden = true;
    renderWelcome();
}

function showChat() {
    el.welcome.hidden = true;
    el.chatBox.hidden = false;
    el.renameThreadBtn.hidden = false;
    el.deleteThreadBtn.hidden = false;
}

function renderWelcome() {
    if (el.welcome.hidden) return;
    const all = sources();
    const active = activeSources();
    const pending = pendingSources();
    let title, subtitle, cta = false, suggestions = false;

    if (!all.length) {
        title = "Mulai dengan menambahkan sumber";
        subtitle = "Upload pricelist, brosur, atau laporan kompetitor. Argos menjawab hanya dari dokumen yang Anda pilih, lengkap dengan sumbernya.";
        cta = true;
    } else if (!active.length && pending.length) {
        title = "Sumber sedang diproses";
        subtitle = `${pending.length} dokumen sedang dibaca. Anda bisa mulai bertanya begitu statusnya siap.`;
    } else if (!active.length) {
        title = "Belum ada sumber yang dicentang";
        subtitle = "Centang minimal satu sumber di panel kiri untuk mulai bertanya.";
    } else {
        title = state.notebook.title;
        subtitle = `Tanyakan harga, fitur, atau kelemahan produk dari ${active.length} sumber yang dicentang.`;
        suggestions = true;
    }
    el.welcomeTitle.textContent = title;
    el.welcomeSubtitle.textContent = subtitle;
    el.welcomeCta.hidden = !cta;
    el.welcomeSuggestions.hidden = !suggestions;
}

$("newChatBtn").addEventListener("click", () => { closeSidebarOnMobile(); if (state.notebook) go(state.notebook.id); });

el.renameThreadBtn.addEventListener("click", async () => {
    const current = state.conversations.find((c) => c.id === state.conversationId);
    const title = await openModal({
        title: "Ganti nama percakapan", subtitle: "Beri nama yang singkat dan deskriptif.",
        icon: "edit", kind: "prompt", defaultValue: current ? current.title : "", placeholder: "Nama percakapan", confirmLabel: "Simpan",
    });
    if (!title || !title.trim()) return;
    try {
        const conv = await api(`/notebooks/${state.notebook.id}/conversations/${state.conversationId}`, {
            method: "PATCH", json: { title: title.trim() },
        });
        el.headerTitle.textContent = conv.title;
        refreshConversations();
    } catch (err) { modalAlert("Nama tidak disimpan", errorText(err)); }
});

el.deleteThreadBtn.addEventListener("click", async () => {
    const ok = await openModal({
        title: "Hapus percakapan?",
        subtitle: "Semua pesan dalam percakapan ini akan dihapus permanen.",
        icon: "danger", confirmLabel: "Hapus", danger: true,
    });
    if (!ok) return;
    try {
        await api(`/notebooks/${state.notebook.id}/conversations/${state.conversationId}`, { method: "DELETE" });
        await refreshConversations();
        go(state.notebook.id);
    } catch (err) { modalAlert("Percakapan tidak dihapus", errorText(err)); }
});

document.querySelectorAll(".welcome-suggestion").forEach((btn) =>
    btn.addEventListener("click", () => { el.chatInput.value = btn.dataset.prompt; sendMessage(); }));

// ---------------------------------------------------------------------------
// Pesan & sitasi
// ---------------------------------------------------------------------------

function scrollToBottom() { el.chatBox.scrollTop = el.chatBox.scrollHeight; }

/**
 * Pesan user. `msg` (opsional, dari riwayat): {id, status, error_code, conversationId, canRetry}.
 * Mengembalikan elemen wrapper agar bisa ditandai gagal / dipulihkan.
 */
function appendUserMessage(text, msg = {}) {
    const group = h("div", { class: "bubble-group" }, h("div", { class: "message user", text }));
    const wrapper = h("div", { class: "message-wrapper user-wrapper" },
        h("div", { class: "msg-avatar user-avatar", text: "U", "aria-hidden": "true" }),
        group);
    el.chatBox.append(wrapper);
    if (msg.status === "failed") {
        markFailed(wrapper, {
            code: msg.error_code,
            messageId: msg.id,
            conversationId: msg.conversationId,
            canRetry: msg.canRetry,
        });
    }
    scrollToBottom();
    return wrapper;
}

/** Tombol kecil yang menyalin request ID, untuk dilaporkan ke admin. */
function requestIdButton(requestId) {
    return h("button", {
        type: "button",
        class: "btn-copy-id",
        title: "Salin kode ini bila melapor ke admin",
        "aria-label": `Salin kode error ${requestId}`,
        onclick: async () => {
            try {
                await navigator.clipboard.writeText(requestId);
                toast("Kode disalin.");
            } catch {
                toast(`Kode: ${requestId}`);
            }
        },
    }, `Kode: ${requestId}`);
}

function appendNotice(text, requestId = null) {
    el.chatBox.append(h("div", { class: "chat-notice", role: "alert" },
        iconAlert(), h("span", { text }), requestId ? requestIdButton(requestId) : null));
    scrollToBottom();
}

// Teks untuk pesan gagal yang dimuat dari riwayat (server hanya menyimpan kodenya).
const FAILURE_TEXT = {
    UPSTREAM_UNAVAILABLE: "layanan AI atau sumber data sedang tidak tersedia.",
    CHAT_TIMEOUT: "jawaban terlalu lama dibuat.",
    CANCELLED: "koneksi terputus sebelum jawaban selesai.",
    INTERNAL_ERROR: "terjadi kesalahan pada sistem.",
};

function failureText(code, message) {
    if (message) return message;
    return `Gagal: ${FAILURE_TEXT[code] || "pesan ini belum terjawab."}`;
}

/** Tandai pesan user sebagai gagal (DESIGN_GROUP_C.md §4): redup + alasan + [Kirim ulang]. */
function markFailed(wrapper, { code, message, requestId, messageId, conversationId, canRetry = true }) {
    clearFailed(wrapper);
    wrapper.classList.add("is-failed");
    const row = h("div", { class: "msg-failure", role: "status" },
        iconAlert(), h("span", { class: "msg-failure-text", text: failureText(code, message) }));
    const actions = h("div", { class: "msg-failure-actions" });
    if (canRetry && messageId && conversationId) {
        actions.append(h("button", {
            type: "button",
            class: "btn-retry",
            onclick: () => retryMessage(wrapper, conversationId, messageId),
        }, "Kirim ulang"));
    }
    if (requestId) actions.append(requestIdButton(requestId));
    if (actions.childElementCount) row.append(actions);
    wrapper.querySelector(".bubble-group").append(row);
}

function clearFailed(wrapper) {
    wrapper.classList.remove("is-failed");
    wrapper.querySelector(".msg-failure")?.remove();
}

/** Pesan baru membuat pesan gagal sebelumnya tidak lagi "terakhir" → tidak bisa dikirim ulang. */
function clearRetryButtons() {
    el.chatBox.querySelectorAll(".btn-retry").forEach((b) => b.remove());
}

function appendBotMessage(text, citations, pending = []) {
    const byLabel = new Map(citations.map((c) => [c.label, c]));
    const bubble = h("div", { class: "message bot" });
    bubble.innerHTML = window.marked ? marked.parse(text || "") : "";
    if (!window.marked) bubble.textContent = text;
    linkCitations(bubble, byLabel);

    const group = h("div", { class: "bubble-group" }, bubble);

    if (citations.length) {
        group.append(h("ol", { class: "cite-list", "aria-label": "Sumber jawaban" },
            ...citations.map((c) => h("li", { class: "cite-list-item", dataset: { label: c.label } },
                h("span", { class: "cite-num", text: c.label }),
                h("span", { class: "cite-list-text", text: citationLine(c) })))));
    }
    if (pending.length) {
        group.append(h("p", { class: "answer-note",
            text: `Belum dipakai karena masih diproses: ${pending.join(", ")}.` }));
    }

    const tts = h("button", { type: "button", class: "btn-action-icon btn-tts", title: "Dengarkan", "aria-label": "Dengarkan jawaban" });
    tts.innerHTML = iconSpeaker();
    tts.addEventListener("click", () => speakMessage(bubble.innerText, tts));
    group.append(h("div", { class: "bubble-actions" }, tts));

    el.chatBox.append(
        h("div", { class: "message-wrapper bot-wrapper" },
            h("div", { class: "msg-avatar bot-avatar", text: "Ar", "aria-hidden": "true" }),
            group));
    scrollToBottom();
}

function citationLine(c) {
    const parts = [c.display_name, `versi ${c.version_no}`, `diunggah ${formatDate(c.uploaded_at)}`];
    if (c.page_number) parts.push(`hal. ${c.page_number}`);
    return parts.join(", ");
}

/** Ganti teks "[n]" di jawaban dengan chip yang bisa di-hover/fokus. */
function linkCitations(root, byLabel) {
    if (!byLabel.size) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode: (n) => (n.parentElement.closest("code, pre") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    const nodes = [];
    while (walker.nextNode()) if (/\[\d{1,3}\]/.test(walker.currentNode.nodeValue)) nodes.push(walker.currentNode);

    for (const node of nodes) {
        const frag = document.createDocumentFragment();
        let last = 0;
        node.nodeValue.replace(/\[(\d{1,3})\]/g, (match, num, offset) => {
            const c = byLabel.get(Number(num));
            if (!c) return match;
            frag.append(node.nodeValue.slice(last, offset));
            frag.append(h("button", {
                type: "button", class: "cite", dataset: { label: num },
                "aria-label": `Sumber ${num}: ${citationLine(c)}`,
                onmouseenter: (e) => showCite(e.currentTarget, c),
                onfocus: (e) => showCite(e.currentTarget, c),
                onmouseleave: hideCite, onblur: hideCite,
                onclick: (e) => { e.stopPropagation(); el.popover.hidden ? showCite(e.currentTarget, c) : hideCite(); },
            }, num));
            last = offset + match.length;
            return match;
        });
        frag.append(node.nodeValue.slice(last));
        node.replaceWith(frag);
    }
}

function showCite(anchor, c) {
    const pop = el.popover;
    pop.replaceChildren(
        h("span", { class: "cite-pop-num", text: c.label }),
        h("div", { class: "cite-pop-body" },
            h("strong", { class: "cite-pop-title", text: c.display_name }),
            h("span", { class: "cite-pop-meta", text: `Versi ${c.version_no}, diunggah ${formatDate(c.uploaded_at)}` }),
            (c.page_number || c.section_heading) && h("span", { class: "cite-pop-where",
                text: [c.page_number && `Halaman ${c.page_number}`, c.section_heading].filter(Boolean).join(", ") })),
    );
    pop.hidden = false;
    const r = anchor.getBoundingClientRect();
    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    let left = Math.min(Math.max(8, r.left + r.width / 2 - pw / 2), window.innerWidth - pw - 8);
    let top = r.top - ph - 8;
    pop.dataset.side = "top";
    if (top < 8) { top = r.bottom + 8; pop.dataset.side = "bottom"; }
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;

    // Sumber yang sama ikut menyala di panel kiri (dipertahankan saat panel di-render ulang).
    state.citedVersion = c.version_id;
    document.querySelectorAll(".source-item.is-cited").forEach((n) => n.classList.remove("is-cited"));
    const row = el.sourceList.querySelector(`[data-version-id="${CSS.escape(c.version_id)}"]`);
    if (row) row.classList.add("is-cited");
}

function hideCite() {
    state.citedVersion = null;
    el.popover.hidden = true;
    document.querySelectorAll(".source-item.is-cited").forEach((n) => n.classList.remove("is-cited"));
}

document.addEventListener("click", hideCite);
el.chatBox.addEventListener("scroll", hideCite, { passive: true });

// ---------------------------------------------------------------------------
// Kirim pesan
// ---------------------------------------------------------------------------

async function sendMessage() {
    const question = el.chatInput.value.trim();
    if (!question || state.sending || !state.notebook) return;

    if (!activeSources().length) {
        renderWelcome();
        toast(pendingSources().length
            ? "Sumber masih diproses. Tunggu sampai statusnya siap."
            : "Centang minimal satu sumber yang sudah siap.", "error");
        return;
    }

    showChat();
    clearRetryButtons();
    const userEl = appendUserMessage(question);
    el.chatInput.value = "";
    setSending(true);

    const notebookId = state.notebook.id;
    try {
        const body = { question };
        if (state.conversationId) body.conversation_id = state.conversationId;
        const res = await api(`/notebooks/${notebookId}/messages`, { method: "POST", json: body });
        if (!state.notebook || state.notebook.id !== notebookId) return;

        appendBotMessage(res.answer, res.citations || [], res.metadata.pending_sources || [], res.metadata);
        adoptConversation(notebookId, res.conversation_id, question);
    } catch (err) {
        if (!state.notebook || state.notebook.id !== notebookId) return;
        const d = err.details || {};
        // Pesan tersimpan sebagai `failed` di server → percakapan baru pun sudah punya ID.
        if (d.conversation_id) adoptConversation(notebookId, d.conversation_id, question);
        markFailed(userEl, {
            code: err.code,
            message: err.message,
            requestId: err.requestId,
            messageId: d.message_id,
            conversationId: d.conversation_id,
        });
        if (err.code === "SOURCES_PROCESSING" || err.code === "NO_ACTIVE_SOURCES") pollSources();
    } finally {
        setSending(false);
    }
}

/** Setelah pesan pertama: pakai ID percakapan dari server, perbarui URL & judul. */
function adoptConversation(notebookId, conversationId, question) {
    if (state.conversationId === conversationId) {
        refreshConversations();
        return;
    }
    state.conversationId = conversationId;
    window.history.replaceState({}, document.title, `/#/nb/${notebookId}/c/${conversationId}`);
    el.headerTitle.textContent = question.length > 60 ? `${question.slice(0, 59)}…` : question;
    refreshTitleSoon();
}

/** Judul otomatis dibuat server di background; ambil lagi sebentar kemudian. */
function refreshTitleSoon() {
    refreshConversations();
    setTimeout(async () => {
        await refreshConversations();
        const conv = state.conversations.find((c) => c.id === state.conversationId);
        if (conv) el.headerTitle.textContent = conv.title;
    }, 2000);
}

/** Kirim ulang pesan gagal: server memakai baris pesan yang sama (tidak ada pertanyaan ganda). */
async function retryMessage(wrapper, conversationId, messageId) {
    if (state.sending || !state.notebook) return;
    const notebookId = state.notebook.id;
    clearFailed(wrapper);
    setSending(true);
    try {
        const res = await api(
            `/notebooks/${notebookId}/conversations/${conversationId}/messages/${messageId}/retry`,
            { method: "POST" },
        );
        if (!state.notebook || state.notebook.id !== notebookId || state.conversationId !== conversationId) return;
        appendBotMessage(res.answer, res.citations || [], res.metadata.pending_sources || [], res.metadata);
        refreshTitleSoon();
    } catch (err) {
        const final = ["MESSAGE_NOT_LATEST", "MESSAGE_NOT_FAILED", "MESSAGE_NOT_FOUND"].includes(err.code);
        markFailed(wrapper, {
            code: err.code, message: err.message, requestId: err.requestId,
            messageId, conversationId, canRetry: !final,
        });
        if (err.code === "SOURCES_PROCESSING" || err.code === "NO_ACTIVE_SOURCES") pollSources();
    } finally {
        setSending(false);
    }
}

function setSending(on) {
    state.sending = on;
    el.chatInput.disabled = on;
    el.sendBtn.disabled = on;
    el.chatLoading.style.display = on ? "block" : "none";
    if (!on) el.chatInput.focus();
}

el.sendBtn.addEventListener("click", sendMessage);
el.chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendMessage(); }
});

// ---------------------------------------------------------------------------
// Text-to-Speech
// ---------------------------------------------------------------------------

let currentAudio = null;
let currentTtsBtn = null;

async function speakMessage(text, btn) {
    if (currentTtsBtn === btn && currentAudio && !currentAudio.paused) {
        currentAudio.pause(); resetTts(btn); currentTtsBtn = null; return;
    }
    if (currentAudio) { currentAudio.pause(); resetTts(currentTtsBtn); }
    currentTtsBtn = btn;
    btn.classList.add("playing");
    btn.innerHTML = iconPause();

    try {
        const response = await fetch(`${API}/voice/tts`, {
            method: "POST",
            headers: { Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
            body: JSON.stringify({ text: text.slice(0, 4000), voice: "alloy", format: "mp3", speed: 1.0 }),
        });
        if (response.status === 401) return logout();
        if (!response.ok) throw new Error("tts");
        const url = URL.createObjectURL(await response.blob());
        currentAudio = new Audio(url);
        await currentAudio.play();
        currentAudio.onended = () => { resetTts(btn); URL.revokeObjectURL(url); currentAudio = null; currentTtsBtn = null; };
    } catch {
        resetTts(btn);
        currentTtsBtn = null;
        toast("Suara tidak bisa diputar saat ini.", "error");
    }
}

function resetTts(btn) {
    if (!btn) return;
    btn.classList.remove("playing");
    btn.innerHTML = iconSpeaker();
}

// ---------------------------------------------------------------------------
// Speech-to-Text
// ---------------------------------------------------------------------------

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

el.micBtn.addEventListener("click", async () => {
    if (isRecording) { mediaRecorder.stop(); return; }
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunks = [];
        mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
        mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };
        mediaRecorder.onstop = async () => {
            isRecording = false;
            el.micBtn.classList.remove("recording");
            stream.getTracks().forEach((t) => t.stop());
            await transcribe(new Blob(audioChunks, { type: "audio/webm" }));
        };
        mediaRecorder.start();
        isRecording = true;
        el.micBtn.classList.add("recording");
        el.chatInput.placeholder = "Mendengarkan… klik mikrofon untuk selesai";
    } catch {
        modalAlert("Akses mikrofon ditolak", "Izinkan akses mikrofon di pengaturan browser untuk merekam suara.");
    }
});

async function transcribe(blob) {
    el.micBtn.disabled = true;
    el.micBtn.classList.add("loading");
    el.chatInput.placeholder = "Memproses suara…";
    const form = new FormData();
    form.append("audio", blob, "recording.webm");
    try {
        const result = await api("/voice/stt?language=id&with_timestamps=false", { method: "POST", form });
        if (result && result.text) { el.chatInput.value = result.text; el.chatInput.focus(); }
    } catch (err) {
        toast(errorText(err), "error");
    } finally {
        el.micBtn.disabled = false;
        el.micBtn.classList.remove("loading");
        el.chatInput.placeholder = "Tanyakan sesuatu tentang sumber Anda…";
    }
}

// ---------------------------------------------------------------------------
// Ikon
// ---------------------------------------------------------------------------

function svg(markup, size = 14) {
    const wrap = document.createElement("span");
    wrap.className = "icon";
    wrap.setAttribute("aria-hidden", "true");
    wrap.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${markup}</svg>`;
    return wrap;
}

const iconX = () => svg('<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>', 13);
const fileIcon = () => svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>', 15);
const iconAlert = () => svg('<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>', 15);

function iconSpeaker() {
    return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
        <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
        <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>`;
}

function iconPause() {
    return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
        <rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>`;
}

// ---------------------------------------------------------------------------
// Sidebar (mobile)
// ---------------------------------------------------------------------------

window.toggleSidebar = function () {
    $("sidebar").classList.toggle("open");
    $("sidebarOverlay").classList.toggle("active");
};

function closeSidebarOnMobile() {
    if (window.matchMedia("(max-width: 768px)").matches && $("sidebar").classList.contains("open")) toggleSidebar();
}

// ---------------------------------------------------------------------------
// Panel modal generik (kelola dokumen, kelola pengguna)
// ---------------------------------------------------------------------------

const panel = { root: null, returnFocus: null, onClose: null };

function openPanel({ title, subtitle = "", onClose = null }) {
    closePanel();
    panel.returnFocus = document.activeElement;
    panel.onClose = onClose;
    const titleId = "panelTitle";
    const body = h("div", { class: "panel-body" });
    const sub = h("p", { class: "source-modal-slots", text: subtitle });
    const card = h("div", { class: "modal-card source-modal panel-modal", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
        h("header", { class: "source-modal-header" },
            h("div", {}, h("h2", { class: "source-modal-title", id: titleId, text: title }), sub),
            h("button", { type: "button", class: "btn-modal-close", "aria-label": "Tutup", onclick: closePanel }, iconX())),
        body);
    panel.root = h("div", { class: "modal-overlay panel-overlay", onclick: (e) => { if (e.target === panel.root) closePanel(); } }, card);
    document.body.append(panel.root);
    document.addEventListener("keydown", panelKeys);
    setTimeout(() => card.querySelector(".btn-modal-close").focus(), 30);
    return { body, setSubtitle: (t) => { sub.textContent = t; } };
}

function closePanel() {
    if (!panel.root) return;
    panel.root.remove();
    panel.root = null;
    document.removeEventListener("keydown", panelKeys);
    if (panel.returnFocus && document.contains(panel.returnFocus)) panel.returnFocus.focus();
    const cb = panel.onClose;
    panel.onClose = null;
    if (cb) cb();
}

function panelKeys(e) {
    if (!modal.root.hidden) return;  // dialog konfirmasi sedang terbuka di atas panel
    if (e.key === "Escape") { e.preventDefault(); closePanel(); }
    else if (e.key === "Tab") trapFocus(e, panel.root);
}

// ── Kelola dokumen: riwayat versi, versi baru, hapus ──

async function openDocumentManager(documentId) {
    let changed = false;
    const { body, setSubtitle } = openPanel({
        title: "Kelola dokumen",
        onClose: () => {
            if (!changed) return;
            if (!sm.root.hidden) loadLibrary();
            refreshNotebook();
        },
    });
    const markChanged = () => { changed = true; };

    async function render() {
        body.replaceChildren(h("p", { class: "pick-empty", text: "Memuat…" }));
        let doc;
        try {
            doc = await api(`/library/documents/${documentId}`);
        } catch (err) {
            body.replaceChildren(h("p", { class: "pick-empty", text: errorText(err) }));
            return;
        }
        const isOwner = state.me && (doc.owner_id === state.me.id);
        setSubtitle(`${doc.display_name}, pemilik ${isOwner ? "Anda" : (doc.owner_name || "pengguna lain")}`);

        const versionRows = doc.versions.map((v) => {
            const status = v.stage === "ready" ? "Siap"
                : FINAL_STAGES.has(v.stage) ? (v.error || STAGE_LABEL[v.stage]) : stageText(v);
            const latest = doc.latest_version && doc.latest_version.id === v.id;
            return h("li", { class: "version-row" },
                h("span", { class: "version-no", text: `v${v.version_no}` }),
                h("span", { class: "version-body" },
                    h("span", { class: "version-title" },
                        v.original_filename,
                        latest ? h("span", { class: "version-badge", text: "Terbaru" }) : null),
                    h("span", { class: "version-meta",
                        text: `${formatDate(v.uploaded_at)}, ${v.page_count ? `${v.page_count} halaman, ` : ""}${status}` }),
                    reuseLine(v.reuse_stats)),
                isOwner && doc.versions.length > 1
                    ? h("button", {
                        type: "button", class: "source-remove version-delete", title: `Hapus versi ${v.version_no}`,
                        "aria-label": `Hapus versi ${v.version_no}`, onclick: () => deleteVersion(doc, v),
                    }, iconX())
                    : null);
        });

        const fileInput = h("input", { type: "file", accept: ".pdf,.md", class: "visually-hidden",
            onchange: (e) => uploadVersion(doc, e.target.files[0]) });

        body.replaceChildren(
            h("h3", { class: "panel-heading", text: "Riwayat versi" }),
            h("ol", { class: "version-list" }, ...versionRows),
            h("div", { class: "panel-actions" },
                h("label", { class: "modal-btn modal-btn--ghost btn-file" }, fileInput, "Upload versi baru"),
                isOwner ? h("button", { type: "button", class: "modal-btn modal-btn--danger",
                    text: "Hapus dokumen", onclick: () => deleteDocument(doc) }) : null),
            h("p", { class: "panel-note", text: isOwner
                ? "Versi yang masih dipakai notebook tidak bisa dihapus. Menghapus dokumen yang masih dipakai notebook orang lain akan mengarsipkannya."
                : "Siapa pun di tim boleh mengunggah versi baru. Hanya pengunggah yang bisa menghapus." }),
        );
    }

    async function uploadVersion(doc, file) {
        if (!file) return;
        const problem = validateFile(file);
        if (problem) { toast(problem, "error"); return; }
        const form = new FormData();
        form.append("file", file);
        try {
            const r = await api(`/library/documents/${doc.id}/versions`, { method: "POST", form });
            markChanged();
            toast(r.status === "existing" ? "File ini sudah ada sebagai salah satu versi." : "Versi baru sedang diproses.", "success");
            render();
        } catch (err) { toast(errorText(err), "error"); }
    }

    async function deleteVersion(doc, v) {
        const ok = await openModal({
            title: `Hapus versi ${v.version_no}?`,
            subtitle: "Data versi ini dihapus permanen. Nomor versinya tidak akan dipakai lagi.",
            icon: "danger", confirmLabel: "Hapus versi", danger: true,
        });
        if (!ok) return;
        try {
            await api(`/library/documents/${doc.id}/versions/${v.id}`, { method: "DELETE" });
            markChanged();
            toast(`Versi ${v.version_no} dihapus.`, "success");
            render();
        } catch (err) { modalAlert("Versi tidak dihapus", errorText(err)); }
    }

    async function deleteDocument(doc) {
        const ok = await openModal({
            title: `Hapus "${doc.display_name}"?`,
            subtitle: "Dokumen dilepas dari notebook Anda. Jika masih dipakai notebook orang lain, dokumen diarsipkan dan baru terhapus setelah tidak dipakai lagi.",
            icon: "danger", confirmLabel: "Hapus dokumen", danger: true,
        });
        if (!ok) return;
        try {
            const r = await api(`/library/documents/${doc.id}`, { method: "DELETE" });
            markChanged();
            toast(r.result === "archived" ? "Dokumen diarsipkan karena masih dipakai notebook lain." : "Dokumen dihapus.", "success");
            closePanel();
        } catch (err) { modalAlert("Dokumen tidak dihapus", errorText(err)); }
    }

    render();
}

async function refreshNotebook() {
    if (!state.notebook) return;
    try {
        const detail = await api(`/notebooks/${state.notebook.id}`);
        state.notebook.sources = detail.sources;
        renderSources();
        schedulePoll();
    } catch { /* tetap tampilkan data lama */ }
}

// ── Kelola pengguna (admin) ──

async function openUserManager() {
    const { body } = openPanel({ title: "Kelola pengguna", subtitle: "Pengguna nonaktif tidak bisa masuk. Dokumen miliknya dialihkan ke Anda." });

    async function render() {
        let users;
        try {
            users = await api("/admin/users");
        } catch (err) {
            body.replaceChildren(h("p", { class: "pick-empty", text: errorText(err) }));
            return;
        }
        body.replaceChildren(h("ul", { class: "user-list" }, ...users.map((u) => {
            const id = `user-${u.id}`;
            return h("li", { class: "user-row" + (u.is_active ? "" : " is-inactive") },
                h("span", { class: "user-row-body" },
                    h("span", { class: "user-row-name", text: u.name || u.email }),
                    h("span", { class: "user-row-meta",
                        text: `${u.email}${u.is_admin ? ", admin" : ""}${u.last_login_at ? `, terakhir masuk ${formatRelative(u.last_login_at)}` : ""}` })),
                u.is_admin ? h("span", { class: "user-row-state", text: "Aktif" })
                    : h("label", { class: "switch", for: id },
                        h("input", { type: "checkbox", id, role: "switch", checked: u.is_active,
                            "aria-label": `${u.is_active ? "Nonaktifkan" : "Aktifkan"} ${u.email}`,
                            onchange: (e) => setActive(u, e.target.checked, e.target) }),
                        h("span", { class: "switch-track", "aria-hidden": "true" }),
                        h("span", { class: "user-row-state", text: u.is_active ? "Aktif" : "Nonaktif" })));
        })));
    }

    async function setActive(u, active, input) {
        if (!active) {
            const ok = await openModal({
                title: `Nonaktifkan ${u.name || u.email}?`,
                subtitle: "Pengguna langsung tidak bisa masuk. Dokumen miliknya dialihkan ke Anda; notebook-nya tetap disimpan.",
                icon: "danger", confirmLabel: "Nonaktifkan", danger: true,
            });
            if (!ok) { input.checked = true; return; }
        }
        try {
            const r = await api(`/admin/users/${u.id}`, { method: "PATCH", json: { is_active: active } });
            toast(active ? "Pengguna diaktifkan kembali."
                : `Pengguna dinonaktifkan; ${r.documents_transferred} dokumen dialihkan ke Anda.`, "success");
        } catch (err) { toast(errorText(err), "error"); }
        render();
    }

    body.replaceChildren(h("p", { class: "pick-empty", text: "Memuat…" }));
    render();
}

$("manageUsersBtn").addEventListener("click", () => { $("userMenu").hidden = true; openUserManager(); });

async function loadMe() {
    try {
        state.me = await api("/users/me");
        $("manageUsersBtn").hidden = !state.me.is_admin;
    } catch { /* menu admin tetap tersembunyi */ }
}

// ---------------------------------------------------------------------------
// Mulai
// ---------------------------------------------------------------------------

loadMe();
handleRoute();
