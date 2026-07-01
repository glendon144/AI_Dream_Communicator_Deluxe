let actions = [];
let selectedAction = null;

const actionsBox = document.getElementById("actions");
const statusBox = document.getElementById("status");
const responseBox = document.getElementById("response");
const selectedTitle = document.getElementById("selected-title");
const selectedDescription = document.getElementById("selected-description");
const callButton = document.getElementById("call-button");
const refreshButton = document.getElementById("refresh");
const statusButton = document.getElementById("status-button");
const parameterPanel = document.getElementById("parameter-panel");
const valueSelect = document.getElementById("value-select");

refreshButton.addEventListener("click", loadActions);
statusButton.addEventListener("click", loadStatus);
callButton.addEventListener("click", callSelectedAction);

window.addEventListener("load", async () => {
  await loadStatus();
  await loadActions();
});

async function loadStatus() {
  statusBox.textContent = "Loading status...";
  try {
    const data = await getJson("/api/status");
    responseBox.textContent = JSON.stringify(data, null, 2);
    if (data.ok) {
      const s = data.status;
      statusBox.textContent = `${s.title || s.name || "WebMCP"} · ${s.action_count || "?"} actions · mode: ${s.mode || "stdio"}`;
    } else {
      statusBox.textContent = data.error || "Status failed.";
    }
  } catch (error) {
    statusBox.textContent = error.message;
  }
}

async function loadActions() {
  actionsBox.innerHTML = "";
  statusBox.textContent = "Loading actions...";

  try {
    const data = await getJson("/api/actions");
    if (!data.ok) {
      statusBox.textContent = data.error || "Could not load actions.";
      return;
    }

    actions = data.actions || [];
    statusBox.textContent = `Loaded ${actions.length} actions.`;
    renderActions();
  } catch (error) {
    statusBox.textContent = error.message;
  }
}

function renderActions() {
  actionsBox.innerHTML = actions.map((action) => `
    <button class="action" data-name="${escapeHtml(action.name)}">
      <div class="action-name">${escapeHtml(action.name)}</div>
      <div class="action-meta">${escapeHtml(action.method || "")} · ${escapeHtml(action.risk || "")}</div>
    </button>
  `).join("");

  for (const button of document.querySelectorAll(".action")) {
    button.addEventListener("click", () => selectAction(button.dataset.name));
  }
}

function selectAction(name) {
  selectedAction = actions.find((a) => a.name === name) || null;

  for (const button of document.querySelectorAll(".action")) {
    button.classList.toggle("selected", button.dataset.name === name);
  }

  if (!selectedAction) {
    selectedTitle.textContent = "Select an action";
    selectedDescription.textContent = "";
    callButton.disabled = true;
    parameterPanel.classList.add("hidden");
    return;
  }

  selectedTitle.textContent = selectedAction.name;
  selectedDescription.textContent = selectedAction.description || "";
  callButton.disabled = false;

  const enumValues = selectedAction.parameters?.value?.enum || [];
  if (selectedAction.method === "setValueAndChange" && enumValues.length) {
    valueSelect.innerHTML = enumValues.map((value) => `
      <option value="${escapeHtml(value)}">${escapeHtml(value)}</option>
    `).join("");
    parameterPanel.classList.remove("hidden");
  } else {
    valueSelect.innerHTML = "";
    parameterPanel.classList.add("hidden");
  }

  responseBox.textContent = JSON.stringify(selectedAction, null, 2);
}

async function callSelectedAction() {
  if (!selectedAction) return;

  const parameters = {};
  if (selectedAction.method === "setValueAndChange") {
    parameters.value = valueSelect.value;
  }

  callButton.disabled = true;
  responseBox.textContent = "Calling action...";

  try {
    const response = await fetch("/api/call", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: selectedAction.name,
        parameters,
      }),
    });

    const data = await response.json();
    responseBox.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    responseBox.textContent = JSON.stringify({ ok: false, error: error.message }, null, 2);
  } finally {
    callButton.disabled = false;
  }
}

async function getJson(url) {
  const response = await fetch(url);
  return await response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
