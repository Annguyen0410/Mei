import { test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";

// Review artefacts. Written to `shots-review/` (git-ignored) rather than
// `test-results/`, which Playwright wipes on every run. Each capture is a
// viewport-sized frame at a known scroll position, because a full-page image of
// a 10k-pixel-tall mobile page cannot be inspected at a useful scale.
const OUT = join(process.cwd(), "shots-review");

/** Instant scrolling + decode every image, so nothing is captured mid-load. */
async function settle(page) {
  await page.evaluate(async () => {
    document.documentElement.style.scrollBehavior = "auto";
    for (let y = 0; y < document.body.scrollHeight; y += 500) {
      window.scrollTo({ top: y, behavior: "instant" });
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
    window.scrollTo({ top: 0, behavior: "instant" });
    await Promise.all(
      Array.from(document.images, (img) => (img.decode ? img.decode().catch(() => {}) : Promise.resolve()))
    );
  });
  await page.waitForTimeout(700);
}

test.beforeAll(async () => {
  await mkdir(OUT, { recursive: true });
});

const SIZES = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "tablet", width: 834, height: 1112 },
  { name: "mobile", width: 390, height: 844 },
];

const SPOTS = ["top", "#browser", "#plan", "#ai", "#themes", "#privacy", "#download", "#faq"];

test("viewport captures at desktop, tablet and mobile widths", async ({ page }) => {
  for (const size of SIZES) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.goto("/", { waitUntil: "networkidle" });
    await settle(page);

    for (const spot of SPOTS) {
      if (spot === "top") {
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
      } else {
        const target = page.locator(spot);
        await target.scrollIntoViewIfNeeded();
        await page.evaluate((selector) => {
          const element = document.querySelector(selector);
          window.scrollTo({ top: element.getBoundingClientRect().top + window.scrollY - 80, behavior: "instant" });
        }, spot);
      }
      await page.waitForTimeout(450);
      await page.screenshot({ path: join(OUT, `${size.name}-${spot.replace("#", "")}.png`) });
    }

    // The very bottom of the page: footer and the closing call to action.
    await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" }));
    await page.waitForTimeout(450);
    await page.screenshot({ path: join(OUT, `${size.name}-end.png`) });
  }
});

test("interactive states", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/", { waitUntil: "networkidle" });
  await settle(page);

  const themes = page.locator("#themes");
  await themes.scrollIntoViewIfNeeded();
  await page.locator('[data-theme-chips] input[value="cyberpunk-neon"]').check();
  await page.locator('[data-accent-chips] input[value="teal"]').check();
  await page.waitForTimeout(500);
  await page.screenshot({ path: join(OUT, "state-theme-cyberpunk.png") });

  await page.locator('[data-theme-chips] input[value="paper-studio"]').check();
  await page.locator('[data-accent-chips] input[value="clay"]').check();
  await page.waitForTimeout(500);
  await page.screenshot({ path: join(OUT, "state-theme-paper.png") });

  await page.locator(".shot img").first().click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(OUT, "state-lightbox.png") });
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/", { waitUntil: "networkidle" });
  await page.locator("details.menu > summary").click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(OUT, "state-mobile-menu.png") });
});

test("social card is generated from og.html", async ({ page }) => {
  await page.setViewportSize({ width: 1200, height: 630 });
  await page.goto("/og.html", { waitUntil: "networkidle" });
  await page.screenshot({ path: join(process.cwd(), "public", "og.png") });
});
