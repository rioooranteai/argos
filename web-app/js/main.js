"use strict";

const API = "/api/v1";
const POLL_MS = 2500;
const FINAL_STAGES = new Set(["ready", "failed", "cancelled"]);

// ---------------------------------------------------------------------------
// Authentication
// ---------------------------------------------------------------------------

// Session = an HttpOnly cookie set by the server (DESIGN_GROUP_D.md D1). JavaScript never
// sees the token, and there is no session data in localStorage. The server only sends
// this page to signed-in users; when the session expires, the API answers 401.

function toLogin() { window.location.href = "/login"; }

async function logout() {
    try {
        await fetch(`${API}/auth/logout`, { method: "POST", credentials: "same-origin" });
    } catch { /* sign out anyway, even if the network fails */ }
    toLogin();
}

// ---------------------------------------------------------------------------
// API helper — every backend error looks like {error: {code, message, request_id}}
// ---------------------------------------------------------------------------

class ApiError extends Error {
    constructor(message, code, requestId, status, details = {}, retryable = false) {
        super(message);
        this.code = code;
        this.requestId = requestId;
        this.status = status;
        this.details = details;      // e.g. {conversation_id, message_id} when a chat fails
        this.retryable = retryable;
    }
}

async function api(path, { method = "GET", json, form } = {}) {
    const headers = {};
    let body;
    if (json !== undefined) {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(json);
    } else if (form) {
        body = form;
    }

    let response;
    try {
        response = await fetch(`${API}${path}`, { method, headers, body, credentials: "same-origin" });
    } catch {
        throw new ApiError("Cannot reach the server. Check your connection.", "NETWORK", null, 0);
    }

    if (response.status === 401) {
        toLogin();
        throw new ApiError("Session expired.", "UNAUTHENTICATED", null, 401);
    }
    if (response.status === 204) return null;

    const data = await response.json().catch(() => null);
    if (!response.ok) {
        const err = data && data.error;
        throw new ApiError(
            (err && err.message) || "The request could not be processed.",
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
    notebook: null,          // details of the active notebook (including sources)
    conversations: [],
    conversationId: null,
    pollTimer: null,
    sending: false,
    citedVersion: null,      // the version highlighted by a citation chip
    me: null,                // {id, email, is_admin} from /users/me
};

// ---------------------------------------------------------------------------
// Display helpers
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
    return d.toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" });
}

function formatRelative(iso) {
    if (!iso) return "";
    // Server times without a zone are UTC
    const d = new Date(/Z|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
    if (isNaN(d)) return "";
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)} d ago`;
    return formatDate(iso);
}

function formatSize(bytes) {
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
    return err.requestId ? `${err.message} (code: ${err.requestId})` : err.message;
}

// ---------------------------------------------------------------------------
// Shared modal (confirm / prompt / info)
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
                     placeholder = "", confirmLabel = "OK", cancelLabel = "Cancel", danger = false }) {
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
// Routing: #/nb/<notebook>  or  #/nb/<notebook>/c/<conversation>
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
    // The last opened notebook (recorded by the server, no localStorage).
    const opened = state.notebooks.filter((n) => n.last_opened_at)
        .sort((a, b) => b.last_opened_at.localeCompare(a.last_opened_at));
    if (opened.length) return opened[0].id;
    if (state.notebooks.length) return state.notebooks[0].id;
    // New user: create one notebook right away so they can start adding sources.
    try {
        const nb = await api("/notebooks", { method: "POST", json: { title: "My notebook" } });
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
            h("span", { class: "notebook-menu-meta", text: `${nb.source_count} source(s)` })),
        ),
    );
}

$("newNotebookBtn").addEventListener("click", async () => {
    closeNotebookMenu();
    const title = await openModal({
        title: "New notebook", subtitle: "One notebook per research topic, for example \"MPV prices 2026\".",
        icon: "edit", kind: "prompt", placeholder: "Notebook title", confirmLabel: "Create notebook",
    });
    if (!title || !title.trim()) return;
    try {
        const nb = await api("/notebooks", { method: "POST", json: { title: title.trim() } });
        state.notebooks.unshift({ ...nb, source_count: 0 });
        go(nb.id);
    } catch (err) { modalAlert("Notebook not created", errorText(err)); }
});

$("renameNotebookBtn").addEventListener("click", async () => {
    closeNotebookMenu();
    if (!state.notebook) return;
    const title = await openModal({
        title: "Rename notebook", icon: "edit", kind: "prompt",
        defaultValue: state.notebook.title, placeholder: "Notebook title", confirmLabel: "Save",
    });
    if (!title || !title.trim()) return;
    try {
        const nb = await api(`/notebooks/${state.notebook.id}`, { method: "PATCH", json: { title: title.trim() } });
        state.notebook.title = nb.title;
        const item = state.notebooks.find((n) => n.id === nb.id);
        if (item) item.title = nb.title;
        renderNotebookSwitcher();
    } catch (err) { modalAlert("Name not saved", errorText(err)); }
});

$("deleteNotebookBtn").addEventListener("click", async () => {
    closeNotebookMenu();
    if (!state.notebook) return;
    const ok = await openModal({
        title: "Delete this notebook?",
        subtitle: "Every conversation in this notebook is deleted too. The documents stay in the Library.",
        icon: "danger", confirmLabel: "Delete notebook", danger: true,
    });
    if (!ok) return;
    try {
        await api(`/notebooks/${state.notebook.id}`, { method: "DELETE" });
        const deletedId = state.notebook.id;
        state.notebook = null;
        state.notebooks = state.notebooks.filter((n) => n.id !== deletedId);
        window.location.hash = "";  // triggers hashchange → handleRoute
    } catch (err) { modalAlert("Notebook not deleted", errorText(err)); }
});

// ---------------------------------------------------------------------------
// Sources
// ---------------------------------------------------------------------------

const STAGE_LABEL = {
    queued: "Waiting in line",
    parsing: "Reading the document",
    vision: "Reading images",
    indexing: "Indexing content",
    extracting: "Extracting data",
    failed: "Processing failed",
    cancelled: "Cancelled",
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
                h("p", { text: "No sources yet. Add documents so Argos can answer from their content." }),
                h("button", { type: "button", class: "btn-inline", text: "Add sources", onclick: openSourceModal })),
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
        meta.push(h("span", { text: `Version ${s.version_no}, ${formatDate(s.uploaded_at)}` }));
        if (s.archived) meta.push(h("span", { class: "source-warn", text: "Archived by the uploader" }));
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
            type: "button", class: "source-remove", title: "Remove from notebook",
            "aria-label": `Remove ${s.display_name} from the notebook`, onclick: () => removeSource(s),
        }, iconX()),
    );

    if (s.update_available) {
        item.append(h("div", { class: "source-update" },
            h("span", { text: `Version ${s.latest_version_no} available` }),
            h("button", { type: "button", class: "btn-inline", text: "Use the latest version", onclick: () => updateSource(s) })));
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
        title: `Remove "${s.display_name}"?`,
        subtitle: processing
            ? "This document is still being processed. If no other notebook uses it, processing stops. The document stays in the Library."
            : "The source is only removed from this notebook. The document stays in the Library.",
        icon: "danger", confirmLabel: "Remove source", danger: true,
    });
    if (!ok) return;
    try {
        state.notebook.sources = await api(`/notebooks/${state.notebook.id}/sources/${s.document_id}`, { method: "DELETE" });
        renderSources();
    } catch (err) { toast(errorText(err), "error"); }
}

function renderScope() {
    const active = activeSources().length;
    el.headerScope.textContent = active ? `Answering from ${active} source(s)` : "";
}

// Poll source status while any are still being processed
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
            if (prev && !FINAL_STAGES.has(prev) && s.stage === "ready") toast(`"${s.display_name}" is ready.`, "success");
            if (prev && !FINAL_STAGES.has(prev) && s.stage === "failed") toast(`"${s.display_name}" failed to process.`, "error");
        }
        renderSources();
    } catch { /* try again on the next round */ }
    schedulePoll();
}

// ---------------------------------------------------------------------------
// "Add sources" modal
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
        modalAlert("Notebook is full", `A notebook holds at most ${state.notebook.max_sources} sources. Remove sources you do not need, then try again.`);
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
    // Similar files left undecided → separate documents (the default, A §6.3).
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
        toast(`${added} similar file(s) saved as separate documents.`, "success");
    }
}

function resolvePendingRequest(pendingId, action) {
    return api(`/notebooks/${state.notebook.id}/sources/pending/${pendingId}/resolve`, {
        method: "POST", json: { action },
    });
}

function sourceModalKeys(e) {
    if (panel.root) return;  // the document manager panel is open on top of it
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
    if (!LIMITS.ext.includes(ext)) return "Unsupported format, use PDF or Markdown";
    if (file.size > LIMITS.fileMb * 1024 * 1024) return `Larger than ${LIMITS.fileMb} MB`;
    if (file.size === 0) return "Empty file";
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
            ? `The notebook only has ${limit} slot(s) left. Remove some files.`
            : `At most ${LIMITS.files} files at a time.`;
    }
    const total = valid.reduce((n, f) => n + f.file.size, 0);
    if (total > LIMITS.batchMb * 1024 * 1024) return `The upload is larger than ${LIMITS.batchMb} MB in total.`;
    return null;
}

const RESULT_TEXT = {
    queued: "Processing in the background",
    existing: "Already in the Library, used right away",
};

function resultRow(r) {
    if (r.status !== "similar") {
        return h("li", { class: `pick-item is-${r.status === "rejected" ? "error" : "ok"}` },
            fileIcon(),
            h("span", { class: "pick-name", text: r.filename }),
            h("span", { class: "pick-status", text: r.status === "rejected" ? r.error_message : (r.doneText || RESULT_TEXT[r.status]) }));
    }
    // Similar to a Library document: the user picks new version or separate document.
    const percent = Math.round((r.similarity || 0) * 100);
    const label = `Choice for ${r.filename}`;
    return h("li", { class: "pick-item is-similar" },
        fileIcon(),
        h("span", { class: "pick-name", text: r.filename }),
        h("span", { class: "pick-status", text: r.busy ? "Saving…" : `${percent}% similar` }),
        h("div", { class: "similar-choice", role: "group", "aria-label": label },
            h("p", { class: "similar-text" },
                r.candidateGone ? r.error_message : ["Its content is similar to ", h("strong", { text: r.similar_document_name }),
                    " in the Library. Save it as a new version of it?"]),
            h("div", { class: "similar-actions" },
                r.candidateGone ? null : h("button", {
                    type: "button", class: "similar-btn similar-btn--accent", disabled: r.busy,
                    onclick: () => resolveSimilar(r, "new_version"),
                }, "Make it a new version"),
                h("button", {
                    type: "button", class: "similar-btn", disabled: r.busy,
                    onclick: () => resolveSimilar(r, "separate"),
                }, "Separate document"))));
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
            doneText: action === "new_version" ? `Saved as a new version of ${name}` : "Saved as a new document",
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
        sm.note.textContent = `${waiting} file(s) resemble existing documents. Choose how to save them; `
            + "if you close this window, they are saved as separate documents.";
    } else {
        sm.note.textContent = added
            ? `${added} source(s) added. You can close this window; processing continues in the background.`
            : "No files were added.";
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
                type: "button", class: "pick-remove", "aria-label": `Remove ${f.file.name} from the list`,
                onclick: () => { sm.files.splice(i, 1); renderSourceModal(); },
            }, iconX())),
    ));
}

function reuseLine(stats) {
    // Only shown when results from the previous version were reused (stage 3).
    if (!stats) return null;
    const parts = [];
    if (stats.chunks_reused) parts.push(`${stats.chunks_reused} of ${stats.chunks} text chunks`);
    if (stats.units_cached) parts.push(`${stats.units_cached} of ${stats.units} AI analysis units`);
    if (stats.images_cached) parts.push(`${stats.images_cached} of ${stats.images} images`);
    if (!parts.length) return null;
    return h("span", { class: "version-reuse", text: `Reused from the previous version: ${parts.join(", ")}` });
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
    sm.libraryList.replaceChildren(h("li", { class: "pick-empty", text: "Loading the Library…" }));
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
            text: sm.search.value.trim() ? "No matching documents." : "The Library is empty. Upload your first document in the New upload tab." }));
        return;
    }
    const inNotebook = new Set(sources().map((s) => s.document_id));
    sm.libraryList.replaceChildren(...sm.library.map((d) => {
        const already = inNotebook.has(d.id);
        const v = d.latest_version;
        const status = !v ? "" : v.stage === "ready" ? `Version ${v.version_no}, ${formatDate(v.uploaded_at)}`
            : FINAL_STAGES.has(v.stage) ? STAGE_LABEL[v.stage] : "Processing";
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
                    text: already ? "Already in this notebook" : [status, d.owner_name && `uploaded by ${d.owner_name}`].filter(Boolean).join(", ") })),
            h("button", {
                type: "button", class: "btn-manage", text: "Manage",
                "aria-label": `Manage ${d.display_name}`, onclick: () => openDocumentManager(d.id),
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
        toast(`${sm.picked.size} source(s) added.`, "success");
        closeSourceModal();
    } catch (err) {
        sm.busy = false;
        sm.note.textContent = errorText(err);
        sm.note.dataset.kind = "error";
        renderSourceModal(true);
    }
}

// ── Footer & buttons ──

function renderSourceModal(keepNote = false) {
    const left = remainingSlots();
    sm.slots.textContent = `${sources().length} of ${state.notebook ? state.notebook.max_sources : 10} sources used`;
    $("dropzoneLimits").textContent =
        `PDF or Markdown, max. ${LIMITS.fileMb} MB per file, ${Math.min(LIMITS.files, Math.max(left, 0))} files at a time`;

    if (!keepNote) { sm.note.textContent = ""; delete sm.note.dataset.kind; }
    sm.cancel.disabled = sm.busy;
    sm.close.disabled = sm.busy;

    if (sm.tab === "upload") {
        renderUploadList();
        if (sm.results) {
            sm.submit.textContent = "Done";
            sm.submit.disabled = false;
            sm.submit.onclick = closeSourceModal;
            sm.cancel.hidden = true;
            return;
        }
        sm.cancel.hidden = false;
        const valid = validUploads().length;
        const problem = uploadProblems();
        if (problem && !keepNote) { sm.note.textContent = problem; sm.note.dataset.kind = "error"; }
        sm.submit.textContent = sm.busy ? "Uploading…" : valid ? `Add ${valid} file(s)` : "Add";
        sm.submit.disabled = sm.busy || !valid || !!problem;
        sm.submit.onclick = submitUpload;
    } else {
        renderLibraryList();
        sm.cancel.hidden = false;
        const n = sm.picked.size;
        const over = n > left;
        if (over && !keepNote) { sm.note.textContent = `The notebook only has ${left} slot(s) left.`; sm.note.dataset.kind = "error"; }
        sm.submit.textContent = sm.busy ? "Adding…" : n ? `Add ${n} document(s)` : "Add";
        sm.submit.disabled = sm.busy || !n || over;
        sm.submit.onclick = submitLibrary;
    }
}

// ---------------------------------------------------------------------------
// Conversations
// ---------------------------------------------------------------------------

function renderConversations() {
    if (!state.conversations.length) {
        el.historyList.replaceChildren(h("div", { class: "history-empty", text: "No conversations in this notebook yet." }));
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
                h("span", { class: "history-item-title", text: c.title || "Untitled" }),
                h("span", { class: "history-item-subtitle", text: formatRelative(c.updated_at) }))),
    ));
}

async function refreshConversations() {
    if (!state.notebook) return;
    try {
        state.conversations = await api(`/notebooks/${state.notebook.id}/conversations`);
        renderConversations();
    } catch { /* the old list stays visible */ }
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
    el.headerTitle.textContent = "Loading…";
    try {
        const detail = await api(`/notebooks/${state.notebook.id}/conversations/${conversationId}`);
        if (state.conversationId !== conversationId) return;
        el.headerTitle.textContent = detail.title || "Untitled";
        const last = detail.messages[detail.messages.length - 1];
        detail.messages.forEach((m) =>
            m.role === "user"
                // Only the last message can be resent (the server rejects the others).
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
    el.headerTitle.textContent = "New chat";
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
        title = "Start by adding sources";
        subtitle = "Upload price lists, brochures or competitor reports. Argos answers only from the documents you choose, with citations.";
        cta = true;
    } else if (!active.length && pending.length) {
        title = "Sources are being processed";
        subtitle = `${pending.length} document(s) being read. You can start asking once they are ready.`;
    } else if (!active.length) {
        title = "No sources checked";
        subtitle = "Check at least one source in the left panel to start asking.";
    } else {
        title = state.notebook.title;
        subtitle = `Ask about prices, features or product weaknesses in the ${active.length} checked source(s).`;
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
        title: "Rename conversation", subtitle: "Give it a short, descriptive name.",
        icon: "edit", kind: "prompt", defaultValue: current ? current.title : "", placeholder: "Conversation name", confirmLabel: "Save",
    });
    if (!title || !title.trim()) return;
    try {
        const conv = await api(`/notebooks/${state.notebook.id}/conversations/${state.conversationId}`, {
            method: "PATCH", json: { title: title.trim() },
        });
        el.headerTitle.textContent = conv.title;
        refreshConversations();
    } catch (err) { modalAlert("Name not saved", errorText(err)); }
});

el.deleteThreadBtn.addEventListener("click", async () => {
    const ok = await openModal({
        title: "Delete conversation?",
        subtitle: "Every message in this conversation will be permanently deleted.",
        icon: "danger", confirmLabel: "Delete", danger: true,
    });
    if (!ok) return;
    try {
        await api(`/notebooks/${state.notebook.id}/conversations/${state.conversationId}`, { method: "DELETE" });
        await refreshConversations();
        go(state.notebook.id);
    } catch (err) { modalAlert("Conversation not deleted", errorText(err)); }
});

document.querySelectorAll(".welcome-suggestion").forEach((btn) =>
    btn.addEventListener("click", () => { el.chatInput.value = btn.dataset.prompt; sendMessage(); }));

// ---------------------------------------------------------------------------
// Messages & citations
// ---------------------------------------------------------------------------

function scrollToBottom() { el.chatBox.scrollTop = el.chatBox.scrollHeight; }

/**
 * A user message. `msg` (optional, from history): {id, status, error_code, conversationId, canRetry}.
 * Returns the wrapper element so it can be marked failed / restored.
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

/** A small button that copies the request ID, to report to the admin. */
function requestIdButton(requestId) {
    return h("button", {
        type: "button",
        class: "btn-copy-id",
        title: "Copy this code when reporting to the admin",
        "aria-label": `Copy error code ${requestId}`,
        onclick: async () => {
            try {
                await navigator.clipboard.writeText(requestId);
                toast("Code copied.");
            } catch {
                toast(`Code: ${requestId}`);
            }
        },
    }, `Code: ${requestId}`);
}

function appendNotice(text, requestId = null) {
    el.chatBox.append(h("div", { class: "chat-notice", role: "alert" },
        iconAlert(), h("span", { text }), requestId ? requestIdButton(requestId) : null));
    scrollToBottom();
}

// Text for failed messages loaded from history (the server only stores the code).
const FAILURE_TEXT = {
    UPSTREAM_UNAVAILABLE: "the AI service or a data source is unavailable.",
    CHAT_TIMEOUT: "the answer took too long.",
    CANCELLED: "the connection dropped before the answer finished.",
    INTERNAL_ERROR: "something went wrong on our side.",
};

function failureText(code, message) {
    if (message) return message;
    return `Failed: ${FAILURE_TEXT[code] || "this message has no answer yet."}`;
}

/** Mark a user message as failed (DESIGN_GROUP_C.md §4): dimmed + reason + [Resend]. */
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
        }, "Resend"));
    }
    if (requestId) actions.append(requestIdButton(requestId));
    if (actions.childElementCount) row.append(actions);
    wrapper.querySelector(".bubble-group").append(row);
}

function clearFailed(wrapper) {
    wrapper.classList.remove("is-failed");
    wrapper.querySelector(".msg-failure")?.remove();
}

/** A new message makes the earlier failed one no longer "last" → it cannot be resent. */
function clearRetryButtons() {
    el.chatBox.querySelectorAll(".btn-retry").forEach((b) => b.remove());
}

/**
 * A bot answer. `info` (optional) = chat response metadata or a message from history:
 * {degraded, issues} (DESIGN_GROUP_C.md §3).
 */
const SAFE_MARKDOWN = { USE_PROFILES: { html: true }, FORBID_TAGS: ["style", "form", "input", "button", "img"], FORBID_ATTR: ["style"] };

function appendBotMessage(text, citations, pending = [], info = {}) {
    const byLabel = new Map(citations.map((c) => [c.label, c]));
    const bubble = h("div", { class: "message bot" });
    // The answer comes from an LLM that reads uploaded documents, so it is untrusted: the
    // Markdown → HTML result is sanitized (no scripts, event handlers, iframes, forms…).
    // Without both libraries the answer is shown as plain text, never as raw HTML.
    if (window.marked && window.DOMPurify) {
        bubble.innerHTML = DOMPurify.sanitize(marked.parse(text || ""), SAFE_MARKDOWN);
    } else {
        bubble.textContent = text;
    }
    linkCitations(bubble, byLabel);

    const group = h("div", { class: "bubble-group" });
    if (info.degraded) group.append(degradedBanner(info.issues || []));
    group.append(bubble);

    if (citations.length) {
        group.append(h("ol", { class: "cite-list", "aria-label": "Answer sources" },
            ...citations.map((c) => h("li", { class: "cite-list-item", dataset: { label: c.label } },
                h("span", { class: "cite-num", text: c.label }),
                h("span", { class: "cite-list-text", text: citationLine(c) })))));
    }
    if (pending.length) {
        group.append(h("p", { class: "answer-note",
            text: `Not used yet because they are still being processed: ${pending.join(", ")}.` }));
    }

    const tts = h("button", { type: "button", class: "btn-action-icon btn-tts", title: "Listen", "aria-label": "Listen to the answer" });
    tts.innerHTML = iconSpeaker();
    tts.addEventListener("click", () => speakMessage(bubble.innerText, tts));
    group.append(h("div", { class: "bubble-actions" }, tts));

    el.chatBox.append(
        h("div", { class: "message-wrapper bot-wrapper" },
            h("div", { class: "msg-avatar bot-avatar", text: "Ar", "aria-hidden": "true" }),
            group));
    scrollToBottom();
}

// ── Degraded answers & the "Show AI process" panel ────────────────────────

const COMPONENT_LABEL = {
    router: "source selection",
    sql: "structured data (SQL)",
    vector: "document search",
};

function degradedBanner(issues) {
    const failed = [...new Set(issues.map((i) => i.component))].filter((c) => c !== "router");
    const parts = [];
    if (failed.length) {
        parts.push(`Some sources failed to load: ${failed.map((c) => COMPONENT_LABEL[c] || c).join(", ")}. `
            + "This answer may be incomplete. Try asking again in a moment.");
    }
    if (issues.some((i) => i.component === "router")) {
        parts.push("Source selection failed, so every source was read.");
    }
    return h("div", { class: "degraded-banner", role: "note" }, iconAlert(), h("span", { text: parts.join(" ") }));
}

function citationLine(c) {
    const parts = [c.display_name, `version ${c.version_no}`, `uploaded ${formatDate(c.uploaded_at)}`];
    if (c.page_number) parts.push(`p. ${c.page_number}`);
    return parts.join(", ");
}

/** Replace "[n]" in the answer with chips that can be hovered/focused. */
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
                "aria-label": `Source ${num}: ${citationLine(c)}`,
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
            h("span", { class: "cite-pop-meta", text: `Version ${c.version_no}, uploaded ${formatDate(c.uploaded_at)}` }),
            (c.page_number || c.section_heading) && h("span", { class: "cite-pop-where",
                text: [c.page_number && `Page ${c.page_number}`, c.section_heading].filter(Boolean).join(", ") })),
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

    // The same source lights up in the left panel too (kept when the panel re-renders).
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
// Send a message
// ---------------------------------------------------------------------------

async function sendMessage() {
    const question = el.chatInput.value.trim();
    if (!question || state.sending || !state.notebook) return;

    if (!activeSources().length) {
        renderWelcome();
        toast(pendingSources().length
            ? "Sources are still being processed. Wait until they are ready."
            : "Check at least one ready source.", "error");
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
        // The message is stored as `failed` on the server → even a new conversation already has an ID.
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

/** After the first message: use the server's conversation ID, update the URL & title. */
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

/** The server writes the auto-title in the background; fetch it again shortly after. */
function refreshTitleSoon() {
    refreshConversations();
    setTimeout(async () => {
        await refreshConversations();
        const conv = state.conversations.find((c) => c.id === state.conversationId);
        if (conv) el.headerTitle.textContent = conv.title;
    }, 2000);
}

/** Resend a failed message: the server reuses the same message row (no duplicate question). */
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
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ text: text.slice(0, 4000), voice: "alloy", format: "mp3", speed: 1.0 }),
        });
        if (response.status === 401) return toLogin();
        if (response.status === 429) {
            const data = await response.json().catch(() => null);
            resetTts(btn);
            currentTtsBtn = null;
            toast((data && data.error && data.error.message) || "Too many requests.", "error");
            return;
        }
        if (!response.ok) throw new Error("tts");
        const url = URL.createObjectURL(await response.blob());
        currentAudio = new Audio(url);
        await currentAudio.play();
        currentAudio.onended = () => { resetTts(btn); URL.revokeObjectURL(url); currentAudio = null; currentTtsBtn = null; };
    } catch {
        resetTts(btn);
        currentTtsBtn = null;
        toast("The audio cannot be played right now.", "error");
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
        el.chatInput.placeholder = "Listening… click the microphone to finish";
    } catch {
        modalAlert("Microphone access denied", "Allow microphone access in your browser settings to record your voice.");
    }
});

async function transcribe(blob) {
    el.micBtn.disabled = true;
    el.micBtn.classList.add("loading");
    el.chatInput.placeholder = "Processing audio…";
    const form = new FormData();
    form.append("audio", blob, "recording.webm");
    try {
        const result = await api("/voice/stt?with_timestamps=false", { method: "POST", form });
        if (result && result.text) { el.chatInput.value = result.text; el.chatInput.focus(); }
    } catch (err) {
        toast(errorText(err), "error");
    } finally {
        el.micBtn.disabled = false;
        el.micBtn.classList.remove("loading");
        el.chatInput.placeholder = "Ask something about your sources…";
    }
}

// ---------------------------------------------------------------------------
// Icons
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

function toggleSidebar() {
    $("sidebar").classList.toggle("open");
    $("sidebarOverlay").classList.toggle("active");
}
for (const id of ["sidebarOverlay", "btnCloseSidebar", "btnMenuToggle"]) {
    $(id)?.addEventListener("click", toggleSidebar);
}

function closeSidebarOnMobile() {
    if (window.matchMedia("(max-width: 768px)").matches && $("sidebar").classList.contains("open")) toggleSidebar();
}

// ---------------------------------------------------------------------------
// Generic panel modal (manage documents, manage users)
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
            h("button", { type: "button", class: "btn-modal-close", "aria-label": "Close", onclick: closePanel }, iconX())),
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
    if (!modal.root.hidden) return;  // a confirm dialog is open on top of the panel
    if (e.key === "Escape") { e.preventDefault(); closePanel(); }
    else if (e.key === "Tab") trapFocus(e, panel.root);
}

// ── Manage documents: version history, new version, delete ──

async function openDocumentManager(documentId) {
    let changed = false;
    const { body, setSubtitle } = openPanel({
        title: "Manage document",
        onClose: () => {
            if (!changed) return;
            if (!sm.root.hidden) loadLibrary();
            refreshNotebook();
        },
    });
    const markChanged = () => { changed = true; };

    async function render() {
        body.replaceChildren(h("p", { class: "pick-empty", text: "Loading…" }));
        let doc;
        try {
            doc = await api(`/library/documents/${documentId}`);
        } catch (err) {
            body.replaceChildren(h("p", { class: "pick-empty", text: errorText(err) }));
            return;
        }
        const isOwner = state.me && (doc.owner_id === state.me.id);
        setSubtitle(`${doc.display_name}, owner ${isOwner ? "you" : (doc.owner_name || "another user")}`);

        const versionRows = doc.versions.map((v) => {
            const status = v.stage === "ready" ? "Ready"
                : FINAL_STAGES.has(v.stage) ? (v.error || STAGE_LABEL[v.stage]) : stageText(v);
            const latest = doc.latest_version && doc.latest_version.id === v.id;
            return h("li", { class: "version-row" },
                h("span", { class: "version-no", text: `v${v.version_no}` }),
                h("span", { class: "version-body" },
                    h("span", { class: "version-title" },
                        v.original_filename,
                        latest ? h("span", { class: "version-badge", text: "Latest" }) : null),
                    h("span", { class: "version-meta",
                        text: `${formatDate(v.uploaded_at)}, ${v.page_count ? `${v.page_count} pages, ` : ""}${status}` }),
                    reuseLine(v.reuse_stats)),
                isOwner && doc.versions.length > 1
                    ? h("button", {
                        type: "button", class: "source-remove version-delete", title: `Delete version ${v.version_no}`,
                        "aria-label": `Delete version ${v.version_no}`, onclick: () => deleteVersion(doc, v),
                    }, iconX())
                    : null);
        });

        const fileInput = h("input", { type: "file", accept: ".pdf,.md", class: "visually-hidden",
            onchange: (e) => uploadVersion(doc, e.target.files[0]) });

        body.replaceChildren(
            h("h3", { class: "panel-heading", text: "Version history" }),
            h("ol", { class: "version-list" }, ...versionRows),
            h("div", { class: "panel-actions" },
                h("label", { class: "modal-btn modal-btn--ghost btn-file" }, fileInput, "Upload a new version"),
                isOwner ? h("button", { type: "button", class: "modal-btn modal-btn--danger",
                    text: "Delete document", onclick: () => deleteDocument(doc) }) : null),
            h("p", { class: "panel-note", text: isOwner
                ? "A version still used by a notebook cannot be deleted. Deleting a document another user's notebook still uses archives it."
                : "Anyone on the team can upload a new version. Only the uploader can delete it." }),
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
            toast(r.status === "existing" ? "This file already exists as one of the versions." : "The new version is being processed.", "success");
            render();
        } catch (err) { toast(errorText(err), "error"); }
    }

    async function deleteVersion(doc, v) {
        const ok = await openModal({
            title: `Delete version ${v.version_no}?`,
            subtitle: "This version's data is permanently deleted. Its version number will not be reused.",
            icon: "danger", confirmLabel: "Delete version", danger: true,
        });
        if (!ok) return;
        try {
            await api(`/library/documents/${doc.id}/versions/${v.id}`, { method: "DELETE" });
            markChanged();
            toast(`Version ${v.version_no} deleted.`, "success");
            render();
        } catch (err) { modalAlert("Version not deleted", errorText(err)); }
    }

    async function deleteDocument(doc) {
        const ok = await openModal({
            title: `Delete "${doc.display_name}"?`,
            subtitle: "The document is removed from your notebooks. If another user's notebook still uses it, it is archived and only deleted once nobody uses it.",
            icon: "danger", confirmLabel: "Delete document", danger: true,
        });
        if (!ok) return;
        try {
            const r = await api(`/library/documents/${doc.id}`, { method: "DELETE" });
            markChanged();
            toast(r.result === "archived" ? "The document was archived because another notebook still uses it." : "Document deleted.", "success");
            closePanel();
        } catch (err) { modalAlert("Document not deleted", errorText(err)); }
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
    } catch { /* keep showing the old data */ }
}

// ── Manage users (admin) ──

async function openUserManager() {
    const { body } = openPanel({ title: "Manage users", subtitle: "Inactive users cannot sign in. Their documents are transferred to you." });

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
                        text: `${u.email}${u.is_admin ? ", admin" : ""}${u.last_login_at ? `, last sign-in ${formatRelative(u.last_login_at)}` : ""}` })),
                u.is_admin ? h("span", { class: "user-row-state", text: "Active" })
                    : h("label", { class: "switch", for: id },
                        h("input", { type: "checkbox", id, role: "switch", checked: u.is_active,
                            "aria-label": `${u.is_active ? "Deactivate" : "Activate"} ${u.email}`,
                            onchange: (e) => setActive(u, e.target.checked, e.target) }),
                        h("span", { class: "switch-track", "aria-hidden": "true" }),
                        h("span", { class: "user-row-state", text: u.is_active ? "Active" : "Inactive" })));
        })));
    }

    async function setActive(u, active, input) {
        if (!active) {
            const ok = await openModal({
                title: `Deactivate ${u.name || u.email}?`,
                subtitle: "The user can no longer sign in. Their documents are transferred to you; their notebooks are kept.",
                icon: "danger", confirmLabel: "Deactivate", danger: true,
            });
            if (!ok) { input.checked = true; return; }
        }
        try {
            const r = await api(`/admin/users/${u.id}`, { method: "PATCH", json: { is_active: active } });
            toast(active ? "User reactivated."
                : `User deactivated; ${r.documents_transferred} document(s) transferred to you.`, "success");
        } catch (err) { toast(errorText(err), "error"); }
        render();
    }

    body.replaceChildren(h("p", { class: "pick-empty", text: "Loading…" }));
    render();
}

$("manageUsersBtn").addEventListener("click", () => { $("userMenu").hidden = true; openUserManager(); });

async function loadMe() {
    try {
        state.me = await api("/users/me");
        $("manageUsersBtn").hidden = !state.me.is_admin;
        renderUserProfile(state.me);
    } catch { /* the admin menu stays hidden */ }
}

/** Name & photo in the sidebar, from /users/me (not from the token). */
function renderUserProfile(me) {
    const fullName = me.name || "";
    const firstName = me.given_name || fullName.split(" ")[0] || "User";
    $("userName").textContent = firstName;
    $("userMenuName").textContent = fullName || firstName;
    $("userMenuEmail").textContent = me.email || "";

    const avatarEl = $("userAvatar");
    const fallbackEl = $("userAvatarFallback");
    fallbackEl.textContent = (fullName || me.email || "U").trim().charAt(0).toUpperCase() || "U";
    avatarEl.querySelector("img")?.remove();
    if (me.picture) {
        const img = h("img", { src: me.picture, alt: fullName || "Profile", referrerpolicy: "no-referrer" });
        img.onload = () => { fallbackEl.style.display = "none"; };
        img.onerror = () => { img.remove(); fallbackEl.style.display = "flex"; };
        avatarEl.prepend(img);
    } else {
        fallbackEl.style.display = "flex";
    }
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

loadMe();
handleRoute();
