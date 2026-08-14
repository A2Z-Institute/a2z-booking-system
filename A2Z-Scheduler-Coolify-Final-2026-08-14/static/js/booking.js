(() => {
  "use strict";

  const form = document.querySelector("[data-booking-form]");
  if (!(form instanceof HTMLFormElement)) return;

  const stepPanels = Array.from(form.querySelectorAll("[data-booking-step]"));
  const progressItems = Array.from(document.querySelectorAll("[data-progress-step]"));
  const providerInputs = Array.from(form.querySelectorAll("[data-provider-input]"));
  const serviceInputs = Array.from(form.querySelectorAll("[data-service-input]"));
  const machine = form.querySelector("[data-machine-select]");
  const dateInput = form.querySelector("#target_date");
  const startTime = form.querySelector("#start_time");
  const endTime = form.querySelector("#end_time");
  const slotPanel = form.querySelector("[data-slot-panel]");
  const slotGrid = form.querySelector("[data-slot-grid]");
  const slotPlaceholder = form.querySelector("[data-slot-placeholder]");
  const slotLoading = form.querySelector("[data-slot-loading]");
  const slotMessage = form.querySelector("[data-slot-message]");
  const submitButton = form.querySelector("[data-booking-submit]");
  const errorBox = form.querySelector("[data-booking-error]");
  const errorText = form.querySelector("[data-booking-error-text]");
  const successBox = form.querySelector("[data-booking-success]");
  const successText = form.querySelector("[data-booking-success-text]");
  const durationDisplays = document.querySelectorAll("[data-duration-total], [data-confirm-duration]");
  const summary = {
    instructor: document.querySelector("[data-summary-instructor]"),
    services: document.querySelector("[data-summary-services]"),
    machine: document.querySelector("[data-summary-machine]"),
    date: document.querySelector("[data-summary-date]"),
    time: document.querySelector("[data-summary-time]"),
    price: document.querySelector("[data-summary-price]"),
  };
  const confirmation = {
    instructor: form.querySelector("[data-confirm-instructor]"),
    services: form.querySelector("[data-confirm-services]"),
    machine: form.querySelector("[data-confirm-machine]"),
    date: form.querySelector("[data-confirm-date]"),
    time: form.querySelector("[data-confirm-time]"),
    duration: form.querySelector("[data-confirm-duration]"),
    price: form.querySelector("[data-confirm-price]"),
  };

  if (
    !(machine instanceof HTMLSelectElement)
    || !(dateInput instanceof HTMLInputElement)
    || !(startTime instanceof HTMLInputElement)
    || !(endTime instanceof HTMLInputElement)
    || !slotPanel
    || !slotGrid
  ) return;

  let currentStep = 1;
  let slotsRequest;
  let debounceTimer;
  let resolvedDuration = 0;
  let resolvedPrice = 0;
  let resolvedCurrency = "INR";

  const selectedProvider = () => providerInputs.find((input) => input.checked);
  const selectedServices = () => serviceInputs.filter((input) => input.checked);

  const selectedText = (select, fallback) => {
    if (!(select instanceof HTMLSelectElement) || !select.value) return fallback;
    return select.options[select.selectedIndex]?.textContent?.trim() || fallback;
  };

  const formatDate = (value) => {
    if (!value) return "Not selected";
    const parsed = new Date(`${value}T00:00:00`);
    if (Number.isNaN(parsed.getTime())) return value;
    return new Intl.DateTimeFormat("en-IN", {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(parsed);
  };

  const formatPrice = (price, currency = "INR") => {
    if (!price) return "Included in course";
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
    }).format(price / 100);
  };

  const calculateSelection = () => {
    const services = selectedServices();
    const duration = services.reduce(
      (total, input) => total + Number(input.dataset.duration || 0),
      0,
    );
    const price = services.reduce(
      (total, input) => total + Number(input.dataset.price || 0),
      0,
    );
    const currency = services[0]?.dataset.currency || "INR";
    if (!resolvedDuration || currentStep === 1) resolvedDuration = duration;
    if (!resolvedPrice || currentStep === 1) resolvedPrice = price;
    resolvedCurrency = currency;
    return { services, duration, price, currency };
  };

  const updateSummary = () => {
    const provider = selectedProvider();
    const { services, duration, price, currency } = calculateSelection();
    const serviceNames = services.map((input) => input.dataset.serviceName);
    const providerLabel = provider?.closest("label")?.querySelector("strong")?.textContent?.trim()
      || "Not selected";
    const machineLabel = selectedText(machine, "Not selected");
    const dateLabel = formatDate(dateInput.value);
    const timeLabel = startTime.value && endTime.value
      ? `${startTime.value}–${endTime.value}`
      : "Not selected";
    const durationLabel = `${resolvedDuration || duration || 0} minutes`;
    const priceLabel = formatPrice(resolvedPrice || price, resolvedCurrency || currency);

    if (summary.instructor) summary.instructor.textContent = providerLabel;
    if (summary.services) summary.services.textContent = serviceNames.join(", ") || "Not selected";
    if (summary.machine) summary.machine.textContent = machineLabel;
    if (summary.date) summary.date.textContent = dateLabel;
    if (summary.time) summary.time.textContent = timeLabel;
    if (summary.price) summary.price.textContent = priceLabel;

    if (confirmation.instructor) confirmation.instructor.textContent = providerLabel;
    if (confirmation.services) confirmation.services.textContent = serviceNames.join(", ") || "—";
    if (confirmation.machine) confirmation.machine.textContent = machineLabel;
    if (confirmation.date) confirmation.date.textContent = dateLabel;
    if (confirmation.time) confirmation.time.textContent = timeLabel;
    if (confirmation.duration) confirmation.duration.textContent = durationLabel;
    if (confirmation.price) confirmation.price.textContent = priceLabel;
    durationDisplays.forEach((element) => {
      element.textContent = duration ? `${resolvedDuration || duration} minutes` : "—";
    });
  };

  const setStep = (step, { focus = true } = {}) => {
    currentStep = Math.max(1, Math.min(4, Number(step)));
    stepPanels.forEach((panel) => {
      panel.hidden = Number(panel.dataset.bookingStep) !== currentStep;
    });
    progressItems.forEach((item) => {
      const itemStep = Number(item.dataset.progressStep);
      item.classList.toggle("is-active", itemStep === currentStep);
      item.classList.toggle("is-complete", itemStep < currentStep);
      if (itemStep === currentStep) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
    });
    updateSummary();
    if (focus) {
      const heading = form.querySelector(`[data-booking-step="${currentStep}"] h2`);
      heading?.setAttribute("tabindex", "-1");
      heading?.focus({ preventScroll: true });
      form.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  const clearSelection = () => {
    startTime.value = "";
    endTime.value = "";
    slotGrid.querySelectorAll(".slot-button").forEach((button) => {
      button.setAttribute("aria-pressed", "false");
    });
    updateSummary();
  };

  const showSlotView = (view) => {
    if (slotPlaceholder) slotPlaceholder.hidden = view !== "placeholder";
    if (slotLoading) slotLoading.hidden = view !== "loading";
    slotGrid.hidden = view !== "slots";
    if (slotMessage) slotMessage.hidden = view !== "message";
    slotPanel.setAttribute("aria-busy", String(view === "loading"));
  };

  const showSlotMessage = (message, allowRetry = false) => {
    if (!slotMessage) return;
    slotMessage.replaceChildren();
    const text = document.createElement("span");
    text.textContent = message;
    slotMessage.append(text);
    if (allowRetry) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "button button-secondary button-small";
      retry.textContent = "Try again";
      retry.addEventListener("click", loadSlots);
      slotMessage.append(retry);
    }
    showSlotView("message");
  };

  const normaliseSlot = (slot) => {
    if (Array.isArray(slot) && slot.length >= 2) return { start: slot[0], end: slot[1] };
    if (!slot || typeof slot !== "object") return null;
    const start = slot.start || slot.start_time;
    const end = slot.end || slot.end_time;
    return start && end ? { start, end } : null;
  };

  const renderSlots = (slots) => {
    slotGrid.replaceChildren();
    const normalised = slots.map(normaliseSlot).filter(Boolean);
    if (!normalised.length) {
      showSlotMessage("No matching times are available. Try another date, instructor, or service.");
      window.A2Z?.announce("No matching training times are available.");
      return;
    }
    normalised.forEach((slot) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "slot-button";
      button.dataset.start = slot.start;
      button.dataset.end = slot.end;
      button.setAttribute("aria-pressed", "false");
      button.textContent = `${slot.start}–${slot.end}`;
      button.addEventListener("click", () => {
        slotGrid.querySelectorAll(".slot-button").forEach((item) => {
          item.setAttribute("aria-pressed", "false");
        });
        button.setAttribute("aria-pressed", "true");
        startTime.value = slot.start;
        endTime.value = slot.end;
        updateSummary();
        window.A2Z?.announce(`Selected ${slot.start} to ${slot.end}.`);
      });
      slotGrid.append(button);
    });
    showSlotView("slots");
    window.A2Z?.announce(`${normalised.length} available training times found.`);
  };

  const parseResponse = async (response) => {
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) return {};
    try {
      return await response.json();
    } catch {
      return {};
    }
  };

  const intakePayload = () => {
    const values = {};
    form.querySelectorAll("[data-intake-input]:not(:disabled)").forEach((input) => {
      if (!(input instanceof HTMLInputElement || input instanceof HTMLSelectElement || input instanceof HTMLTextAreaElement)) return;
      if (input instanceof HTMLInputElement && input.type === "file") return;
      const key = input.name.replace(/^intake_/, "");
      if (input instanceof HTMLInputElement && input.type === "checkbox") {
        values[key] = input.checked ? "true" : "";
      } else {
        values[key] = input.value;
      }
    });
    return values;
  };

  async function loadSlots() {
    clearSelection();
    const provider = selectedProvider();
    const services = selectedServices();
    if (!provider || !services.length || !machine.value || !dateInput.value) {
      showSlotView("placeholder");
      return;
    }
    if (slotsRequest) slotsRequest.abort();
    slotsRequest = new AbortController();
    showSlotView("loading");
    const query = new URLSearchParams({
      machine_id: machine.value,
      instructor_id: provider.value,
      date: dateInput.value,
      intake: JSON.stringify(intakePayload()),
    });
    services.forEach((service) => query.append("service_id", service.value));
    try {
      const response = await fetch(`${form.dataset.slotsUrl}?${query.toString()}`, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        signal: slotsRequest.signal,
      });
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      const data = await parseResponse(response);
      if (!response.ok) {
        throw new Error(data.error || data.message || "Availability could not be loaded.");
      }
      resolvedDuration = Number(data.duration_minutes || 0);
      resolvedPrice = Number(data.price_cents || 0);
      resolvedCurrency = data.currency || "INR";
      updateSummary();
      renderSlots(data.slots || data.available_slots || []);
    } catch (error) {
      if (error.name === "AbortError") return;
      showSlotMessage(
        error.message || "Availability could not be loaded. Check your connection and try again.",
        true,
      );
      window.A2Z?.announce("Availability could not be loaded.");
    }
  }

  const queueSlotRefresh = () => {
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(loadSlots, 180);
  };

  const syncServiceFields = () => {
    const selectedIds = new Set(selectedServices().map((input) => input.value));
    form.querySelectorAll("[data-intake-service]").forEach((section) => {
      const active = selectedIds.has(section.dataset.intakeService);
      section.hidden = !active;
      section.querySelectorAll("[data-intake-input]").forEach((input) => {
        input.disabled = !active;
      });
    });
  };

  const syncMachineOptions = () => {
    const selected = selectedServices();
    let allowedIds = null;
    selected.forEach((service) => {
      const ids = new Set(
        (service.dataset.machineIds || "").split(",").filter(Boolean),
      );
      if (!ids.size) return;
      allowedIds = allowedIds === null
        ? ids
        : new Set([...allowedIds].filter((id) => ids.has(id)));
    });
    Array.from(machine.options).forEach((option, index) => {
      if (index === 0) return;
      const allowed = selected.length > 0 && (allowedIds === null || allowedIds.has(option.value));
      option.hidden = !allowed;
      option.disabled = !allowed;
      if (!allowed && option.selected) machine.value = "";
    });
    if (!selected.length) machine.value = "";
  };

  const validateStep = (step) => {
    let controls = [];
    if (step === 1) {
      controls = [
        ...providerInputs,
        ...serviceInputs,
        machine,
        ...form.querySelectorAll("[data-intake-input]:not(:disabled)"),
      ];
      if (!selectedProvider()) {
        providerInputs[0]?.reportValidity();
        window.A2Z?.announce("Choose an instructor.");
        return false;
      }
      if (!selectedServices().length) {
        serviceInputs[0]?.setCustomValidity("Choose at least one service.");
        serviceInputs[0]?.reportValidity();
        serviceInputs[0]?.setCustomValidity("");
        return false;
      }
    } else if (step === 2) {
      controls = [dateInput];
      if (!startTime.value || !endTime.value) {
        showSlotMessage("Choose one of the available times before continuing.");
        slotPanel.focus();
        return false;
      }
    } else if (step === 3) {
      controls = Array.from(form.querySelectorAll('[data-booking-step="3"] input, [data-booking-step="3"] textarea'));
    }
    const invalid = controls.find((control) => typeof control.checkValidity === "function" && !control.checkValidity());
    if (invalid) {
      invalid.reportValidity();
      return false;
    }
    return true;
  };

  form.querySelectorAll("[data-step-next]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!validateStep(currentStep)) return;
      setStep(button.dataset.stepNext);
      if (currentStep === 2) queueSlotRefresh();
    });
  });
  form.querySelectorAll("[data-step-back]").forEach((button) => {
    button.addEventListener("click", () => setStep(button.dataset.stepBack));
  });

  providerInputs.forEach((input) => {
    input.addEventListener("change", () => {
      clearSelection();
      updateSummary();
      queueSlotRefresh();
    });
  });
  serviceInputs.forEach((input) => {
    input.addEventListener("change", () => {
      resolvedDuration = 0;
      resolvedPrice = 0;
      syncServiceFields();
      syncMachineOptions();
      clearSelection();
      updateSummary();
      queueSlotRefresh();
    });
  });
  machine.addEventListener("change", queueSlotRefresh);
  dateInput.addEventListener("change", queueSlotRefresh);
  form.querySelectorAll("[data-intake-input]").forEach((input) => {
    input.addEventListener("change", queueSlotRefresh);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!validateStep(3) || !startTime.value || !endTime.value) {
      setStep(startTime.value ? 3 : 2);
      return;
    }
    if (errorBox) errorBox.hidden = true;
    if (successBox) successBox.hidden = true;
    const formData = new FormData(form);
    form.setAttribute("aria-busy", "true");
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "Confirming…";
    }
    try {
      const response = await fetch(form.dataset.submitUrl, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "X-CSRF-Token": formData.get("csrf_token"),
        },
        credentials: "same-origin",
        body: formData,
      });
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      const data = await parseResponse(response);
      if (!response.ok || data.success === false) {
        throw new Error(
          data.error
          || data.message
          || "Your appointment could not be confirmed. Check the details and try again.",
        );
      }
      if (successText) successText.textContent = data.message || "Your appointment is confirmed.";
      if (successBox) successBox.hidden = false;
      window.A2Z?.announce(data.message || "Your appointment is confirmed.");
      const destination = data.redirect || form.dataset.successUrl;
      window.setTimeout(() => window.location.assign(destination), 900);
    } catch (error) {
      if (errorText) errorText.textContent = error.message || "Your appointment could not be confirmed.";
      if (errorBox) errorBox.hidden = false;
      window.A2Z?.announce(error.message || "Your appointment could not be confirmed.");
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = "Confirm appointment";
      }
      form.removeAttribute("aria-busy");
    }
  });

  syncServiceFields();
  syncMachineOptions();
  updateSummary();
  showSlotView("placeholder");
  setStep(1, { focus: false });
})();
