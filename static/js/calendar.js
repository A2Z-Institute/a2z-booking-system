(() => {
  "use strict";

  const STAFF_DAY_START = 6 * 60;
  const STAFF_DAY_END = (18 * 60) + 30;
  // Bookings are coloured by instructor rather than equipment/service. This
  // makes each staff column easy to scan while keeping the calendar white.
  const INSTRUCTOR_EVENT_COLOURS = [
    "#2F6B9A", "#237A57", "#7A4EAB", "#A45C1B", "#0F766E",
    "#A33A4A", "#49657A", "#7A6A32", "#4D5D93", "#8A4D70",
  ];

  const calendar = document.querySelector("[data-calendar]");
  const dialog = document.querySelector("[data-appointment-dialog]");
  const editor = dialog?.querySelector("[data-appointment-form]");
  if (!calendar || !(dialog instanceof HTMLDialogElement) || !(editor instanceof HTMLFormElement)) return;

  const grid = calendar.querySelector("[data-calendar-grid]");
  const calendarScroll = calendar.querySelector("[data-calendar-scroll]");
  const message = calendar.querySelector("[data-calendar-message]");
  const dateInput = calendar.querySelector("[data-calendar-date]");
  const branchFilter = calendar.querySelector("[data-calendar-branch]");
  const instructorFilter = calendar.querySelector("[data-calendar-instructor]");
  const viewFilter = calendar.querySelector("[data-calendar-view]");
  const statusFilter = calendar.querySelector("[data-calendar-status]");
  const rangeLabel = calendar.querySelector("[data-calendar-range]");

  const bookingIdInput = editor.querySelector("[data-editor-booking-id]");
  const revisionInput = editor.querySelector("[data-editor-revision]");
  const clientInput = editor.querySelector("[data-editor-client], [data-editor-student]");
  const instructorInput = editor.querySelector("[data-editor-instructor]");
  const machineInput = editor.querySelector("[data-editor-machine]");
  const serviceChecks = Array.from(editor.querySelectorAll("[data-editor-service]"));
  const servicePicker = editor.querySelector("[data-service-picker]");
  const servicePickerEmpty = editor.querySelector("[data-service-picker-empty]");
  const servicePickerOpenButton = editor.querySelector("[data-service-picker-open]");
  const serviceTriggerTitle = editor.querySelector("[data-service-trigger-title]");
  const serviceTotal = editor.querySelector("[data-service-total]");
  const additionalDetails = editor.querySelector("[data-editor-additional]");
  const additionalToggle = editor.querySelector("[data-editor-additional-toggle]");
  const legacyServices = editor.querySelector("[data-editor-services]");
  const editorDate = editor.querySelector("[data-editor-date]");
  const editorStart = editor.querySelector("[data-editor-start]");
  const editorEnd = editor.querySelector("[data-editor-end]");
  const editorStatus = editor.querySelector("[data-editor-status]");
  const editorNotes = editor.querySelector("[data-editor-notes]");
  const bufferBefore = editor.querySelector("[data-editor-buffer-before]");
  const bufferAfter = editor.querySelector("[data-editor-buffer-after]");
  const repeatInput = editor.querySelector("[data-editor-repeat]");
  const repeatCount = editor.querySelector("[data-editor-repeat-count]");
  const allowDoubleBooking = editor.querySelector("[data-editor-allow-double-booking]");
  const clientFirstName = editor.querySelector("[data-new-client-first-name]");
  const clientLastName = editor.querySelector("[data-new-client-last-name]");
  const clientPhone = editor.querySelector("[data-new-client-phone]");
  const clientEmail = editor.querySelector("[data-new-client-email]");
  const clientTypeahead = editor.querySelector("[data-client-typeahead]");
  const clientTypeaheadResults = editor.querySelector("[data-client-typeahead-results]");
  const clientContactInputs = [clientFirstName, clientLastName, clientPhone, clientEmail]
    .filter((input) => input instanceof HTMLInputElement);

  const busyInstructor = editor.querySelector("[data-editor-busy-instructor]");
  const busyDate = editor.querySelector("[data-editor-busy-date]");
  const busyStart = editor.querySelector("[data-editor-busy-start]");
  const busyEnd = editor.querySelector("[data-editor-busy-end]");
  const busyKind = editor.querySelector("[data-editor-busy-kind]");
  const busyTitle = editor.querySelector("[data-editor-busy-title]");
  const busyNotes = editor.querySelector("[data-editor-busy-notes]");
  const busyRepeat = editor.querySelector("[data-editor-busy-repeat]");
  const busyRepeatCount = editor.querySelector("[data-editor-busy-repeat-count]");
  const slotInstructor = editor.querySelector("[data-editor-slot-instructor]");
  const slotMachine = editor.querySelector("[data-editor-slot-machine]");
  const slotDate = editor.querySelector("[data-editor-slot-date]");
  const slotStart = editor.querySelector("[data-editor-slot-start]");
  const slotEnd = editor.querySelector("[data-editor-slot-end]");
  const slotNotes = editor.querySelector("[data-editor-slot-notes]");
  const slotRepeat = editor.querySelector("[data-editor-slot-repeat]");
  const slotRepeatCount = editor.querySelector("[data-editor-slot-repeat-count]");

  const errorBox = editor.querySelector("[data-editor-error]");
  const errorText = editor.querySelector("[data-editor-error-text]");
  const saveButton = editor.querySelector("[data-editor-save]");
  const cancelAppointmentButton = editor.querySelector("[data-editor-cancel]");
  const deleteClientUpcomingButton = editor.querySelector("[data-editor-delete-client-upcoming]");
  const permanentDeleteButton = editor.querySelector("[data-editor-permanent-delete]");
  const bookingMenu = editor.querySelector("[data-editor-booking-menu]");
  const clientDetailsLink = editor.querySelector("[data-editor-client-details]");
  const clientNotesLink = editor.querySelector("[data-editor-client-notes]");
  const whatsappConfirmationButton = editor.querySelector("[data-editor-whatsapp]");
  const deleteBusyButton = editor.querySelector("[data-editor-busy-delete]");
  const deleteUpcomingBusyButton = editor.querySelector("[data-editor-busy-delete-upcoming]");
  const deleteBusyForAllButton = editor.querySelector("[data-editor-busy-delete-all]");
  const deleteSlotButton = editor.querySelector("[data-editor-slot-delete]");
  const durationText = editor.querySelector("[data-editor-duration]");
  const endTimeText = editor.querySelector("[data-editor-end-time]");
  const existingSummary = editor.querySelector("[data-editor-existing-summary]");
  const seriesSummary = editor.querySelector("[data-editor-series-summary]");
  const titleText = editor.querySelector("[data-editor-title]");
  const eyebrowText = editor.querySelector("[data-editor-eyebrow]");
  const descriptionText = editor.querySelector("[data-editor-description]");
  const csrf = editor.querySelector('[name="csrf_token"]')?.value || "";
  const currentRole = document.body.dataset.userRole || "";
  const canManageOwnSlots = calendar.dataset.canManageOwnSlots === "true";
  const currentInstructorId = String(calendar.dataset.currentInstructorId || "");

  if (
    !grid
    || !message
    || !(dateInput instanceof HTMLInputElement)
    || !(instructorFilter instanceof HTMLSelectElement)
    || !(viewFilter instanceof HTMLSelectElement)
    || !(statusFilter instanceof HTMLSelectElement)
    || !(clientInput instanceof HTMLSelectElement)
    || !(instructorInput instanceof HTMLSelectElement)
    || !(machineInput instanceof HTMLSelectElement)
    || !(editorDate instanceof HTMLInputElement)
    || !(editorStart instanceof HTMLSelectElement)
  ) return;

  let events = [];
  let loadRequest;
  let loadInFlight = false;
  let loadGeneration = 0;
  let draggedEvent = null;
  let dragTimePreview = null;
  let activePointerDragCleanup = null;
  let resizingEventId = null;
  let suppressEventClickUntil = 0;
  let editingEvent = null;
  let editorType = "appointment";
  let lastFocused = null;
  let initialClientHandled = false;
  let clientSearchTimer;
  let clientSearchRequest;
  let fillingClient = false;
  let servicePickerSnapshot = [];
  let resetHorizontalScroll = false;
  let restoreHorizontalScroll = true;
  let saveInFlight = false;
  let moveInFlight = false;
  let trailerFinishAuto = false;
  let reconcileTimer = null;
  let whatsappConfirmationEvent = null;
  // The calendar column is the authoritative instructor selection. Keep it
  // outside the hidden form control so branch filtering or form resets cannot
  // discard the instructor while a new client is being created.
  let appointmentInstructorId = "";
  let appointmentBranchId = "";

  const calendarStateStorageKey = [
    "a2z-calendar-state-v1",
    window.location.pathname,
  ].join(":");

  const restoreCalendarState = () => {
    const locationUrl = new URL(window.location.href);
    let stored = {};
    try {
      stored = JSON.parse(window.sessionStorage.getItem(calendarStateStorageKey) || "{}");
    } catch {
      stored = {};
    }
    const requestedDate = locationUrl.searchParams.get("date") || stored.date || "";
    if (/^\d{4}-\d{2}-\d{2}$/.test(requestedDate)) dateInput.value = requestedDate;

    const requestedView = locationUrl.searchParams.get("view") || stored.view || "";
    if (["day", "week"].includes(requestedView)) viewFilter.value = requestedView;

    const requestedBranch = locationUrl.searchParams.get("branch_id")
      ?? stored.branchId
      ?? "";
    if (branchFilter instanceof HTMLSelectElement
      && Array.from(branchFilter.options).some((option) => option.value === String(requestedBranch))) {
      branchFilter.value = String(requestedBranch);
      syncInstructorFilterForBranch();
    }

    const requestedInstructor = locationUrl.searchParams.get("instructor_id")
      ?? stored.instructorId
      ?? "";
    const requestedInstructorOption = Array.from(instructorFilter.options).find(
      (option) => option.value === String(requestedInstructor) && !option.disabled,
    );
    if (requestedInstructorOption) instructorFilter.value = String(requestedInstructor);

    const requestedStatus = locationUrl.searchParams.get("status") ?? stored.status ?? "";
    if (Array.from(statusFilter.options).some((option) => option.value === String(requestedStatus))) {
      statusFilter.value = String(requestedStatus);
    }
  };

  // Remember the agent's horizontal position for this calendar view. This
  // prevents an edit, background refresh, or browser refresh from jumping
  // back to the first instructor column.
  const horizontalScrollStorageKey = () => [
    "a2z-calendar-scroll-v1",
    window.location.pathname,
    dateInput.value,
    viewFilter.value,
    branchFilter?.value || "all-branches",
    instructorFilter.value || "all",
  ].join(":");

  const storedHorizontalScroll = () => {
    try {
      const value = Number(window.sessionStorage.getItem(horizontalScrollStorageKey()));
      return Number.isFinite(value) && value > 0 ? value : 0;
    } catch {
      return 0;
    }
  };

  const rememberHorizontalScroll = () => {
    if (!calendarScroll) return;
    try {
      window.sessionStorage.setItem(horizontalScrollStorageKey(), String(calendarScroll.scrollLeft));
    } catch {
      // The calendar remains usable when browser storage is unavailable.
    }
  };

  // The server response is applied immediately.  A short, quiet follow-up
  // sync keeps a multi-user calendar accurate without making an agent wait
  // for a full grid rebuild after every click, drag, or save.
  const queueCalendarReconcile = (delay = 2200) => {
    window.clearTimeout(reconcileTimer);
    reconcileTimer = window.setTimeout(() => {
      if (activePointerDragCleanup || draggedEvent || resizingEventId !== null) {
        queueCalendarReconcile(700);
        return;
      }
      void loadEvents({ silent: true, force: true });
    }, delay);
  };

  const persistCalendarDate = () => {
    const selectedDate = String(dateInput?.value || "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(selectedDate)) return;
    const locationUrl = new URL(window.location.href);
    locationUrl.searchParams.set("date", selectedDate);
    locationUrl.searchParams.set("view", viewFilter.value);
    if (branchFilter?.value) {
      locationUrl.searchParams.set("branch_id", branchFilter.value);
    } else {
      locationUrl.searchParams.delete("branch_id");
    }
    if (instructorFilter.value) {
      locationUrl.searchParams.set("instructor_id", instructorFilter.value);
    } else {
      locationUrl.searchParams.delete("instructor_id");
    }
    if (statusFilter.value) {
      locationUrl.searchParams.set("status", statusFilter.value);
    } else {
      locationUrl.searchParams.delete("status");
    }
    try {
      window.sessionStorage.setItem(calendarStateStorageKey, JSON.stringify({
        date: selectedDate,
        view: viewFilter.value,
        branchId: branchFilter?.value || "",
        instructorId: instructorFilter.value,
        status: statusFilter.value,
      }));
    } catch {
      // URL state still makes refresh reliable when browser storage is unavailable.
    }
    window.history.replaceState({}, "", locationUrl);
  };

  const parseJson = async (response) => {
    try {
      return await response.json();
    } catch {
      return {};
    }
  };

  const hideClientMatches = () => {
    if (clientTypeahead) clientTypeahead.hidden = true;
    if (clientTypeaheadResults) clientTypeaheadResults.replaceChildren();
  };

  const selectClientMatch = (client) => {
    fillingClient = true;
    if (clientFirstName) clientFirstName.value = client.full_name || "";
    if (clientLastName) clientLastName.value = client.admission_number || "";
    if (clientPhone) clientPhone.value = client.phone || "";
    if (clientEmail) clientEmail.value = client.email || "";
    let option = Array.from(clientInput.options).find((item) => String(item.value) === String(client.id));
    if (!option) {
      option = document.createElement("option");
      option.value = String(client.id);
      option.textContent = client.full_name || "Client";
      option.dataset.branchId = String(client.branch_id || "");
      clientInput.append(option);
    }
    option.hidden = false;
    option.disabled = false;
    clientInput.value = String(client.id);
    fillingClient = false;
    hideClientMatches();
    syncEditorOptions();
    const clientUrl = replaceId(calendar.dataset.clientUrlTemplate || "", client.id);
    if (clientDetailsLink) clientDetailsLink.href = `${clientUrl}#upcoming-title`;
    if (clientNotesLink) clientNotesLink.href = `${clientUrl}#client-notes`;
    if (cancelAppointmentButton) cancelAppointmentButton.hidden = true;
    if (bookingMenu) bookingMenu.hidden = false;
    announce(`${client.full_name || "Client"} selected.`);
  };

  const showClientMatches = (clients, query) => {
    if (!clientTypeahead || !clientTypeaheadResults) return;
    clientTypeaheadResults.replaceChildren();
    if (!clients.length) {
      const empty = document.createElement("div");
      empty.className = "client-typeahead-empty";
      empty.textContent = `No existing client matches “${query}”. The client will be created when you save.`;
      clientTypeaheadResults.append(empty);
    } else {
      clients.forEach((client) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "client-typeahead-option";
        [
          ["name", client.full_name || "—"],
          ["phone", client.phone || "No phone"],
        ].forEach(([field, value]) => {
          const span = document.createElement("span");
          span.className = `client-typeahead-${field}`;
          span.textContent = value;
          span.title = value;
          button.append(span);
        });
        button.addEventListener("click", () => selectClientMatch(client));
        clientTypeaheadResults.append(button);
      });
    }
    clientTypeahead.hidden = false;
  };

  const searchClients = async (query) => {
    clientSearchRequest?.abort();
    clientSearchRequest = new AbortController();
    try {
      const url = new URL(calendar.dataset.clientSearchUrl, window.location.origin);
      url.searchParams.set("q", query);
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        signal: clientSearchRequest.signal,
      });
      const data = await parseJson(response);
      if (!response.ok) throw new Error(data.error || "Client search failed.");
      showClientMatches(data.clients || [], query);
    } catch (error) {
      if (error.name !== "AbortError") hideClientMatches();
    }
  };

  const queueClientSearch = (input) => {
    if (fillingClient || editingEvent) return;
    clientInput.value = "";
    if (bookingMenu) bookingMenu.hidden = true;
    if (cancelAppointmentButton) cancelAppointmentButton.hidden = true;
    clearTimeout(clientSearchTimer);
    const query = input.value.trim();
    if (query.length < 2) {
      hideClientMatches();
      return;
    }
    clientSearchTimer = window.setTimeout(() => searchClients(query), 220);
  };
  const toDate = (value) => new Date(`${value}T00:00:00`);
  const toInputDate = (value) => {
    const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 10);
  };
  const addDays = (value, amount) => {
    const next = new Date(value);
    next.setDate(next.getDate() + amount);
    return next;
  };
  const mondayFor = (value) => addDays(value, value.getDay() === 0 ? -6 : 1 - value.getDay());
  const minutes = (value) => {
    const [hour, minute] = String(value || "00:00").split(":").map(Number);
    return (hour * 60) + minute;
  };
  const timeValue = (value) => {
    const bounded = Math.max(0, Math.min((24 * 60) - 1, value));
    return `${String(Math.floor(bounded / 60)).padStart(2, "0")}:${String(bounded % 60).padStart(2, "0")}`;
  };
  const formatClock = (value, compact = false) => {
    const total = minutes(value);
    const hour24 = Math.floor(total / 60);
    const minute = total % 60;
    const hour12 = hour24 % 12 || 12;
    const suffix = hour24 < 12 ? "am" : "pm";
    return compact && minute === 0
      ? `${hour12}${suffix}`
      : `${hour12}:${String(minute).padStart(2, "0")} ${suffix}`;
  };
  const whatsappNumber = (value) => {
    let digits = String(value || "").replace(/\D/g, "");
    if (digits.startsWith("0")) digits = digits.slice(1);
    return digits.length === 10 ? `91${digits}` : digits;
  };
  const formatWhatsappDate = (value) => {
    const [year, month, day] = String(value || "").split("-").map(Number);
    if (!year || !month || !day) return String(value || "");
    return new Intl.DateTimeFormat("en-IN", {
      day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
    }).format(new Date(Date.UTC(year, month - 1, day)));
  };
  const openWhatsappConfirmation = (appointment) => {
    const number = whatsappNumber(appointment?.student_phone);
    if (!number || number.length < 10) {
      showError("Add a valid client phone number before sending a WhatsApp confirmation.");
      return;
    }
    const service = appointment.service_name || appointment.machine_category || appointment.machine_name || "Training";
    const equipment = appointment.machine_category || appointment.machine_name || "";
    const lines = [
      `Hello ${appointment.student_name || ""},`,
      "Your A2Z Institute training is confirmed.",
      `Service: ${service}`,
      `Date: ${formatWhatsappDate(appointment.date)}`,
      `Time: ${formatClock(appointment.start_time)} – ${formatClock(appointment.end_time)}`,
      `Instructor: ${appointment.instructor_name || ""}`,
    ];
    if (equipment && equipment !== service) lines.push(`Equipment: ${equipment}`);
    lines.push("Please arrive on time. Thank you.");
    lines.push("", "Note: Instructors may vary based on availability.");
    window.open(`https://wa.me/${number}?text=${encodeURIComponent(lines.join("\n"))}`, "_blank", "noopener");
  };
  const formatDay = (value, includeYear = false) => new Intl.DateTimeFormat("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(includeYear ? { year: "numeric" } : {}),
  }).format(value);
  const formatRange = (start, end) => (
    toInputDate(start) === toInputDate(end)
      ? formatDay(start, true)
      : `${formatDay(start)} – ${formatDay(end, true)}`
  );
  const compactScreen = () => window.matchMedia("(max-width: 720px)").matches;
  const announce = (text) => window.A2Z?.announce?.(text);
  const showError = (text) => {
    if (errorText) errorText.textContent = text;
    if (errorBox) {
      errorBox.hidden = false;
      errorBox.scrollIntoView({ block: "nearest" });
    }
  };
  const clearError = () => {
    if (errorBox) errorBox.hidden = true;
  };

  const mergeSavedEvents = (savedEvents = []) => {
    if (!savedEvents.length) return;
    const savedIds = new Set(savedEvents.map((item) => `${item.type || "appointment"}:${item.id}`));
    events = events.filter((item) => !savedIds.has(`${item.type || "appointment"}:${item.id}`));
    events.push(...savedEvents);
    events.sort((a, b) => (
      `${a.date || ""}-${a.start_time || ""}`
        .localeCompare(`${b.date || ""}-${b.start_time || ""}`)
    ));
    renderCalendar();
  };
  // Route templates may end at the ID (`.../0`) or continue with an action
  // (`.../0/permanent`). Replace the placeholder in both forms.
  const replaceId = (template, id) => template.replace(/\/0(?=\/|$)/, `/${id}`);
  const displayStatus = (status) => {
    if (status === "Approved") return "Confirmed";
    if (status === "Rejected") return "Declined";
    return status || "";
  };
  const repeatLabels = {
    daily: "Daily",
    weekdays: "Weekdays",
    mwf: "Monday, Wednesday & Friday",
    tuth: "Tuesday & Thursday",
    weekly: "Weekly",
    fortnightly: "Every 2 weeks",
    every_2_weeks: "Every 2 weeks",
    every_3_weeks: "Every 3 weeks",
    every_4_weeks: "Every 4 weeks",
    every_5_weeks: "Every 5 weeks",
    every_6_weeks: "Every 6 weeks",
    every_8_weeks: "Every 8 weeks",
    monthly: "Monthly",
    every_2_months: "Every 2 months",
    yearly: "Yearly",
  };
  const updateSeriesSummary = (event) => {
    if (!seriesSummary) return;
    if (!event?.series_id) {
      seriesSummary.hidden = true;
      seriesSummary.textContent = "";
      return;
    }
    const position = Math.max(1, Number(event.series_position || 1));
    const count = Math.max(position, Number(event.series_count || position));
    const rule = repeatLabels[event.repeat_rule] || "Repeating";
    seriesSummary.textContent = `Occurrence ${position} of ${count} · ${rule}`;
    seriesSummary.hidden = false;
  };
  const syncRepeatCount = (repeatControl, countControl) => {
    if (!(repeatControl instanceof HTMLSelectElement) || !(countControl instanceof HTMLInputElement)) return;
    const repeats = repeatControl.value !== "none";
    countControl.min = repeats ? "2" : "1";
    if (!repeats) {
      countControl.value = "1";
    } else if (Number(countControl.value || 0) < 2) {
      countControl.value = "2";
    }
  };

  const instructors = Array.from(instructorInput.options)
    .filter((option) => option.value)
    .map((option) => ({
      id: option.value,
      name: option.textContent.trim(),
      branchId: option.dataset.branchId || "",
      branchName: option.dataset.branchName || "",
    }));

  const syncInstructorFilterForBranch = () => {
    if (!(branchFilter instanceof HTMLSelectElement)) return;
    const branchId = String(branchFilter.value || "");
    Array.from(instructorFilter.options).forEach((option) => {
      if (!option.value) return;
      const allowed = !branchId || option.dataset.branchId === branchId;
      option.hidden = !allowed;
      option.disabled = !allowed;
      if (!allowed && option.selected) instructorFilter.value = "";
    });
  };

  const setAppointmentInstructor = (instructorId, branchId = "") => {
    const requestedId = String(instructorId || "");
    const instructor = instructors.find((item) => item.id === requestedId);
    appointmentInstructorId = instructor?.id || requestedId;
    appointmentBranchId = String(instructor?.branchId || branchId || "").trim();
    instructorInput.value = appointmentInstructorId;
    editor.dataset.appointmentBranchId = appointmentBranchId;
  };

  const period = () => {
    const anchor = toDate(dateInput.value);
    if (viewFilter.value === "week") {
      const start = mondayFor(anchor);
      return { start, end: addDays(start, 6) };
    }
    return { start: anchor, end: anchor };
  };

  const columnsForView = () => {
    const { start } = period();
    const selectedBranchId = branchFilter?.value || "";
    const branchInstructors = instructors.filter(
      (item) => !selectedBranchId || item.branchId === selectedBranchId,
    );
    if (viewFilter.value === "week") {
      let instructorId = instructorFilter.value;
      if (!instructorId && branchInstructors.length) {
        instructorId = branchInstructors[0].id;
        instructorFilter.value = instructorId;
      }
      const instructor = branchInstructors.find((item) => item.id === instructorId);
      if (!instructor) return [];
      return Array.from({ length: 7 }, (_, index) => {
        const target = addDays(start, index);
        return {
          date: toInputDate(target),
          instructorId: instructor.id,
          title: formatDay(target),
          subtitle: instructor.name,
          branchId: instructor.branchId,
          branchName: instructor.branchName,
          nonWorking: false,
        };
      });
    }
    const targetDate = toInputDate(start);
    const visible = branchInstructors.filter(
      (item) => !instructorFilter.value || item.id === instructorFilter.value,
    );
    return visible.map((instructor) => ({
      date: targetDate,
      instructorId: instructor.id,
      title: instructor.name,
      subtitle: formatDay(start),
      branchId: instructor.branchId,
      branchName: instructor.branchName,
      nonWorking: false,
    }));
  };

  const timeSlots = () => {
    const slots = [];
    for (let value = STAFF_DAY_START; value < STAFF_DAY_END; value += 15) slots.push(timeValue(value));
    return slots;
  };

  const visibleEventRange = (event) => {
    const start = Math.max(STAFF_DAY_START, minutes(event.start_time));
    const end = Math.min(STAFF_DAY_END, minutes(event.end_time));
    return end > start ? { start, end } : null;
  };
  const eventSlotStart = (event) => {
    const range = visibleEventRange(event);
    return range ? timeValue(Math.floor(range.start / 15) * 15) : null;
  };
  const eventClass = (event) => {
    const range = visibleEventRange(event);
    const durationSteps = Math.max(
      1,
      Math.min(48, Math.ceil(((range?.end || 15) - (range?.start || 0)) / 15)),
    );
    const status = String(event.status || "busy").toLowerCase().replace(/[^a-z]+/g, "-");
    return `calendar-event duration-${durationSteps} event-status-${status}${event.type === "busy" ? " calendar-busy-event" : ""}${event.type === "slot" ? " calendar-booking-slot" : ""}`;
  };

  const instructorEventColour = (instructorId) => {
    const text = String(instructorId || "");
    let hash = 0;
    for (let index = 0; index < text.length; index += 1) {
      hash = ((hash * 31) + text.charCodeAt(index)) >>> 0;
    }
    return INSTRUCTOR_EVENT_COLOURS[hash % INSTRUCTOR_EVENT_COLOURS.length];
  };

  const branchColour = (branchId) => {
    const palette = ["#185FA5", "#0F766E", "#9A3412", "#6D28D9", "#A21CAF"];
    const text = String(branchId || "");
    let hash = 0;
    for (let index = 0; index < text.length; index += 1) {
      hash = ((hash * 31) + text.charCodeAt(index)) >>> 0;
    }
    return palette[hash % palette.length];
  };

  const assignOverlapLanes = (columnEvents, hasBookingSlot) => {
    const appointments = columnEvents
      .filter((item) => item.type === "appointment")
      .sort((a, b) => minutes(a.start_time) - minutes(b.start_time)
        || minutes(a.end_time) - minutes(b.end_time));
    let group = [];
    let groupEnd = -1;
    const finishGroup = () => {
      if (!group.length) return;
      const laneEnds = [];
      let laneCount = 1;
      group.forEach((item) => {
        const start = minutes(item.start_time);
        let lane = laneEnds.findIndex((end) => end <= start);
        if (lane < 0) lane = laneEnds.length;
        laneEnds[lane] = minutes(item.end_time);
        item._calendarLane = lane;
        laneCount = Math.max(laneCount, laneEnds.length);
      });
      const base = hasBookingSlot ? 32 : 0;
      const available = 100 - base;
      group.forEach((item) => {
        // Smart Scheduling places the original appointment on the right and
        // grows approved double bookings toward the left.
        const displayLane = laneCount - 1 - item._calendarLane;
        item._calendarLaneCount = laneCount;
        item._calendarLeft = base + (available * displayLane / laneCount);
        item._calendarRight = 100 - (base + (available * (displayLane + 1) / laneCount));
      });
      group = [];
    };
    appointments.forEach((item) => {
      const start = minutes(item.start_time);
      if (group.length && start >= groupEnd) finishGroup();
      group.push(item);
      groupEnd = Math.max(groupEnd, minutes(item.end_time));
    });
    finishGroup();
  };

  const setServiceSelection = (ids) => {
    const selected = new Set((ids || []).map(String));
    serviceChecks.forEach((input) => {
      input.checked = selected.has(input.value);
    });
    if (legacyServices instanceof HTMLSelectElement) {
      Array.from(legacyServices.options).forEach((option) => {
        option.selected = selected.has(option.value);
      });
    }
  };
  const selectedServices = () => serviceChecks.filter((input) => input.checked && !input.disabled);
  const selectedServiceIds = () => selectedServices().map((input) => Number(input.value));
  const updateServiceTrigger = () => {
    if (!serviceTriggerTitle) return;
    const selected = selectedServices();
    serviceTriggerTitle.textContent = selected.length
      ? selected.map((input) => input.closest("label")?.querySelector("strong")?.textContent?.trim()).filter(Boolean).join(", ")
      : "Click here to choose services";
  };

  const setEditorType = (type) => {
    editorType = ["busy", "slot"].includes(type) ? type : "appointment";
    editor.querySelectorAll("[data-editor-tab]").forEach((tab) => {
      const selected = tab.dataset.editorTab === editorType;
      tab.classList.toggle("is-active", selected);
      tab.setAttribute("aria-selected", String(selected));
    });
    editor.querySelectorAll("[data-editor-panel]").forEach((panel) => {
      const selected = panel.dataset.editorPanel === editorType;
      panel.hidden = !selected;
      panel.querySelectorAll("input, select, textarea, button").forEach((control) => {
        if (!control.matches("[data-editor-close], [data-editor-tab]")) control.disabled = !selected;
      });
    });
    if (saveButton) saveButton.textContent = editorType === "busy" ? "Save busy time" : editorType === "slot" ? "Save slot" : "Save appointment";
  };

  const syncSlotMachines = () => {
    const branchId = slotInstructor?.selectedOptions[0]?.dataset.branchId || "";
    Array.from(slotMachine?.options || []).forEach((option, index) => {
      if (index === 0) return;
      const allowed = !branchId || option.dataset.branchId === branchId;
      option.hidden = !allowed;
      option.disabled = !allowed;
      if (!allowed && option.selected) slotMachine.value = "";
    });
  };

  const syncMachines = () => {
    const branchId = appointmentBranchId
      || instructorInput.selectedOptions[0]?.dataset.branchId
      || "";
    let compatible = null;
    selectedServices().forEach((service) => {
      const ids = new Set((service.dataset.machineIds || "").split(",").filter(Boolean));
      if (!ids.size) return;
      compatible = compatible === null
        ? ids
        : new Set([...compatible].filter((id) => ids.has(id)));
    });
    const allowedOptions = [];
    Array.from(machineInput.options).forEach((option, index) => {
      if (index === 0) return;
      const allowed = (!branchId || option.dataset.branchId === branchId)
        && (compatible === null || compatible.has(option.value));
      option.hidden = !allowed;
      option.disabled = !allowed;
      if (allowed) allowedOptions.push(option);
      if (!allowed && option.selected) machineInput.value = "";
    });
    if (!machineInput.value && allowedOptions.length) machineInput.value = allowedOptions[0].value;
  };

  const syncEditorOptions = () => {
    const normaliseBranch = (value) => String(value || "").trim();
    const instructorBranch = normaliseBranch(
      appointmentBranchId
      || instructorInput.selectedOptions[0]?.dataset.branchId
      || editor.dataset.appointmentBranchId,
    );
    const clientBranch = normaliseBranch(clientInput.selectedOptions[0]?.dataset.branchId);
    const branchId = instructorBranch || clientBranch;

    Array.from(clientInput.options).forEach((option, index) => {
      if (index === 0) return;
      const allowed = !instructorBranch || normaliseBranch(option.dataset.branchId) === instructorBranch;
      option.hidden = !allowed;
      option.disabled = !allowed;
      if (!allowed && option.selected) clientInput.value = "";
    });
    // Do not filter or clear the instructor from client data. The clicked
    // calendar column wins; a client from another branch is cleared above.
    Array.from(instructorInput.options).forEach((option, index) => {
      if (index === 0) return;
      option.hidden = false;
      option.disabled = false;
    });
    if (appointmentInstructorId) instructorInput.value = appointmentInstructorId;
    serviceChecks.forEach((input) => {
      // Staff-managed appointments can be transferred to another instructor.
      // Keep the service when both records belong to the same branch.
      const allowed = !branchId || normaliseBranch(input.dataset.branchId) === branchId;
      input.disabled = !allowed;
      input.closest("label")?.toggleAttribute("hidden", !allowed);
      if (!allowed) input.checked = false;
    });
    editor.querySelectorAll("[data-service-picker-group]").forEach((group) => {
      const hasAvailableService = Array.from(group.querySelectorAll("[data-editor-service]"))
        .some((input) => !input.disabled);
      group.hidden = !hasAvailableService;
    });
    if (servicePickerEmpty) {
      servicePickerEmpty.hidden = serviceChecks.some((input) => !input.disabled);
    }
    syncMachines();
    updateDuration();
  };

  const updateDuration = ({ useServicePadding = false } = {}) => {
    const selected = selectedServices();
    const duration = selected.reduce((total, input) => total + Number(input.dataset.duration || 0), 0);
    if (durationText) durationText.textContent = duration ? `${duration} minutes` : "Choose services";
    if (endTimeText) endTimeText.textContent = "";
    if (useServicePadding && selected.length) {
      if (bufferBefore) bufferBefore.value = selected[0].dataset.bufferBefore || "0";
      if (bufferAfter) bufferAfter.value = selected[selected.length - 1].dataset.bufferAfter || "0";
    }
    if (legacyServices instanceof HTMLSelectElement) {
      const selectedIds = new Set(selected.map((input) => input.value));
      Array.from(legacyServices.options).forEach((option) => {
        option.selected = selectedIds.has(option.value);
      });
    }
    updateServiceTrigger();
  };

  const isTrailerBooking = () => {
    const selectedServiceNames = selectedServices().map((input) => (
      input.closest("label")?.querySelector("strong")?.textContent || ""
    ));
    const machineName = machineInput.selectedOptions[0]?.textContent || "";
    return [...selectedServiceNames, machineName].some((name) => (
      /(?:\b20\s*TRAILER\b|\bJEEP\s*TRAILER\b|\bTRAILER\b)/i.test(name)
    ));
  };

  const applyTrailerDefaultFinish = () => {
    if (bookingIdInput.value || editorType !== "appointment" || !isTrailerBooking()) return;
    const finish = minutes(editorStart.value) + 30;
    if (editorEnd instanceof HTMLSelectElement && finish <= STAFF_DAY_END) {
      editorEnd.value = timeValue(finish);
      trailerFinishAuto = true;
    }
  };

  const populateAppointment = (event) => {
    bookingIdInput.value = event.id;
    revisionInput.value = event.revision || "";
    clientInput.value = String(event.client_id || event.student_user_id || "");
    setAppointmentInstructor(event.instructor_id, event.branch_id);
    machineInput.value = String(event.machine_id || "");
    editorDate.value = event.date;
    editorStart.value = event.start_time;
    if (editorEnd) editorEnd.value = event.end_time;
    if (editorStatus) {
      // Instructors use their own three-state workflow.  An existing
      // Confirmed/Approved booking appears as No Action until the instructor
      // chooses a follow-up status.
      const instructorStatus = event.status === "Approved" ? "No Action" : event.status;
      editorStatus.value = currentRole === "instructor"
        ? (["No Action", "Pending", "Completed"].includes(instructorStatus) ? instructorStatus : "No Action")
        : (event.status || "Approved");
    }
    if (editorNotes) editorNotes.value = event.notes || "";
    const firstNameInput = editor.querySelector("[data-new-client-first-name]");
    const lastNameInput = editor.querySelector("[data-new-client-last-name]");
    const phoneInput = editor.querySelector("[data-new-client-phone]");
    const emailInput = editor.querySelector("[data-new-client-email]");
    if (firstNameInput) firstNameInput.value = event.student_name || "";
    if (lastNameInput) lastNameInput.value = event.admission_number || "";
    if (phoneInput) phoneInput.value = event.student_phone || "";
    if (emailInput) emailInput.value = event.student_email || "";
    if (bufferBefore) bufferBefore.value = String(event.buffer_before_minutes || 0);
    if (bufferAfter) bufferAfter.value = String(event.buffer_after_minutes || 0);
    if (allowDoubleBooking) allowDoubleBooking.checked = Boolean(event.allow_double_booking);
    if (repeatInput) repeatInput.value = "none";
    if (repeatCount) repeatCount.value = "1";
    if (allowDoubleBooking) allowDoubleBooking.checked = false;
    setServiceSelection([]);
    syncEditorOptions();
    setServiceSelection(event.service_ids?.length ? event.service_ids : [event.service_id].filter(Boolean));
    syncMachines();
    updateDuration();
    if (serviceTotal) {
      serviceTotal.hidden = false;
      serviceTotal.textContent = `Total: ₹${(Number(event.service_price_cents || 0) / 100).toFixed(2)}`;
    }
    const clientUrl = replaceId(calendar.dataset.clientUrlTemplate || "", event.student_user_id || event.client_id || 0);
    if (clientDetailsLink) clientDetailsLink.href = `${clientUrl}#upcoming-title`;
    if (clientNotesLink) clientNotesLink.href = `${clientUrl}#client-notes`;
    whatsappConfirmationEvent = event;
    if (whatsappConfirmationButton) {
      whatsappConfirmationButton.hidden = !String(event.student_phone || "").trim();
    }
    syncRepeatCount(repeatInput, repeatCount);

    if (existingSummary) {
      existingSummary.hidden = false;
      existingSummary.querySelector("[data-editor-summary-client]").textContent = event.student_name || "Client";
      existingSummary.querySelector("[data-editor-summary-service]").textContent = event.service_name || "Appointment";
      existingSummary.querySelector("[data-editor-summary-status]").textContent = displayStatus(event.status);
      const summaryPhone = existingSummary.querySelector("[data-editor-summary-phone]");
      if (summaryPhone) {
        const phone = String(event.student_phone || "").trim();
        summaryPhone.textContent = phone || "No phone on file";
        summaryPhone.href = phone ? `tel:${phone.replace(/[^+\d]/g, "")}` : "#";
        summaryPhone.toggleAttribute("aria-disabled", !phone);
      }
      const paddingSummary = existingSummary.querySelector("[data-editor-summary-padding]");
      if (paddingSummary) {
        paddingSummary.textContent =
          `${event.buffer_before_minutes || 0} min before · ${event.buffer_after_minutes || 0} min after`;
      }
    }
  };

  const prepareNewEditor = (
    targetDate,
    instructorId,
    start,
    trigger,
    initialType = "appointment",
    selectedClientId = "",
    bookingSlot = null,
  ) => {
    if (currentRole === "instructor") {
      const isOwnSlot = initialType === "slot"
        && canManageOwnSlots
        && String(instructorId || "") === currentInstructorId;
      if (!isOwnSlot) return;
    }
    lastFocused = trigger || document.activeElement;
    editingEvent = null;
    whatsappConfirmationEvent = null;
    editor.reset();
    trailerFinishAuto = false;
    clearError();
    bookingIdInput.value = "";
    revisionInput.value = "";
    updateSeriesSummary(null);
    if (existingSummary) existingSummary.hidden = true;
    if (whatsappConfirmationButton) whatsappConfirmationButton.hidden = true;
    setServiceSelection([]);
    setAppointmentInstructor(instructorId || instructorFilter.value || instructors[0]?.id || "");
    clientInput.value = String(selectedClientId || "");
    editorDate.value = targetDate || dateInput.value;
    editorStart.value = start || "09:00";
    if (editorEnd instanceof HTMLSelectElement) {
      editorEnd.value = timeValue(Math.min(STAFF_DAY_END, minutes(editorStart.value) + 15));
    }
    if (editorStatus) editorStatus.value = "Approved";
    if (repeatInput) repeatInput.value = "none";
    if (repeatCount) repeatCount.value = "1";
    syncRepeatCount(repeatInput, repeatCount);
    if (busyInstructor) busyInstructor.value = instructorInput.value;
    if (busyKind) busyKind.value = "breakfast";
    if (busyDate) busyDate.value = editorDate.value;
    if (busyStart) busyStart.value = editorStart.value;
    if (busyEnd) busyEnd.value = timeValue(Math.min(STAFF_DAY_END, minutes(editorStart.value) + 60));
    if (busyRepeat) busyRepeat.value = "none";
    if (busyRepeatCount) busyRepeatCount.value = "1";
    syncRepeatCount(busyRepeat, busyRepeatCount);
    if (slotInstructor) slotInstructor.value = instructorInput.value;
    if (slotDate) slotDate.value = editorDate.value;
    if (slotStart) slotStart.value = editorStart.value;
    if (slotEnd) slotEnd.value = timeValue(Math.min(STAFF_DAY_END, minutes(editorStart.value) + 60));
    if (slotRepeat) slotRepeat.value = "none";
    if (slotRepeatCount) slotRepeatCount.value = "1";
    if (slotNotes) slotNotes.value = "";
    syncSlotMachines();
    syncRepeatCount(slotRepeat, slotRepeatCount);
    if (eyebrowText) eyebrowText.textContent = "New schedule item";
    if (titleText) titleText.textContent = initialType === "busy"
      ? "Add busy time"
      : initialType === "slot" ? "Add booking slot" : "Add appointment";
    if (descriptionText) {
      descriptionText.textContent = initialType === "busy"
        ? "Block time that staff should not use for appointments."
        : initialType === "slot"
          ? "Mark equipment availability on your own calendar."
          : "Create a confirmed appointment while speaking with the client.";
    }
    if (cancelAppointmentButton) cancelAppointmentButton.hidden = true;
    if (permanentDeleteButton) permanentDeleteButton.hidden = true;
    if (bookingMenu) bookingMenu.hidden = true;
    if (serviceTotal) serviceTotal.hidden = true;
    if (deleteBusyButton) deleteBusyButton.hidden = true;
    if (deleteUpcomingBusyButton) deleteUpcomingBusyButton.hidden = true;
    if (deleteBusyForAllButton) deleteBusyForAllButton.hidden = true;
    if (deleteSlotButton) deleteSlotButton.hidden = true;
    if (saveButton) saveButton.hidden = false;
    setEditorType(initialType);
    syncEditorOptions();
    if (currentRole === "instructor" && slotInstructor) slotInstructor.disabled = true;
    if (initialType === "appointment" && bookingSlot) {
      const machineId = String(bookingSlot.machine_id || "");
      const normalise = (value) => String(value || "")
        .toLowerCase()
        .replace(/practical|training|test|practice/g, "")
        .replace(/[^a-z0-9]+/g, "");
      const slotNames = [bookingSlot.machine_name, bookingSlot.machine_category]
        .map(normalise)
        .filter(Boolean);
      const candidates = serviceChecks.filter((input) => (
        !input.disabled
        && new Set((input.dataset.machineIds || "").split(",").filter(Boolean)).has(machineId)
      ));
      const score = (input) => {
        const serviceName = normalise(input.closest("label")?.querySelector("strong")?.textContent);
        return Math.max(0, ...slotNames.map((slotName) => (
          serviceName === slotName ? 100 : serviceName.includes(slotName) ? 80 : slotName.includes(serviceName) ? 70 : 0
        )));
      };
      const matchingService = candidates.sort((left, right) => score(right) - score(left))[0];
      if (matchingService) matchingService.checked = true;
      syncMachines();
      const machineOption = Array.from(machineInput.options).find((option) => option.value === machineId && !option.disabled);
      if (machineOption) machineInput.value = machineId;
    }
    updateDuration();
    applyTrailerDefaultFinish();
    dialog.showModal();
  };

  const openInitialClientEditor = () => {
    const selectedClientId = calendar.dataset.selectedClient || calendar.dataset.initialClientId || "";
    if (!selectedClientId || initialClientHandled) return;
    initialClientHandled = true;
    const clientOption = Array.from(clientInput.options).find(
      (option) => option.value === String(selectedClientId),
    );
    if (!clientOption) return;
    const branchId = clientOption.dataset.branchId || "";
    const currentInstructor = instructors.find((item) => (
      item.id === instructorFilter.value && (!branchId || item.branchId === branchId)
    ));
    const preferredInstructor = currentInstructor
      || instructors.find((item) => !branchId || item.branchId === branchId)
      || instructors[0];
    prepareNewEditor(
      dateInput.value,
      preferredInstructor?.id || "",
      "09:00",
      document.querySelector("[data-add-appointment]"),
      "appointment",
      selectedClientId,
    );
  };

  const openEditorForEvent = (event, trigger) => {
    lastFocused = trigger || document.activeElement;
    editingEvent = event;
    editor.reset();
    clearError();
    updateSeriesSummary(event);
    if (event.type === "slot") {
      bookingIdInput.value = String(event.id);
      revisionInput.value = String(event.revision || "");
      if (slotInstructor) slotInstructor.value = String(event.instructor_id);
      if (slotMachine) slotMachine.value = String(event.machine_id);
      if (slotDate) slotDate.value = event.date;
      if (slotStart) slotStart.value = event.start_time;
      if (slotEnd) slotEnd.value = event.end_time;
      if (slotNotes) slotNotes.value = event.notes || "";
      if (slotRepeat) slotRepeat.value = "none";
      if (slotRepeatCount) slotRepeatCount.value = "1";
      syncSlotMachines();
      if (eyebrowText) eyebrowText.textContent = "Booking slot";
      if (titleText) titleText.textContent = event.title || "Edit booking slot";
      if (descriptionText) descriptionText.textContent = "Appointments remain bookable inside this slot band.";
      if (cancelAppointmentButton) cancelAppointmentButton.hidden = true;
      if (permanentDeleteButton) permanentDeleteButton.hidden = true;
      if (bookingMenu) bookingMenu.hidden = true;
      if (deleteBusyButton) deleteBusyButton.hidden = true;
      if (deleteUpcomingBusyButton) deleteUpcomingBusyButton.hidden = true;
      if (deleteBusyForAllButton) deleteBusyForAllButton.hidden = true;
      if (deleteSlotButton) deleteSlotButton.hidden = !event.can_edit;
      if (saveButton) saveButton.hidden = !event.can_edit;
      setEditorType("slot");
      if (currentRole === "instructor" && slotInstructor) slotInstructor.disabled = true;
    } else if (event.type === "busy") {
      bookingIdInput.value = String(event.id);
      revisionInput.value = String(event.revision || "");
      if (busyInstructor) busyInstructor.value = String(event.instructor_id);
      if (busyDate) busyDate.value = event.date;
      if (busyStart) busyStart.value = event.start_time;
      if (busyEnd) busyEnd.value = event.end_time;
      if (busyKind) busyKind.value = event.busy_kind || "busy";
      if (busyTitle) busyTitle.value = event.title || "Busy";
      if (busyNotes) busyNotes.value = event.notes || "";
      if (busyRepeat) busyRepeat.value = "none";
      if (busyRepeatCount) busyRepeatCount.value = "1";
      syncRepeatCount(busyRepeat, busyRepeatCount);
      if (eyebrowText) eyebrowText.textContent = "Busy time";
      if (titleText) titleText.textContent = event.title || "Busy time";
      if (descriptionText) descriptionText.textContent = "This time is unavailable for appointments.";
      if (cancelAppointmentButton) cancelAppointmentButton.hidden = true;
      if (permanentDeleteButton) permanentDeleteButton.hidden = true;
      if (bookingMenu) bookingMenu.hidden = true;
      if (deleteBusyButton) deleteBusyButton.hidden = !event.can_edit;
      if (deleteUpcomingBusyButton) deleteUpcomingBusyButton.hidden = !event.can_edit;
      if (deleteBusyForAllButton) {
        deleteBusyForAllButton.hidden = !event.can_edit
          || !["breakfast", "lunch", "tea"].includes(event.busy_kind);
      }
      if (deleteSlotButton) deleteSlotButton.hidden = true;
      if (saveButton) saveButton.hidden = !event.can_edit;
      setEditorType("busy");
      if (!event.can_edit) {
        editor.querySelectorAll('[data-editor-panel="busy"] input, [data-editor-panel="busy"] select, [data-editor-panel="busy"] textarea, [data-editor-panel="busy"] button').forEach((control) => {
          control.disabled = true;
        });
      }
    } else {
      populateAppointment(event);
      if (eyebrowText) eyebrowText.textContent = `Appointment #${event.id}`;
      if (titleText) titleText.textContent = "Edit appointment";
      if (descriptionText) descriptionText.textContent = "Update the client, services, staff, time, status, or private notes.";
      if (cancelAppointmentButton) {
        cancelAppointmentButton.hidden = !event.can_edit || ![
          "Approved", "Pending", "Not Confirmed", "Running Late", "Arrived", "Rescheduled",
        ].includes(event.status);
      }
      if (bookingMenu) bookingMenu.hidden = !event.can_edit;
      if (deleteBusyButton) deleteBusyButton.hidden = true;
      if (deleteUpcomingBusyButton) deleteUpcomingBusyButton.hidden = true;
      if (deleteBusyForAllButton) deleteBusyForAllButton.hidden = true;
      if (deleteSlotButton) deleteSlotButton.hidden = true;
      if (saveButton) {
        saveButton.hidden = !event.can_edit && !event.can_update_status;
        if (currentRole === "instructor") saveButton.textContent = "Save status";
      }
      if (permanentDeleteButton) permanentDeleteButton.hidden = currentRole !== "admin";
      setEditorType("appointment");
      if (!event.can_edit) {
        if (titleText) titleText.textContent = "Appointment details";
        if (descriptionText) descriptionText.textContent = "View the active customer details needed for follow-up.";
        editor.querySelectorAll('[data-editor-panel="appointment"] input, [data-editor-panel="appointment"] select, [data-editor-panel="appointment"] textarea, [data-editor-panel="appointment"] button').forEach((control) => {
          control.disabled = true;
        });
        if (currentRole === "instructor" && event.can_update_status && editorStatus) {
          editorStatus.disabled = false;
          if (saveButton) saveButton.disabled = false;
        }
      }
    }
    dialog.showModal();
  };

  const createEventButton = (event) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = eventClass(event);
    const isBusy = event.type === "busy";
    const isSlot = event.type === "slot";
    const canStartDoubleBooking = Boolean(event.can_edit)
      && !isBusy
      && !isSlot
      && ["admin", "booking_agent"].includes(currentRole)
      && !["Cancelled", "Rejected", "Completed", "No-show"].includes(event.status);
    const canDragEvent = Boolean(event.can_edit) && (
      event.type === "appointment"
      || (isSlot && (currentRole === "admin" || canManageOwnSlots))
      || (isBusy && currentRole === "admin")
    );
    button.draggable = false;
    button.classList.toggle("is-movable", canDragEvent);
    button.dataset.eventId = event.id;
    button.style.setProperty(
      "--event-colour",
      !isBusy && !isSlot
        ? instructorEventColour(event.instructor_id)
        : (event.service_color || "#667085"),
    );
    const range = visibleEventRange(event) || {
      start: minutes(event.start_time),
      end: minutes(event.end_time),
    };
    const offsetMinutes = ((range.start % 15) + 15) % 15;
    button.style.setProperty(
      "--event-offset",
      `calc(${offsetMinutes / 15} * var(--calendar-quarter-height))`,
    );
    const durationMinutes = Math.max(5, range.end - range.start);
    const isShortAppointment = !isBusy && !isSlot && durationMinutes <= 15;
    button.style.setProperty(
      "--event-duration",
      `calc(${durationMinutes / 15} * var(--calendar-quarter-height))`,
    );
    if (isSlot && !event.can_edit) {
      button.setAttribute("aria-readonly", "true");
      button.title = "Book an appointment in this admin-managed slot";
    }
    if (!isBusy && !isSlot && Number.isFinite(event._calendarLeft)) {
      button.style.left = `calc(${event._calendarLeft}% + 2px)`;
      button.style.right = `calc(${event._calendarRight}% + 2px)`;
      if ((event._calendarLaneCount || 1) > 1) button.classList.add("is-overlapping");
    }
    button.innerHTML = `
      <span class="calendar-event-time"></span>
      <strong class="calendar-event-client"></strong>
      <span class="calendar-event-service"></span>
      <small class="calendar-event-status"></small>
      ${canStartDoubleBooking ? `<span class="calendar-event-double-book${isShortAppointment ? " is-compact" : ""}" title="Add another booking at this time">${isShortAppointment ? "+" : "+ Book"}</span>` : ''}
      ${canDragEvent ? `<span class="calendar-event-resize" title="Drag to change ${isSlot ? "slot" : isBusy ? "busy time" : "appointment"} duration" aria-label="Resize ${isSlot ? "booking slot" : isBusy ? "busy time" : "appointment"}"></span>` : ''}
    `;
    button.querySelector(".calendar-event-client").textContent =
      isBusy || isSlot ? (event.title || "Booking slot") : (event.student_name || "Client");
    button.querySelector(".calendar-event-time").textContent = (
      event.type === "busy"
      && event.start_time === "00:00"
      && event.end_time === "23:59"
    ) ? "All day" : `${formatClock(event.start_time)} – ${formatClock(event.end_time)}`;
    button.querySelector(".calendar-event-service").textContent = isSlot ? "Available for booking" : isBusy
      ? (event.instructor_name || "Unavailable")
      : (event.machine_category || event.machine_name || event.service_name || "Equipment");
    button.querySelector(".calendar-event-status").textContent = isSlot ? "" : isBusy
      ? "Unavailable"
      : (event.student_phone || "No phone");
    button.setAttribute(
      "aria-label",
      isBusy || isSlot
        ? `${event.title || "Busy time"}, ${event.start_time} to ${event.end_time}`
        : `${event.student_name}, ${event.machine_category || event.machine_name || event.service_name || "equipment"}, ${event.student_phone || "no phone"}, ${event.start_time} to ${event.end_time}`,
    );
    button.addEventListener("click", (clickEvent) => {
      clickEvent.stopPropagation();
      if (Date.now() < suppressEventClickUntil) return;
      if (canStartDoubleBooking && clickEvent.target.closest(".calendar-event-double-book")) {
        prepareNewEditor(
          event.date,
          event.instructor_id,
          event.start_time,
          button,
          "appointment",
          "",
          event,
        );
        return;
      }
      if (isSlot && currentRole === "booking_agent") {
        prepareNewEditor(
          event.date,
          event.instructor_id,
          event.start_time,
          button,
          "appointment",
          "",
          event,
        );
        return;
      }
      if (isSlot && currentRole === "instructor" && !event.can_edit) return;
      openEditorForEvent(event, button);
    });
    if (canDragEvent) {
      button.addEventListener("pointerdown", (pointerEvent) => {
        if (
          pointerEvent.button !== 0
          || moveInFlight
          || resizingEventId !== null
          || pointerEvent.target.closest(".calendar-event-resize")
        ) return;
        activePointerDragCleanup?.();
        // Do not prevent the normal pointer-down action here.  It keeps a
        // simple click reliable for opening an appointment; preventDefault is
        // used only after the user has deliberately moved far enough to drag.
        if (pointerEvent.target.closest(".calendar-event-double-book")) return;
        const originX = pointerEvent.clientX;
        const originY = pointerEvent.clientY;
        const duration = Math.max(15, minutes(event.end_time) - minutes(event.start_time));
        let started = false;
        const requiresLongPress = pointerEvent.pointerType === "touch";
        let dragArmed = !requiresLongPress;
        let longPressTimer = null;
        let targetSlot = null;

        if (requiresLongPress) {
          longPressTimer = window.setTimeout(() => {
            dragArmed = true;
          }, 450);
        }

        const clearTarget = () => {
          targetSlot?.classList.remove("is-drop-target");
          targetSlot = null;
        };
        const cleanup = () => {
          window.clearTimeout(longPressTimer);
          window.removeEventListener("pointermove", movePointer);
          window.removeEventListener("pointerup", finishPointer);
          window.removeEventListener("pointercancel", cancelPointer);
          clearTarget();
          draggedEvent = null;
          calendarScroll?.classList.remove("is-event-dragging");
          button.classList.remove("is-dragging");
          dragTimePreview?.remove();
          dragTimePreview = null;
          if (activePointerDragCleanup === cleanup) activePointerDragCleanup = null;
        };
        const movePointer = (moveEvent) => {
          const distance = Math.hypot(moveEvent.clientX - originX, moveEvent.clientY - originY);
          // Touch screens need an intentional press-and-hold before a booking
          // can move. A normal swipe stays available for scrolling and a tap
          // still opens the booking editor.
          if (!dragArmed) {
            if (distance >= 9) window.clearTimeout(longPressTimer);
            return;
          }
          if (!started && distance < 7) return;
          if (!started) {
            started = true;
            draggedEvent = event;
            calendarScroll?.classList.add("is-event-dragging");
            button.classList.add("is-dragging");
            dragTimePreview = document.createElement("div");
            dragTimePreview.className = "calendar-drag-time-preview";
            document.body.append(dragTimePreview);
          }
          moveEvent.preventDefault();
          const bounds = calendarScroll?.getBoundingClientRect();
          if (bounds && calendarScroll) {
            const horizontalEdge = Math.min(90, bounds.width * 0.1);
            const verticalEdge = Math.min(70, bounds.height * 0.1);
            if (moveEvent.clientX < bounds.left + horizontalEdge) calendarScroll.scrollLeft -= 22;
            else if (moveEvent.clientX > bounds.right - horizontalEdge) calendarScroll.scrollLeft += 22;
            if (moveEvent.clientY < bounds.top + verticalEdge) calendarScroll.scrollTop -= 18;
            else if (moveEvent.clientY > bounds.bottom - verticalEdge) calendarScroll.scrollTop += 18;
          }
          const candidate = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY)?.closest(".calendar-slot");
          const candidateStart = candidate?.dataset.dropStart || "";
          const valid = Boolean(
            candidate
            && !candidate.classList.contains("is-non-working")
            && candidate.dataset.dropDate
            && candidate.dataset.dropInstructorId
            && minutes(candidateStart) + duration <= STAFF_DAY_END
          );
          if (candidate !== targetSlot) clearTarget();
          if (valid) {
            targetSlot = candidate;
            targetSlot.classList.add("is-drop-target");
            const finish = timeValue(minutes(candidateStart) + duration);
            if (dragTimePreview) {
              dragTimePreview.textContent = `${formatClock(candidateStart)} – ${formatClock(finish)}`;
              dragTimePreview.style.left = `${moveEvent.clientX + 14}px`;
              dragTimePreview.style.top = `${moveEvent.clientY + 14}px`;
            }
          }
        };
        const finishPointer = (finishEvent) => {
          const destination = targetSlot;
          const wasStarted = started;
          cleanup(finishEvent);
          if (!wasStarted) return;
          suppressEventClickUntil = Date.now() + 400;
          if (!destination) return;
          const targetDate = destination.dataset.dropDate;
          const targetInstructorId = destination.dataset.dropInstructorId;
          const targetStart = destination.dataset.dropStart;
          const destinationBookingSlot = events.find((item) => (
            item.type === "slot"
            && item.date === targetDate
            && String(item.instructor_id) === String(targetInstructorId)
            && minutes(item.start_time) <= minutes(targetStart)
            && minutes(item.end_time) > minutes(targetStart)
          ));
          void moveEvent(event, {
            date: targetDate,
            instructorId: targetInstructorId,
            start: targetStart,
            ...(event.type === "appointment" && destinationBookingSlot
              ? { machineId: destinationBookingSlot.machine_id }
              : {}),
            ...(event.type === "slot" ? { end: timeValue(minutes(targetStart) + duration) } : {}),
          });
        };
        const cancelPointer = (cancelEvent) => cleanup(cancelEvent);
        activePointerDragCleanup = cleanup;
        window.addEventListener("pointermove", movePointer, { passive: false });
        window.addEventListener("pointerup", finishPointer, { once: true });
        window.addEventListener("pointercancel", cancelPointer, { once: true });
      });
      button.addEventListener("dragstart", (dragEvent) => {
        // Native HTML dragging behaves inconsistently across Chromium builds.
        dragEvent.preventDefault();
      });
      button.addEventListener("dragend", () => {
        draggedEvent = null;
        calendarScroll?.classList.remove("is-event-dragging");
        button.classList.remove("is-dragging");
        dragTimePreview?.remove();
        dragTimePreview = null;
      });
      const resizeHandle = button.querySelector(".calendar-event-resize");
      resizeHandle?.setAttribute("draggable", "false");
      resizeHandle?.addEventListener("pointerdown", (pointerEvent) => {
        pointerEvent.preventDefault();
        pointerEvent.stopPropagation();
        if (moveInFlight || resizingEventId !== null) return;
        resizingEventId = event.id;
        const originY = pointerEvent.clientY;
        const originalEnd = minutes(event.end_time);
        const slotHeight = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--calendar-quarter-height")) || 21;
        let nextEnd = originalEnd;
        let didResize = false;
        const requiresLongPress = pointerEvent.pointerType === "touch";
        let resizeArmed = !requiresLongPress;
        let resizeLongPressTimer = null;
        if (requiresLongPress) {
          resizeLongPressTimer = window.setTimeout(() => {
            resizeArmed = true;
          }, 450);
        }
        resizeHandle.setPointerCapture?.(pointerEvent.pointerId);
        const move = (moveEvent) => {
          const distance = Math.abs(moveEvent.clientY - originY);
          if (!resizeArmed) {
            if (distance >= 9) window.clearTimeout(resizeLongPressTimer);
            return;
          }
          // Ignore normal clicks and tiny hand movements on the grip. A resize
          // begins only after a deliberate vertical movement.
          if (!didResize && distance < 6) return;
          didResize = true;
          const steps = Math.round((moveEvent.clientY - originY) / slotHeight);
          nextEnd = Math.max(minutes(event.start_time) + 15, Math.min(STAFF_DAY_END, originalEnd + (steps * 15)));
          const nextDuration = nextEnd - minutes(event.start_time);
          button.style.setProperty(
            "--event-duration",
            `calc(${nextDuration / 15} * var(--calendar-quarter-height))`,
          );
          button.querySelector(".calendar-event-time").textContent = `${formatClock(event.start_time)} – ${formatClock(timeValue(nextEnd))}`;
          button.classList.add("is-resizing");
        };
        const finish = async (finishEvent) => {
          window.clearTimeout(resizeLongPressTimer);
          resizeHandle.removeEventListener("pointermove", move);
          resizeHandle.removeEventListener("pointerup", finish);
          resizeHandle.removeEventListener("pointercancel", cancel);
          if (resizeHandle.hasPointerCapture?.(finishEvent.pointerId)) {
            resizeHandle.releasePointerCapture(finishEvent.pointerId);
          }
          button.classList.remove("is-resizing");
          resizingEventId = null;
          if (!didResize || nextEnd === originalEnd) return;
          suppressEventClickUntil = Date.now() + 350;
          await moveEvent(event, {
            date: event.date,
            instructorId: event.instructor_id,
            start: event.start_time,
            end: timeValue(nextEnd),
          });
        };
        const cancel = (cancelEvent) => {
          window.clearTimeout(resizeLongPressTimer);
          resizeHandle.removeEventListener("pointermove", move);
          resizeHandle.removeEventListener("pointerup", finish);
          resizeHandle.removeEventListener("pointercancel", cancel);
          if (resizeHandle.hasPointerCapture?.(cancelEvent.pointerId)) {
            resizeHandle.releasePointerCapture(cancelEvent.pointerId);
          }
          button.classList.remove("is-resizing");
          resizingEventId = null;
          renderCalendar();
        };
        resizeHandle.addEventListener("pointermove", move);
        resizeHandle.addEventListener("pointerup", finish, { once: true });
        resizeHandle.addEventListener("pointercancel", cancel, { once: true });
      });
    }
    return button;
  };

  calendarScroll?.addEventListener("dragover", (event) => {
    if (!draggedEvent) return;
    const bounds = calendarScroll.getBoundingClientRect();
    const edgeSize = Math.min(110, bounds.width * 0.12);
    if (event.clientX < bounds.left + edgeSize) {
      calendarScroll.scrollLeft -= 18;
    } else if (event.clientX > bounds.right - edgeSize) {
      calendarScroll.scrollLeft += 18;
    }
  });

  const moveEvent = async (event, target) => {
    if (
      !event?.can_edit
      || (event.type === "slot" && currentRole !== "admin" && !canManageOwnSlots)
      || moveInFlight
    ) return;
    moveInFlight = true;
    message.hidden = false;
    message.classList.remove("is-error");
    message.textContent = "Checking the new time…";
    try {
      const isBookingSlot = event.type === "slot";
      const isBusyTime = event.type === "busy";
      const isAppointment = !isBookingSlot && !isBusyTime;
      const updateUrl = isBookingSlot
        ? replaceId(calendar.dataset.slotUpdateUrlTemplate, event.id)
        : isBusyTime
          ? replaceId(calendar.dataset.busyUpdateUrlTemplate, event.id)
          : replaceId(calendar.dataset.updateUrlTemplate, event.id);
      let currentEvent = event;
      let allowDoubleBooking = Boolean(event.allow_double_booking);
      let allowPastAppointment = false;
      if (isAppointment) {
        const now = new Date();
        const localToday = toInputDate(now);
        const currentMinutes = (now.getHours() * 60) + now.getMinutes();
        const movingIntoPast = target.date < localToday || (
          target.date === localToday && minutes(target.start) < currentMinutes
        );
        if (movingIntoPast) {
          if (currentRole !== "admin") {
            throw new Error("Past appointments can be moved only by an administrator.");
          }
          const confirmed = window.confirm(
            `This moves the appointment to ${target.date} at ${formatClock(target.start)}, which has already passed.\n\n` +
            "Do you want to save it as a past appointment?",
          );
          if (!confirmed) {
            renderCalendar();
            message.hidden = true;
            return;
          }
          allowPastAppointment = true;
        }
      }
      let response;
      let data;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        response = await fetch(updateUrl, {
          method: "PATCH",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
          },
          credentials: "same-origin",
          body: JSON.stringify({
            revision: currentEvent.revision,
            target_date: target.date,
            start_time: target.start,
            ...(target.end ? { end_time: target.end } : {}),
            instructor_id: Number(target.instructorId),
            machine_id: Number(target.machineId || currentEvent.machine_id),
            ...(isAppointment && allowPastAppointment ? { allow_past_appointment: true } : {}),
            ...(isAppointment ? { allow_double_booking: allowDoubleBooking } : {}),
            ...(isBusyTime ? {
              break_type: currentEvent.busy_kind || "busy",
              title: currentEvent.title || "Busy time",
              notes: currentEvent.notes || "",
            } : {}),
          }),
        });
        data = await parseJson(response);
        const revisionConflict = response.status === 409
          && /changed in another window|refresh and try again/i.test(data.error || "");
        if (revisionConflict) {
          // Another browser saved first. Pull its current revision immediately,
          // then retry this explicit drag without asking for a page refresh.
          await loadEvents({ silent: true, force: true });
          const freshEvent = events.find((item) => (
            String(item.id) === String(event.id) && item.type === event.type
          ));
          if (!freshEvent) {
            throw new Error(`This ${isBookingSlot ? "booking slot" : isBusyTime ? "busy time" : "appointment"} no longer exists.`);
          }
          currentEvent = freshEvent;
          continue;
        }
        const canOverrideConflict = isAppointment
          && response.status === 409
          && data.conflict_type === "schedule"
          && data.can_override
          && !allowDoubleBooking;
        if (canOverrideConflict) {
          const approved = window.confirm(
            `${data.error}\n\nMove it anyway and record this as an allowed double booking?`,
          );
          if (approved) {
            allowDoubleBooking = true;
            continue;
          }
        }
        break;
      }
      if (!response.ok) throw new Error(data.error || `The ${isBookingSlot ? "booking slot" : isBusyTime ? "busy time" : "appointment"} could not be moved.`);
      if (data.event) mergeSavedEvents([data.event]);
      announce(isBookingSlot ? "Booking slot moved." : isBusyTime ? "Busy time moved." : "Appointment moved.");
      message.hidden = true;
      await loadEvents({ silent: true, force: true });
      queueCalendarReconcile();
    } catch (error) {
      // Restore the server-backed size and position after a rejected resize/drop.
      renderCalendar();
      message.hidden = false;
      message.classList.add("is-error");
      message.textContent = error.message || `The ${event.type === "slot" ? "booking slot" : event.type === "busy" ? "busy time" : "appointment"} could not be moved.`;
      announce(message.textContent);
    } finally {
      moveInFlight = false;
    }
  };

  const wireSlot = (slot, column, start, occupied = false) => {
    const disabled = column.nonWorking;
    const bookingSlot = events.find((item) => (
      item.type === "slot"
      && item.date === column.date
      && String(item.instructor_id) === String(column.instructorId)
      && minutes(item.start_time) <= minutes(start)
      && minutes(item.end_time) > minutes(start)
    ));
    slot.dataset.dropDate = column.date;
    slot.dataset.dropInstructorId = String(column.instructorId);
    slot.dataset.dropStart = start;
    slot.classList.toggle("is-non-working", disabled);
    slot.classList.toggle("is-occupied", occupied);
    slot.setAttribute("aria-disabled", String(disabled || occupied));
    const canReceiveDraggedEvent = () => {
      if (!draggedEvent) return false;
      if (
        draggedEvent.type === "slot"
        && currentRole === "instructor"
        && String(column.instructorId) !== currentInstructorId
      ) return false;
      const duration = Math.max(15, minutes(draggedEvent.end_time) - minutes(draggedEvent.start_time));
      if (minutes(start) + duration > STAFF_DAY_END) return false;
      // Let the server validate occupied destinations so the user receives the
      // exact conflict reason instead of a silent failed drop.
      return !disabled;
    };
    slot.addEventListener("dragover", (event) => {
      if (!canReceiveDraggedEvent()) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      slot.classList.add("is-drop-target");
      const duration = Math.max(15, minutes(draggedEvent.end_time) - minutes(draggedEvent.start_time));
      const finish = timeValue(minutes(start) + duration);
      if (dragTimePreview) {
        dragTimePreview.textContent = `${formatClock(start)} – ${formatClock(finish)}`;
        dragTimePreview.style.left = `${event.clientX + 14}px`;
        dragTimePreview.style.top = `${event.clientY + 14}px`;
      }
    });
    slot.addEventListener("dragleave", () => slot.classList.remove("is-drop-target"));
    slot.addEventListener("drop", (event) => {
      if (!canReceiveDraggedEvent()) return;
      event.preventDefault();
      slot.classList.remove("is-drop-target");
      dragTimePreview?.remove();
      dragTimePreview = null;
      const duration = Math.max(15, minutes(draggedEvent.end_time) - minutes(draggedEvent.start_time));
      moveEvent(draggedEvent, {
        date: column.date,
        instructorId: column.instructorId,
        start,
        ...(draggedEvent.type === "appointment" && bookingSlot
          ? { machineId: bookingSlot.machine_id }
          : {}),
        ...(draggedEvent.type === "slot" ? { end: timeValue(minutes(start) + duration) } : {}),
      });
    });
    if (disabled || occupied) return;
    const instructorOwnSlotMode = currentRole === "instructor"
      && canManageOwnSlots
      && String(column.instructorId) === currentInstructorId;
    if (currentRole === "instructor" && !instructorOwnSlotMode) return;
    // A visible plus affordance makes it clear that an empty white cell can
    // start a booking. The server still checks conflicts and asks authorised
    // staff before recording an allowed double booking.
    slot.dataset.bookLabel = `${instructorOwnSlotMode ? "+ Slot" : "+ Book"} ${formatClock(start)}`;
    let longPressTimer;
    let longPressed = false;
    slot.addEventListener("pointerdown", (event) => {
      if (event.pointerType !== "touch") return;
      longPressed = false;
      longPressTimer = window.setTimeout(() => {
        longPressed = true;
        prepareNewEditor(column.date, column.instructorId, start, slot, instructorOwnSlotMode ? "slot" : "appointment", "", bookingSlot);
      }, 500);
    });
    ["pointerup", "pointercancel", "pointerleave"].forEach((name) => {
      slot.addEventListener(name, () => window.clearTimeout(longPressTimer));
    });
    slot.addEventListener("click", () => {
      if (longPressed) {
        longPressed = false;
        return;
      }
      prepareNewEditor(column.date, column.instructorId, start, slot, instructorOwnSlotMode ? "slot" : "appointment", "", bookingSlot);
    });
    slot.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      prepareNewEditor(column.date, column.instructorId, start, slot, instructorOwnSlotMode ? "slot" : "appointment", "", bookingSlot);
    });
  };

  const renderCalendar = () => {
    const preservedScrollLeft = resetHorizontalScroll
      ? 0
      : Math.max(0, calendarScroll?.scrollLeft || 0);
    grid.replaceChildren();
    const columns = columnsForView();
    const slots = timeSlots();
    if (!columns.length) {
      message.hidden = false;
      message.textContent = "Add or verify an instructor to start using the calendar.";
      return;
    }
    const timeColumn = document.createElement("div");
    timeColumn.className = "calendar-time-column";
    const timezone = document.createElement("div");
    timezone.className = "calendar-column-header calendar-timezone";
    timezone.textContent = "IST";
    timeColumn.append(timezone);
    slots.forEach((start) => {
      const label = document.createElement("div");
      label.className = "calendar-time-label";
      label.textContent = start.endsWith(":00") ? formatClock(start, true) : "";
      timeColumn.append(label);
    });
    grid.append(timeColumn);

    columns.forEach((column) => {
      const section = document.createElement("section");
      section.className = "calendar-schedule-column";
      section.dataset.date = column.date;
      section.dataset.instructorId = column.instructorId;
      section.style.setProperty("--instructor-colour", instructorEventColour(column.instructorId));
      section.style.setProperty("--branch-colour", branchColour(column.branchId));
      const columnEvents = events.filter((item) => (
        item.date === column.date
        && String(item.instructor_id) === String(column.instructorId)
      ));
      const hasBookingSlot = columnEvents.some((item) => item.type === "slot");
      assignOverlapLanes(columnEvents, hasBookingSlot);
      section.classList.toggle("has-booking-slot", hasBookingSlot);
      const header = document.createElement("header");
      header.className = "calendar-column-header";
      const title = document.createElement("strong");
      const subtitle = document.createElement("span");
      title.textContent = column.title;
      subtitle.textContent = column.subtitle;
      header.append(title, subtitle);
      if (branchFilter instanceof HTMLSelectElement && column.branchName) {
        const branchBadge = document.createElement("small");
        branchBadge.className = "calendar-branch-badge";
        branchBadge.textContent = column.branchName;
        header.append(branchBadge);
      }
      section.append(header);
      slots.forEach((start) => {
        const slot = document.createElement("div");
        slot.tabIndex = 0;
        slot.setAttribute("role", "button");
        slot.className = "calendar-slot";
        slot.dataset.start = start;
        const slotStart = minutes(start);
        const slotEnd = slotStart + 15;
        const coveringEvents = events.filter((item) => (
          String(item.instructor_id) === String(column.instructorId)
          && item.date === column.date
          && minutes(item.start_time) < slotEnd
          && minutes(item.end_time) > slotStart
          && item.type !== "slot"
          && (item.type === "busy" || !["Cancelled", "Rejected"].includes(item.status))
        ));
        const startsHere = events.filter((item) => (
          String(item.instructor_id) === String(column.instructorId)
          && item.date === column.date
          && eventSlotStart(item) === start
        )).sort((a, b) => (a.type === "slot" ? -1 : 1) - (b.type === "slot" ? -1 : 1));
        const occupied = coveringEvents.length > 0;
        slot.setAttribute("aria-label", occupied
          ? `${column.title}, ${column.subtitle}, ${start}. Occupied`
          : `${column.title}, ${column.subtitle}, ${start}. Book appointment`);
        wireSlot(slot, column, start, occupied);
        startsHere.forEach((item) => slot.append(createEventButton(item)));
        section.append(slot);
      });
      grid.append(section);
    });
    if (calendarScroll) calendarScroll.scrollLeft = preservedScrollLeft;
  };

  async function loadEvents({ silent = false, force = false } = {}) {
    if (loadInFlight && !force) return false;
    loadRequest?.abort();
    const requestController = new AbortController();
    const requestGeneration = ++loadGeneration;
    loadRequest = requestController;
    loadInFlight = true;
    // Keep the selected day in the URL. A normal refresh then asks Flask for
    // this same day instead of falling back to today's calendar.
    persistCalendarDate();
    const selectedPeriod = period();
    const start = toInputDate(selectedPeriod.start);
    const end = toInputDate(selectedPeriod.end);
    if (rangeLabel) rangeLabel.textContent = formatRange(selectedPeriod.start, selectedPeriod.end);
    if (!silent) {
      message.hidden = false;
      message.classList.remove("is-error");
      message.textContent = "Loading appointments…";
    }
    const query = new URLSearchParams({ start, end });
    if (branchFilter?.value) query.set("branch_id", branchFilter.value);
    if (instructorFilter.value) query.set("instructor_id", instructorFilter.value);
    if (statusFilter.value) query.set("status", statusFilter.value);
    query.set("_sync", String(Date.now()));
    try {
      const response = await fetch(`${calendar.dataset.eventsUrl}?${query}`, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        signal: requestController.signal,
      });
      const data = await parseJson(response);
      if (!response.ok) throw new Error(data.error || "The calendar could not be loaded.");
      if (requestGeneration !== loadGeneration) return false;
      // A silent background refresh must never rebuild the calendar while a
      // pointer drag or resize is active; doing so creates duplicate trackers.
      if (silent && (activePointerDragCleanup || draggedEvent || resizingEventId !== null)) {
        return false;
      }
      events = data.events || [];
      if (!silent) message.hidden = true;
      renderCalendar();
      if (resetHorizontalScroll && calendarScroll) {
        calendarScroll.scrollLeft = 0;
        resetHorizontalScroll = false;
        restoreHorizontalScroll = false;
      } else if (restoreHorizontalScroll && calendarScroll) {
        calendarScroll.scrollLeft = storedHorizontalScroll();
        restoreHorizontalScroll = false;
      }
      openInitialClientEditor();
      return true;
    } catch (error) {
      if (error.name === "AbortError") return false;
      if (silent) {
        console.warn("Calendar auto-sync failed:", error);
        return false;
      }
      message.hidden = false;
      message.classList.add("is-error");
      message.textContent = error.message || "The calendar could not be loaded.";
      return false;
    } finally {
      if (requestGeneration === loadGeneration) {
        loadInFlight = false;
        if (loadRequest === requestController) loadRequest = null;
      }
    }
  }

  const createClient = async () => {
    const fullName = editor.querySelector("[data-new-client-first-name]")?.value.trim() || "";
    const admissionNumber = editor.querySelector("[data-new-client-last-name]")?.value.trim() || "";
    const phone = editor.querySelector("[data-new-client-phone]")?.value.trim() || "";
    const email = editor.querySelector("[data-new-client-email]")?.value.trim() || "";
    const branchId = appointmentBranchId
      || instructorInput.selectedOptions[0]?.dataset.branchId
      || "";
    if (!fullName || !admissionNumber || !phone) {
      throw new Error("Enter the client's full name, admission number, and phone number.");
    }
    if (!branchId) {
      throw new Error("Choose the instructor before creating the client.");
    }
    const button = editor.querySelector("[data-new-client-save]");
    if (button) button.disabled = true;
    clearError();
    try {
      const response = await fetch(calendar.dataset.clientCreateUrl, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
        },
        credentials: "same-origin",
        body: JSON.stringify({
          full_name: fullName,
          admission_number: admissionNumber,
          phone,
          email,
          branch_id: Number(branchId),
          instructor_id: Number(appointmentInstructorId || instructorInput.value),
        }),
      });
      const data = await parseJson(response);
      const record = data.client || data.existing_client;
      if (!response.ok && !record) throw new Error(data.error || "The client could not be created.");
      if (!record?.id) throw new Error("The client record was not returned. Refresh and try again.");
      let option = Array.from(clientInput.options).find((item) => String(item.value) === String(record.id));
      if (!option) {
        option = document.createElement("option");
        option.value = String(record.id);
        option.dataset.branchId = String(record.branch_id || branchId);
        option.textContent = record.full_name || fullName;
        clientInput.append(option);
      }
      option.hidden = false;
      option.disabled = false;
      clientInput.value = option.value;
      syncEditorOptions();
      announce(response.ok ? "Client created and selected." : "Existing client selected.");
      // Return the authoritative server id as well as updating the hidden
      // selector. Branch filtering can rebuild/clear that selector, but it
      // must never discard the client that was just created for this save.
      return Number(record.id);
    } catch (error) {
      throw new Error(error.message || "The client could not be created.");
    } finally {
      if (button) button.disabled = false;
    }
  };

  const appointmentPayload = () => {
    const repeat = repeatInput?.value || "none";
    return {
      student_id: Number(clientInput.value),
      instructor_id: Number(appointmentInstructorId || instructorInput.value),
      machine_id: Number(machineInput.value),
      service_ids: selectedServiceIds(),
      target_date: editorDate.value,
      start_time: editorStart.value,
      end_time: editorEnd?.value || "",
      status: editorStatus?.value || "Approved",
      buffer_before_minutes: 0,
      buffer_after_minutes: 0,
      repeat,
      repeat_count: repeat === "none" ? 1 : Math.max(2, Number(repeatCount?.value || 2)),
      allow_double_booking: Boolean(allowDoubleBooking?.checked),
      notes: editorNotes?.value || "",
      revision: Number(revisionInput.value || 0),
    };
  };

  const saveAppointment = async () => {
    let payload = appointmentPayload();
    const firstName = clientFirstName?.value.trim() || "";
    const lastName = clientLastName?.value.trim() || "";
    const phone = clientPhone?.value.trim() || "";
    if (!firstName || !lastName) throw new Error("Client first name and last name are required.");
    if (!phone) throw new Error("Client phone number is required.");
    if (!payload.notes.trim()) throw new Error("Appointment notes are required.");
    if (!payload.student_id) {
      const createdClientId = await createClient();
      payload = appointmentPayload();
      payload.student_id = Number(payload.student_id || createdClientId);
      if (!payload.student_id) {
        throw new Error("The client could not be selected. Check the client details and try again.");
      }
    }
    if (!payload.service_ids.length) throw new Error("Choose at least one service.");
    if (!payload.instructor_id || !payload.machine_id) throw new Error("Choose the instructor and compatible equipment.");
    if (!payload.target_date || !payload.start_time || !payload.end_time) throw new Error("Choose the date, start, and finish time.");
    if (minutes(payload.end_time) <= minutes(payload.start_time)) throw new Error("Finish must be later than start.");
    if (minutes(payload.start_time) < STAFF_DAY_START || minutes(payload.end_time) > STAFF_DAY_END) {
      throw new Error("Appointments must be between 6:00 am and 6:30 pm.");
    }
    const now = new Date();
    const localToday = toInputDate(now);
    const currentMinutes = (now.getHours() * 60) + now.getMinutes();
    const isPastAppointment = payload.target_date < localToday || (
      payload.target_date === localToday && minutes(payload.start_time) < currentMinutes
    );
    if (isPastAppointment) {
      if (currentRole !== "admin") {
        throw new Error("Past appointments can be created or edited only by an administrator.");
      }
      const confirmed = window.confirm(
        `This appointment is on ${payload.target_date} at ${formatClock(payload.start_time)}, which has already passed.\n\nDo you want to save it as a past appointment?`
      );
      if (!confirmed) throw new Error("Past appointment was not saved.");
      payload = { ...payload, allow_past_appointment: true };
    }
    const editing = Boolean(bookingIdInput.value);
    const url = editing
      ? replaceId(calendar.dataset.updateUrlTemplate, bookingIdInput.value)
      : calendar.dataset.createUrl;
    const submit = async (body) => {
      const response = await fetch(url, {
        method: editing ? "PATCH" : "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
        },
        credentials: "same-origin",
        body: JSON.stringify(body),
      });
      return { response, data: await parseJson(response) };
    };
    let { response, data } = await submit(payload);
    if (
      response.status === 409
      && data.conflict_type === "schedule"
      && data.can_override
      && !payload.allow_double_booking
    ) {
      const approved = window.confirm(
        `${data.error}\n\nBook anyway and record this as an allowed double booking?`
      );
      if (approved) {
        if (allowDoubleBooking) allowDoubleBooking.checked = true;
        payload = { ...payload, allow_double_booking: true };
        ({ response, data } = await submit(payload));
      }
    }
    if (!response.ok) throw new Error(data.error || "The appointment could not be saved.");
    return {
      message: editing ? "Appointment updated." : (
        Number(data.created_count || 1) > 1
          ? `${data.created_count} appointments created.`
          : "Appointment added."
      ),
      savedEvents: data.events || (data.event ? [data.event] : []),
    };
  };

  const saveInstructorStatus = async () => {
    if (!editingEvent || editingEvent.type !== "appointment") {
      throw new Error("Open an appointment before changing its status.");
    }
    const response = await fetch(
      replaceId(calendar.dataset.instructorStatusUrlTemplate, editingEvent.id),
      {
        method: "PATCH",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
        },
        credentials: "same-origin",
        body: JSON.stringify({
          status: editorStatus?.value || "No Action",
          revision: editingEvent.revision,
        }),
      },
    );
    const data = await parseJson(response);
    if (!response.ok) throw new Error(data.error || "The status could not be changed.");
    return {
      message: `Status changed to ${data.event?.status || editorStatus?.value}.`,
      savedEvents: data.event ? [data.event] : [],
    };
  };

  const saveBusyTime = async () => {
    const repeat = busyRepeat?.value || "none";
    const payload = {
      instructor_id: Number(busyInstructor?.value || 0),
      target_date: busyDate?.value || "",
      start_time: busyStart?.value || "",
      end_time: busyEnd?.value || "",
      break_type: busyKind?.value || "busy",
      title: busyTitle?.value || "",
      notes: busyNotes?.value || "",
      repeat,
      repeat_count: repeat === "none" ? 1 : Math.max(2, Number(busyRepeatCount?.value || 2)),
      revision: Number(revisionInput.value || 0),
    };
    if (!payload.instructor_id || !payload.target_date || !payload.start_time || !payload.end_time) {
      throw new Error("Choose the instructor, date, start, and finish time.");
    }
    if (minutes(payload.end_time) <= minutes(payload.start_time)) throw new Error("Finish must be later than start.");
    const editing = editingEvent?.type === "busy" && Boolean(bookingIdInput.value);
    const url = editing
      ? replaceId(calendar.dataset.busyUpdateUrlTemplate, bookingIdInput.value)
      : calendar.dataset.busyCreateUrl;
    const response = await fetch(url, {
      method: editing ? "PATCH" : "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
      },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });
    const data = await parseJson(response);
    if (!response.ok) throw new Error(data.error || "The busy time could not be saved.");
    return {
      message: editing ? "Busy time updated." : (
        Number(data.created_count || 1) > 1
          ? `${data.created_count} busy periods added.`
          : "Busy time added."
      ),
      savedEvents: data.events || (data.event ? [data.event] : []),
    };
  };

  const saveBookingSlot = async () => {
    const repeat = slotRepeat?.value || "none";
    const payload = {
      instructor_id: Number(slotInstructor?.value || 0),
      machine_id: Number(slotMachine?.value || 0),
      target_date: slotDate?.value || "",
      start_time: slotStart?.value || "",
      end_time: slotEnd?.value || "",
      notes: slotNotes?.value || "",
      repeat,
      repeat_count: repeat === "none" ? 1 : Math.max(2, Number(slotRepeatCount?.value || 2)),
      revision: Number(revisionInput.value || 0),
    };
    if (!payload.instructor_id || !payload.machine_id || !payload.target_date || !payload.start_time || !payload.end_time) {
      throw new Error("Choose staff, equipment, date, start, and finish time.");
    }
    if (minutes(payload.end_time) <= minutes(payload.start_time)) throw new Error("Finish must be later than start.");
    if (minutes(payload.start_time) < STAFF_DAY_START || minutes(payload.end_time) > STAFF_DAY_END) {
      throw new Error("Booking slots must be between 6:00 am and 6:30 pm.");
    }
    const editing = editingEvent?.type === "slot" && Boolean(bookingIdInput.value);
    const url = editing
      ? replaceId(calendar.dataset.slotUpdateUrlTemplate, bookingIdInput.value)
      : calendar.dataset.slotCreateUrl;
    const response = await fetch(url, {
      method: editing ? "PATCH" : "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": csrf },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });
    const data = await parseJson(response);
    if (!response.ok) throw new Error(data.error || "The booking slot could not be saved.");
    return {
      message: editing ? "Booking slot updated." : (
        Number(data.created_count || 1) > 1
          ? `${data.created_count} booking slots added.`
          : "Booking slot added."
      ),
      savedEvents: data.events || (data.event ? [data.event] : []),
    };
  };

  editor.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saveInFlight) return;
    clearError();
    if (!editor.checkValidity()) {
      editor.reportValidity();
      return;
    }
    saveInFlight = true;
    editor.setAttribute("aria-busy", "true");
    if (saveButton) {
      saveButton.disabled = true;
      saveButton.textContent = "Saving…";
    }
    try {
      const result = currentRole === "instructor" && editorType === "appointment"
        ? await saveInstructorStatus()
        : editorType === "busy" ? await saveBusyTime()
        : editorType === "slot" ? await saveBookingSlot()
        : await saveAppointment();
      mergeSavedEvents(result?.savedEvents || []);
      const savedDate = result?.savedEvents?.[0]?.date;
      if (/^\d{4}-\d{2}-\d{2}$/.test(String(savedDate || ""))) {
        if (dateInput.value !== savedDate) {
          dateInput.value = savedDate;
          resetHorizontalScroll = true;
        }
      }
      dialog.close();
      announce(result?.message || result);
      await loadEvents({ silent: true, force: true });
      queueCalendarReconcile();
    } catch (error) {
      showError(error.message || "The schedule item could not be saved.");
    } finally {
      saveInFlight = false;
      editor.removeAttribute("aria-busy");
      if (saveButton) {
        saveButton.disabled = false;
        saveButton.textContent = currentRole === "instructor" && editorType === "appointment"
          ? "Save status"
          : editorType === "busy" ? "Save busy time"
          : editorType === "slot" ? "Save slot"
          : "Save appointment";
      }
    }
  });

  editor.querySelectorAll("[data-editor-close]").forEach((button) => {
    button.addEventListener("click", () => dialog.close());
  });
  editor.querySelectorAll("[data-editor-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      if (editingEvent) return;
      setEditorType(button.dataset.editorTab);
      if (titleText) titleText.textContent = editorType === "busy" ? "Add busy time" : editorType === "slot" ? "Add booking slot" : "Add appointment";
      if (descriptionText) {
        descriptionText.textContent = editorType === "busy"
          ? "Block time that staff should not use for appointments."
          : editorType === "slot" ? "Mark equipment availability without blocking appointments."
          : "Create a confirmed appointment while speaking with the client.";
      }
    });
  });
  editor.querySelector("[data-new-client-toggle]")?.addEventListener("click", () => {
    const panel = editor.querySelector("[data-new-client-panel]");
    if (!panel) return;
    panel.hidden = !panel.hidden;
    if (!panel.hidden) editor.querySelector("[data-new-client-first-name]")?.focus();
  });
  editor.querySelector("[data-new-client-save]")?.addEventListener("click", createClient);

  clientContactInputs.forEach((input) => {
    input.addEventListener("input", () => queueClientSearch(input));
    input.addEventListener("focus", () => {
      if (!editingEvent && input.value.trim().length >= 2) queueClientSearch(input);
    });
  });
  document.addEventListener("pointerdown", (event) => {
    if (!clientTypeahead?.hidden
      && !clientTypeahead.contains(event.target)
      && !clientContactInputs.includes(event.target)) hideClientMatches();
  });

  clientInput.addEventListener("change", syncEditorOptions);
  whatsappConfirmationButton?.addEventListener("click", () => {
    if (whatsappConfirmationEvent) openWhatsappConfirmation(whatsappConfirmationEvent);
  });
  repeatInput?.addEventListener("change", () => syncRepeatCount(repeatInput, repeatCount));
  busyRepeat?.addEventListener("change", () => syncRepeatCount(busyRepeat, busyRepeatCount));
  slotRepeat?.addEventListener("change", () => syncRepeatCount(slotRepeat, slotRepeatCount));
  instructorInput.addEventListener("change", () => {
    setAppointmentInstructor(
      instructorInput.value,
      instructorInput.selectedOptions[0]?.dataset.branchId || "",
    );
    syncEditorOptions();
    if (busyInstructor && !editingEvent) busyInstructor.value = instructorInput.value;
  });
  slotInstructor?.addEventListener("change", () => {
    syncSlotMachines();
  });
  serviceChecks.forEach((input) => {
    input.addEventListener("change", () => {
      syncMachines();
      updateDuration({ useServicePadding: !bookingIdInput.value });
      applyTrailerDefaultFinish();
      updateServiceTrigger();
    });
  });
  machineInput.addEventListener("change", applyTrailerDefaultFinish);
  servicePickerOpenButton?.addEventListener("click", () => {
    if (!servicePicker) return;
    // Re-evaluate branch visibility whenever the picker opens. This also
    // repairs stale hidden states after switching branches or calendar cells.
    syncEditorOptions();
    servicePickerSnapshot = selectedServiceIds().map(String);
    servicePicker.hidden = false;
    servicePicker.querySelector("input:not(:disabled)")?.focus();
  });
  editor.querySelectorAll("[data-service-picker-close], [data-service-picker-done]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.hasAttribute("data-service-picker-close")) {
        setServiceSelection(servicePickerSnapshot);
        syncMachines();
        updateDuration();
      }
      if (servicePicker) servicePicker.hidden = true;
      updateServiceTrigger();
      servicePickerOpenButton?.focus();
    });
  });
  additionalToggle?.addEventListener("click", () => {
    if (!(additionalDetails instanceof HTMLDetailsElement)) return;
    additionalDetails.open = !additionalDetails.open;
    additionalToggle.innerHTML = additionalDetails.open
      ? 'Less <span aria-hidden="true">⌄</span>'
      : 'More <span aria-hidden="true">⌃</span>';
  });
  editorStart.addEventListener("change", () => {
    if (trailerFinishAuto && !bookingIdInput.value && isTrailerBooking()) {
      applyTrailerDefaultFinish();
      return;
    }
    if (editorEnd instanceof HTMLSelectElement && minutes(editorEnd.value) <= minutes(editorStart.value)) {
      editorEnd.value = timeValue(minutes(editorStart.value) + 15);
    }
  });
  editorEnd?.addEventListener("change", () => {
    trailerFinishAuto = false;
    if (endTimeText) endTimeText.textContent = "";
  });

  cancelAppointmentButton?.addEventListener("click", async () => {
    if (!editingEvent || editingEvent.type !== "appointment") return;
    const permanentlyDelete = currentRole === "booking_agent";
    const confirmation = permanentlyDelete
      ? `Delete ${editingEvent.student_name}'s appointment? This will immediately free the time for another booking.`
      : `Delete ${editingEvent.student_name}'s appointment from the active calendar? The record will be retained as cancelled.`;
    if (!window.confirm(confirmation)) return;
    clearError();
    try {
      const response = await fetch(
        replaceId(
          permanentlyDelete ? calendar.dataset.deleteUrlTemplate : calendar.dataset.cancelUrlTemplate,
          editingEvent.id,
        ),
        {
          method: "DELETE",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
          },
          credentials: "same-origin",
          body: JSON.stringify({ revision: editingEvent.revision }),
        },
      );
      const data = await parseJson(response);
      if (!response.ok) throw new Error(data.error || "The appointment could not be deleted.");
      dialog.close();
      announce(permanentlyDelete ? "Appointment deleted. The time is now available." : "Appointment cancelled.");
      await loadEvents({ force: true });
    } catch (error) {
      showError(error.message || "The appointment could not be deleted.");
    }
  });

  permanentDeleteButton?.addEventListener("click", async () => {
    if (!editingEvent || editingEvent.type !== "appointment" || currentRole !== "admin") return;
    if (!window.confirm(`Delete ${editingEvent.student_name}'s appointment permanently? Click OK to delete it.`)) return;
    clearError();
    try {
      const response = await fetch(
        replaceId(calendar.dataset.deleteUrlTemplate, editingEvent.id),
        {
          method: "DELETE",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
          },
          credentials: "same-origin",
          body: JSON.stringify({ revision: editingEvent.revision }),
        },
      );
      const data = await parseJson(response);
      if (!response.ok) throw new Error(data.error || "The appointment could not be deleted.");
      dialog.close();
      announce("Appointment permanently deleted.");
      await loadEvents({ force: true });
    } catch (error) {
      showError(error.message || "The appointment could not be deleted.");
    }
  });

  deleteClientUpcomingButton?.addEventListener("click", async () => {
    if (!editingEvent || editingEvent.type !== "appointment") return;
    clearError();
    const url = replaceId(
      calendar.dataset.clientUpcomingDeleteUrlTemplate,
      editingEvent.id,
    );
    try {
      const previewResponse = await fetch(url, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      const preview = await parseJson(previewResponse);
      if (!previewResponse.ok) {
        throw new Error(preview.error || "The client's upcoming bookings could not be checked.");
      }
      if (!preview.count) {
        window.alert(`${preview.client_name || editingEvent.student_name} has no active bookings from ${preview.from_date}.`);
        return;
      }
      const confirmed = window.confirm(
        `Permanently delete ${preview.count} active booking${preview.count === 1 ? "" : "s"} ` +
        `for ${preview.client_name || editingEvent.student_name} from ${preview.from_date} onward?\n\n` +
        "Earlier bookings and other clients will not be changed. This cannot be undone.",
      );
      if (!confirmed) return;

      deleteClientUpcomingButton.disabled = true;
      const deleteResponse = await fetch(url, {
        method: "DELETE",
        headers: { Accept: "application/json", "X-CSRF-Token": csrf },
        credentials: "same-origin",
      });
      const result = await parseJson(deleteResponse);
      if (!deleteResponse.ok) {
        throw new Error(result.error || "The client's upcoming bookings could not be deleted.");
      }
      dialog.close();
      announce(`${result.deleted_count || 0} upcoming client bookings deleted.`);
      await loadEvents({ force: true });
    } catch (error) {
      showError(error.message || "The client's upcoming bookings could not be deleted.");
    } finally {
      deleteClientUpcomingButton.disabled = false;
    }
  });

  deleteBusyButton?.addEventListener("click", async () => {
    if (!editingEvent || editingEvent.type !== "busy") return;
    if (!window.confirm("Delete this busy time?")) return;
    try {
      const response = await fetch(
        replaceId(calendar.dataset.busyDeleteUrlTemplate, editingEvent.id),
        {
          method: "DELETE",
          headers: { Accept: "application/json", "X-CSRF-Token": csrf },
          credentials: "same-origin",
        },
      );
      const data = await parseJson(response);
      if (!response.ok) throw new Error(data.error || "The busy time could not be deleted.");
      dialog.close();
      announce("Busy time deleted.");
      await loadEvents({ force: true });
    } catch (error) {
      showError(error.message || "The busy time could not be deleted.");
    }
  });

  deleteUpcomingBusyButton?.addEventListener("click", async () => {
    if (!editingEvent || editingEvent.type !== "busy") return;
    const url = replaceId(
      calendar.dataset.busyUpcomingDeleteUrlTemplate || "",
      editingEvent.id,
    );
    if (!url) return;
    clearError();
    try {
      const previewResponse = await fetch(url, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      const preview = await parseJson(previewResponse);
      if (!previewResponse.ok) {
        throw new Error(preview.error || "Upcoming busy time could not be checked.");
      }
      if (!preview.count) {
        window.alert(`There are no upcoming occurrences of this busy slot from ${preview.from_date}.`);
        return;
      }
      const confirmed = window.confirm(
        `Delete ${preview.count} occurrence${preview.count === 1 ? "" : "s"} of `
        + `${preview.busy_title || editingEvent.title} (${formatClock(preview.start_time)}–${formatClock(preview.end_time)}) `
        + `for ${preview.instructor_name || editingEvent.instructor_name} from ${preview.from_date} onward?\n\n`
        + "Other busy slots, earlier occurrences, other instructors, and all appointments will remain. This cannot be undone.",
      );
      if (!confirmed) return;

      deleteUpcomingBusyButton.disabled = true;
      const deleteResponse = await fetch(url, {
        method: "DELETE",
        headers: { Accept: "application/json", "X-CSRF-Token": csrf },
        credentials: "same-origin",
      });
      const result = await parseJson(deleteResponse);
      if (!deleteResponse.ok) {
        throw new Error(result.error || "Upcoming busy time could not be deleted.");
      }
      dialog.close();
      announce(`${result.deleted_count || 0} upcoming occurrences of this busy slot deleted.`);
      await loadEvents({ force: true });
    } catch (error) {
      showError(error.message || "Upcoming busy time could not be deleted.");
    } finally {
      deleteUpcomingBusyButton.disabled = false;
    }
  });

  deleteBusyForAllButton?.addEventListener("click", async () => {
    if (!editingEvent || editingEvent.type !== "busy") return;
    const kind = editingEvent.busy_kind || "";
    if (!["breakfast", "lunch", "tea"].includes(kind)) return;
    const label = editingEvent.title || "this break";
    if (!window.confirm(`Delete ${label} for every instructor on ${editingEvent.date}? This cannot be undone from the calendar.`)) return;
    try {
      const url = (calendar.dataset.busyBulkDeleteUrlTemplate || "")
        .replace("__BREAK_KIND__", encodeURIComponent(kind));
      const response = await fetch(url, {
        method: "DELETE",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
        },
        credentials: "same-origin",
        body: JSON.stringify({ target_date: editingEvent.date }),
      });
      const data = await parseJson(response);
      if (!response.ok) throw new Error(data.error || "The break could not be removed for all instructors.");
      dialog.close();
      announce(`${label} removed for all instructors.`);
      await loadEvents({ force: true });
    } catch (error) {
      showError(error.message || "The break could not be removed for all instructors.");
    }
  });

  deleteSlotButton?.addEventListener("click", async () => {
    if (!editingEvent || editingEvent.type !== "slot") return;
    if (!window.confirm("Delete this booking slot? Existing appointments will remain.")) return;
    try {
      const response = await fetch(replaceId(calendar.dataset.slotDeleteUrlTemplate, editingEvent.id), {
        method: "DELETE",
        headers: { Accept: "application/json", "X-CSRF-Token": csrf },
        credentials: "same-origin",
      });
      const data = await parseJson(response);
      if (!response.ok) throw new Error(data.error || "The booking slot could not be deleted.");
      dialog.close();
      announce("Booking slot deleted.");
      await loadEvents({ force: true });
    } catch (error) {
      showError(error.message || "The booking slot could not be deleted.");
    }
  });

  dialog.addEventListener("close", () => {
    editingEvent = null;
    whatsappConfirmationEvent = null;
    if (whatsappConfirmationButton) whatsappConfirmationButton.hidden = true;
    lastFocused?.focus?.();
  });
  dialog.addEventListener("click", (event) => {
    // A click on the dialog element itself is a click on its backdrop. Keep
    // clicks anywhere inside the appointment form working normally.
    if (event.target === dialog && !saveInFlight) dialog.close();
  });
  document.addEventListener("pointerdown", (event) => {
    if (!(event.target instanceof Node)) return;
    if (
      servicePicker
      && !servicePicker.hidden
      && !servicePicker.contains(event.target)
      && !servicePickerOpenButton?.contains(event.target)
    ) {
      servicePicker.hidden = true;
      updateServiceTrigger();
    }
    if (
      clientTypeahead
      && !clientTypeahead.hidden
      && !clientTypeahead.contains(event.target)
      && !clientContactInputs.some((input) => input.contains(event.target))
    ) hideClientMatches();
  });
  document.querySelector("[data-add-appointment]")?.addEventListener("click", (event) => {
    prepareNewEditor(
      dateInput.value,
      instructorFilter.value || instructors[0]?.id,
      "09:00",
      event.currentTarget,
    );
  });
  document.querySelector("[data-calendar-print]")?.addEventListener("click", () => window.print());
  calendar.querySelector("[data-calendar-previous]")?.addEventListener("click", () => {
    dateInput.value = toInputDate(addDays(toDate(dateInput.value), viewFilter.value === "week" ? -7 : -1));
    resetHorizontalScroll = true;
    loadEvents({ force: true });
  });
  calendar.querySelector("[data-calendar-next]")?.addEventListener("click", () => {
    dateInput.value = toInputDate(addDays(toDate(dateInput.value), viewFilter.value === "week" ? 7 : 1));
    resetHorizontalScroll = true;
    loadEvents({ force: true });
  });
  calendar.querySelector("[data-calendar-today]")?.addEventListener("click", () => {
    dateInput.value = toInputDate(new Date());
    resetHorizontalScroll = true;
    loadEvents({ force: true });
  });
  dateInput.addEventListener("change", () => { resetHorizontalScroll = true; loadEvents({ force: true }); });
  statusFilter.addEventListener("change", () => loadEvents({ force: true }));
  viewFilter.addEventListener("change", () => { resetHorizontalScroll = true; loadEvents({ force: true }); });
  instructorFilter.addEventListener("change", () => {
    viewFilter.value = instructorFilter.value && !compactScreen() ? "week" : "day";
    resetHorizontalScroll = true;
    loadEvents({ force: true });
  });
  branchFilter?.addEventListener("change", () => {
    syncInstructorFilterForBranch();
    viewFilter.value = "day";
    resetHorizontalScroll = true;
    loadEvents({ force: true });
  });

  calendarScroll?.addEventListener("scroll", rememberHorizontalScroll, { passive: true });
  window.addEventListener("pagehide", () => {
    rememberHorizontalScroll();
    persistCalendarDate();
  });

  restoreCalendarState();
  if (compactScreen()) viewFilter.value = "day";
  loadEvents();

  // Keep all open calendar screens aligned without requiring a page refresh.
  // Local saves are still merged immediately; this short poll covers changes
  // made by other users or browser tabs.
  window.setInterval(() => {
    if (
      document.visibilityState === "visible"
      && !dialog.open
      && !moveInFlight
      && !saveInFlight
      && !activePointerDragCleanup
      && !draggedEvent
      && resizingEventId === null
    ) void loadEvents({ silent: true });
  }, 2000);
  window.addEventListener("focus", () => {
    if (!dialog.open && !moveInFlight && !saveInFlight && !activePointerDragCleanup && resizingEventId === null) {
      void loadEvents({ silent: true });
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && !dialog.open && !activePointerDragCleanup && resizingEventId === null) {
      void loadEvents({ silent: true });
    }
  });
})();
