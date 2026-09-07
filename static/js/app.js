(() => {
  "use strict";

  const navToggle = document.querySelector("[data-nav-toggle]");
  const siteNav = document.querySelector("[data-site-nav]");

  // Native <details> menus do not close automatically when the user clicks
  // elsewhere. Close calendar filters, account menus, and action menus when
  // focus moves outside the currently open menu.
  document.addEventListener("pointerdown", (event) => {
    if (!(event.target instanceof Node)) return;
    document.querySelectorAll("details[open]").forEach((details) => {
      if (!details.contains(event.target)) details.open = false;
    });
  });

  const setNavigationOpen = (open) => {
    if (!navToggle || !siteNav) return;
    navToggle.setAttribute("aria-expanded", String(open));
    const label = navToggle.querySelector(".sr-only");
    if (label) label.textContent = open ? "Close navigation" : "Open navigation";
    siteNav.classList.toggle("is-open", open);
  };

  if (navToggle && siteNav) {
    navToggle.addEventListener("click", () => {
      setNavigationOpen(navToggle.getAttribute("aria-expanded") !== "true");
    });

    siteNav.addEventListener("click", (event) => {
      if (event.target.closest("a")) setNavigationOpen(false);
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && navToggle.getAttribute("aria-expanded") === "true") {
        setNavigationOpen(false);
        navToggle.focus();
      }
    });

    window.addEventListener("resize", () => {
      if (window.matchMedia("(min-width: 860px)").matches) setNavigationOpen(false);
    });
  }

  document.querySelectorAll("[data-dismiss]").forEach((button) => {
    button.addEventListener("click", () => {
      const alert = button.closest("[data-dismissible]");
      if (!alert) return;
      alert.remove();
    });
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    const submitter = event.submitter;
    const confirmation = submitter?.dataset.confirm || form.dataset.confirm;
    if (confirmation && !window.confirm(confirmation)) {
      event.preventDefault();
      return;
    }

    if (form.matches("[data-async-form]") || event.defaultPrevented || !form.checkValidity()) return;

    // Disabled submit controls are omitted from native form data. Preserve a
    // named button's intent (for example approve vs decline) before locking
    // the form against double submissions.
    if (submitter?.name) {
      const intent = document.createElement("input");
      intent.type = "hidden";
      intent.name = submitter.name;
      intent.value = submitter.value;
      form.append(intent);
    }

    const submitButtons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
    submitButtons.forEach((button) => {
      button.disabled = true;
      button.setAttribute("aria-disabled", "true");
    });
    form.setAttribute("aria-busy", "true");
  });

  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    const input = document.getElementById(button.getAttribute("aria-controls"));
    if (!(input instanceof HTMLInputElement)) return;

    button.addEventListener("click", () => {
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.textContent = show ? "Hide" : "Show";
      button.setAttribute("aria-label", `${show ? "Hide" : "Show"} password`);
    });
  });

  const dateFormatter = new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  document.querySelectorAll("[data-format-date]").forEach((element) => {
    const rawDate = element.getAttribute("datetime") || element.dataset.formatDate;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(rawDate || "")) return;
    const date = new Date(`${rawDate}T00:00:00`);
    if (!Number.isNaN(date.getTime())) element.textContent = dateFormatter.format(date);
  });

  document.querySelectorAll("[data-today-min]").forEach((input) => {
    if (!(input instanceof HTMLInputElement) || input.min) return;
    const now = new Date();
    const localDate = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 10);
    input.min = localDate;
  });

  document.querySelectorAll("[data-reset-filters]").forEach((button) => {
    button.addEventListener("click", () => {
      const form = button.closest("form");
      if (!form) return;
      form.querySelectorAll("input, select").forEach((control) => {
        if (control.type === "hidden") return;
        control.value = "";
      });
      form.submit();
    });
  });

  document.querySelectorAll("[data-copy-target]").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget || "");
      const value = target?.textContent?.trim();
      if (!value) return;

      try {
        await navigator.clipboard.writeText(value);
      } catch (_error) {
        const textArea = document.createElement("textarea");
        textArea.value = value;
        textArea.setAttribute("readonly", "");
        textArea.style.position = "fixed";
        textArea.style.opacity = "0";
        document.body.append(textArea);
        textArea.select();
        document.execCommand("copy");
        textArea.remove();
      }

      const originalLabel = button.textContent;
      button.textContent = "Copied";
      window.A2Z?.announce("Copied to clipboard");
      window.setTimeout(() => {
        button.textContent = originalLabel;
      }, 1800);
    });
  });

  document.querySelectorAll("[data-role-form]").forEach((form) => {
    const roleSelect = form.querySelector("[data-role-select]");
    const phone = form.querySelector("[data-role-phone]");
    const branch = form.querySelector("[data-role-branch]");
    const instructorOnly = form.querySelectorAll("[data-instructor-only]");
    const studentOnly = form.querySelectorAll("[data-student-only]");
    const instructorChoices = form.querySelectorAll("[data-create-instructor-choice]");
    const noInstructors = form.querySelector("[data-no-branch-instructors]");

    const syncInstructorChoices = () => {
      const branchId = branch?.value || "";
      let visibleCount = 0;
      instructorChoices.forEach((choice) => {
        const matches = Boolean(branchId) && choice.dataset.branchId === branchId;
        choice.hidden = !matches;
        const input = choice.querySelector("input");
        if (input) {
          input.disabled = !matches;
          if (!matches) input.checked = false;
        }
        if (matches) visibleCount += 1;
      });
      if (noInstructors) noInstructors.hidden = !branchId || visibleCount > 0;
    };

    const syncRoleFields = () => {
      const role = roleSelect?.value || "";
      instructorOnly.forEach((field) => {
        field.hidden = role !== "instructor";
        field.querySelectorAll("input, select, textarea").forEach((control) => {
          control.disabled = role !== "instructor";
        });
      });
      studentOnly.forEach((field) => {
        field.hidden = role !== "student";
        field.querySelectorAll("input, select, textarea").forEach((control) => {
          control.disabled = role !== "student";
        });
      });
      if (phone) phone.required = false;
      syncInstructorChoices();
    };

    roleSelect?.addEventListener("change", syncRoleFields);
    branch?.addEventListener("change", syncInstructorChoices);
    syncRoleFields();
  });

  document.querySelectorAll("[data-permission-fieldset]").forEach((fieldset) => {
    const form = fieldset.closest("form");
    const roleSelect = form?.querySelector("[data-permission-role]");
    const permissionInputs = fieldset.querySelectorAll("[data-permission-bit]");
    const administrator = fieldset.querySelector("[data-administrator-permission]");
    const defaults = { admin: 255, booking_agent: 111, instructor: 100, student: 0 };

    const syncPermissions = (applyDefaults = false) => {
      const role = roleSelect?.value || fieldset.dataset.currentRole || "";
      const administratorSelected = role === "admin";
      if (administrator) administrator.checked = administratorSelected;
      permissionInputs.forEach((input) => {
        if (applyDefaults || administratorSelected) {
          const bit = Number(input.dataset.permissionBit || 0);
          input.checked = Boolean((defaults[role] || 0) & bit);
        }
        input.disabled = administratorSelected || role === "student";
      });
      fieldset.dataset.currentRole = role;
    };

    roleSelect?.addEventListener("change", () => syncPermissions(true));
    syncPermissions(false);
  });

  const userFilters = document.querySelector("[data-user-filters]");
  if (userFilters) {
    const search = userFilters.querySelector("[data-user-search]");
    const role = userFilters.querySelector("[data-user-role-filter]");
    const status = userFilters.querySelector("[data-user-status-filter]");
    const records = document.querySelectorAll("[data-user-record]");
    const emptyState = document.querySelector("[data-user-filter-empty]");

    const filterUsers = () => {
      const query = search?.value.trim().toLowerCase() || "";
      const selectedRole = role?.value || "";
      const selectedStatus = status?.value || "";
      let matches = 0;
      records.forEach((record) => {
        const visible = (!query || record.dataset.search?.toLowerCase().includes(query))
          && (!selectedRole || record.dataset.role === selectedRole)
          && (!selectedStatus || record.dataset.status === selectedStatus);
        record.hidden = !visible;
        if (visible) matches += 1;
      });
      if (emptyState) emptyState.hidden = matches > 0;
    };

    [search, role, status].forEach((control) => {
      control?.addEventListener(control === search ? "input" : "change", filterUsers);
    });
    userFilters.querySelector("[data-clear-user-filters]")?.addEventListener("click", () => {
      if (search) search.value = "";
      if (role) role.value = "";
      if (status) status.value = "";
      filterUsers();
      search?.focus();
    });
  }

  const instructorOrderTable = document.querySelector("[data-instructor-order-table]");
  if (instructorOrderTable) {
    const body = instructorOrderTable.querySelector("tbody");
    const message = document.querySelector("[data-instructor-order-message]");
    const csrfToken = instructorOrderTable.dataset.csrfToken || "";
    const orderUrl = instructorOrderTable.dataset.orderUrl || "";
    let draggedRow = null;
    let savingOrder = false;

    const setOrderMessage = (text, error = false) => {
      if (!message) return;
      message.textContent = text;
      message.classList.toggle("form-error", error);
    };

    const clearDropTargets = () => {
      body?.querySelectorAll(".is-instructor-drop-target").forEach((row) => row.classList.remove("is-instructor-drop-target"));
    };

    const saveOrder = async () => {
      if (savingOrder || !body || !orderUrl) return;
      const instructorIds = Array.from(body.querySelectorAll("[data-instructor-order-row]"))
        .map((row) => Number(row.dataset.instructorId))
        .filter(Number.isInteger);
      if (!instructorIds.length) return;
      savingOrder = true;
      setOrderMessage("Saving calendar order…");
      try {
        const response = await fetch(orderUrl, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
          },
          body: JSON.stringify({ instructor_ids: instructorIds }),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || !result.success) throw new Error(result.error || "Could not save the calendar order.");
        setOrderMessage("Calendar order saved. The calendar columns now use this order.");
      } catch (error) {
        setOrderMessage(error.message || "Could not save the calendar order. Please try again.", true);
      } finally {
        savingOrder = false;
      }
    };

    body?.querySelectorAll("[data-instructor-order-row]").forEach((row) => {
      const handle = row.querySelector("[data-instructor-order-handle]");
      if (!handle) return;
      handle.addEventListener("dragstart", (event) => {
        if (savingOrder) {
          event.preventDefault();
          return;
        }
        draggedRow = row;
        row.classList.add("is-instructor-dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", row.dataset.instructorId || "");
      });
      handle.addEventListener("dragend", () => {
        draggedRow?.classList.remove("is-instructor-dragging");
        draggedRow = null;
        clearDropTargets();
      });
      row.addEventListener("dragover", (event) => {
        if (!draggedRow || draggedRow === row) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        clearDropTargets();
        row.classList.add("is-instructor-drop-target");
      });
      row.addEventListener("drop", (event) => {
        event.preventDefault();
        if (!draggedRow || draggedRow === row || !body) return;
        const before = event.clientY < row.getBoundingClientRect().top + row.getBoundingClientRect().height / 2;
        body.insertBefore(draggedRow, before ? row : row.nextSibling);
        clearDropTargets();
        saveOrder();
      });
    });
  }

  const assignmentForm = document.querySelector("[data-assignment-form]");
  if (assignmentForm) {
    const student = assignmentForm.querySelector("[data-assignment-student]");
    const instructor = assignmentForm.querySelector("[data-assignment-instructor]");
    const hint = assignmentForm.querySelector("[data-assignment-hint]");

    const filterAssignmentInstructors = () => {
      const branchId = student?.selectedOptions[0]?.dataset.branchId || "";
      let available = 0;
      Array.from(instructor?.options || []).forEach((option, index) => {
        if (index === 0) return;
        const matches = Boolean(branchId) && option.dataset.branchId === branchId;
        option.hidden = !matches;
        option.disabled = !matches;
        if (matches) available += 1;
      });
      if (instructor) instructor.value = "";
      if (hint) {
        hint.textContent = !branchId
          ? "Select a student to see instructors in the same branch."
          : available
            ? `${available} verified instructor${available === 1 ? "" : "s"} available in this branch.`
            : "No verified instructor is available in this student's branch.";
      }
    };

    student?.addEventListener("change", filterAssignmentInstructors);
    filterAssignmentInstructors();
  }

  window.A2Z = {
    announce(message) {
      const announcer = document.getElementById("app-announcer");
      if (!announcer) return;
      announcer.textContent = "";
      window.setTimeout(() => {
        announcer.textContent = message;
      }, 30);
    },
  };
})();
