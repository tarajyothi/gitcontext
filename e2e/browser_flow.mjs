// Real-browser end-to-end test of GitContext (Chromium via Playwright). Drives the REAL UI at BASE.
// Run: node browser_flow.mjs http://localhost:3000 ./shots   (needs: playwright-core, @sparticuz/chromium)
import chromium from "@sparticuz/chromium";
import { chromium as pw } from "playwright-core";
import fs from "node:fs";

const BASE = process.argv[2] ?? "http://localhost:3000";
const SHOTS = process.argv[3] ?? "./shots";
fs.mkdirSync(SHOTS, { recursive: true });
const email = `browser-${Date.now()}@example.com`, password = "correct-horse-1";
const REPO = "https://github.com/pallets/click";
const results = [], consoleErrors = [];
const browser = await pw.launch({ executablePath: await chromium.executablePath(), args: chromium.args, headless: true });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, ignoreHTTPSErrors: process.env.IGNORE_TLS === "1" });
const page = await ctx.newPage();
page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
page.on("console", (m) => m.type() === "error" && consoleErrors.push(`console: ${m.text()} @ ${page.url()}`));

async function step(name, fn) {
  try { const detail = await fn(); results.push({ step: name, ok: true, detail: detail ?? "" }); console.log("PASS", name, detail ?? ""); }
  catch (e) { results.push({ step: name, ok: false, detail: e.message.split("\n")[0] }); console.log("FAIL", name, "->", e.message.split("\n")[0]); }
}
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png` });
const expect = (c, m) => { if (!c) throw new Error(m); };
const card = () => page.locator("li", { hasText: "pallets/click" }).first();
const badge = async () => ((await card().innerText()).match(/(pending|indexing[^\n]*|ready|failed)/)?.[0] ?? "").trim();
async function watchUntil(final, ms = 120000) {   // records every distinct badge text the UI actually shows
  const seen = [], t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const b = await badge().catch(() => "");
    if (b && seen.at(-1) !== b) seen.push(b);
    if (b.startsWith(final)) return seen;
    await page.waitForTimeout(100);
  }
  throw new Error("timeout; saw: " + seen.join(" -> "));
}

await step("1 landing page opens", async () => {
  await page.goto(BASE + "/");
  await page.getByRole("heading", { name: /Understand any GitHub repo/ }).waitFor();
  await shot("01-landing");
});
await step("2 sign up with a fresh account (real form)", async () => {
  await page.getByRole("link", { name: "Get started" }).click();
  await page.waitForURL("**/signup");
  await page.getByPlaceholder("Email").fill(email);
  await page.getByPlaceholder("Password (8+ characters)").fill(password);
  await shot("02-signup");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("**/dashboard");
  return email;
});
await step("3 redirected to dashboard, logged-in state visible", async () => {
  await page.getByRole("heading", { name: "Repositories" }).waitFor();
  await page.getByText(email).waitFor();
  await page.getByText("No repositories yet").waitFor();
  await shot("03-dashboard-empty");
});
await step("4 refresh: session persists", async () => {
  await page.reload();
  await page.getByRole("heading", { name: "Repositories" }).waitFor();
  await page.getByText(email).waitFor();
  expect(page.url().endsWith("/dashboard"), "not on dashboard after reload: " + page.url());
});
let states1 = [], chunkText = "";
await step("5-7 connect pallets/click; observe REAL states in the UI until ready", async () => {
  await page.getByLabel("GitHub repository URL").fill(REPO);
  await page.getByRole("button", { name: "Connect repository" }).click();
  await card().waitFor();
  states1 = await watchUntil("ready");
  await shot("04-dashboard-ready");
  return states1.join(" -> ");
});
await step("8 dashboard shows the indexed repo with real counts", async () => {
  const t = await card().innerText();
  const m = t.match(/(\d+) files · ([\d,]+) chunks/);
  expect(m && +m[1] >= 100 && +m[2].replace(/,/g, "") >= 1000 && /python/.test(t), "unexpected card: " + t.replace(/\n/g, " | "));
  chunkText = m[2];
  return t.replace(/\n/g, " | ");
});
let wsUrl = "";
await step("9 open workspace", async () => {
  await card().getByRole("link", { name: "Open workspace" }).click();
  await page.waitForURL(/\/repositories\/\d+$/);
  wsUrl = page.url();
  await page.getByRole("heading", { name: "pallets/click" }).waitFor();
  const t = await page.locator("main").innerText();
  expect(t.includes(chunkText) && /ready/.test(t), "workspace metadata missing (expected chunks " + chunkText + ")");
  await shot("05-workspace");
});
await step("10-11 refresh workspace: state persists", async () => {
  await page.reload();
  await page.getByRole("heading", { name: "pallets/click" }).waitFor();
  const t = await page.locator("main").innerText();
  expect(t.includes(chunkText) && /ready/.test(t) && page.url() === wsUrl, "state lost after reload");
});
await step("11a workspace shows how the repository was indexed (first index = full)", async () => {
  const t = await page.locator("[data-testid=last-index]").innerText();
  expect(/Last index: full/.test(t) && /reused 0 of/.test(t), "last-index text: " + t);
  return t;
});
await step("11b search the codebase from the workspace (real results with citations)", async () => {
  await page.getByLabel("Search query").fill("how is a progress bar rendered");
  await page.getByRole("button", { name: "Search" }).click();
  const hits = page.locator("[data-testid=hit]");
  await hits.first().waitFor();
  const texts = await hits.allInnerTexts();
  expect(texts.length >= 3, "expected several results, got " + texts.length);
  expect(texts.slice(0, 5).some((t) => /_termui_impl\.py:\d+-\d+/.test(t) && /ProgressBar/.test(t)), "ProgressBar not in top 5: " + texts.slice(0, 5).map((t) => t.split("\n")[0]).join(" | "));
  expect(texts.every((t) => /\.\w+:\d+-\d+/.test(t)), "a result lacks a file:line citation");
  await shot("05b-search");
  await page.getByLabel("Search query").fill("zzzzqqqq nonexistentword");
  await page.getByRole("button", { name: "Search" }).click();
  await page.waitForTimeout(800);
  return texts.slice(0, 3).map((t) => t.split("\n")[0]).join(" | ");
});
await step("11c ask an answerable question: cited answer with real source lines", async () => {
  await page.getByLabel("Your question").fill("How do I ask the user a yes or no confirmation question?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const answer = page.locator("[data-testid=answer]");
  await answer.waitFor();
  const cites = await page.locator("[data-testid=citation]").allInnerTexts();
  expect(cites.length >= 1 && cites.every((t) => /\.\w+:\d+-\d+/.test(t)), "citations missing or malformed");
  expect(cites.some((t) => /termui\.py/.test(t) && /confirm/.test(t)), "confirm() not cited: " + cites.map((t) => t.split("\n")[0]).join(" | "));
  expect(/\[1\]/.test(await answer.innerText()), "answer text has no [n] citation marker");
  await shot("05c-answer");
  return cites.length + " citations; " + cites[0].split("\n")[0];
});
await step("11d ask an unanswerable question: honest refusal, no citations", async () => {
  await page.getByLabel("Your question").fill("How are Stripe payments processed?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const refusal = page.locator("[data-testid=refusal]");
  await refusal.waitFor();
  const t = await refusal.innerText();
  expect(/couldn't find enough evidence/.test(t) && /stripe/i.test(t), "refusal text: " + t);
  expect((await page.locator("[data-testid=citation]").count()) === 0, "refusal must not show citations");
  await shot("05d-refusal");
  return t.split("\n")[0];
});
await step("11e question history persists across reload", async () => {
  await page.reload();
  await page.getByRole("heading", { name: "pallets/click" }).waitFor();
  const h = page.locator("[data-testid=history]");
  await h.waitFor();
  const t = await h.innerText();
  expect(/Stripe/.test(t) && /confirmation/.test(t) && /no evidence/.test(t) && /answered/.test(t), "history: " + t.replace(/\n/g, " | "));
});
await step("12 log out -> /login", async () => {
  await page.getByRole("button", { name: "Log out" }).click();
  await page.waitForURL("**/login");
});
await step("13 protected pages and API rejected after logout", async () => {
  await page.goto(BASE + "/dashboard"); await page.waitForURL("**/login**");
  await page.goto(wsUrl); await page.waitForURL("**/login**");
  const api = await ctx.request.get(BASE + "/api/repositories");
  const one = await ctx.request.get(BASE + "/api" + new URL(wsUrl).pathname);
  expect(api.status() === 401 && one.status() === 401, `API statuses ${api.status()}/${one.status()}`);
  await shot("06-login-after-logout");
  return "dashboard->/login, workspace->/login, API 401/401";
});
await step("14 log in again (real form)", async () => {
  await page.getByPlaceholder("Email").fill(email);
  await page.getByPlaceholder("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  // Logout redirected us from the workspace to /login?next=<workspace>, so login must return us there.
  await page.waitForURL(wsUrl);
  await page.getByRole("heading", { name: "pallets/click" }).waitFor();
  await page.goto(BASE + "/dashboard");
  return "returned to the originally requested workspace via ?next=, then opened dashboard";
});
await step("15 repository still exists and is ready", async () => {
  await card().waitFor();
  expect((await badge()).startsWith("ready"), "badge: " + (await badge()));
});
await step("16-17 click Re-index; observe REAL state changes in the UI", async () => {
  await card().getByRole("button", { name: "Re-index" }).click();
  const seen = [];
  const t0 = Date.now();
  while (Date.now() - t0 < 120000) {
    const b = await badge().catch(() => "");
    if (b && seen.at(-1) !== b) seen.push(b);
    if (seen.length > 1 && b.startsWith("ready")) break;
    await page.waitForTimeout(100);
  }
  expect(seen.length >= 2 && seen.at(-1).startsWith("ready") && seen.some((s) => s.startsWith("indexing") || s === "pending"), "states: " + seen.join(" -> "));
  expect((await card().innerText()).includes(chunkText + " chunks"), "chunk count changed after re-index (was " + chunkText + ")");
  return seen.join(" -> ");
});
await step("17b after re-index the workspace reports an INCREMENTAL run that reused everything", async () => {
  await card().getByRole("link", { name: "Open workspace" }).click();
  await page.waitForURL(/\/repositories\/\d+$/);
  const t = await page.locator("[data-testid=last-index]").innerText();
  expect(/Last index: incremental/.test(t) && /0 new\/changed/.test(t) && /0 removed/.test(t) && !/reused 0 of/.test(t), "last-index text: " + t);
  await shot("05e-incremental");
  await page.goto(BASE + "/dashboard");
  await card().waitFor();
  return t;
});
await step("18-19 invalid repository URL shows a useful error", async () => {
  await page.getByLabel("GitHub repository URL").fill("https://example.com/x/y");
  await page.getByRole("button", { name: "Connect repository" }).click();
  const alert = page.locator("p[role=alert]");
  await alert.waitFor();
  const msg = await alert.innerText();
  expect(/GitHub URL like https:\/\/github\.com\/owner\/repo/.test(msg), "message: " + msg);
  await shot("07-invalid-url-error");
  return msg;
});
await step("20 non-existent repo ends FAILED with readable error + Retry", async () => {
  await page.getByLabel("GitHub repository URL").fill("https://github.com/octocat/this-repo-does-not-exist-gitcontext-xyz");
  await page.getByRole("button", { name: "Connect repository" }).click();
  const c = page.locator("li", { hasText: "this-repo-does-not-exist" }).first();
  await c.getByText("failed").first().waitFor({ timeout: 60000 });
  const t = await c.innerText();
  expect(/not found or private/.test(t) && (await c.getByRole("button", { name: "Retry" }).count()) === 1, t);
  await shot("08-failed-repo");
});
await step("21 responsive: mobile viewport dashboard", async () => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.reload();
  await page.getByRole("heading", { name: "Repositories" }).waitFor();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  await shot("09-mobile");
  if (overflow) {
    const bad = await page.evaluate(() => [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1)
      .slice(0, 4).map((e) => `${e.tagName.toLowerCase()}.${String(e.className).slice(0, 50)} right=${Math.round(e.getBoundingClientRect().right)} "${(e.textContent || "").slice(0, 30)}"`));
    throw new Error("horizontal overflow on mobile: " + bad.join(" ; "));
  }
});

await browser.close();
const unexpected = consoleErrors.filter((e) => !/401|Failed to load resource/.test(e));
fs.writeFileSync(`${SHOTS}/report.json`, JSON.stringify({ email, results, states1, consoleErrors }, null, 1));
console.log(`\n${results.filter((r) => r.ok).length}/${results.length} steps passed; console errors: ${consoleErrors.length} (unexpected: ${unexpected.length})`);
consoleErrors.forEach((e) => console.log("  ", e));
process.exit(results.every((r) => r.ok) && unexpected.length === 0 ? 0 : 1);
