# Mei Window Tab Bridge

Load this folder as an **unpacked extension** in Chrome or Opera GX to move a
whole browser workspace (all tabs, all monitors) over to Mei.

## What it does

- **Capture This Window** — grab every tab in the current browser window.
- **Capture ALL Windows** — grab every tab in every browser window. Each window
  is treated as one monitor/screen, ordered left→right, so a dual-screen setup
  becomes `Screen 1` (e.g. 50 tabs) + `Screen 2` (e.g. 32 tabs).
- Exports as a **single JSON** (`workspace.json`) or a **ZIP** containing one
  JSON per screen. Tab titles/URLs keep full Unicode (Vietnamese, emoji, …).

## Install

1. Open `chrome://extensions` (or `opera://extensions`).
2. Enable **Developer mode**.
3. Click **Load unpacked** and select **this** folder (`Extensions\tab-window-bridge`).
4. Or load the pre-packed `Extensions\MeiBridge-extension.zip` via **Load unpacked** after extracting it.

> ⚠️ **Lỗi "Cannot load extension with file or directory name _legacy"** xảy ra khi bạn
> load nhầm thư mục **gốc của Mei** (`new browser\new browser`) — thư mục đó chứa
> `_legacy` (tên bắt đầu bằng `_` bị trình duyệt cấm) và không có `manifest.json`,
> nên Chrome/Edge báo **Could not load manifest**.
> Đúng thư mục cần load là `Extensions\tab-window-bridge` (bên trong đã có sẵn
> `manifest.json` và không có tên nào bắt đầu bằng `_`).

## Export flow (two screens → two Mei workspaces)

1. Click the extension icon, then **Capture ALL Windows**.
2. Click **Download ZIP all** (or **Download JSON all**).
3. In Mei, open the sidebar menu → **Extension Import Center**.
4. Click **Import File** and choose the `.zip` (or `.json`).
5. Click **Import All as Workspaces** — Screen 1 lands in Workspace 1,
   Screen 2 in Workspace 2, and extra screens get new workspaces.

You can also keep a single window: **Capture This Window → Copy JSON → Store
Payload → Import Selected Batch** imports it into the current workspace.
