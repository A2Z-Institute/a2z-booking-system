(() => {
  const panel = document.querySelector("[data-booking-insights-chat]");
  if (!panel) return;
  const form = panel.querySelector("[data-chat-form]");
  if (!form) return;
  const input = panel.querySelector("[data-chat-input]");
  const messages = panel.querySelector("[data-chat-messages]");
  const submit = panel.querySelector("[data-chat-submit]");
  const status = panel.querySelector("[data-chat-status]");
  const storageKey = `a2z-booking-chat:${panel.dataset.branch}:${panel.dataset.dateFrom}:${panel.dataset.dateTo}:${panel.dataset.days}`;
  let history = [];

  const appendMessage = (role, content) => {
    const wrapper = document.createElement("div");
    wrapper.className = `insights-chat-message ${role}`;
    const heading = document.createElement("strong");
    heading.textContent = role === "user" ? "You" : "A2Z Assistant";
    const copy = document.createElement("p");
    copy.textContent = content;
    wrapper.append(heading, copy);
    messages.append(wrapper);
    messages.scrollTop = messages.scrollHeight;
  };

  try {
    history = JSON.parse(sessionStorage.getItem(storageKey) || "[]");
    if (!Array.isArray(history)) history = [];
  } catch (_) {
    history = [];
  }
  history.slice(-8).forEach((item) => {
    if (item && ["user", "assistant"].includes(item.role) && item.content) appendMessage(item.role, item.content);
  });

  panel.querySelectorAll("[data-chat-suggestion]").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.dataset.chatSuggestion || "";
      input.focus();
    });
  });

  panel.querySelector("[data-chat-clear]")?.addEventListener("click", () => {
    history = [];
    sessionStorage.removeItem(storageKey);
    messages.innerHTML = "";
    appendMessage("assistant", "Chat cleared. Ask a new question about the selected booking statistics.");
    status.textContent = "Read-only assistant. It cannot change appointments.";
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    appendMessage("user", question);
    input.value = "";
    submit.disabled = true;
    status.textContent = "OpenAI is analysing the anonymous totals…";
    try {
      const response = await fetch(panel.dataset.chatUrl, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRF-Token": panel.dataset.csrfToken,
        },
        body: JSON.stringify({
          question,
          history: history.slice(-6),
          days: panel.dataset.days,
          branch: panel.dataset.branch,
          date_from: panel.dataset.dateFrom,
          date_to: panel.dataset.dateTo,
        }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || "The chatbot could not answer.");
      const answer = String(result.answer || "").trim();
      appendMessage("assistant", answer);
      history.push({ role: "user", content: question }, { role: "assistant", content: answer });
      history = history.slice(-8);
      sessionStorage.setItem(storageKey, JSON.stringify(history));
      status.textContent = "Answer based only on the selected anonymous booking totals.";
    } catch (error) {
      appendMessage("assistant", error.message || "The chatbot could not answer. Please try again.");
      status.textContent = "No booking data was changed.";
    } finally {
      submit.disabled = false;
      input.focus();
    }
  });
})();
