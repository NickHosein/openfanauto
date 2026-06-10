/**
 * OpenFanAuto — single-page vanilla JS UI
 * Dependencies: Tabler (Bootstrap 5), Chart.js 4.x
 */

// =========================================================================
// 0.  Utilities & state
// =========================================================================

const API_BASE = ""; // same origin

let state = {
  fans: [],           // [{id, mode, alias, value, rpm}]
  temps: {},          // {sensor_name: temp_c}
  diskIds: {},        // {sensor_name: last_4_of_serial}
  profiles: {},       // {name: {CurveType, Points, TempSource, UsePWM}}
  controls: {},       // {fan_id_str: {AssignedProfile}}
  automation: false,
  chart: null,        // Chart.js instance
  curvePoints: [],    // [{x: temp, y: value}] working copy
};

/** GET an API endpoint, return parsed JSON data field (or throw). */
async function apiGet(path) {
  const r = await fetch(API_BASE + path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const j = await r.json();
  if (j.status !== "ok") throw new Error(j.message || "API error");
  return j.data;
}

/** Send a GET to a command endpoint. */
async function apiCmd(path) {
  const r = await fetch(API_BASE + path);
  const j = await r.json();
  return j;
}

// =========================================================================
// 1.  Polling loop — fetches fan status + sensors every 2 s
// =========================================================================

async function poll() {
  // Fan status (critical for UI)
  try {
    const fanData = await apiGet("/api/v0/fan/status");
    state.fans = (fanData.fans || []).map(f => ({
      ...f,
      rpm: (fanData.rpm || {})[f.id] || 0,
    }));
    updateStatus("ok");
  } catch (e) {
    updateStatus("error");
    console.error("Fan poll error:", e);
  }

  // Sensors (best-effort — don't break fans if this fails)
  try {
    const sensorData = await apiGet("/api/v0/sensors");
    state.temps = (sensorData && sensorData.temperatures) || {};
    state.diskIds = (sensorData && sensorData.disk_ids) || {};
  } catch (e) {
    state.temps = {};
    state.diskIds = {};
    console.warn("Sensor poll failed:", e);
  }

  renderFanTiles();
  renderTempTiles();
  populateTempSourceSelect();
}

function updateStatus(which) {
  const dot = document.getElementById("status-dot");
  const txt = document.getElementById("status-text");
  dot.className = "status-dot me-2";
  if (which === "ok") {
    dot.classList.add("ok");
    txt.textContent = "Connected";
  } else {
    dot.classList.add("error");
    txt.textContent = "Disconnected";
  }
}

function startPolling(ms = 2000) {
  poll();
  setInterval(poll, ms);
}

// =========================================================================
// 2.  Fan tiles — simplified: badge + RPM, no toggle button
// =========================================================================

function renderFanTiles() {
  const container = document.getElementById("fan-tiles");
  if (!container) return;
  if (!state.fans.length) {
    container.innerHTML = '<div class="col-12 text-muted">No fan data</div>';
    return;
  }
  container.innerHTML = state.fans.map(f => {
    const rpm = f.rpm || 0;
    const modeClass = f.mode === "auto" ? "card-auto" : "card-manual";
    const badgeClass = f.mode === "auto" ? "bg-primary" : "bg-secondary";
    return `
      <div class="col-sm-6 col-md-4 col-lg-3 col-xl-2">
        <div class="card fan-tile ${modeClass}">
          <div class="card-body text-center p-3">
            <div class="fan-mode-badge badge ${badgeClass} mb-1">${escHtml(f.mode)}</div>
            <div class="text-muted small">${escHtml(f.alias || `Fan #${f.id+1}`)}</div>
            <div class="fan-rpm">${rpm.toLocaleString()}</div>
            <div class="text-muted small">RPM</div>
          </div>
        </div>
      </div>`;
  }).join("");
}

// =========================================================================
// 3.  Temperature tiles
// =========================================================================

function renderTempTiles() {
  const container = document.getElementById("temp-tiles");
  const entries = Object.entries(state.temps);
  if (!entries.length) {
    container.innerHTML = '<div class="col-12 text-muted">No sensor data</div>';
    document.getElementById("temps-updated").textContent = "";
    return;
  }
  const now = new Date().toLocaleTimeString();
  document.getElementById("temps-updated").textContent = `Updated ${now}`;

  container.innerHTML = entries.map(([name, temp]) => {
    let cls = "cold";
    if (temp > 45) cls = "hot";
    else if (temp > 35) cls = "warm";
    const idSuffix = (state.diskIds || {})[name] || "";
    return `
      <div class="col-6 col-sm-4 col-md-3 col-lg-2">
        <div class="card temp-tile ${cls}">
          <div class="card-body text-center p-3">
            <div class="temp-source">${escHtml(name)}</div>
            ${idSuffix ? `<div class="temp-id" title="Serial suffix">${escHtml(idSuffix)}</div>` : ""}
            <div class="temp-value">${temp.toFixed(0)}°C</div>
          </div>
        </div>
      </div>`;
  }).join("");
}

function populateTempSourceSelect() {
  const sel = document.getElementById("curve-temp-source");
  if (!sel) return;
  const keys = Object.keys(state.temps);
  if (!keys.length) { sel.innerHTML = '<option value="" disabled>No sensors loaded</option>'; return; }
  const current = new Set([...sel.selectedOptions].map(o => o.value));
  sel.innerHTML = keys.map(k => `<option value="${escHtml(k)}">${escHtml(k)}</option>`).join("");
  [...sel.options].forEach(o => { if (current.has(o.value)) o.selected = true; });
}

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

// =========================================================================
// 4.  All-fans dropdown
// =========================================================================

document.getElementById("all-fans-value").addEventListener("input", function () {
  document.getElementById("all-fans-value-label").textContent = `${this.value}%`;
});

document.getElementById("btn-all-fans-pwm").addEventListener("click", async () => {
  const val = document.getElementById("all-fans-value").value;
  await apiCmd(`/api/v0/fan/all/set?value=${val}`);
  setTimeout(poll, 300);
});

// =========================================================================
// 5.  All-fans dropdown  (no more automation toggle — removed)
// =========================================================================

// =========================================================================
// 6.  Fan Curve Editor (Chart.js)
// =========================================================================

let chartInstance = null;
const curveCanvas = document.getElementById("curve-chart");

function buildChart(points, curveType) {
  const pts = points || [];
  const sorted = [...pts].sort((a, b) => a.x - b.x);
  const stepped = curveType === "threshold";

  if (chartInstance) {
    chartInstance.destroy();
    chartInstance = null;
  }

  chartInstance = new Chart(curveCanvas, {
    type: "scatter",
    data: {
      datasets: [{
        label: "Fan Curve",
        data: sorted,
        showLine: true,
        stepped: stepped ? "before" : false,
        borderColor: "#206bc4",
        backgroundColor: "#206bc4",
        pointRadius: 6,
        pointHoverRadius: 9,
        tension: stepped ? 0 : 0.3,
        fill: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      onClick: onChartClick,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.parsed.x}°C → ${ctx.parsed.y}${ctx.dataset.label.includes("PWM") ? "%" : " RPM"}`,
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          title: { display: true, text: "Temperature (°C)" },
          min: 0,
          max: 80,
          ticks: { stepSize: 10 },
        },
        y: {
          type: "linear",
          title: { display: true, text: document.getElementById("curve-use-pwm").checked ? "PWM %" : "RPM" },
          min: 0,
          max: 100,
          ticks: { stepSize: 10 },
        },
      },
    },
  });
}

function onChartClick(evt) {
  const canvasPos = chartInstance.scales;
  const xVal = Math.round(chartInstance.scales.x.getValueForPixel(evt.x));
  const yVal = Math.round(chartInstance.scales.y.getValueForPixel(evt.y));

  // Add point
  state.curvePoints.push({ x: Math.max(0, xVal), y: Math.max(0, yVal) });
  refreshChart();
  renderPointsTable();
}

// Right-click to delete nearest point
curveCanvas.addEventListener("contextmenu", (evt) => {
  evt.preventDefault();
  const points = chartInstance.getElementsAtEventForMode(evt, "nearest", { intersect: true }, true);
  if (points.length) {
    const idx = points[0].index;
    state.curvePoints.splice(idx, 1);
    refreshChart();
    renderPointsTable();
  }
});

function refreshChart() {
  buildChart(state.curvePoints, document.getElementById("curve-type-select").value);
}

function renderPointsTable() {
  const container = document.getElementById("curve-points-table");
  const sorted = [...state.curvePoints].sort((a, b) => a.x - b.x);
  if (!sorted.length) {
    container.innerHTML = '<div class="text-muted small">No points. Click the chart to add.</div>';
    return;
  }
  container.innerHTML = sorted.map((p, i) => `
    <div class="point-row">
      <span>${p.x}°C → ${p.y}</span>
      <button class="btn btn-sm btn-outline-danger" data-idx="${i}" title="Remove">&times;</button>
    </div>
  `).join("");

  container.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => {
      state.curvePoints.splice(parseInt(btn.dataset.idx), 1);
      refreshChart();
      renderPointsTable();
    });
  });
}

// Load profile into editor
async function loadProfile(name) {
  if (!name || !state.profiles[name]) {
    state.curvePoints = [];
    document.getElementById("curve-type-select").value = "threshold";
    document.getElementById("curve-use-pwm").checked = false;
    const ts = document.getElementById("curve-temp-source");
    if (ts) { for (const o of ts.options) o.selected = false; }
    refreshChart();
    renderPointsTable();
    return;
  }
  const p = state.profiles[name];
  document.getElementById("curve-profile-name").value = name;
  document.getElementById("curve-type-select").value = p.CurveType || "threshold";
  document.getElementById("curve-use-pwm").checked = !!p.UsePWM;
  const sources = p.TempSource || [];
  const ts = document.getElementById("curve-temp-source");
  if (ts) { for (const o of ts.options) o.selected = sources.includes(o.value); }

  const pts = p.Points || {};
  state.curvePoints = Object.entries(pts).map(([k, v]) => ({ x: parseFloat(k), y: parseInt(v) }));
  refreshChart();
  renderPointsTable();
}

// Populate profile dropdown
function populateProfileSelect() {
  const sel = document.getElementById("curve-profile-select");
  if (!sel) return;
  sel.innerHTML = '<option value="">New Profile</option>';
  Object.keys(state.profiles).forEach(name => {
    sel.innerHTML += `<option value="${escHtml(name)}">${escHtml(name)}</option>`;
  });
}

document.getElementById("curve-profile-select").addEventListener("change", function () {
  loadProfile(this.value);
});

document.getElementById("curve-type-select").addEventListener("change", refreshChart);

document.getElementById("curve-use-pwm").addEventListener("change", refreshChart);

// Save profile
document.getElementById("btn-save-curve").addEventListener("click", async () => {
const name = document.getElementById("curve-profile-name").value.trim();
  if (!name) return;

  const points = {};
  state.curvePoints.forEach(p => { points[p.x] = p.y; });

  const ts = document.getElementById("curve-temp-source");
  const tempSource = ts ? [...ts.selectedOptions].map(o => o.value) : [];

  const payload = new URLSearchParams({
    name: name,
    type: document.getElementById("curve-type-select").value,
    points: JSON.stringify(points),
    tempsource: tempSource.join(","),
    usepwm: document.getElementById("curve-use-pwm").checked ? "true" : "false",
  });

  // We build a manual fetch because the add handler reads POST body params
  try {
    const r = await fetch("/api/v0/profiles/add", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: payload.toString(),
    });
    const j = await r.json();
    if (j.status === "ok") {
      flashMsg(`Profile '${name}' saved in memory.`, "success");
      // Refresh profiles list
      const pData = await apiGet("/api/v0/profiles/list");
      state.profiles = pData.profiles || {};
      state.controls = pData.controls || {};
      populateProfileSelect();
      document.getElementById("curve-profile-select").value = name;
      // Show assign-to-fan helper
      showAssignUI(name);
    } else {
      flashMsg("Error: " + j.message, "danger");
    }
  } catch (e) {
    flashMsg("Failed to save profile: " + e, "danger");
  }
});

// Delete profile
document.getElementById("btn-delete-curve").addEventListener("click", async () => {
  const name = document.getElementById("curve-profile-name").value.trim();
  if (!name) { flashMsg("Enter or load a profile name first", "danger"); return; }
  if (!confirm(`Delete profile '${name}'?`)) return;
  await apiCmd(`/api/v0/profiles/remove?name=${encodeURIComponent(name)}`);
  const pData = await apiGet("/api/v0/profiles/list");
  state.profiles = pData.profiles || {};
  state.controls = pData.controls || {};
  populateProfileSelect();
  loadProfile("");
});

// =========================================================================
// 7.  Save-to-disk, flash messages, assign-to-fan
// =========================================================================

/** Show a non-blocking flash message toast at the top of the page. */
function flashMsg(message, type) {
  const container = document.querySelector(".page-body .container-xl");
  if (!container) return;
  const alert = document.createElement("div");
  alert.className = `alert alert-${type || "success"} alert-dismissible fade show`;
  alert.role = "alert";
  alert.style.marginBottom = "1rem";
  alert.innerHTML = `${message} <button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
  container.insertBefore(alert, container.firstChild);
  setTimeout(() => {
    if (alert.parentNode) alert.parentNode.removeChild(alert);
  }, 5000);
}

/** Show a fan-assignment dropdown after a profile is saved. */
function showAssignUI(profileName) {
  // Remove any existing assign row
  const old = document.getElementById("assign-row");
  if (old) old.remove();

  const cardBody = document.querySelector("#curve-points-table").closest(".card-body");
  if (!cardBody) return;

  const fans = state.fans || [];
  if (!fans.length) return;

  const row = document.createElement("div");
  row.id = "assign-row";
  row.className = "mt-3 pt-3 border-top";
  row.innerHTML = `
    <label class="form-label">Assign '${escHtml(profileName)}' to fan:</label>
    <div class="d-flex gap-2">
      <select class="form-select" id="assign-fan-select">
        <option value="">— choose fan —</option>
        ${fans.map(f => `<option value="${f.id}">${escHtml(f.alias || `Fan #${f.id + 1}`)}</option>`).join("")}
      </select>
      <button class="btn btn-outline-primary" id="btn-assign-fan">Assign</button>
    </div>
  `;
  cardBody.appendChild(row);

  document.getElementById("btn-assign-fan").addEventListener("click", async () => {
    const fanId = document.getElementById("assign-fan-select").value;
    if (!fanId) return;
    try {
      const r = await fetch("/api/v0/controls/assign", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ fan: fanId, profile: profileName }),
      });
      const j = await r.json();
      flashMsg(j.message, j.status === "ok" ? "success" : "danger");
      // Refresh controls
      const pData = await apiGet("/api/v0/profiles/list");
      state.controls = pData.controls || {};
    } catch (e) {
      flashMsg("Assign failed: " + e, "danger");
    }
  });
}

// Save to Disk button
document.getElementById("btn-save-disk").addEventListener("click", async () => {
  const btn = document.getElementById("btn-save-disk");
  btn.disabled = true;
  btn.textContent = "Saving...";
  try {
    const j = await apiCmd("/api/v0/config/save");
    flashMsg(j.message, j.status === "ok" ? "success" : "danger");
  } catch (e) {
    flashMsg("Save failed: " + e, "danger");
  }
  btn.disabled = false;
  btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon"><path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M6 4h10l4 4v10a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2v-12a2 2 0 0 1 2 -2"/><path d="M12 14m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M14 4l0 4l-6 0l0 -4"/></svg> Save`;
});

// =========================================================================
// 8.  Initialisation
// =========================================================================

async function init() {
  // Load profiles
  try {
    const pData = await apiGet("/api/v0/profiles/list");
    state.profiles = pData.profiles || {};
    state.controls = pData.controls || {};
    populateProfileSelect();
  } catch (e) {
    console.warn("Could not load profiles:", e);
  }


  // Initial chart
  buildChart([], "threshold");
  populateTempSourceSelect();

  // Repopulate fan select in curve editor when fan data arrives
  function populateFanSelect() {
    const sel = document.getElementById("curve-fan-select");
    if (!sel) return;
    sel.innerHTML = (state.fans || []).map(f =>
      `<option value="${f.id}">${escHtml(f.alias || `Fan #${f.id+1}`)}</option>`
    ).join("");
  }
  populateFanSelect();

  const origRender = renderFanTiles;
  renderFanTiles = function () {
    origRender();
    populateFanSelect();
  };

  startPolling();
}

document.addEventListener("DOMContentLoaded", init);