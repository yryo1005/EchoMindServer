// EchoMindブラウザフロントエンド．ビルドツールを使わないプレーンなJavaScript．

const TOKEN_STORAGE_KEY = "echomind_access_token";

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function formatTimestamp(isoString) {
  const date = new Date(isoString);
  return date.toLocaleString("ja-JP", { hour12: false });
}

// --- 認証 ---

function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch (error) {
    return null;
  }
}

function setToken(token) {
  try {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch (error) {
    // ブラウザのプライベートモード等でlocalStorageが使えない場合は無視する
  }
}

function clearToken() {
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch (error) {
    // 無視する
  }
}

// 認証付きfetch．401が返った場合は自動的にログイン画面へ戻す．
async function authorizedFetch(url, options = {}) {
  const token = getToken();
  const headers = { ...(options.headers || {}), Authorization: `Bearer ${token}` };
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401) {
    clearToken();
    showAuthScreen();
    throw new Error("ログインの有効期限が切れました．再度ログインしてください．");
  }
  return response;
}

function showAuthScreen() {
  document.getElementById("auth-screen").classList.remove("hidden");
  document.getElementById("app-root").classList.add("hidden");
}

async function showAppRoot() {
  document.getElementById("auth-screen").classList.add("hidden");
  document.getElementById("app-root").classList.remove("hidden");

  try {
    const response = await authorizedFetch("/api/auth/me");
    if (response.ok) {
      const me = await response.json();
      document.getElementById("current-user-email").textContent = me.email;
    }
  } catch (error) {
    return;
  }

  loadConversations();
  loadPersons();
}

function setupAuth() {
  const authTabButtons = document.querySelectorAll(".auth-tab-button");
  authTabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      authTabButtons.forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".auth-form").forEach((f) => f.classList.remove("active"));
      button.classList.add("active");
      document.getElementById(`${button.dataset.authTab}-form`).classList.add("active");
    });
  });

  const statusEl = document.getElementById("auth-status");

  document.getElementById("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("login-email").value.trim();
    const password = document.getElementById("login-password").value;

    statusEl.textContent = "ログイン中…";
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `サーバーエラー (${response.status})`);
      }
      const data = await response.json();
      setToken(data.access_token);
      statusEl.textContent = "";
      await showAppRoot();
    } catch (error) {
      statusEl.textContent = `エラー: ${error.message}`;
    }
  });

  document.getElementById("register-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("register-email").value.trim();
    const password = document.getElementById("register-password").value;

    statusEl.textContent = "登録中…";
    try {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `サーバーエラー (${response.status})`);
      }
      const data = await response.json();
      setToken(data.access_token);
      statusEl.textContent = "";
      await showAppRoot();
    } catch (error) {
      statusEl.textContent = `エラー: ${error.message}`;
    }
  });

  document.getElementById("logout-button").addEventListener("click", () => {
    clearToken();
    showAuthScreen();
  });
}

// --- タブ切り替え ---

function setupTabs() {
  const buttons = document.querySelectorAll(".tab-button");
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      button.classList.add("active");
      document.getElementById(`tab-${button.dataset.tab}`).classList.add("active");
    });
  });
}

// --- 質問(QA)タブ ---

function setupChat() {
  const form = document.getElementById("chat-form");
  const statusEl = document.getElementById("chat-status");
  const resultEl = document.getElementById("chat-result");
  const answerEl = document.getElementById("chat-answer");
  const referencesEl = document.getElementById("chat-references");
  const submitButton = form.querySelector("button");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = document.getElementById("chat-query").value.trim();
    if (!query) return;

    submitButton.disabled = true;
    statusEl.textContent = "回答を生成しています…";
    resultEl.classList.add("hidden");

    try {
      const response = await authorizedFetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      if (!response.ok) {
        throw new Error(`サーバーエラー (${response.status})`);
      }
      const data = await response.json();

      answerEl.textContent = data.answer;
      referencesEl.innerHTML = "";
      data.references.forEach((ref) => {
        const li = document.createElement("li");
        li.textContent = formatTimestamp(ref);
        referencesEl.appendChild(li);
      });

      resultEl.classList.remove("hidden");
      statusEl.textContent = "";
    } catch (error) {
      statusEl.textContent = `エラーが発生しました: ${error.message}`;
    } finally {
      submitButton.disabled = false;
    }
  });
}

// --- 過去の会話を聞くタブ ---

async function loadConversations() {
  const listEl = document.getElementById("conversation-list");
  listEl.innerHTML = "<li class=\"placeholder\">読み込み中…</li>";

  try {
    const response = await authorizedFetch("/api/conversations?limit=50");
    if (!response.ok) throw new Error(`サーバーエラー (${response.status})`);
    const conversations = await response.json();

    listEl.innerHTML = "";
    if (conversations.length === 0) {
      listEl.innerHTML = "<li class=\"placeholder\">会話がまだありません．</li>";
      return;
    }

    conversations.forEach((conversation) => {
      const li = document.createElement("li");
      li.className = "conversation-item";
      li.dataset.conversationId = conversation.conversation_id;
      li.innerHTML = `
        <div>${escapeHtml(conversation.participant_names.join("，"))}</div>
        <div class="meta">${formatTimestamp(conversation.started_at)}(${conversation.utterance_count}発言)</div>
      `;
      li.addEventListener("click", () => selectConversation(conversation.conversation_id, li));
      listEl.appendChild(li);
    });
  } catch (error) {
    listEl.innerHTML = `<li class="placeholder">読み込みに失敗しました: ${escapeHtml(error.message)}</li>`;
  }
}

async function selectConversation(conversationId, listItemEl) {
  document.querySelectorAll(".conversation-item").forEach((el) => el.classList.remove("selected"));
  listItemEl.classList.add("selected");

  const detailEl = document.getElementById("conversation-detail");
  detailEl.innerHTML = "<p class=\"placeholder\">読み込み中…</p>";

  try {
    const response = await authorizedFetch(`/api/conversations/${conversationId}`);
    if (!response.ok) throw new Error(`サーバーエラー (${response.status})`);
    const conversation = await response.json();

    detailEl.innerHTML = "";
    conversation.utterances.forEach((utterance) => {
      const div = document.createElement("div");
      div.className = "utterance-item";
      div.innerHTML = `
        <span class="speaker">${escapeHtml(utterance.person_name || "不明な人物")}</span>
        <span class="timestamp">${formatTimestamp(utterance.start_time)}</span>
        <p class="text">${escapeHtml(utterance.text)}</p>
      `;
      const audioEl = document.createElement("audio");
      audioEl.controls = true;
      // 音声の取得には認証が必要なため，blob URLを経由して<audio>要素に渡す
      authorizedFetch(utterance.audio_url)
        .then((res) => res.blob())
        .then((blob) => {
          audioEl.src = URL.createObjectURL(blob);
        })
        .catch(() => {});
      div.appendChild(audioEl);
      detailEl.appendChild(div);
    });
  } catch (error) {
    detailEl.innerHTML = `<p class="placeholder">読み込みに失敗しました: ${escapeHtml(error.message)}</p>`;
  }
}

// --- 話者の名前を設定タブ ---

async function loadPersons() {
  const tbody = document.getElementById("person-table-body");
  tbody.innerHTML = "<tr><td colspan=\"4\" class=\"placeholder\">読み込み中…</td></tr>";

  try {
    const response = await authorizedFetch("/api/persons");
    if (!response.ok) throw new Error(`サーバーエラー (${response.status})`);
    const persons = await response.json();

    tbody.innerHTML = "";
    if (persons.length === 0) {
      tbody.innerHTML = "<tr><td colspan=\"4\" class=\"placeholder\">人物がまだ登録されていません．</td></tr>";
      return;
    }

    persons.forEach((person) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="person-id">${escapeHtml(person.person_id)}</td>
        <td><input type="text" value="${escapeHtml(person.name || "")}" placeholder="名前を入力" /></td>
        <td>${person.utterance_count}</td>
        <td><button type="button">保存</button></td>
      `;
      const input = tr.querySelector("input");
      const button = tr.querySelector("button");
      button.addEventListener("click", () => savePersonName(person.person_id, input.value, button));
      tbody.appendChild(tr);
    });
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="4" class="placeholder">読み込みに失敗しました: ${escapeHtml(error.message)}</td></tr>`;
  }
}

async function savePersonName(personId, name, button) {
  if (!name.trim()) {
    window.alert("名前を入力してください．");
    return;
  }

  button.disabled = true;
  button.textContent = "保存中…";

  try {
    const response = await authorizedFetch(`/api/persons/${personId}/name`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!response.ok) throw new Error(`サーバーエラー (${response.status})`);
    button.textContent = "保存しました";
  } catch (error) {
    window.alert(`保存に失敗しました: ${error.message}`);
    button.textContent = "保存";
  } finally {
    button.disabled = false;
  }
}

// --- 初期化 ---

setupAuth();
setupTabs();
setupChat();

if (getToken()) {
  showAppRoot();
} else {
  showAuthScreen();
}
