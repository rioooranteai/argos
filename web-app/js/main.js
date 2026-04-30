const API_BASE_URL = "/api/v1";

// ---------------------------------------------------------------------------
// Authentication
// ---------------------------------------------------------------------------

const params = new URLSearchParams(window.location.search);
const tokenFromUrl = params.get("token");
if (tokenFromUrl) {
    localStorage.setItem("access_token", tokenFromUrl);
    // Strip the query but keep any existing hash route.
    window.history.replaceState({}, document.title, "/" + (window.location.hash || ""));
}

function getToken()    { return localStorage.getItem("access_token"); }
function isLoggedIn()  { return !!getToken(); }

if (!isLoggedIn()) {
    window.location.href = "/login";
}

function authHeaders(extraHeaders = {}) {
    return { "Authorization": `Bearer ${getToken()}`, ...extraHeaders };
}

async function handleResponse(response) {
    if (response.status === 401) {
        localStorage.removeItem("access_token");
        window.location.href = "/login";
        return null;
    }
    return response;
}

// ---------------------------------------------------------------------------
// DOM References
// ---------------------------------------------------------------------------

const fileInput        = document.getElementById("fileInput");
const fileListDiv      = document.getElementById("file-list");
const uploadBtn        = document.getElementById("uploadBtn");
const uploadStatus     = document.getElementById("upload-status");
const chatInput        = document.getElementById("chatInput");
const chatBox          = document.getElementById("chatBox");
const sendBtn          = document.getElementById("sendBtn");
const chatLoading      = document.getElementById("chatLoading");
const micBtn           = document.getElementById("micBtn");
const newChatBtn       = document.getElementById("newChatBtn");
const historyList      = document.getElementById("historyList");
const historyCount     = document.getElementById("historyCount");
const historyEmpty     = document.getElementById("historyEmpty");
const welcomeScreen    = document.getElementById("welcomeScreen");
const chatHeaderTitle  = document.getElementById("chatHeaderTitle");
const renameThreadBtn  = document.getElementById("renameThreadBtn");
const deleteThreadBtn  = document.getElementById("deleteThreadBtn");

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let currentConversationId = null;
let conversationCache     = []; // cached list of conversations from /conversations

// ---------------------------------------------------------------------------
// Modal helper (login-card style) — replaces native alert/confirm/prompt
// ---------------------------------------------------------------------------

const MODAL_ICONS = {
    edit: '<svg fill="none" height="22" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24" width="22"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
    danger: '<svg fill="none" height="22" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24" width="22"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>',
    info: '<svg fill="none" height="22" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24" width="22"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8"  y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>',
};

const modalEl        = document.getElementById("appModal");
const modalIconEl    = document.getElementById("modalIcon");
const modalTitleEl   = document.getElementById("modalTitle");
const modalSubEl     = document.getElementById("modalSubtitle");
const modalInputEl   = document.getElementById("modalInput");
const modalCancelBtn = document.getElementById("modalCancelBtn");
const modalConfirmBtn= document.getElementById("modalConfirmBtn");

let _modalResolver = null;

function _closeModal(value) {
    modalEl.hidden = true;
    modalEl.classList.remove("is-danger");
    document.removeEventListener("keydown", _modalKeyHandler);
    if (_modalResolver) {
        const r = _modalResolver;
        _modalResolver = null;
        r(value);
    }
}

function _modalKeyHandler(e) {
    if (e.key === "Escape") {
        e.preventDefault();
        _closeModal(null);
    } else if (e.key === "Enter") {
        // Enter confirms (only when input not multiline / when focus is in input or on confirm)
        if (!modalInputEl.hidden && document.activeElement === modalInputEl) {
            e.preventDefault();
            modalConfirmBtn.click();
        }
    }
}

modalCancelBtn.addEventListener("click", () => _closeModal(null));
modalEl.addEventListener("click", (e) => {
    if (e.target === modalEl) _closeModal(null);  // backdrop click
});

/**
 * Open modal as a Promise.
 * @param {object} opts
 * @param {string} opts.title
 * @param {string} [opts.subtitle]
 * @param {"edit"|"danger"|"info"} [opts.icon]
 * @param {"prompt"|"confirm"|"alert"} [opts.kind]
 * @param {string} [opts.defaultValue]   for prompt
 * @param {string} [opts.placeholder]    for prompt
 * @param {string} [opts.confirmLabel]
 * @param {string} [opts.cancelLabel]
 * @param {boolean} [opts.danger]        styles confirm button as danger
 * @returns {Promise<string|boolean|null>}  prompt → string|null, confirm → bool, alert → true
 */
function openModal(opts) {
    const {
        title,
        subtitle = "",
        icon = "info",
        kind = "confirm",
        defaultValue = "",
        placeholder = "",
        confirmLabel = "OK",
        cancelLabel = "Batal",
        danger = false,
    } = opts;

    modalIconEl.innerHTML  = MODAL_ICONS[icon] || MODAL_ICONS.info;
    modalTitleEl.textContent = title;
    modalSubEl.textContent   = subtitle;
    modalSubEl.style.display = subtitle ? "" : "none";

    if (kind === "prompt") {
        modalInputEl.hidden = false;
        modalInputEl.value = defaultValue;
        modalInputEl.placeholder = placeholder;
    } else {
        modalInputEl.hidden = true;
    }

    modalConfirmBtn.textContent = confirmLabel;
    modalCancelBtn.textContent  = cancelLabel;

    // Hide cancel for plain alert
    modalCancelBtn.style.display = (kind === "alert") ? "none" : "";

    // Danger styling on confirm button
    modalConfirmBtn.classList.toggle("modal-btn--danger", !!danger);
    modalConfirmBtn.classList.toggle("modal-btn--primary", !danger);

    modalEl.hidden = false;

    // Focus management
    setTimeout(() => {
        if (kind === "prompt") {
            modalInputEl.focus();
            modalInputEl.select();
        } else {
            modalConfirmBtn.focus();
        }
    }, 30);

    document.addEventListener("keydown", _modalKeyHandler);

    return new Promise((resolve) => {
        _modalResolver = resolve;
        modalConfirmBtn.onclick = () => {
            if (kind === "prompt") {
                _closeModal(modalInputEl.value);
            } else if (kind === "confirm") {
                _closeModal(true);
            } else {
                _closeModal(true);
            }
        };
    });
}

function modalAlert(title, subtitle = "") {
    return openModal({ title, subtitle, kind: "alert", icon: "info", confirmLabel: "OK" });
}

// ---------------------------------------------------------------------------
// File Upload (unchanged)
// ---------------------------------------------------------------------------

fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
        const names = Array.from(fileInput.files).map(f => f.name).join(", ");
        fileListDiv.textContent = names;
        uploadBtn.style.display = "block";
        uploadStatus.textContent = "";
    } else {
        fileListDiv.textContent = "";
        uploadBtn.style.display = "none";
    }
});

async function uploadFiles() {
    if (fileInput.files.length === 0) return;

    const formData = new FormData();
    for (let i = 0; i < fileInput.files.length; i++) {
        formData.append("files", fileInput.files[i]);
    }

    uploadBtn.disabled = true;
    uploadBtn.textContent = "Memproses...";
    uploadStatus.textContent = "Ekstraksi AI berjalan...";

    try {
        const raw = await fetch(`${API_BASE_URL}/document/upload`, {
            method: "POST",
            headers: authHeaders(),
            body: formData
        });

        const response = await handleResponse(raw);
        if (!response) return;

        const result = await response.json();

        if (response.ok) {
            uploadStatus.textContent = "Sukses! Data siap ditanyakan.";
            uploadStatus.style.color = "var(--green)";
            fileInput.value = "";
            fileListDiv.textContent = "";
            uploadBtn.style.display = "none";
        } else {
            uploadStatus.textContent = `Gagal: ${result.detail || "Error server"}`;
            uploadStatus.style.color = "var(--red)";
        }
    } catch (error) {
        uploadStatus.textContent = `Koneksi terputus: ${error.message}`;
        uploadStatus.style.color = "var(--red)";
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.textContent = "Ekstrak ke DB";
    }
}

uploadBtn.addEventListener("click", uploadFiles);

// ---------------------------------------------------------------------------
// Chat rendering
// ---------------------------------------------------------------------------

function appendMessage(sender, text) {
    const wrapper = document.createElement("div");
    wrapper.classList.add("message-wrapper", `${sender}-wrapper`);

    const avatar = document.createElement("div");
    avatar.classList.add("msg-avatar", sender === "bot" ? "bot-avatar" : "user-avatar");
    avatar.textContent = sender === "bot" ? "Ar" : "U";

    const group = document.createElement("div");
    group.classList.add("bubble-group");

    const bubble = document.createElement("div");
    bubble.classList.add("message", sender);
    if (sender === "bot") bubble.innerHTML = marked.parse(text || "");
    else bubble.textContent = text;

    const actions = document.createElement("div");
    actions.classList.add("bubble-actions");

    if (sender === "bot") {
        const ttsBtn = document.createElement("button");
        ttsBtn.className = "btn-action-icon btn-tts";
        ttsBtn.title = "Dengarkan";
        ttsBtn.innerHTML = iconSpeaker();
        ttsBtn.addEventListener("click", () => speakMessage(text, ttsBtn));
        actions.appendChild(ttsBtn);
    }

    group.appendChild(bubble);
    group.appendChild(actions);
    wrapper.appendChild(avatar);
    wrapper.appendChild(group);
    chatBox.appendChild(wrapper);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function clearChatView() {
    chatBox.innerHTML = "";
}

function showWelcome() {
    welcomeScreen.style.display = "flex";
    chatBox.style.display = "none";
    chatHeaderTitle.textContent = "AI Chat Helper";
    renameThreadBtn.style.display = "none";
    deleteThreadBtn.style.display = "none";
}

function showChat() {
    welcomeScreen.style.display = "none";
    chatBox.style.display = "block";
    renameThreadBtn.style.display = "inline-flex";
    deleteThreadBtn.style.display = "inline-flex";
}

// ---------------------------------------------------------------------------
// Conversation API
// ---------------------------------------------------------------------------

async function fetchConversations() {
    try {
        const raw = await fetch(`${API_BASE_URL}/chat/conversations`, {
            method: "GET",
            headers: authHeaders()
        });
        const response = await handleResponse(raw);
        if (!response || !response.ok) return [];
        return await response.json();
    } catch (e) {
        console.error("Failed to fetch conversations:", e);
        return [];
    }
}

async function fetchConversationDetail(conversationId) {
    try {
        const raw = await fetch(
            `${API_BASE_URL}/chat/conversations/${conversationId}`,
            { method: "GET", headers: authHeaders() }
        );
        const response = await handleResponse(raw);
        if (!response) return null;
        if (response.status === 404) return null;
        if (!response.ok) return null;
        return await response.json();
    } catch (e) {
        console.error("Failed to fetch conversation:", e);
        return null;
    }
}

async function renameConversation(conversationId, newTitle) {
    try {
        const raw = await fetch(
            `${API_BASE_URL}/chat/conversations/${conversationId}`,
            {
                method: "PATCH",
                headers: authHeaders({ "Content-Type": "application/json" }),
                body: JSON.stringify({ title: newTitle })
            }
        );
        const response = await handleResponse(raw);
        return response && response.ok;
    } catch (e) {
        console.error("Rename failed:", e);
        return false;
    }
}

async function deleteConversation(conversationId) {
    try {
        const raw = await fetch(
            `${API_BASE_URL}/chat/conversations/${conversationId}`,
            { method: "DELETE", headers: authHeaders() }
        );
        const response = await handleResponse(raw);
        return response && (response.ok || response.status === 204);
    } catch (e) {
        console.error("Delete failed:", e);
        return false;
    }
}

// ---------------------------------------------------------------------------
// Sidebar thread list
// ---------------------------------------------------------------------------

async function refreshThreadList() {
    conversationCache = await fetchConversations();
    renderThreadList();
}

function renderThreadList() {
    historyList.innerHTML = "";
    historyCount.textContent = String(conversationCache.length);

    if (conversationCache.length === 0) {
        const empty = document.createElement("div");
        empty.classList.add("history-empty");
        empty.textContent = "Belum ada percakapan.";
        historyList.appendChild(empty);
        return;
    }

    conversationCache.forEach(conv => {
        const item = document.createElement("div");
        item.classList.add("history-item");
        if (conv.id === currentConversationId) item.classList.add("active");
        item.dataset.conversationId = conv.id;

        const content = document.createElement("div");
        content.classList.add("history-item-content");

        const title = document.createElement("div");
        title.classList.add("history-item-title");
        title.textContent = conv.title || "Untitled";

        const sub = document.createElement("div");
        sub.classList.add("history-item-subtitle");
        sub.textContent = formatRelative(conv.updated_at);

        content.appendChild(title);
        content.appendChild(sub);
        item.appendChild(content);

        item.addEventListener("click", () => {
            navigateToConversation(conv.id);
        });

        historyList.appendChild(item);
    });
}

function formatRelative(isoTs) {
    if (!isoTs) return "";
    const d = new Date(isoTs);
    if (isNaN(d.getTime())) return "";
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60)        return "baru saja";
    if (diff < 3600)      return `${Math.floor(diff / 60)} menit lalu`;
    if (diff < 86400)     return `${Math.floor(diff / 3600)} jam lalu`;
    if (diff < 604800)    return `${Math.floor(diff / 86400)} hari lalu`;
    return d.toLocaleDateString("id-ID");
}

// ---------------------------------------------------------------------------
// Routing (hash-based)
// ---------------------------------------------------------------------------

function parseHashRoute() {
    const h = window.location.hash || "";
    const m = h.match(/^#\/chat\/([a-zA-Z0-9-]+)$/);
    return m ? m[1] : null;
}

function navigateToConversation(conversationId) {
    if (conversationId === currentConversationId) return;
    window.location.hash = `#/chat/${conversationId}`;
}

function navigateToNewChat() {
    if (window.location.hash) {
        window.location.hash = "";
    } else {
        // Already at root — re-render the welcome state explicitly.
        currentConversationId = null;
        clearChatView();
        showWelcome();
        renderThreadList();
    }
}

async function handleRouteChange() {
    const target = parseHashRoute();

    if (!target) {
        currentConversationId = null;
        clearChatView();
        showWelcome();
        renderThreadList();
        return;
    }

    // Load thread.
    currentConversationId = target;
    clearChatView();
    showChat();
    chatHeaderTitle.textContent = "Memuat...";

    const detail = await fetchConversationDetail(target);
    if (!detail) {
        // Either 404 or fetch error — fall back to welcome.
        currentConversationId = null;
        window.location.hash = "";
        return;
    }

    chatHeaderTitle.textContent = detail.title || "Untitled";
    detail.messages.forEach(m => {
        appendMessage(m.role === "user" ? "user" : "bot", m.content);
    });
    renderThreadList();
}

window.addEventListener("hashchange", handleRouteChange);

// ---------------------------------------------------------------------------
// Send message
// ---------------------------------------------------------------------------

async function sendMessage() {
    const question = chatInput.value.trim();
    if (!question) return;

    // Switch to chat view if we're on the welcome screen.
    if (welcomeScreen.style.display !== "none") {
        showChat();
    }

    appendMessage("user", question);
    chatInput.value = "";

    chatInput.disabled = true;
    sendBtn.disabled = true;
    chatLoading.style.display = "block";

    try {
        const body = { question };
        if (currentConversationId) body.conversation_id = currentConversationId;

        const raw = await fetch(`${API_BASE_URL}/chat/`, {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body)
        });

        const response = await handleResponse(raw);
        if (!response) return;

        const result = await response.json();

        if (response.ok) {
            appendMessage("bot", result.answer);

            // If this was a new conversation, persist its ID + update URL.
            if (result.conversation_id && !currentConversationId) {
                currentConversationId = result.conversation_id;
                // replaceState avoids triggering hashchange (we already loaded).
                window.history.replaceState(
                    {}, document.title,
                    `/#/chat/${currentConversationId}`
                );
                // Refresh sidebar so the new thread appears.
                // Slight delay lets the auto-title task on the server run; we
                // poll once after 1.5s to pick up the LLM-generated title.
                refreshThreadList();
                setTimeout(refreshThreadList, 1500);
            } else {
                // Existing conversation: refresh list so updated_at re-orders.
                refreshThreadList();
            }
        } else {
            appendMessage("bot", `Maaf, terjadi kesalahan: ${result.detail || "Ditolak sistem."}`);
        }
    } catch (error) {
        appendMessage("bot", "Koneksi gagal. Pastikan server aktif.");
    } finally {
        chatInput.disabled = false;
        sendBtn.disabled = false;
        chatLoading.style.display = "none";
        chatInput.focus();
    }
}

sendBtn.addEventListener("click", sendMessage);
chatInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter" && !e.shiftKey) sendMessage();
});

// ---------------------------------------------------------------------------
// New chat / rename / delete
// ---------------------------------------------------------------------------

newChatBtn.addEventListener("click", navigateToNewChat);

renameThreadBtn.addEventListener("click", async () => {
    if (!currentConversationId) return;
    const current = conversationCache.find(c => c.id === currentConversationId);
    const proposed = await openModal({
        title: "Ganti nama percakapan",
        subtitle: "Beri nama yang singkat dan deskriptif.",
        icon: "edit",
        kind: "prompt",
        defaultValue: current?.title || "",
        placeholder: "Nama percakapan",
        confirmLabel: "Simpan",
        cancelLabel: "Batal",
    });
    if (proposed === null) return;
    const trimmed = proposed.trim();
    if (!trimmed) return;
    const ok = await renameConversation(currentConversationId, trimmed);
    if (ok) {
        chatHeaderTitle.textContent = trimmed;
        await refreshThreadList();
    } else {
        await modalAlert("Gagal mengganti nama", "Silakan coba lagi sebentar lagi.");
    }
});

deleteThreadBtn.addEventListener("click", async () => {
    if (!currentConversationId) return;
    const confirmed = await openModal({
        title: "Hapus percakapan?",
        subtitle: "Tindakan ini tidak bisa dibatalkan. Semua pesan dalam percakapan ini akan dihapus permanen.",
        icon: "danger",
        kind: "confirm",
        confirmLabel: "Hapus",
        cancelLabel: "Batal",
        danger: true,
    });
    if (!confirmed) return;
    const ok = await deleteConversation(currentConversationId);
    if (ok) {
        currentConversationId = null;
        await refreshThreadList();
        navigateToNewChat();
    } else {
        await modalAlert("Gagal menghapus", "Percakapan tidak bisa dihapus saat ini. Coba lagi.");
    }
});

// ---------------------------------------------------------------------------
// Welcome suggestions
// ---------------------------------------------------------------------------

document.querySelectorAll(".welcome-suggestion").forEach(btn => {
    btn.addEventListener("click", () => {
        const prompt = btn.dataset.prompt;
        if (!prompt) return;
        chatInput.value = prompt;
        sendMessage();
    });
});

// ---------------------------------------------------------------------------
// Text-to-Speech
// ---------------------------------------------------------------------------

let currentAudio  = null;
let currentTtsBtn = null;

async function speakMessage(text, btnEl) {
    if (currentTtsBtn === btnEl && currentAudio && !currentAudio.paused) {
        currentAudio.pause();
        _resetTtsBtn(btnEl);
        currentTtsBtn = null;
        return;
    }

    if (currentAudio) {
        currentAudio.pause();
        _resetTtsBtn(currentTtsBtn);
    }

    currentTtsBtn = btnEl;
    btnEl.classList.add("playing");
    btnEl.innerHTML = iconPause();

    try {
        const raw = await fetch(`${API_BASE_URL}/voice/tts`, {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({ text, voice: "alloy", format: "mp3", speed: 1.0 })
        });

        const response = await handleResponse(raw);
        if (!response) return;
        if (!response.ok) throw new Error("Server error");

        const blob = await response.blob();
        const url  = URL.createObjectURL(blob);

        currentAudio = new Audio(url);
        await currentAudio.play();

        currentAudio.onended = () => {
            _resetTtsBtn(btnEl);
            URL.revokeObjectURL(url);
            currentAudio  = null;
            currentTtsBtn = null;
        };
    } catch (err) {
        console.error("TTS error:", err);
        _resetTtsBtn(btnEl);
        currentTtsBtn = null;
    }
}

function _resetTtsBtn(btn) {
    if (!btn) return;
    btn.classList.remove("playing");
    btn.innerHTML = iconSpeaker();
}

// ---------------------------------------------------------------------------
// Speech-to-Text
// ---------------------------------------------------------------------------

let mediaRecorder = null;
let audioChunks   = [];
let isRecording   = false;

micBtn.addEventListener("click", async () => {
    if (isRecording) {
        mediaRecorder.stop();
        return;
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunks  = [];
        mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });

        mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) audioChunks.push(e.data);
        };

        mediaRecorder.onstop = async () => {
            isRecording = false;
            micBtn.classList.remove("recording");
            stream.getTracks().forEach(t => t.stop());

            const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
            await transcribeAudioServer(audioBlob);
        };

        mediaRecorder.start();
        isRecording = true;
        micBtn.classList.add("recording");
        chatInput.placeholder = "Mendengarkan... (Klik mic untuk selesai)";
    } catch (err) {
        modalAlert("Akses mikrofon ditolak", "Izinkan akses mikrofon di pengaturan browser untuk merekam suara.");
    }
});

async function transcribeAudioServer(audioBlob) {
    micBtn.disabled = true;
    micBtn.classList.add("loading");
    chatInput.placeholder = "Memproses suara...";

    const formData = new FormData();
    formData.append("audio", audioBlob, "recording.webm");

    try {
        const raw = await fetch(`${API_BASE_URL}/voice/stt?language=id&with_timestamps=false`, {
            method: "POST",
            headers: authHeaders(),
            body: formData
        });

        const response = await handleResponse(raw);
        if (!response) return;

        const result = await response.json();

        if (response.ok && result.text) {
            chatInput.value = result.text;
            chatInput.focus();
        } else {
            throw new Error("Gagal memproses audio");
        }
    } catch (err) {
        console.error("STT error:", err);
    } finally {
        micBtn.disabled = false;
        micBtn.classList.remove("loading");
        chatInput.placeholder = "Tulis pesan...";
    }
}

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------

function iconSpeaker() {
    return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
        <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
        <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
    </svg>`;
}

function iconPause() {
    return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
        <rect x="6" y="4" width="4" height="16"/>
        <rect x="14" y="4" width="4" height="16"/>
    </svg>`;
}

// ---------------------------------------------------------------------------
// Sidebar toggle
// ---------------------------------------------------------------------------

window.toggleSidebar = function () {
    document.getElementById("sidebar").classList.toggle("open");
    document.getElementById("sidebarOverlay").classList.toggle("active");
};

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

(async function init() {
    await refreshThreadList();
    await handleRouteChange();
})();
