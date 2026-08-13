(() => {
  "use strict";

  const form = document.querySelector("[data-time-off-form]");
  const allDay = form?.querySelector("[data-all-day]");
  const partialFields = form?.querySelectorAll("[data-partial-time]");
  const partialInputs = form?.querySelectorAll("[data-partial-time-input]");

  const syncTimeOffFields = () => {
    if (!allDay || !partialFields || !partialInputs) return;
    const wholeDay = allDay.checked;
    partialFields.forEach((field) => {
      field.hidden = wholeDay;
    });
    partialInputs.forEach((input) => {
      input.disabled = wholeDay;
      input.required = !wholeDay;
    });
  };

  if (allDay) {
    allDay.addEventListener("change", syncTimeOffFields);
    syncTimeOffFields();
  }
})();
