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
      <div style="flex:0 0 calc(20% - 0.4rem); min-width:130px">
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
    const hasTemp = temp !== null && temp !== undefined;
    if (hasTemp) {
      if (temp > 45) cls = "hot";
      else if (temp > 35) cls = "warm";
    } else {
      cls = "spun-down";
    }
    const idSuffix = (state.diskIds || {})[name] || "";
    const tempDisplay = hasTemp ? `${temp.toFixed(0)}°C` : "—";
    const tempTitle = hasTemp ? "" : "spun down";
    return `
      <div class="col-6 col-sm-4 col-md-3 col-lg-2">
        <div class="card temp-tile ${cls}">
          <div class="card-body text-center p-3">
            <div class="temp-source">${escHtml(name)}</div>
            ${idSuffix ? `<div class="temp-id" title="Serial suffix">${escHtml(idSuffix)}</div>` : ""}
            <div class="temp-value" title="${tempTitle}">${tempDisplay}</div>
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
// 4.  Manual fan control
// =========================================================================

// Mode toggle changes slider range
document.getElementById("manual-mode-select").addEventListener("change", function () {
  const slider = document.getElementById("manual-fan-value");
  const label = document.getElementById("manual-value-label");
  if (this.value === "pwm") {
    slider.min = 0; slider.max = 100; slider.value = 50; slider.step = 1;
    label.textContent = "50%";
  } else {
    slider.min = 0; slider.max = 5500; slider.value = 1000; slider.step = 50;
    label.textContent = "1000 RPM";
  }
});

document.getElementById("manual-fan-value").addEventListener("input", function () {
  const mode = document.getElementById("manual-mode-select").value;
  document.getElementById("manual-value-label").textContent =
    mode === "pwm" ? `${this.value}%` : `${this.value} RPM`;
});

// Apply manual speed (handles individual fans and "All Fans")
document.getElementById("btn-apply-manual").addEventListener("click", async () => {
  const idx = document.getElementById("manual-fan-select").value;
  const mode = document.getElementById("manual-mode-select").value;
  const val = document.getElementById("manual-fan-value").value;
  try {
    if (idx === "all") {
      if (mode === "pwm") {
        await apiCmd(`/api/v0/fan/all/set?value=${val}`);
      } else {
        for (let i = 0; i < 10; i++) await apiCmd(`/api/v0/fan/${i}/rpm?value=${val}`);
      }
      for (let i = 0; i < 10; i++) await apiCmd(`/api/v0/fan/${i}/mode?mode=manual`);
      flashMsg(`All fans set to ${val}${mode === "pwm" ? "%" : " RPM"} (manual).`, "success");
    } else {
      if (mode === "pwm") {
        await apiCmd(`/api/v0/fan/${idx}/pwm?value=${val}`);
      } else {
        await apiCmd(`/api/v0/fan/${idx}/rpm?value=${val}`);
      }
      await apiCmd(`/api/v0/fan/${idx}/mode?mode=manual`);
      flashMsg("Manual speed applied.", "success");
    }
    setTimeout(poll, 300);
  } catch (e) { flashMsg("Manual apply failed: " + e, "danger"); }
});

// Populate the manual fan dropdown (includes "All Fans" option)
function populateManualSelect() {
  const sel = document.getElementById("manual-fan-select");
  if (!sel) return;
  sel.innerHTML = '<option value="all">All Fans</option>' +
    (state.fans || []).map(f =>
      `<option value="${f.id}">${escHtml(f.alias || `Fan #${f.id+1}`)}</option>`
    ).join("");
}

// =========================================================================
// 6.  All-fans dropdown  (no more automation toggle — removed)
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
          max: document.getElementById("curve-use-pwm").checked ? 100 : 5500,
          ticks: { stepSize: document.getElementById("curve-use-pwm").checked ? 10 : 500 },
        },
      },
    },
  });
}

function onChartClick(evt) {
  const xVal = Math.max(0, Math.round(chartInstance.scales.x.getValueForPixel(evt.x)));
  const yVal = Math.max(0, Math.round(chartInstance.scales.y.getValueForPixel(evt.y)));

  // Check for existing point at same temperature (±1 °C tolerance)
  const existing = state.curvePoints.findIndex(p => Math.abs(p.x - xVal) <= 1);
  if (existing >= 0) {
    // Update existing point's value instead of duplicating
    state.curvePoints[existing].y = yVal;
  } else {
    state.curvePoints.push({ x: xVal, y: yVal });
  }
  refreshChart();
  renderPointsTable();
}

// Right-click to delete nearest point (manual coordinate matching)
curveCanvas.addEventListener("contextmenu", (evt) => {
  evt.preventDefault();
  const xVal = Math.round(chartInstance.scales.x.getValueForPixel(evt.offsetX));
  const existing = state.curvePoints.findIndex(p => Math.abs(p.x - xVal) <= 1);
  if (existing >= 0) {
    state.curvePoints.splice(existing, 1);
    refreshChart();
    renderPointsTable();
  }
});

// Click-to-toggle for multi-select dropdowns (no Ctrl needed)
function setupClickToggle(sel) {
  sel.addEventListener("mousedown", function (evt) {
    const opt = evt.target.closest("option");
    if (!opt) return;
    evt.preventDefault();
    opt.selected = !opt.selected;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
setupClickToggle(document.getElementById("curve-fan-select"));
setupClickToggle(document.getElementById("curve-temp-source"));

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
    document.getElementById("curve-type-select").value = "linear";
    document.getElementById("curve-use-pwm").checked = true;
    const ts = document.getElementById("curve-temp-source");
    if (ts) { for (const o of ts.options) o.selected = false; }
    const fs = document.getElementById("curve-fan-select");
    if (fs) { for (const o of fs.options) o.selected = false; }
    refreshChart();
    renderPointsTable();
    return;
  }
  const p = state.profiles[name];
  document.getElementById("curve-profile-name").value = name;
    document.getElementById("curve-type-select").value = p.CurveType || "linear";
  document.getElementById("curve-use-pwm").checked = !!p.UsePWM;
  const sources = p.TempSource || [];
  const ts = document.getElementById("curve-temp-source");
  if (ts) { for (const o of ts.options) o.selected = sources.includes(o.value); }
  // Select fans assigned to this profile
  const fs = document.getElementById("curve-fan-select");
  if (fs) {
    for (const o of fs.options) {
      const ctrl = (state.controls || {})[o.value] || {};
      o.selected = ctrl.AssignedProfile === name;
    }
  }

  const pts = p.Points || {};
  state.curvePoints = Object.entries(pts).map(([k, v]) => ({ x: parseFloat(k), y: parseInt(v) }));
  refreshChart();
  renderPointsTable();
}

// Populate profile dropdown (suppress change event during rebuild)
function populateProfileSelect() {
  const sel = document.getElementById("curve-profile-select");
  if (!sel) return;
  const prev = sel.value;
  const handler = sel.onchange;
  sel.onchange = null;
  sel.innerHTML = '<option value="">New Profile</option>';
  Object.keys(state.profiles).forEach(name => {
    sel.innerHTML += `<option value="${escHtml(name)}">${escHtml(name)}</option>`;
  });
  sel.value = prev;
  sel.onchange = handler || function () { loadProfile(this.value); };
}

document.getElementById("curve-profile-select").addEventListener("change", function () {
  document.getElementById("curve-profile-name").value = this.value;
  loadProfile(this.value);
});

document.getElementById("curve-type-select").addEventListener("change", refreshChart);

document.getElementById("curve-use-pwm").addEventListener("change", refreshChart);

// Clear button — reset editor to defaults
document.getElementById("btn-clear-curve").addEventListener("click", () => {
  state.curvePoints = [];
  document.getElementById("curve-profile-name").value = "";
  document.getElementById("curve-type-select").value = "linear";
  document.getElementById("curve-use-pwm").checked = true;
  document.getElementById("curve-profile-select").value = "";
  const ts = document.getElementById("curve-temp-source");
  if (ts) { for (const o of ts.options) o.selected = false; }
  const fs = document.getElementById("curve-fan-select");
  if (fs) { for (const o of fs.options) o.selected = false; }
  refreshChart();
  renderPointsTable();
});

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
      // Show toast immediately — don't block the user on fan assignments
      flashMsg(`Profile '${name}' saved.`, "success");

      // Collect selected fans + any existing controls referencing this profile
      const fanSel = document.getElementById("curve-fan-select");
      const fanIds = fanSel ? [...fanSel.selectedOptions].map(o => o.value) : [];
      for (const [fid, ctrl] of Object.entries(state.controls || {})) {
        if (ctrl.AssignedProfile === name && !fanIds.includes(fid)) fanIds.push(fid);
      }

      // Fire all fan assignments in parallel, then refresh the dropdown
      if (fanIds.length) {
        Promise.all(fanIds.map(fid =>
          fetch("/api/v0/controls/assign", {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: new URLSearchParams({ fan: fid, profile: name }),
          })
        )).then(async () => {
          const pData = await apiGet("/api/v0/profiles/list");
          state.profiles = pData.profiles || {};
          state.controls = pData.controls || {};
          populateProfileSelect();
          document.getElementById("curve-profile-select").value = name;
        }).catch(e => console.warn("Background fan assignment failed:", e));
      } else {
        // No fans to assign — just refresh the dropdown
        const pData = await apiGet("/api/v0/profiles/list");
        state.profiles = pData.profiles || {};
        state.controls = pData.controls || {};
        populateProfileSelect();
        document.getElementById("curve-profile-select").value = name;
      }
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
  document.getElementById("curve-profile-select").value = "";
  document.getElementById("curve-profile-name").value = "";
  loadProfile("");
});

// =========================================================================
// 7.  Save-to-disk, flash messages, assign-to-fan
// =========================================================================

/** Show a flash toast in the bottom-right corner that auto-fades after 5s. */
function flashMsg(message, type) {
  const toast = document.createElement("div");
  toast.className = `flash-toast alert alert-${type || "success"} d-flex align-items-center`;
  toast.style.cssText = "position:fixed;bottom:1.5rem;right:1.5rem;z-index:9999;min-width:280px;max-width:420px;opacity:0;transition:opacity 0.3s ease";
  toast.innerHTML = `<span class="flex-fill small">${message}</span><button type="button" class="btn-close ms-2" onclick="this.parentElement.remove()"></button>`;
  document.body.appendChild(toast);
  // Trigger fade-in
  requestAnimationFrame(() => { toast.style.opacity = "1"; });
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 300);
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

// (Save-to-disk button removed — config writes happen on profile save)

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
  buildChart([], "linear");
  populateTempSourceSelect();
  populateManualSelect();

  // Repopulate fan select in curve editor when fan data arrives
  // Annotates each option with its current profile assignment
  function populateFanSelect() {
    const sel = document.getElementById("curve-fan-select");
    if (!sel) return;
    const current = new Set([...sel.selectedOptions].map(o => o.value));
    sel.innerHTML = (state.fans || []).map(f => {
      const ctrl = (state.controls || {})[String(f.id)] || {};
      const profile = ctrl.AssignedProfile || "";
      const label = profile
        ? `${escHtml(f.alias || `Fan #${f.id+1}`)} → ${escHtml(profile)}`
        : `${escHtml(f.alias || `Fan #${f.id+1}`)} — manual`;
      return `<option value="${f.id}">${label}</option>`;
    }).join("");
    [...sel.options].forEach(o => { if (current.has(o.value)) { o.selected = true; } });
  }
  populateFanSelect();

  const origRender = renderFanTiles;
  renderFanTiles = function () {
    origRender();
    populateFanSelect();
    populateManualSelect();
  };

  startPolling();
}

document.addEventListener("DOMContentLoaded", init);