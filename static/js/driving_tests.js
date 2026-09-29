(() => {
  "use strict";

  const picker = document.querySelector("[data-driving-client-picker]");
  if (picker) {
    const search = picker.querySelector("[data-driving-client-search]");
    const clientId = picker.querySelector("[data-driving-client-id]");
    const selection = picker.querySelector("[data-driving-client-selection]");
    const results = picker.querySelector("[data-driving-client-results]");
    const instructorSelect = document.querySelector("[data-driving-instructor-select]");
    let searchTimer = null;
    let searchRequest = null;

    const filterInstructors = (branchId) => {
      if (!(instructorSelect instanceof HTMLSelectElement)) return;
      Array.from(instructorSelect.options).forEach((option) => {
        if (!option.value) return;
        option.hidden = Boolean(branchId) && option.dataset.branchId !== String(branchId);
      });
      if (instructorSelect.selectedOptions[0]?.hidden) instructorSelect.value = "";
    };

    const chooseClient = (client) => {
      clientId.value = client.id;
      search.value = client.full_name || "";
      search.setCustomValidity("");
      selection.textContent = `${client.full_name}${client.admission_number ? ` · ${client.admission_number}` : ""}${client.phone ? ` · ${client.phone}` : ""}`;
      selection.hidden = false;
      results.hidden = true;
      results.replaceChildren();
      filterInstructors(client.branch_id);
    };

    const renderResults = (clients) => {
      results.replaceChildren();
      if (!clients.length) {
        const empty = document.createElement("p");
        empty.textContent = "No matching client found.";
        results.append(empty);
      } else {
        clients.forEach((client) => {
          const button = document.createElement("button");
          button.type = "button";
          button.innerHTML = `<strong></strong><span></span>`;
          button.querySelector("strong").textContent = client.full_name || "Unnamed client";
          button.querySelector("span").textContent = [client.admission_number, client.phone].filter(Boolean).join(" · ") || "No admission number or phone";
          button.addEventListener("click", () => chooseClient(client));
          results.append(button);
        });
      }
      results.hidden = false;
    };

    search?.addEventListener("input", () => {
      clientId.value = "";
      selection.hidden = true;
      filterInstructors("");
      window.clearTimeout(searchTimer);
      searchRequest?.abort();
      const query = search.value.trim();
      if (query.length < 2) {
        results.hidden = true;
        results.replaceChildren();
        return;
      }
      searchTimer = window.setTimeout(async () => {
        const controller = new AbortController();
        searchRequest = controller;
        try {
          const url = new URL(picker.dataset.searchUrl, window.location.origin);
          url.searchParams.set("q", query);
          const response = await fetch(url, { headers: { Accept: "application/json" }, signal: controller.signal });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || "Client search failed.");
          renderResults(data.clients || []);
        } catch (error) {
          if (error.name !== "AbortError") renderResults([]);
        }
      }, 220);
    });

    picker.closest("form")?.addEventListener("submit", (event) => {
      if (clientId.value) return;
      event.preventDefault();
      search.setCustomValidity("Select a candidate from the search results.");
      search.reportValidity();
    });
  }

  const instructorFilter = document.querySelector("[data-driving-instructor-filter]");
  if (instructorFilter) {
    const search = instructorFilter.querySelector("[data-driving-instructor-filter-search]");
    const instructorId = instructorFilter.querySelector("[data-driving-instructor-filter-id]");
    const results = instructorFilter.querySelector("[data-driving-instructor-filter-results]");
    const empty = instructorFilter.querySelector("[data-driving-instructor-filter-empty]");
    const options = Array.from(results?.querySelectorAll("button[data-instructor-id]") || []);
    const branch = document.querySelector("#test-filter-branch");
    const filterForm = instructorFilter.closest("form");

    const refreshInstructorSuggestions = () => {
      const query = (search?.value || "").trim().toLocaleLowerCase();
      const branchId = branch?.value || "";
      let matches = 0;
      options.forEach((option) => {
        const matchesName = !query || option.dataset.instructorLabel.toLocaleLowerCase().includes(query);
        const matchesBranch = !branchId || option.dataset.instructorBranch === branchId;
        option.hidden = !(matchesName && matchesBranch);
        if (!option.hidden) matches += 1;
      });
      if (empty) empty.hidden = matches > 0;
      if (results) results.hidden = false;
    };

    const chooseInstructor = (option) => {
      search.value = option.dataset.instructorLabel;
      instructorId.value = option.dataset.instructorId;
      search.setCustomValidity("");
      results.hidden = true;
    };

    options.forEach((option) => {
      option.addEventListener("click", () => chooseInstructor(option));
    });

    search?.addEventListener("focus", refreshInstructorSuggestions);
    search?.addEventListener("input", () => {
      instructorId.value = "";
      search.setCustomValidity("");
      refreshInstructorSuggestions();
    });
    search?.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && results) results.hidden = true;
    });
    branch?.addEventListener("change", () => {
      const selected = options.find((option) => option.dataset.instructorId === instructorId.value);
      if (selected && branch.value && selected.dataset.instructorBranch !== branch.value) {
        search.value = "";
        instructorId.value = "";
      }
      if (document.activeElement === search) refreshInstructorSuggestions();
    });
    document.addEventListener("click", (event) => {
      if (results && !instructorFilter.contains(event.target)) results.hidden = true;
    });
    filterForm?.addEventListener("submit", (event) => {
      const typed = search.value.trim();
      if (!typed || instructorId.value) return;
      const branchId = branch?.value || "";
      const exact = options.filter((option) => (
        option.dataset.instructorLabel.toLocaleLowerCase() === typed.toLocaleLowerCase()
        && (!branchId || option.dataset.instructorBranch === branchId)
      ));
      if (exact.length === 1) {
        chooseInstructor(exact[0]);
        return;
      }
      event.preventDefault();
      search.setCustomValidity("Choose an instructor from the suggestions.");
      search.reportValidity();
      refreshInstructorSuggestions();
    });
  }

  const resultStatus = document.querySelector("[data-driving-result-status]");
  const failureFields = document.querySelector("[data-driving-failure-fields]");
  const failureReason = document.querySelector("[data-driving-failure-reason]");
  const failedSection = document.querySelector("[data-driving-failed-section]");
  const retestToggle = document.querySelector("[data-driving-retest-toggle]");
  const retestDate = document.querySelector("[data-driving-retest-date]");
  const syncResultFields = () => {
    const failed = resultStatus?.value === "Failed";
    if (failureFields) failureFields.hidden = !failed;
    if (failureReason) failureReason.required = failed;
    if (failedSection) failedSection.required = failed;
    if (retestDate) retestDate.disabled = !failed || !retestToggle?.checked;
  };
  resultStatus?.addEventListener("change", syncResultFields);
  retestToggle?.addEventListener("change", syncResultFields);
  syncResultFields();

  document.querySelectorAll("[data-driving-quick-result-form]").forEach((form) => {
    const status = form.querySelector("[data-driving-quick-result-status]");
    const failedSection = form.querySelector("[data-driving-quick-failed-section]");
    const syncQuickResult = () => {
      const failed = status?.value === "Failed";
      if (failedSection) {
        failedSection.hidden = !failed;
        failedSection.disabled = !failed;
        failedSection.required = failed;
      }
    };
    status?.addEventListener("change", syncQuickResult);
    syncQuickResult();
  });
})();
