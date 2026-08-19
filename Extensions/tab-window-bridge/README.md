# Mei Window Tab Bridge

Load this folder as an unpacked extension in Chrome or Opera GX.

Flow:

1. Open the extension popup in the browser window you want to export.
2. Click `Capture This Window`.
3. Click `Copy JSON`.
4. In Mei, open `Import Center`.
5. Paste the JSON into `Store Payload`.
6. Select the stored batch and click `Import Selected Batch`.

Each browser window is stored separately by its `window_id` in extension local storage.
