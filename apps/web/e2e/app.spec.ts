import { expect, test, type Page } from "@playwright/test";

/** Fresh visitor: no saved language, no conversations. */
async function chooseLanguage(page: Page, label: "English" | "हिंदी" | "मराठी") {
  await page.goto("/");
  await page.getByRole("button", { name: label }).click();
}

async function ask(page: Page, question: string) {
  await page.getByRole("textbox").first().fill(question);
  await page.locator('button[type="submit"]').click();
}

/** Plan: "Responsive layout tested at 360px width" — nothing may scroll sideways. */
async function expectNoSideScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test("first launch shows the language picker in every language", async ({ page }) => {
  await page.goto("/");
  for (const label of ["English", "हिंदी", "मराठी"]) {
    await expect(page.getByRole("button", { name: label })).toBeVisible();
  }
  await expectNoSideScroll(page);
});

test("English: ask sell or hold, get a grounded answer with sources", async ({ page }) => {
  await chooseLanguage(page, "English");
  await ask(page, "Should I sell my onion now? I have 20 quintals.");

  const decision = page.getByText(/^(Sell now|Hold|Not enough data)/).first();
  await expect(decision).toBeVisible();
  await expect(page.getByText(/Confidence: (High|Medium|Low)/)).toBeVisible();
  await expect(page.getByText("Please note", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "Show sources" }).click();
  await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible();
  await expect(page.getByText("demo", { exact: false }).first()).toBeVisible(); // synthetic prices are labelled
  await expectNoSideScroll(page);
});

test("Marathi: the answer and the interface are in Marathi", async ({ page }) => {
  await chooseLanguage(page, "मराठी");
  await expect(page.locator("html")).toHaveAttribute("lang", "mr");
  await ask(page, "मी कांदा आता विकू की थांबू?");

  const answer = page.locator("article, .card").filter({ hasText: /[ऀ-ॿ]{3,}/ }).last();
  await expect(answer).toBeVisible();
  const text = (await answer.innerText()).replace(/[0-9₹,.\s:–\-()/%]/g, "");
  const devanagari = (text.match(/[ऀ-ॿ]/g) ?? []).length;
  expect(devanagari / Math.max(text.length, 1)).toBeGreaterThan(0.6);
  await expectNoSideScroll(page);
});

test("prices page lists markets and flags old data", async ({ page }) => {
  await chooseLanguage(page, "English");
  await page.getByRole("link", { name: "Prices" }).click();
  await expect(page.getByRole("heading", { name: "Mandi prices" })).toBeVisible();
  await expect(page.getByText("These are demo (synthetic) prices", { exact: false })).toBeVisible();
  await expect(page.getByText("Recent").first()).toBeVisible();
  await expect(page.getByText("Old data").first()).toBeVisible(); // the synthetic Manmad feed stops early
  await expectNoSideScroll(page);
});

test("history keeps the conversation and can reopen it", async ({ page }) => {
  await chooseLanguage(page, "English");
  await ask(page, "How should I store onion?");
  await expect(page.getByText("Please note", { exact: false })).toBeVisible();

  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByRole("heading", { name: "Your questions" })).toBeVisible();
  const item = page.getByText("How should I store onion?", { exact: false }).first();
  await expect(item).toBeVisible();
  await item.click();
  await expect(page.getByText("Please note", { exact: false })).toBeVisible();
  await expectNoSideScroll(page);
});

test("settings: switching language updates the whole interface", async ({ page }) => {
  await chooseLanguage(page, "English");
  await page.getByRole("link", { name: "Settings" }).click();
  await page.getByRole("button", { name: "हिंदी" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "hi");
  await expect(page.getByRole("link", { name: "भाव" })).toBeVisible();
  await expect(page.getByRole("link", { name: "इतिहास" })).toBeVisible();

  // The choice survives a reload.
  await page.reload();
  await expect(page.getByRole("link", { name: "भाव" })).toBeVisible();
  await expectNoSideScroll(page);
});
