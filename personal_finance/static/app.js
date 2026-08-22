document.addEventListener("DOMContentLoaded", () => {
  const savedScrollPosition = sessionStorage.getItem("transaction-scroll-position");
  if (savedScrollPosition !== null) {
    sessionStorage.removeItem("transaction-scroll-position");
    requestAnimationFrame(() => window.scrollTo(0, Number(savedScrollPosition)));
  }
  const categoryNode = document.querySelector("#category-data");
  const categories = categoryNode ? JSON.parse(categoryNode.textContent) : {};
  const expenseNode = document.querySelector("#expense-data");
  const expenses = expenseNode ? JSON.parse(expenseNode.textContent) : [];
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";

  document.querySelector(".nav-toggle")?.addEventListener("click", (event) => {
    const nav = document.querySelector(".site-header nav");
    const open = nav.classList.toggle("open");
    event.currentTarget.setAttribute("aria-expanded", String(open));
  });

  document.querySelectorAll("[data-open-dialog]").forEach((button) => {
    button.addEventListener("click", () => document.getElementById(button.dataset.openDialog)?.showModal());
  });
  document.querySelectorAll(".close-dialog").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog")?.close("cancel"));
  });

  document.querySelectorAll(".delete-category").forEach((button) => {
    button.addEventListener("click", () => {
      const dialog = document.querySelector("#delete-category-dialog");
      const form = dialog.querySelector("form");
      const level = button.dataset.level;
      const type = button.dataset.type;
      const parent = button.dataset.parent;
      const subcategory = button.dataset.subcategory;
      form.elements.level.value = level;
      form.elements.transaction_type.value = type;
      form.elements.parent.value = parent;
      form.elements.subcategory.value = subcategory;
      const names = [type, parent, subcategory].filter(Boolean);
      dialog.querySelector("#delete-category-name").textContent = names.join(" → ");
      const replacement = form.elements.replacement_id;
      replacement.value = "";
      [...replacement.options].forEach((option) => {
        if (!option.value) return;
        const inScope = option.dataset.type === type
          && (level === "type" || option.dataset.parent === parent)
          && (level !== "subcategory" || option.dataset.subcategory === subcategory);
        option.disabled = inScope;
        option.hidden = inScope;
      });
      dialog.showModal();
    });
  });

  function fillSelect(select, values, placeholder, selected) {
    select.innerHTML = `<option value="">${placeholder}</option>`;
    [...values].sort((left, right) => left.localeCompare(right, undefined, { sensitivity: "base" })).forEach((value) => {
      const option = new Option(value, value, false, value === selected);
      select.add(option);
    });
    select._refreshScrollableMenu?.();
  }

  const categoryPicker = document.createElement("dialog");
  categoryPicker.className = "category-picker-dialog";
  categoryPicker.innerHTML = `
    <div class="category-picker-heading">
      <h2>Choose category</h2>
      <button type="button" aria-label="Close">×</button>
    </div>
    <div class="category-picker-options" role="listbox"></div>`;
  document.body.append(categoryPicker);
  const pickerTitle = categoryPicker.querySelector("h2");
  const pickerOptions = categoryPicker.querySelector(".category-picker-options");
  let activeCategoryPicker = null;

  function closeCategoryPicker() {
    activeCategoryPicker?.button.setAttribute("aria-expanded", "false");
    activeCategoryPicker = null;
    if (categoryPicker.open) categoryPicker.close();
  }
  categoryPicker.querySelector(".category-picker-heading button").addEventListener("click", closeCategoryPicker);
  categoryPicker.addEventListener("click", (event) => {
    if (event.target === categoryPicker) closeCategoryPicker();
  });
  categoryPicker.addEventListener("close", () => {
    activeCategoryPicker?.button.setAttribute("aria-expanded", "false");
    activeCategoryPicker = null;
  });

  function enhanceScrollableSelect(select) {
    if (select.dataset.scrollableSelect === "true") return;
    select.dataset.scrollableSelect = "true";
    const wrapper = document.createElement("div");
    wrapper.className = "scrollable-select";
    select.before(wrapper);
    wrapper.append(select);
    select.classList.add("scrollable-select-source");

    const button = document.createElement("button");
    button.type = "button";
    button.className = "scrollable-select-button";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", select.getAttribute("aria-label") || "Choose an option");
    wrapper.append(button);

    const rebuild = () => {
      const selected = select.options[select.selectedIndex];
      button.textContent = selected?.textContent || "Choose…";
    };
    select._refreshScrollableMenu = rebuild;
    button.addEventListener("click", () => {
      if (categoryPicker.open) categoryPicker.close();
      activeCategoryPicker = { select, button };
      pickerTitle.textContent = `Choose ${select.getAttribute("aria-label") || "category"}`;
      pickerOptions.innerHTML = "";
      [...select.options].forEach((option) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "category-picker-option";
        item.textContent = option.textContent;
        item.setAttribute("role", "option");
        item.setAttribute("aria-selected", String(option.selected));
        item.addEventListener("click", () => {
          select.value = option.value;
          select.dispatchEvent(new Event("change", { bubbles: true }));
          rebuild();
          closeCategoryPicker();
          button.focus();
        });
        pickerOptions.append(item);
      });
      button.setAttribute("aria-expanded", "true");
      categoryPicker.showModal();
      pickerOptions.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
    });
    rebuild();
  }

  function initializeCategoryGroup(typeSelect) {
    const container = typeSelect.parentElement;
    const parent = container.querySelector(".category-parent");
    const sub = container.querySelector(".category-sub");
    if (!parent || !sub) return;
    const updateSubs = () => fillSelect(sub, categories[typeSelect.value]?.[parent.value] || [], "Subcategory", sub.dataset.selected || "");
    const updateParents = () => {
      fillSelect(parent, Object.keys(categories[typeSelect.value] || {}), "Parent", parent.dataset.selected || "");
      updateSubs();
    };
    typeSelect.addEventListener("change", () => { parent.dataset.selected = ""; sub.dataset.selected = ""; updateParents(); });
    parent.addEventListener("change", () => { sub.dataset.selected = ""; updateSubs(); });
    typeSelect._refreshCategories = updateParents;
    updateParents();
    [typeSelect, parent, sub].forEach(enhanceScrollableSelect);
  }
  document.querySelectorAll(".category-type").forEach(initializeCategoryGroup);

  const existingType = document.querySelector("#existing-category-type");
  const existingParent = document.querySelector("#existing-category-parent");
  if (existingType && existingParent) {
    const typeName = document.querySelector("#new-category-type");
    const parentName = document.querySelector("#new-category-parent");
    existingType.addEventListener("change", () => {
      typeName.value = existingType.value;
      fillSelect(existingParent, Object.keys(categories[existingType.value] || {}), "Choose existing parent…", "");
      existingParent.disabled = !existingType.value;
      parentName.value = "";
    });
    existingParent.addEventListener("change", () => {
      parentName.value = existingParent.value;
    });
  }

  document.querySelectorAll(".recurring-toggle").forEach((checkbox) => {
    const saveRecurring = async () => {
      const interval = checkbox.closest(".recurring-control").querySelector(".recurrence-interval").value;
      const body = new URLSearchParams({ enabled: String(checkbox.checked), interval, csrf_token: csrfToken });
      const response = await fetch(checkbox.dataset.url, { method: "POST", body });
      if (!response.ok) { checkbox.checked = !checkbox.checked; alert("The recurring setting could not be saved."); }
    };
    checkbox.addEventListener("change", saveRecurring);
    checkbox.closest(".recurring-control").querySelector(".recurrence-interval").addEventListener("change", () => { if (checkbox.checked) saveRecurring(); });
  });

  document.querySelectorAll("[data-paid-url]").forEach((checkbox) => {
    checkbox.addEventListener("change", async () => {
      const row = checkbox.closest("tr");
      const select = row.querySelector(".transaction-match");
      const body = new URLSearchParams({ paid: String(checkbox.checked), transaction_match: select?.value || "", csrf_token: csrfToken });
      const response = await fetch(checkbox.dataset.paidUrl, { method: "POST", body });
      if (!response.ok) { checkbox.checked = !checkbox.checked; alert("The budget item could not be updated."); return; }
      checkbox.nextElementSibling.textContent = checkbox.checked ? "Paid" : "Mark paid";
      row.classList.toggle("paid-row", checkbox.checked);
    });
  });

  let pendingEditForm = null;
  document.querySelectorAll(".transaction-edit-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      if (form.dataset.approved === "true") {
        sessionStorage.setItem("transaction-scroll-position", String(window.scrollY));
        return;
      }
      event.preventDefault();
      const response = await fetch(`/transactions/${form.dataset.transactionId}/matches`);
      const { matches } = await response.json();
      if (!matches.length) { form.dataset.approved = "true"; form.requestSubmit(); return; }
      pendingEditForm = form;
      const list = document.querySelector("#match-list");
      list.innerHTML = "";
      matches.forEach((match) => {
        const label = document.createElement("label");
        const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.value = match.id; checkbox.checked = true;
        const date = document.createElement("span"); date.textContent = match.date;
        const description = document.createElement("span"); description.textContent = match.description;
        const amount = document.createElement("strong"); amount.textContent = match.amount;
        label.append(checkbox, date, description, amount);
        list.append(label);
      });
      document.querySelector("#bulk-update-dialog").showModal();
    });
  });
  document.querySelector("#bulk-update-dialog")?.addEventListener("close", (event) => {
    if (!pendingEditForm) return;
    if (event.target.returnValue === "default") {
      event.target.querySelectorAll("input:checked").forEach((checkbox) => {
        const hidden = document.createElement("input"); hidden.type = "hidden"; hidden.name = "apply_to"; hidden.value = checkbox.value; pendingEditForm.append(hidden);
      });
    }
    pendingEditForm.dataset.approved = "true";
    pendingEditForm.requestSubmit();
  });

  let splitTransaction = null;
  const splitDialog = document.querySelector("#split-dialog");
  const splitLines = document.querySelector("#split-lines");
  function makeSelect(className, placeholder, values, selected = "") {
    const select = document.createElement("select"); select.className = className; select.add(new Option(placeholder, ""));
    values.forEach((value) => select.add(new Option(value.label || value, value.id || value, false, String(value.id || value) === String(selected))));
    return select;
  }
  function addSplitLine(split = {}) {
    const row = document.createElement("div");
    row.className = "split-line";
    const description = document.createElement("input"); description.className = "split-description"; description.value = split.description || ""; description.placeholder = "Description";
    const amount = document.createElement("input"); amount.className = "split-amount"; amount.value = split.amount || ""; amount.inputMode = "decimal"; amount.placeholder = "Signed amount";
    const categoryGroup = document.createElement("div"); categoryGroup.className = "split-categories";
    const type = makeSelect("split-type category-type", "Type", Object.keys(categories), split.transaction_type);
    const parent = makeSelect("split-parent category-parent", "Parent", [], split.parent_category); parent.dataset.selected = split.parent_category || "";
    const subcategory = makeSelect("split-sub category-sub", "Subcategory", [], split.subcategory); subcategory.dataset.selected = split.subcategory || "";
    categoryGroup.append(type, parent, subcategory);
    const options = document.createElement("div"); options.className = "split-options";
    const recurringLabel = document.createElement("label"); const recurring = document.createElement("input"); recurring.type = "checkbox"; recurring.className = "split-recurring"; recurring.checked = Boolean(split.is_recurring); recurringLabel.append(recurring, " Recurring");
    const reimbursementLabel = document.createElement("label"); const reimbursement = document.createElement("input"); reimbursement.type = "checkbox"; reimbursement.className = "split-reimbursement"; reimbursement.checked = Boolean(split.is_reimbursement); reimbursementLabel.append(reimbursement, " Reimbursement");
    const interval = makeSelect("split-interval", "Frequency", [{ id: 1, label: "Monthly" }, { id: 3, label: "Quarterly" }, { id: 6, label: "Every 6 months" }, { id: 12, label: "Yearly" }], split.interval_months || 1);
    const expense = makeSelect("split-expense", "Link expense…", expenses, split.reimbursement_for_id || "");
    options.append(recurringLabel, interval, reimbursementLabel, expense);
    const remove = document.createElement("button"); remove.type = "button"; remove.className = "icon-button danger"; remove.textContent = "Remove"; remove.addEventListener("click", () => row.remove());
    row.append(description, amount, categoryGroup, options, remove);
    splitLines.append(row);
    initializeCategoryGroup(type);
  }
  document.querySelectorAll(".split-button").forEach((button) => button.addEventListener("click", async () => {
    splitTransaction = { id: button.dataset.id, amount: button.dataset.amount, description: button.dataset.description };
    document.querySelector("#split-total").textContent = `Split ${button.dataset.description}. Amounts must total ${button.dataset.amount}.`;
    const response = await fetch(`/transactions/${button.dataset.id}/splits`); const result = await response.json();
    splitLines.innerHTML = "";
    if (result.splits.length) result.splits.forEach(addSplitLine); else { addSplitLine({ description: button.dataset.description, amount: button.dataset.amount }); addSplitLine(); }
    document.querySelector("#split-error").textContent = ""; splitDialog.showModal();
  }));
  document.querySelector("#add-split-line")?.addEventListener("click", () => addSplitLine());
  document.querySelector("#save-splits")?.addEventListener("click", async () => {
    const splits = [...splitLines.querySelectorAll(".split-line")].map((row) => ({ description: row.querySelector(".split-description").value, amount: row.querySelector(".split-amount").value, transaction_type: row.querySelector(".split-type").value, parent_category: row.querySelector(".split-parent").value, subcategory: row.querySelector(".split-sub").value, is_recurring: row.querySelector(".split-recurring").checked, interval_months: row.querySelector(".split-interval").value, is_reimbursement: row.querySelector(".split-reimbursement").checked, reimbursement_for_id: row.querySelector(".split-expense").value }));
    const response = await fetch(`/transactions/${splitTransaction.id}/splits`, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken }, body: JSON.stringify({ splits }) });
    const result = await response.json();
    if (!response.ok) { document.querySelector("#split-error").textContent = result.error; return; }
    location.reload();
  });

  document.querySelectorAll(".edit-budget").forEach((button) => button.addEventListener("click", () => {
    const dialog = document.querySelector("#edit-budget"); const form = document.querySelector("#edit-budget-form");
    form.action = button.dataset.url; form.elements.description.value = button.dataset.description; form.elements.due_date.value = button.dataset.date; form.elements.amount.value = button.dataset.amount; form.elements.is_reimbursement.checked = button.dataset.reimbursement === "true";
    const type = form.querySelector(".category-type"); const parent = form.querySelector(".category-parent"); const sub = form.querySelector(".category-sub");
    type.value = button.dataset.type; parent.dataset.selected = button.dataset.parent; sub.dataset.selected = button.dataset.subcategory; type._refreshCategories();
    dialog.showModal();
  }));

  document.querySelector(".balance-form")?.addEventListener("submit", (event) => {
    const form = event.currentTarget; const entered = Number(form.elements.balance.value.replaceAll(",", "")); const current = Number(form.dataset.current); const difference = entered - current;
    if (!confirm(`Review transactions before resetting the balance.\n\nCalculated balance: $${current.toFixed(2)}\nEntered bank balance: $${entered.toFixed(2)}\nUnexplained difference: $${difference.toFixed(2)}\n\nCreate this checkpoint?`)) event.preventDefault();
  });
});
