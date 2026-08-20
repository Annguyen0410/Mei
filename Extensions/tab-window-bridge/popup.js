const STORAGE_KEY = "litebrowserWindowBatches";

function setStatus(text, isError = false) {
  const node = document.getElementById("status");
  node.textContent = text || "";
  node.style.color = isError ? "#fca5a5" : "#fde68a";
}

async function getStoredBatches() {
  const data = await chrome.storage.local.get([STORAGE_KEY]);
  return data[STORAGE_KEY] || {};
}

async function saveStoredBatches(batches) {
  await chrome.storage.local.set({ [STORAGE_KEY]: batches });
}

function normalizeBrowserName() {
  const ua = navigator.userAgent || "";
  if (/OPR\//i.test(ua) || /Opera/i.test(ua)) return "opera-gx";
  if (/Chrome/i.test(ua)) return "chrome";
  return "chromium";
}

/* --- pure helpers -------------------------------------------------------- */

function tabsToPayload(tabs, browserName) {
  return tabs
    .filter(tab => tab.url && /^https?:/i.test(tab.url))
    .map(tab => ({
      url: tab.url,
      title: tab.title || tab.url,
      active: Boolean(tab.active),
      pinned: Boolean(tab.pinned),
      index: Number(tab.index || 0),
    }))
    .sort((a, b) => a.index - b.index);
}

function buildWindowPayload(windowId, sourceLabel, tabs, browserName, createdAt, screenIndex) {
  const payload = {
    batch_id: `${browserName}_window_${windowId}`,
    window_id: String(windowId),
    source_browser: browserName,
    source_label: sourceLabel || `Window ${windowId}`,
    created_at: createdAt,
    tabs,
  };
  if (Number.isInteger(screenIndex)) payload.screen_index = screenIndex;
  return payload;
}

/* Wrap the whole multi-window export in a container Mei's Import Center
 * understands. Each browser window (i.e. each monitor/screen) becomes one
 * batch, so screen 1 → batch 1 (50 tabs), screen 2 → batch 2 (32 tabs), etc. */
function buildWorkspacePayload(batches, browserName, createdAt) {
  return {
    format: "mei-multi-window",
    version: 1,
    source_browser: browserName,
    created_at: createdAt,
    window_count: batches.length,
    batches,
  };
}

/* --- captures ------------------------------------------------------------- */

async function captureCurrentWindow() {
  const [currentTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!currentTab?.windowId) {
    throw new Error("Could not detect the current window.");
  }

  const tabs = await chrome.tabs.query({ currentWindow: true });
  const httpTabs = tabsToPayload(tabs, normalizeBrowserName());
  if (!httpTabs.length) {
    throw new Error("This window has no normal web tabs to export.");
  }

  const now = Date.now();
  const browserName = normalizeBrowserName();
  const labelInput = document.getElementById("labelInput").value.trim();
  const payload = buildWindowPayload(
    currentTab.windowId,
    labelInput || `Window ${currentTab.windowId}`,
    httpTabs,
    browserName,
    now,
  );

  const batches = await getStoredBatches();
  batches[String(currentTab.windowId)] = payload;
  await saveStoredBatches(batches);
  return payload;
}

async function captureAllWindows() {
  // One browser window == one screen/monitor. Order windows so screen 1 is
  // first; each gets a numbered label and its tabs sorted by position.
  let windows = await chrome.windows.getAll({ populate: true });
  if (!windows.length) {
    throw new Error("No browser windows found.");
  }
  // Sort left→right so "Screen 1" is the leftmost monitor, matching how people
  // read a dual-monitor desk (screen 1 = 50 tabs, screen 2 = 32 tabs, ...).
  windows = windows.slice().sort((a, b) => (a.left || 0) - (b.left || 0));
  const browserName = normalizeBrowserName();
  const now = Date.now();
  const stored = await getStoredBatches();
  const payloads = [];

  windows.forEach((win, idx) => {
    const httpTabs = tabsToPayload(win.tabs || [], browserName);
    if (!httpTabs.length) return;
    const payload = buildWindowPayload(
      win.id,
      `Screen ${idx + 1}`,
      httpTabs,
      browserName,
      now,
      idx,
    );
    payloads.push(payload);
    stored[String(win.id)] = payload;
  });

  if (!payloads.length) {
    throw new Error("No windows with normal web tabs to export.");
  }

  await saveStoredBatches(stored);
  return buildWorkspacePayload(payloads, browserName, now);
}

/* --- rendering ------------------------------------------------------------ */

async function loadCurrentWindowBatch() {
  const [currentTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!currentTab?.windowId) return null;
  const batches = await getStoredBatches();
  return batches[String(currentTab.windowId)] || null;
}

function showPayload(payload) {
  document.getElementById("payloadOutput").value = payload ? JSON.stringify(payload, null, 2) : "";
  if (payload?.source_label) {
    document.getElementById("labelInput").value = payload.source_label;
  }
}

async function writeClipboardText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (error) {
      console.warn("navigator.clipboard failed; falling back to textarea copy.", error);
    }
  }

  const output = document.getElementById("payloadOutput");
  output.value = text;
  output.focus();
  output.select();
  if (!document.execCommand("copy")) {
    throw new Error("Clipboard copy is not available in this browser context.");
  }
}

/* --- actions -------------------------------------------------------------- */

async function copyPayload() {
  let payload = await loadCurrentWindowBatch();
  if (!payload) payload = await captureCurrentWindow();
  showPayload(payload);
  await writeClipboardText(JSON.stringify(payload, null, 2));
  setStatus(`Copied ${payload.tabs.length} tabs from ${payload.source_label}.`);
}

async function downloadPayload() {
  let payload = await loadCurrentWindowBatch();
  if (!payload) payload = await captureCurrentWindow();
  showPayload(payload);
  downloadBlob(JSON.stringify(payload, null, 2), `litebrowser-window-${payload.window_id}.json`, "application/json");
  setStatus(`Downloaded window ${payload.window_id}.`);
}

async function captureAllAndShow() {
  const workspace = await captureAllWindows();
  showPayload(workspace);
  const total = workspace.batches.reduce((sum, b) => sum + b.tabs.length, 0);
  setStatus(`Captured ${workspace.window_count} windows · ${total} tabs.`);
}

async function downloadAllJson() {
  const workspace = await captureAllWindows();
  showPayload(workspace);
  downloadBlob(JSON.stringify(workspace, null, 2), "mei-workspace-all-windows.json", "application/json");
  setStatus(`Downloaded JSON with ${workspace.window_count} windows.`);
}

async function downloadAllZip() {
  const workspace = await captureAllWindows();
  showPayload(workspace);

  // One JSON file per window/screen plus a combined manifest so Mei can split
  // screen 1 and screen 2 back into separate workspaces.
  const entries = workspace.batches.map((batch, idx) => ({
    name: `screen-${idx + 1}.json`,
    data: JSON.stringify(batch, null, 2),
  }));
  entries.unshift({
    name: "workspace.json",
    data: JSON.stringify(workspace, null, 2),
  });

  const zip = MeiZip.createZip(entries);
  const blob = new Blob([zip], { type: "application/zip" });
  const url = URL.createObjectURL(blob);
  try {
    await chrome.downloads.download({ url, filename: "mei-workspace-all-windows.zip", saveAs: true });
    setStatus(`Downloaded ZIP with ${workspace.window_count} windows.`);
  } finally {
    URL.revokeObjectURL(url);
  }
}

async function downloadBlob(text, filename, mime) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  try {
    await chrome.downloads.download({ url, filename, saveAs: true });
  } finally {
    URL.revokeObjectURL(url);
  }
}

async function refreshStoredBatch() {
  const payload = await loadCurrentWindowBatch();
  showPayload(payload);
  if (!payload) {
    setStatus("No stored batch for this window yet.");
    return;
  }
  setStatus(`Loaded stored batch with ${payload.tabs.length} tabs.`);
}

/* --- wire-up -------------------------------------------------------------- */

document.getElementById("captureBtn").addEventListener("click", async () => {
  try {
    const payload = await captureCurrentWindow();
    showPayload(payload);
    setStatus(`Stored ${payload.tabs.length} tabs for ${payload.source_label}.`);
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Capture failed.", true);
  }
});

document.getElementById("captureAllBtn").addEventListener("click", async () => {
  try {
    await captureAllAndShow();
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Capture all failed.", true);
  }
});

document.getElementById("copyBtn").addEventListener("click", async () => {
  try {
    await copyPayload();
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Copy failed.", true);
  }
});

document.getElementById("downloadBtn").addEventListener("click", async () => {
  try {
    await downloadPayload();
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Download failed.", true);
  }
});

document.getElementById("downloadAllJsonBtn").addEventListener("click", async () => {
  try {
    await downloadAllJson();
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Download all failed.", true);
  }
});

document.getElementById("downloadAllZipBtn").addEventListener("click", async () => {
  try {
    await downloadAllZip();
  } catch (error) {
    console.error(error);
    setStatus(error.message || "ZIP export failed.", true);
  }
});

document.getElementById("refreshBtn").addEventListener("click", async () => {
  try {
    await refreshStoredBatch();
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Refresh failed.", true);
  }
});

refreshStoredBatch().catch(error => {
  console.error(error);
  setStatus("Could not read stored batch.", true);
});
