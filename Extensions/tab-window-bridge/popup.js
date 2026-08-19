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

async function captureCurrentWindow() {
  const [currentTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!currentTab?.windowId) {
    throw new Error("Could not detect the current window.");
  }

  const tabs = await chrome.tabs.query({ currentWindow: true });
  const httpTabs = tabs
    .filter(tab => tab.url && /^https?:/i.test(tab.url))
    .map(tab => ({
      url: tab.url,
      title: tab.title || tab.url,
      active: Boolean(tab.active),
      pinned: Boolean(tab.pinned),
      index: Number(tab.index || 0)
    }))
    .sort((a, b) => a.index - b.index);

  if (!httpTabs.length) {
    throw new Error("This window has no normal web tabs to export.");
  }

  const now = Date.now();
  const browserName = normalizeBrowserName();
  const labelInput = document.getElementById("labelInput").value.trim();
  const windowId = currentTab.windowId;
  const payload = {
    batch_id: `${browserName}_window_${windowId}`,
    window_id: windowId,
    source_browser: browserName,
    source_label: labelInput || `Window ${windowId}`,
    created_at: now,
    tabs: httpTabs
  };

  const batches = await getStoredBatches();
  batches[String(windowId)] = payload;
  await saveStoredBatches(batches);
  return payload;
}

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
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const filename = `litebrowser-window-${payload.window_id}.json`;
  try {
    await chrome.downloads.download({ url, filename, saveAs: true });
    setStatus(`Downloaded ${filename}.`);
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
