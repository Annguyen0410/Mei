// The site's only script: a theme explorer driven by the app's real palette
// data, a native-dialog lightbox, and reveal-on-scroll that degrades to
// "everything visible" when IntersectionObserver or motion is not available.
import { themeData } from "./data/theme-tokens.js";

const root = document.documentElement;
// Progressive enhancement lives behind this attribute: without the module,
// nothing is hidden and every control is replaced by the <noscript> copy.
root.dataset.js = "true";

const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

/* ------------------------------------------------------------------ themes */

const FRAME_VARS = {
  MAIN_BG: "--p-bg",
  MAIN_BG_ALT: "--p-bg-alt",
  SIDEBAR_BG: "--p-rail",
  SIDEBAR_BORDER: "--p-line",
  CARD_BG: "--p-card",
  TEXT: "--p-ink",
  TEXT_MUTED: "--p-muted",
  ACCENT: "--p-accent",
  ACCENT_SOFT: "--p-accent-soft",
};

function shortLabel(label) {
  return label.split("·")[0].trim();
}

function initThemeExplorer() {
  const explorer = document.querySelector("[data-theme-explorer]");
  const frame = document.querySelector("[data-theme-frame]");
  const themeField = document.querySelector("[data-theme-chips]");
  const accentField = document.querySelector("[data-accent-chips]");
  const status = document.querySelector("[data-theme-status]");
  if (!explorer || !frame || !themeField || !accentField) return;

  const stored = (() => {
    try {
      return JSON.parse(localStorage.getItem("mei.theme") || "null");
    } catch {
      return null;
    }
  })();

  const state = {
    theme: themeData.themes.find((theme) => theme.id === stored?.theme)?.id || themeData.defaultTheme,
    accent: themeData.accents.some((accent) => accent.id === stored?.accent)
      ? stored.accent
      : themeData.defaultAccent,
  };

  // Radios rather than buttons: arrow-key navigation and the radio group
  // semantics come from the platform, not from a keydown handler.
  for (const theme of themeData.themes) {
    const label = document.createElement("label");
    label.className = "chip";
    label.title = theme.label;
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "mei-theme";
    input.value = theme.id;
    input.checked = theme.id === state.theme;
    const text = document.createElement("span");
    text.textContent = shortLabel(theme.label);
    label.append(input, text);
    themeField.append(label);
  }

  for (const accent of themeData.accents) {
    const label = document.createElement("label");
    label.className = "swatch";
    label.style.setProperty("--swatch", accent.base);
    label.title = accent.label;
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "mei-accent";
    input.value = accent.id;
    input.checked = accent.id === state.accent;
    const name = document.createElement("span");
    name.className = "visually-hidden";
    name.textContent = accent.label;
    const dot = document.createElement("span");
    dot.className = "swatch__dot";
    dot.setAttribute("aria-hidden", "true");
    label.append(input, dot, name);
    accentField.append(label);
  }

  function apply() {
    const theme = themeData.themes.find((item) => item.id === state.theme) ?? themeData.themes[0];
    const accent = theme.accents[state.accent] ?? theme.accents[themeData.defaultAccent];
    for (const [token, variable] of Object.entries(FRAME_VARS)) {
      frame.style.setProperty(variable, theme.tokens[token]);
    }
    frame.style.setProperty("--p-accent", accent.ACCENT);
    frame.style.setProperty("--p-accent-hover", accent.ACCENT_HOVER);
    frame.style.setProperty("--p-accent-soft", accent.ACCENT_SOFT);
    frame.style.setProperty("--p-on-accent", accent.TEXT_ON_ACCENT);
    frame.dataset.scheme = theme.dark ? "dark" : "light";
    status.textContent = `${theme.label} · ${themeData.accents.find((item) => item.id === state.accent)?.label ?? ""}`;
    try {
      localStorage.setItem("mei.theme", JSON.stringify(state));
    } catch {
      /* a private window without storage still gets a working preview */
    }
  }

  function applyWithTransition() {
    if (!document.startViewTransition || prefersReducedMotion.matches) {
      apply();
      return;
    }
    document.startViewTransition(apply);
  }

  themeField.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLInputElement)) return;
    state.theme = event.target.value;
    applyWithTransition();
  });
  accentField.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLInputElement)) return;
    state.accent = event.target.value;
    applyWithTransition();
  });

  apply();
}

/* ---------------------------------------------------------------- lightbox */

function initLightbox() {
  const dialog = document.querySelector("[data-lightbox]");
  const image = document.querySelector("[data-lightbox-img]");
  const caption = document.querySelector("[data-lightbox-caption]");
  const close = document.querySelector("[data-lightbox-close]");
  if (!dialog || !image || !caption) return;
  if (typeof dialog.showModal !== "function") return;

  for (const shot of document.querySelectorAll(".shot")) {
    const img = shot.querySelector("img");
    if (!img) continue;        const captionText = shot.querySelector("figcaption")?.textContent?.trim() ?? img.alt;
    img.classList.add("shot__zoom");
    img.addEventListener("click", () => {
      image.src = img.currentSrc || img.src;
      image.alt = img.alt;
      caption.textContent = captionText;
      dialog.showModal();
    });
  }

  // Preferences (Modern Web Guidance: declarative-dialog-popover-control,
  // dialog): the markup carries `closedby="any"` and the close control is a
  // `form method="dialog"`, so neither needs a click handler. Only browsers
  // without support for `closedBy` get the backdrop shim.
  if (!("closedBy" in HTMLDialogElement.prototype)) {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  }
}

/* ------------------------------------------------------------ reveal pass */

function initReveal() {
  const targets = document.querySelectorAll(
    ".section-head, .step, .split__copy, .shot, .ai-card, .link-map, .explorer, .loop__item, .privacy-claims > div, .caveat, .doc-grid li, .integration-list li, .download__assets, details, .closing"
  );
  if (!targets.length) return;

  if (!("IntersectionObserver" in window) || prefersReducedMotion.matches) {
    for (const target of targets) target.classList.add("is-in");
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-in");
          observer.unobserve(entry.target);
        }
      }
    },
    { rootMargin: "0px 0px -8% 0px", threshold: 0.05 }
  );

  for (const target of targets) {
    target.classList.add("reveal");
    observer.observe(target);
  }
  // Insurance: the content must never stay invisible because a scrolling
  // container or a snapshot tool never fired the observer.
  window.setTimeout(() => {
    for (const target of targets) target.classList.add("is-in");
  }, 2500);
}

/* -------------------------------------------------------------- small menu */

function initMenu() {
  const menu = document.querySelector("details.menu");
  if (!menu) return;
  menu.addEventListener("click", (event) => {
    if (event.target instanceof HTMLAnchorElement) menu.open = false;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menu.open) {
      menu.open = false;
      menu.querySelector("summary")?.focus();
    }
  });
}

initThemeExplorer();
initLightbox();
initReveal();
initMenu();
