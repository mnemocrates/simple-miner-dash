/**
 * simple-miner-dash — app.js
 * Single-page logic: search view ↔ stats view, driven by ?address= URL param.
 */

/* ── Strict Bitcoin address pattern (mirrors the CGI-side regex) ─────────── */
const ADDRESS_RE = /^(bc1[a-z0-9]{25,90}|[13][a-zA-Z0-9]{25,34})$/;

/* ── Entry point ─────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", init);

function init() {
  const params = new URLSearchParams(window.location.search);
  const address = (params.get("address") || "").trim();
  const pool    = (params.get("pool")    || "default").trim();

  if (address) {
    renderStatsView(address, pool);
  } else {
    renderSearchView();
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   SEARCH VIEW
═══════════════════════════════════════════════════════════════════════════ */
function renderSearchView() {
  const tpl = document.getElementById("tpl-search");
  const app = document.getElementById("app");
  app.replaceChildren(tpl.content.cloneNode(true));

  const form   = app.querySelector("#search-form");
  const input  = app.querySelector("#address-input");
  const errEl  = app.querySelector("#search-error");

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const value = input.value.trim();

    if (!value) {
      showFieldError(errEl, "Please enter a Bitcoin address.");
      input.focus();
      return;
    }
    if (!ADDRESS_RE.test(value)) {
      showFieldError(errEl, "That doesn't look like a valid Bitcoin address.");
      input.focus();
      return;
    }

    hideFieldError(errEl);
    const poolValue = app.querySelector("#pool-select").value;
    window.location.href = "/?address=" + encodeURIComponent(value)
                         + "&pool="    + encodeURIComponent(poolValue);
  });

  input.addEventListener("input", () => hideFieldError(errEl));
}

function showFieldError(el, msg) {
  el.textContent = msg;
  el.hidden = false;
}

function hideFieldError(el) {
  el.hidden = true;
  el.textContent = "";
}

/* ═══════════════════════════════════════════════════════════════════════════
   STATS VIEW
═══════════════════════════════════════════════════════════════════════════ */
function renderStatsView(address, pool) {
  const tpl = document.getElementById("tpl-stats");
  const app = document.getElementById("app");
  app.replaceChildren(tpl.content.cloneNode(true));

  // Address bar
  app.querySelector("#address-display").textContent = address;

  // Back link preserves plain /
  app.querySelector("#back-link").setAttribute("href", "/");

  // Set pool selector to current pool and handle switching
  const poolSelect = app.querySelector("#pool-select");
  poolSelect.value = pool;
  poolSelect.addEventListener("change", () => {
    window.location.href = "/?address=" + encodeURIComponent(address)
                         + "&pool="    + encodeURIComponent(poolSelect.value);
  });

  // Show loading spinner while fetching
  const statsContent  = app.querySelector("#stats-content");
  const errorBanner   = app.querySelector("#error-banner");
  const workerSelect  = app.querySelector("#worker-select");

  showLoading(statsContent);

  fetchMinerData(address, pool)
    .then((data) => {
      hideLoading(statsContent);
      if (data.error) {
        showError(errorBanner, errorMessage(data.error));
        return;
      }

      // Populate worker dropdown
      populateWorkerDropdown(workerSelect, data);

      // Initial render: overall stats
      statsContent.hidden = false;
      renderStatsCards(app, data);

      // Worker selection handler
      workerSelect.addEventListener("change", () => {
        const val = workerSelect.value;
        if (val === "__all__") {
          renderStatsCards(app, data);
        } else {
          const workers = data.worker || [];
          const w = workers.find((wk) => wk.workername === val);
          if (w) renderStatsCards(app, w, /* isWorker */ true);
        }
      });
    })
    .catch(() => {
      hideLoading(statsContent);
      showError(errorBanner, "Could not connect to the server. Please try again later.");
    });
}

/* ── Data fetching ───────────────────────────────────────────────────────── */
async function fetchMinerData(address, pool) {
  const url = "/api/miner?address=" + encodeURIComponent(address)
            + "&pool=" + encodeURIComponent(pool);
  const resp = await fetch(url, { cache: "no-store" });
  const json = await resp.json();
  return json;
}

/* ── Worker dropdown ─────────────────────────────────────────────────────── */
function populateWorkerDropdown(select, data) {
  const workers = data.worker || [];

  const allOpt = new Option("All Workers", "__all__");
  select.appendChild(allOpt);

  workers.forEach((w) => {
    const label = workerDisplayName(w.workername);
    const opt = new Option(label, w.workername);
    select.appendChild(opt);
  });

  // If there's exactly one worker (plus the all option) pre-select the worker
  // so the user immediately sees useful data — but leave as "All" by default.
}

/**
 * Returns a short display name for a worker.
 * "bc1q...abc.nano3s" → "nano3s"
 * "bc1q...abc"        → "Default"
 */
function workerDisplayName(workername) {
  const dot = workername.indexOf(".");
  if (dot === -1) return "Default";
  return workername.slice(dot + 1);
}

/* ── Stats card rendering ────────────────────────────────────────────────── */
function renderStatsCards(app, data, isWorker = false) {
  renderHashrateCards(app.querySelector("#cards-hashrate"), data);
  renderSharesCards(app.querySelector("#cards-shares"), data);
  renderStatusCards(app.querySelector("#cards-status"), data, isWorker);
}

function renderHashrateCards(container, data) {
  container.replaceChildren(
    makeCard(formatHashrate(data.hashrate1m),  "1 min",  hashrateClass(data.hashrate1m)),
    makeCard(formatHashrate(data.hashrate5m),  "5 min",  hashrateClass(data.hashrate5m)),
    makeCard(formatHashrate(data.hashrate1hr), "1 hour", hashrateClass(data.hashrate1hr)),
    makeCard(formatHashrate(data.hashrate1d),  "1 day",  hashrateClass(data.hashrate1d)),
    makeCard(formatHashrate(data.hashrate7d),  "7 days", hashrateClass(data.hashrate7d))
  );
}

function renderSharesCards(container, data) {
  container.replaceChildren(
    makeCard(formatLargeNumber(data.shares),               "Total Shares"),
    makeCard(formatLargeNumber(data.bestshare, 2),         "Best Share",  "accent", /* wide */ true),
    makeCard(formatLargeNumber(data.bestever),             "Best Ever",   "accent", /* wide */ true)
  );
}

function renderStatusCards(container, data, isWorker) {
  const cards = [
    makeCard(formatTimestamp(data.lastshare), "Last Share", timestampClass(data.lastshare)),
  ];

  if (!isWorker) {
    // Top-level fields not present on individual worker objects
    if (data.workers !== undefined) {
      cards.push(makeCard(String(data.workers), "Active Workers",
        data.workers > 0 ? "green" : "muted"));
    }
    if (data.authorised !== undefined) {
      cards.push(makeCard(formatTimestamp(data.authorised), "Authorised", "muted"));
    }
  }

  container.replaceChildren(...cards);
}

/* ── Card factory ────────────────────────────────────────────────────────── */
function makeCard(value, label, valueClass = "", wide = false) {
  const card  = document.createElement("div");
  card.className = "stat-card" + (wide ? " wide" : "");

  const valEl = document.createElement("div");
  valEl.className = "stat-value" + (valueClass ? " " + valueClass : "");
  valEl.textContent = value ?? "—";

  const lblEl = document.createElement("div");
  lblEl.className = "stat-label";
  lblEl.textContent = label;

  card.appendChild(valEl);
  card.appendChild(lblEl);
  return card;
}

/* ── Loading state helpers ───────────────────────────────────────────────── */
function showLoading(contentEl) {
  contentEl.hidden = true;
  const wrapper = document.createElement("div");
  wrapper.className = "loading";
  wrapper.id = "__loading__";
  wrapper.innerHTML = '<div class="spinner"></div><span>Loading…</span>';
  contentEl.parentNode.insertBefore(wrapper, contentEl);
}

function hideLoading(contentEl) {
  const existing = document.getElementById("__loading__");
  if (existing) existing.remove();
}

/* ── Error banner helper ─────────────────────────────────────────────────── */
function showError(bannerEl, message) {
  bannerEl.querySelector("#error-message").textContent = message;
  bannerEl.hidden = false;
}

function errorMessage(code) {
  const map = {
    miner_not_found: "Miner not found. Check the address and try again.",
    invalid_address: "Invalid Bitcoin address.",
    invalid_data:    "The miner data file could not be read.",
    internal_error:  "A server error occurred. Please try again later.",
  };
  return map[code] || "An unexpected error occurred.";
}

/* ═══════════════════════════════════════════════════════════════════════════
   FORMATTING HELPERS
═══════════════════════════════════════════════════════════════════════════ */

/**
 * Hashrate strings from ckpool are already human-readable (e.g. "27.8T", "5.01G").
 * A value of "0" means the miner hasn't submitted a share in that window.
 */
function formatHashrate(value) {
  if (value === undefined || value === null) return "—";
  const s = String(value).trim();
  if (s === "0") return "0";
  return s;
}

/** CSS class for a hashrate value cell */
function hashrateClass(value) {
  if (value === undefined || value === null || String(value).trim() === "0") return "zero";
  return "green";
}

/**
 * Format a large number (shares, bestshare, bestever) with commas.
 * bestshare can be a float; bestever is always an integer.
 */
function formatLargeNumber(value, decimals = 0) {
  if (value === undefined || value === null) return "—";
  const n = Number(value);
  if (isNaN(n)) return String(value);
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Convert Unix epoch seconds to a local human-readable string */
function formatTimestamp(epoch) {
  if (!epoch) return "—";
  const d = new Date(Number(epoch) * 1000);
  return d.toLocaleString(undefined, {
    year:   "numeric",
    month:  "short",
    day:    "numeric",
    hour:   "2-digit",
    minute: "2-digit",
  });
}

/** Colour class for a last-share timestamp (stale if > 30 min old) */
function timestampClass(epoch) {
  if (!epoch) return "muted";
  const ageMin = (Date.now() / 1000 - Number(epoch)) / 60;
  if (ageMin < 30) return "green";
  if (ageMin < 120) return "";
  return "muted";
}
