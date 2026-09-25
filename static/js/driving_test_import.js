(() => {
  "use strict";

  const container = document.querySelector("[data-import-client-search-url]");
  const form = document.querySelector("[data-import-confirm-form]");
  if (!container || !form) return;

  const endpoint = container.dataset.importClientSearchUrl;
  const confirmButton = form.querySelector("[data-import-confirm-button]");
  const readyCount = document.querySelector("[data-import-ready-count]");
  const baseReady = Number(form.dataset.baseReady || 0);

  const updateCount = () => {
    const selected = Array.from(form.querySelectorAll("[data-import-client-id]"))
      .filter((input) => input.value).length;
    const total = baseReady + selected;
    if (readyCount) readyCount.textContent = String(total);
    if (confirmButton) {
      confirmButton.disabled = total < 1;
      confirmButton.textContent = `Confirm and register ${total} candidate${total === 1 ? "" : "s"}`;
    }
  };

  container.querySelectorAll("[data-import-client-picker]").forEach((picker) => {
    const search = picker.querySelector("[data-import-client-search]");
    const clientId = picker.querySelector("[data-import-client-id]");
    const selection = picker.querySelector("[data-import-client-selection]");
    const results = picker.querySelector("[data-import-client-results]");
    const status = picker.closest("tr")?.querySelector("[data-import-row-status]");
    let timer = null;
    let requestController = null;

    const choose = (client) => {
      clientId.value = String(client.id);
      selection.textContent = [client.full_name, client.admission_number, client.phone]
        .filter(Boolean).join(" · ");
      selection.hidden = false;
      results.hidden = true;
      results.replaceChildren();
      if (status) {
        status.textContent = "Selected";
        status.classList.remove("status-rejected");
        status.classList.add("status-approved");
      }
      updateCount();
    };

    const render = (clients) => {
      results.replaceChildren();
      if (!clients.length) {
        const empty = document.createElement("p");
        empty.textContent = "No existing client found. Try the name or admission number.";
        results.append(empty);
      } else {
        clients.forEach((client) => {
          const button = document.createElement("button");
          button.type = "button";
          button.innerHTML = "<strong></strong><span></span>";
          button.querySelector("strong").textContent = client.full_name || "Unnamed client";
          button.querySelector("span").textContent = [client.admission_number, client.phone]
            .filter(Boolean).join(" · ") || "No admission number or phone";
          button.addEventListener("click", () => choose(client));
          results.append(button);
        });
      }
      results.hidden = false;
    };

    const searchClients = async () => {
      const query = search.value.trim();
      if (query.length < 2) {
        results.hidden = true;
        return;
      }
      requestController?.abort();
      requestController = new AbortController();
      try {
        const url = new URL(endpoint, window.location.origin);
        url.searchParams.set("q", query);
        const response = await fetch(url, {
          headers: { Accept: "application/json" },
          signal: requestController.signal,
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Client search failed.");
        render(data.clients || []);
      } catch (error) {
        if (error.name !== "AbortError") render([]);
      }
    };

    search.addEventListener("focus", searchClients, { once: true });
    search.addEventListener("input", () => {
      clientId.value = "";
      selection.hidden = true;
      if (status) {
        status.textContent = "Needs selection";
        status.classList.remove("status-approved");
        status.classList.add("status-rejected");
      }
      updateCount();
      window.clearTimeout(timer);
      timer = window.setTimeout(searchClients, 220);
    });
  });

  updateCount();
})();
