# Mei website

The product site for Mei. It is a **separate product** from the desktop app and
from the embedded web workspaces in `web_support/`:

| Directory | What it is | Shipped inside `Mei.exe`? |
|---|---|---|
| `web_support/` | Local web apps the desktop app opens (hub, boitoan, …) and the release ZIP validates | Yes |
| `website/` | This marketing/product site | No |

Nothing here is imported by the Python application, and `Mei.spec` does not
reference this folder. The release workflow's `web_support` validation is
untouched.

## Stack

Plain HTML, one stylesheet, one ES module. No framework and no runtime
dependency. Vite is a dev dependency for the dev server, hashed asset build and
`preview`; Playwright (against the Chrome already installed on the machine)
verifies the result.

```
website/
├── index.html              the page
├── 404.html                self-contained error page
├── og.html                 source of the social card (rendered to public/og.png)
├── src/styles.css          all styling, in cascade layers
├── src/main.js             theme explorer, lightbox, reveal, menu
├── src/data/theme-tokens.js generated from litebrowser/core/theme_data.py
├── public/                 icon.png, shots/*.png, robots.txt, og.png
└── tests/                  Playwright specs
```

## Colour data

`src/data/theme-tokens.js` is generated from the app's own theme module so the
preview cannot drift from the product: 12 of the 35 palettes (including every
café default) plus all 15 accents, with the accent lift the app computes per
palette. Regenerate after changing a palette:

```bash
python - <<'PY'
import json, os, sys
sys.path.insert(0, os.path.dirname(os.getcwd()))
from litebrowser.core import theme_data as td
# see the header of src/data/theme-tokens.js for the exact shape
PY
```

The generated file is committed because the site must build without Python.

## Screenshots in `public/shots/`

These are real renders of the Qt application, captured offscreen on Windows at
1440×900 from a seeded throwaway profile (`notes`, `tasks`, `weekly-plan`,
`review`, `overview`, `calendar`, `boards`, `files`). They are not mockups and
not retouched. The notes page is excluded on purpose: its list rows paint the
title twice, which is a real defect in the delegate that should be fixed in the
app before it is shown off.

## Commands

```bash
cd website
npm install
npm run dev          # http://127.0.0.1:5173
npm run build        # dist/
npm run preview      # http://127.0.0.1:4173, serves dist/
npm test             # Playwright: functional + layout + dialog/keyboard checks
npm run test:shots   # writes test-results/shots/*.png and public/og.png
```

`npm test` requires Google Chrome installed (`channel: "chrome"` in
`playwright.config.js`), so no browser download is needed.

## Deployment

The build is static: `dist/` can be served by any file host. `vite.config.js`
uses `base: "./"`, so the same `dist/` works from a domain root or a subpath.

* **GitHub Pages (recommended here):** publish `website/dist` from a workflow or
  push it to a `gh-pages` branch; the repo already owns the project page path.
* **Netlify / Cloudflare Pages / Vercel:** build command `npm run build`,
  publish directory `website/dist`.

Before deploying on a real domain, add the canonical URL and a `Sitemap:` line —
both are deliberately omitted today because this repository has not published a
production URL, and a guessed canonical is worse than none.

## Accessibility and quality notes

* One `h1`, landmarks, a skip link, visible focus rings, `aria-live` status for
  the theme switcher, native `<dialog>` for the image viewer, native `<details>`
  for the FAQ and the mobile menu (works without JavaScript).
* The reveal-on-scroll pass hides nothing without JavaScript and un-hides
  everything after 2.5 s even if the observer never fires.
* `prefers-reduced-motion` removes every transition, including the view
  transition used when switching themes.
* Container queries drive the explorer mockup and the screenshot captions;
  `subgrid` aligns the four process steps where it is supported.
* Colour comes from the app's contrast-checked palette, so the page inherits the
  contrast work already done for the desktop UI.
