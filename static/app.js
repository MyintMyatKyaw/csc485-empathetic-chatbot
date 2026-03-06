const history = [];
let didClearExamples = false;

function nowTimeLabel() {
  return "now (prototype)";
}

function clearExampleMessagesOnce() {
  if (didClearExamples) return;
  const ex = document.getElementById("exampleMessages");
  if (ex) ex.remove();
  didClearExamples = true;
}

function setInputEnabled(enabled) {
  const input = document.getElementById("userInput");
  const btn = document.getElementById("sendBtn");
  input.disabled = !enabled;
  btn.disabled = !enabled;
  btn.style.opacity = enabled ? "1" : "0.6";
  btn.style.cursor = enabled ? "pointer" : "not-allowed";
}

function appendBubble(role, text) {
  const chatWindow = document.getElementById("chatWindow");

  const row = document.createElement("div");
  row.className = role === "user" ? "message-row user" : "message-row";

  const bubble = document.createElement("div");
  bubble.className = (role === "user" ? "user-bubble" : "bot-bubble") + " bubble";
  bubble.innerHTML =
    text.replace(/\n/g, "<br>") +
    `<div class="timestamp">${role === "user" ? "User" : "Chatbot"} · ${nowTimeLabel()}</div>`;

  if (role === "user") {
    const avatar = document.createElement("div");
    avatar.className = "avatar user";
    avatar.textContent = "U";
    row.appendChild(bubble);
    row.appendChild(avatar);
  } else {
    const avatar = document.createElement("div");
    avatar.className = "avatar bot";
    avatar.textContent = "AI";
    row.appendChild(avatar);
    row.appendChild(bubble);
  }

  chatWindow.appendChild(row);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return row;
}

function updateEmotionPanel(emotion) {
  const badge = document.getElementById("emotionBadge");
  if (badge) badge.textContent = `${emotion.primary_emotion} (${(emotion.intensity ?? 0).toFixed(2)})`;

  const list = document.getElementById("emotionList");
  if (!list) return;

  const items = [];
  items.push(["Primary", emotion.primary_emotion]);
  if (emotion.secondary_emotion) items.push(["Secondary", emotion.secondary_emotion]);
  items.push(["Intensity", (emotion.intensity ?? 0).toFixed(2)]);
  items.push(["Risk", emotion.risk_level || "none"]);
  (emotion.needs || []).slice(0, 4).forEach((n, i) => items.push([`Need ${i + 1}`, n]));

  list.innerHTML = items.map(([k, v]) => `<li><span>${k}</span><span>${v}</span></li>`).join("");
}

async function sendMessage() {
  const input = document.getElementById("userInput");
  const text = input.value.trim();
  if (!text) return;

  clearExampleMessagesOnce();

  // user bubble
  appendBubble("user", text);
  history.push({ role: "user", content: text });
  input.value = "";

  // loading bubble
  setInputEnabled(false);
  const loadingRow = appendBubble("assistant", "Thinking…");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history })
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error("Server error:", res.status, errText);
      loadingRow.remove();
      appendBubble("assistant", `Server error (${res.status}). Check terminal/console.`);
      return;
    }

    const data = await res.json();

    loadingRow.remove();
    appendBubble("assistant", data.reply || "(no reply)");
    history.push({ role: "assistant", content: data.reply || "" });

    if (data.emotion) updateEmotionPanel(data.emotion);

  } catch (err) {
    console.error(err);
    loadingRow.remove();
    appendBubble("assistant", "Sorry—something went wrong connecting to the server.");
  } finally {
    setInputEnabled(true);
    input.focus();
  }
}

// Hook up button + Enter key
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("sendBtn").addEventListener("click", sendMessage);

  const input = document.getElementById("userInput");
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
});
