const API_BASE_URL = "/api/v1";

// ---------------------------------------------------------------------------
// Authentication
// ---------------------------------------------------------------------------

const params = new URLSearchParams(window.location.search);
const token = params.get("token");
if (token) {
    localStorage.setItem("access_token", token);
    window.history.replaceState({}, document.title, "/");
}

function getToken() {
    return localStorage.getItem("access_token");
}

function isLoggedIn() {
    return !!getToken();
}

if (!isLoggedIn()) {
    window.location.href = "/login";
}

function authHeaders(extraHeaders = {}) {
    return {
        "Authorization": `Bearer ${getToken()}`,
        ...extraHeaders
    };
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

const fileInput    = document.getElementById("fileInput");
const fileListDiv  = document.getElementById("file-list");
const uploadBtn    = document.getElementById("uploadBtn");
const uploadStatus = document.getElementById("upload-status");
const chatInput    = document.getElementById("chatInput");
const chatBox      = document.getElementById("chatBox");
const sendBtn      = document.getElementById("sendBtn");
const chatLoading  = document.getElementById("chatLoading");
const micBtn       = document.getElementById("micBtn");

// ---------------------------------------------------------------------------
// File Upload
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
// Chat
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
    bubble.innerHTML = sender === "bot" ? marked.parse(text) : "";
    if (sender !== "bot") bubble.textContent = text;

    const actions = document.createElement("div");
    actions.classList.add("bubble-actions");

    const ttsBtn = document.createElement("button");
    ttsBtn.className = "btn-action-icon btn-tts";
    ttsBtn.title = "Dengarkan";
    ttsBtn.innerHTML = iconSpeaker();
    ttsBtn.addEventListener("click", () => speakMessage(text, ttsBtn));

    actions.appendChild(ttsBtn);
    group.appendChild(bubble);
    group.appendChild(actions);
    wrapper.appendChild(avatar);
    wrapper.appendChild(group);
    chatBox.appendChild(wrapper);
    chatBox.scrollTop = chatBox.scrollHeight;
}

async function sendMessage() {
    const question = chatInput.value.trim();
    if (!question) return;

    appendMessage("user", question);
    chatInput.value = "";

    chatInput.disabled = true;
    sendBtn.disabled = true;
    chatLoading.style.display = "block";

    try {
        const raw = await fetch(`${API_BASE_URL}/chat/`, {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({ question })
        });

        const response = await handleResponse(raw);
        if (!response) return;

        const result = await response.json();

        if (response.ok) {
            appendMessage("bot", result.answer);
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
        alert("Akses mikrofon ditolak.");
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
        chatInput.placeholder = "Ketik atau bicara...";
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
// Sidebar
// ---------------------------------------------------------------------------

window.toggleSidebar = function () {
    document.getElementById("sidebar").classList.toggle("open");
    document.getElementById("sidebarOverlay").classList.toggle("active");
};

// ---------------------------------------------------------------------------
// Welcome TTS
// ---------------------------------------------------------------------------

const welcomeTtsBtn = document.getElementById("welcomeTtsBtn");
if (welcomeTtsBtn) {
    welcomeTtsBtn.addEventListener("click", function () {
        speakMessage(
            "Halo! Saya Argos. Unggah dokumen PDF di menu kiri, lalu tanyakan apa saja seputar harga, fitur, atau metrik kompetitor.",
            this
        );
    });
}

// ---------------------------------------------------------------------------
// Chat History
// ---------------------------------------------------------------------------

let chatHistory = [];
const historyList     = document.getElementById("historyList");
const historyCount    = document.getElementById("historyCount");
const clearHistoryBtn = document.getElementById("clearHistoryBtn");

function addToHistory(userText, botText) {
    const entry = { id: Date.now(), title: userText, subtitle: botText };
    chatHistory.unshift(entry);
    if (chatHistory.length > 50) chatHistory.pop();
    renderHistory();
}

function renderHistory() {
    if (!historyList) return;
    historyList.innerHTML = "";
    historyCount.textContent = `${chatHistory.length}/50`;

    chatHistory.forEach(entry => {
        const item = document.createElement("div");
        item.classList.add("history-item");

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.classList.add("history-checkbox");

        const content = document.createElement("div");
        content.classList.add("history-item-content");

        const title = document.createElement("div");
        title.classList.add("history-item-title");
        title.textContent = entry.title;

        const sub = document.createElement("div");
        sub.classList.add("history-item-subtitle");
        sub.textContent = entry.subtitle;

        content.appendChild(title);
        content.appendChild(sub);
        item.appendChild(cb);
        item.appendChild(content);
        historyList.appendChild(item);
    });
}

// Intercept sendMessage to capture the question before it clears the input
const _origSendMessage = sendMessage;
window.sendMessage = async function () {
    const question = chatInput.value.trim();
    if (!question) return;
    await _origSendMessage();
};

// Observe chatBox for new bot messages and record them in history
const _historyObserver = new MutationObserver((mutations) => {
    mutations.forEach(m => {
        m.addedNodes.forEach(node => {
            if (node.classList && node.classList.contains("bot-wrapper")) {
                const botBubble = node.querySelector(".message.bot");
                if (!botBubble) return;

                const allWrappers = Array.from(chatBox.children);
                const idx = allWrappers.indexOf(node);
                let userText = "";

                for (let i = idx - 1; i >= 0; i--) {
                    const userMsg = allWrappers[i].querySelector(".message.user");
                    if (userMsg) {
                        userText = userMsg.textContent.trim();
                        break;
                    }
                }

                const botText = botBubble.textContent.trim().slice(0, 60) +
                    (botBubble.textContent.length > 60 ? "..." : "");

                if (userText) addToHistory(userText, botText);
            }
        });
    });
});
_historyObserver.observe(chatBox, { childList: true });

if (clearHistoryBtn) {
    clearHistoryBtn.addEventListener("click", () => {
        chatHistory = [];
        renderHistory();
    });
}

renderHistory();
