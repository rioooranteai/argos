const API_BASE_URL = "/api/v1";

const fileInput    = document.getElementById('fileInput');
const fileListDiv  = document.getElementById('file-list');
const uploadBtn    = document.getElementById('uploadBtn');
const uploadStatus = document.getElementById('upload-status');
const chatInput    = document.getElementById('chatInput');
const chatBox      = document.getElementById('chatBox');
const sendBtn      = document.getElementById('sendBtn');
const chatLoading  = document.getElementById('chatLoading');

fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
        const fileNames = Array.from(fileInput.files).map(f => f.name).join(', ');
        fileListDiv.textContent = `File: ${fileNames}`;
        uploadBtn.style.display = 'block';
        uploadStatus.textContent = '';
    } else {
        fileListDiv.textContent = '';
        uploadBtn.style.display = 'none';
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
    uploadStatus.style.color = "var(--text-muted)";

    try {
        const response = await fetch(`${API_BASE_URL}/document/upload`, {
            method: "POST",
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            uploadStatus.textContent = "Sukses! Data siap ditanyakan.";
            uploadStatus.style.color = "#10b981";
            fileInput.value = "";
            fileListDiv.textContent = "";
            uploadBtn.style.display = "none";
        } else {
            uploadStatus.textContent = `Gagal: ${result.detail || 'Error server'}`;
            uploadStatus.style.color = "var(--primary)";
        }
    } catch (error) {
        uploadStatus.textContent = `Koneksi terputus: ${error.message}`;
        uploadStatus.style.color = "var(--primary)";
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.textContent = "Ekstrak ke DB";
    }
}

function appendMessage(sender, text) {
    const wrapperDiv = document.createElement('div');
    wrapperDiv.classList.add('message-wrapper', `${sender}-wrapper`);

    const msgDiv = document.createElement('div');
    msgDiv.classList.add('message', sender);

    if (sender === 'bot') {
        // marked.js sudah dimuat di <head>, selalu tersedia
        msgDiv.innerHTML = marked.parse(text);
    } else {
        // Sanitasi XSS untuk input user
        msgDiv.textContent = text;
    }

    wrapperDiv.appendChild(msgDiv);
    chatBox.appendChild(wrapperDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

async function sendMessage() {
    const question = chatInput.value.trim();
    if (!question) return;

    appendMessage('user', question);
    chatInput.value = '';

    chatInput.disabled = true;
    sendBtn.disabled = true;
    chatLoading.style.display = 'block';
    chatBox.scrollTop = chatBox.scrollHeight;

    try {
        const response = await fetch(`${API_BASE_URL}/chat/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question })
        });

        const result = await response.json();

        if (response.ok) {
            appendMessage('bot', result.answer);
        } else {
            appendMessage('bot', `Maaf: ${result.detail || 'Ditolak sistem.'}`);
        }
    } catch (error) {
        appendMessage('bot', `Koneksi gagal. Pastikan server aktif. Error: ${error.message}`);
    } finally {
        chatInput.disabled = false;
        sendBtn.disabled = false;
        chatLoading.style.display = 'none';
        chatInput.focus();
    }
}

uploadBtn.addEventListener('click', uploadFiles);
sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
});