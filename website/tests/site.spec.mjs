import { test, expect } from "@playwright/test";

const PAGES = ["/"];

test.describe("site shell", () => {
  test("loads without console errors, failed requests or broken anchors", async ({ page }) => {
    const problems = [];
    page.on("console", (message) => {
      if (message.type() === "error") problems.push(`console: ${message.text()}`);
    });
    page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
    page.on("requestfailed", (request) => {
      const url = request.url();
      if (url.startsWith("http://127.0.0.1")) problems.push(`request failed: ${url}`);
    });

    const response = await page.goto("/", { waitUntil: "networkidle" });
    expect(response.status()).toBe(200);
    expect(problems).toEqual([]);

    await expect(page).toHaveTitle(/Mei/);
    await expect(page.locator("h1")).toHaveCount(1);

    // Every in-page link must resolve to a real element.
    const hashes = await page.$$eval('a[href^="#"]', (links) =>
      links.map((link) => link.getAttribute("href")).filter((href) => href && href.length > 1)
    );
    for (const hash of new Set(hashes)) {
      await expect(page.locator(hash), `anchor ${hash}`).toHaveCount(1);
    }

    // The UI screenshots are `loading="lazy"` and the stylesheet scrolls
    // smoothly, so the walk below forces instant scrolling and then asks the
    // browser to decode every image: that is what actually proves the file
    // exists on the server, rather than proving it is still queued.
    await page.evaluate(async () => {
      document.documentElement.style.scrollBehavior = "auto";
      for (let y = 0; y < document.body.scrollHeight; y += 500) {
        window.scrollTo({ top: y, behavior: "instant" });
        await new Promise((resolve) => setTimeout(resolve, 30));
      }
      window.scrollTo({ top: 0, behavior: "instant" });
      await Promise.all(
        Array.from(document.images, (img) => (img.decode ? img.decode().catch(() => {}) : Promise.resolve()))
      );
    });
    await page.waitForLoadState("networkidle");

    // Images must be real files with alt text (the icon and the UI renders).
    // The lightbox's <img> intentionally has no src until a screenshot is
    // opened, so only elements that declare one are checked here.
    const images = await page.$$eval("img[src]", (nodes) =>
      nodes.map((node) => ({
        src: node.currentSrc || node.src,
        alt: node.getAttribute("alt"),
        complete: node.complete,
        width: node.naturalWidth,
      }))
    );
    expect(images.length).toBeGreaterThanOrEqual(6);
    for (const image of images) {
      expect(image.alt, `${image.src} needs alt text`).not.toBeNull();
      expect(image.complete, `${image.src} did not load`).toBe(true);
      expect(image.width, `${image.src} has no pixels`).toBeGreaterThan(0);
    }
    // And the four UI renders specifically, since those are the files a release
    // could plausibly forget to copy into the build.
    expect(images.filter((image) => image.src.includes("/shots/"))).toHaveLength(4);
  });

  test("the theme explorer repaints from real palette tokens", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    const frame = page.locator("[data-theme-frame]");
    const status = page.locator("[data-theme-status]");

    await expect(page.locator("[data-theme-chips] input")).toHaveCount(12);
    await expect(page.locator("[data-accent-chips] input")).toHaveCount(15);

    const before = await frame.evaluate((node) => getComputedStyle(node.querySelector(".preview")).backgroundColor);

    await page.getByRole("radio", { name: /Midnight AMOLED/i }).check();
    await expect(frame).toHaveAttribute("data-scheme", "dark");
    const after = await frame.evaluate((node) => getComputedStyle(node.querySelector(".preview")).backgroundColor);
    expect(after).not.toBe(before);
    expect(after).toBe("rgb(5, 6, 7)");

    const accentBefore = await frame.evaluate((node) => node.style.getPropertyValue("--p-accent"));
    await page.locator('[data-accent-chips] input[value="rose"]').check();
    const accentAfter = await frame.evaluate((node) => node.style.getPropertyValue("--p-accent"));
    expect(accentAfter).not.toBe(accentBefore);
    await expect(status).toContainText(/Sakura|rose/i);
  });

  test("the gallery closes with its ✕, and a click on the image does not", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    const dialog = page.locator("dialog[data-lightbox]");
    const closeButton = page.locator(".lightbox__close");

    await page.locator(".shot img").first().click();
    await expect(dialog).toBeVisible();

    // The ✕ must be the topmost element at its own centre, otherwise a
    // full-width image inside the dialog eats the click.
    await expect(closeButton).toBeVisible();
    const reachable = await closeButton.evaluate((button) => {
      const rect = button.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return hit === button || button.contains(hit);
    });
    expect(reachable, "the close button is covered by another element").toBe(true);

    // Clicking the picture itself keeps the gallery open.
    await page.locator("[data-lightbox-img]").click({ position: { x: 40, y: 40 } });
    await expect(dialog).toBeVisible();

    await closeButton.click();
    await expect(dialog).not.toBeVisible();

    // …and the same gallery re-opens on the next click.
    await page.locator(".shot img").first().click();
    await expect(dialog).toBeVisible();
    await closeButton.click();
    await expect(dialog).not.toBeVisible();
  });

  test("a screenshot opens in the native dialog and closes on Escape", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    const dialog = page.locator("dialog[data-lightbox]");
    await expect(dialog).not.toBeVisible();
    await page.locator(".shot img").first().click();
    await expect(dialog).toBeVisible();
    await expect(page.locator("[data-lightbox-caption]")).not.toBeEmpty();
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
  });

  test("interactive controls are reachable by keyboard", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await page.keyboard.press("Tab");
    await expect(page.locator(".skip-link")).toBeFocused();
    const chip = page.locator("[data-theme-chips] input").first();
    await chip.focus();
    await expect(chip).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(page.locator("[data-theme-chips] input").nth(1)).toBeChecked();
  });

  for (const path of PAGES) {
    test(`no horizontal overflow at three widths: ${path}`, async ({ page }) => {
      for (const viewport of [
        { width: 1440, height: 900 },
        { width: 834, height: 1112 },
        { width: 390, height: 844 },
      ]) {
        await page.setViewportSize(viewport);
        await page.goto(path, { waitUntil: "networkidle" });
        const overflow = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
        }));
        expect(overflow.scroll, `overflow at ${viewport.width}px`).toBeLessThanOrEqual(overflow.client + 1);
      }
    });
  }

  test("mobile menu opens, links close it", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/", { waitUntil: "networkidle" });
    const menu = page.locator("details.menu");
    await expect(menu).toBeVisible();
    await menu.locator("summary").click();
    await expect(menu).toHaveAttribute("open", "");
    await menu.locator('a[href="#themes"]').click();
    await expect(menu).not.toHaveAttribute("open", "");
  });

  test("404 page renders with a way home", async ({ page }) => {
    const response = await page.goto("/404.html");
    expect(response.status()).toBe(200);
    await expect(page.locator("h1")).toContainText(/shelf/i);
    await expect(page.getByRole("link", { name: /home page/i })).toBeVisible();
  });
});
