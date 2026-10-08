// Day-6 showcase: secrets masked, incremental re-index after real file changes, rate limit. Screenshots + captioned video.
// Needs: scripts/demo_server.py (backend :8000) and the frontend on :3000.   node day6_demo.mjs http://localhost:3000 ./out /tmp/demo-repo
import chromium from "@sparticuz/chromium";
import { chromium as pw } from "playwright-core";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const BASE = process.argv[2] ?? "http://localhost:3000", OUT = process.argv[3] ?? "./out", FIX = process.argv[4] ?? "/tmp/demo-repo";
fs.rmSync(OUT, { recursive: true, force: true }); fs.mkdirSync(`${OUT}/frames`, { recursive: true }); fs.mkdirSync(`${OUT}/shots`, { recursive: true });
const email = `maria-${Date.now()}@example.com`, password = "correct-horse-1";
const browser = await pw.launch({ executablePath: await chromium.executablePath(), args: chromium.args, headless: true });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 } });
const page = await ctx.newPage();
await page.addInitScript(() => {
  const mk = (id, parent, css) => { let e = document.getElementById(id); if (!e) { e = document.createElement("div"); e.id = id; Object.assign(e.style, css); parent.appendChild(e); } return e; };
  setInterval(() => {
    const root = document.documentElement; if (!root || document.readyState !== "complete") return;
    const bar = mk("__cap", root, { position: "fixed", left: "0", right: "0", bottom: "0", padding: "10px 16px", background: "rgba(2,6,23,.94)", borderTop: "2px solid #059669", font: "600 17px system-ui,sans-serif", zIndex: "2147483647", pointerEvents: "none" });
    mk("__capt", bar, { color: "#34d399" }).textContent = sessionStorage.getItem("__cap") || "";
    mk("__cur", root, { position: "fixed", width: "18px", height: "18px", border: "3px solid #f59e0b", borderRadius: "50%", background: "rgba(245,158,11,.25)", zIndex: "2147483647", pointerEvents: "none", left: "-60px", top: "-60px", transform: "translate(-50%,-50%)" });
  }, 200);
  document.addEventListener("mousemove", (e) => { const c = document.getElementById("__cur"); if (c) { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; } }, true);
});
const cdp = await ctx.newCDPSession(page); const stamps = []; let n = 0;
cdp.on("Page.screencastFrame", async (f) => { fs.writeFileSync(`${OUT}/frames/${String(n++).padStart(5, "0")}.jpg`, Buffer.from(f.data, "base64")); stamps.push(f.metadata.timestamp); try { await cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }); } catch {} });
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 85, maxWidth: 1280, maxHeight: 720, everyNthFrame: 1 });

const pause = (ms) => page.waitForTimeout(ms);
const caption = (t) => page.evaluate((t) => { sessionStorage.setItem("__cap", t); const c = document.getElementById("__capt"); if (c) c.textContent = t; }, t);
const moveTo = async (l) => { await l.scrollIntoViewIfNeeded(); const b = await l.boundingBox(); if (b) await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 18 }); };
const click = async (l) => { await moveTo(l); await pause(250); await l.click(); };
const type = async (l, t, d = 32) => { await moveTo(l); await l.click(); await l.fill(""); await l.pressSequentially(t, { delay: d }); };
const shot = (name) => page.screenshot({ path: `${OUT}/shots/${name}.png` });
const panel = (title) => page.locator("section", { has: page.getByRole("heading", { name: title, exact: true }) });
const git = (...a) => execFileSync("git", ["-C", FIX, "-c", "user.name=demo", "-c", "user.email=demo@example.com", ...a], { stdio: "pipe" });
const summary = () => page.locator("[data-testid=last-index]").innerText();

await page.goto(BASE + "/signup"); await pause(600);
await caption("Day 6 demo: hardening on a repo that contains fake credentials and a hostile symlink");
await type(page.getByPlaceholder("Email"), email); await type(page.getByPlaceholder("Password (8+ characters)"), password, 28);
await click(page.getByRole("button", { name: "Sign up" })); await page.waitForURL("**/dashboard"); await pause(1200);
await caption("1. Connect a repository (a local fixture stands in for GitHub)");
await type(page.getByLabel("GitHub repository URL"), "https://github.com/acme/payments-service", 26); await pause(400);
await click(page.getByRole("button", { name: "Connect repository" }));
const card = page.locator("li", { hasText: "payments-service" }).first(); await card.waitFor();
await card.getByRole("link", { name: "Open workspace" }).waitFor({ timeout: 60000 }); await pause(900);
await click(card.getByRole("link", { name: "Open workspace" }));
await page.locator("[data-testid=last-index]").waitFor(); await pause(1500);
await caption("2. FIRST index = full. Credentials were masked before storing; the symlink was skipped");
const first = await summary(); await shot("d6-01-first-index-full"); await pause(2500);

await caption("3. Search for the AWS key: the index only contains [REDACTED:...]");
await type(page.getByLabel("Search query"), "aws access key id", 30); await click(page.getByRole("button", { name: "Search", exact: true }));
await page.locator("[data-testid=hit]").first().waitFor(); await pause(1200);
await panel("Search code").scrollIntoViewIfNeeded(); await pause(800);
const hits = await page.locator("[data-testid=hit]").allInnerTexts();
await shot("d6-02-secrets-masked"); await pause(3000);
const leaked = hits.join("\n").includes("AKIA" + "IOSFODNN7EXAMPLE");

await caption("4. A teammate pushes changes: edit 1 file, add 1 file, delete 1 file");
fs.appendFileSync(`${FIX}/app/billing.py`, '\n\ndef partial_refund(payment_id, amount_cents):\n    """Refund only part of a payment."""\n    return {"payment": payment_id, "refunded": amount_cents}\n');
fs.writeFileSync(`${FIX}/app/invoices.py`, '"""Invoices."""\n\n\ndef create_invoice(customer_id, items):\n    """Create an invoice for a customer from line items."""\n    return {"customer": customer_id, "total": sum(items)}\n');
fs.rmSync(`${FIX}/docs/guide.md`); git("add", "-A"); git("commit", "-qm", "billing: partial refunds, invoices; drop old guide"); await pause(1200);
await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" })); await pause(900);
await caption("5. Click Re-index: only the changed files are re-chunked and re-embedded");
await click(page.getByRole("button", { name: "Re-index", exact: true }));
await page.locator("[data-testid=last-index]").filter({ hasText: "incremental" }).waitFor({ timeout: 60000 }); await pause(1500);
const second = await summary(); await shot("d6-03-incremental-reindex"); await pause(3500);

await caption("6. The new code is searchable immediately");
await type(page.getByLabel("Search query"), "create an invoice for a customer", 28); await click(page.getByRole("button", { name: "Search", exact: true }));
await page.locator("[data-testid=hit]").first().waitFor(); await pause(1200); await panel("Search code").scrollIntoViewIfNeeded(); await pause(600);
const top = (await page.locator("[data-testid=hit]").first().innerText()).split("\n")[0];
await shot("d6-04-new-code-searchable"); await pause(2500);

await caption("7. Abuse protection: the 4th question inside a minute is rate-limited (limit set to 3 for this demo)");
const q = page.getByLabel("Your question");
for (let i = 1; i <= 4; i++) {
  await type(q, `where is refund_payment defined (${i})`, 12); await click(page.getByRole("button", { name: "Ask", exact: true }));
  if (i < 4) await page.locator("[data-testid=answer], [data-testid=refusal]").first().waitFor();
  await pause(i < 4 ? 600 : 300);
}
const banner = page.locator("p[role=alert]"); await banner.waitFor(); const limitMsg = await banner.innerText(); await pause(500);
await panel("Ask a question").scrollIntoViewIfNeeded(); await pause(500); await shot("d6-05-rate-limited"); await pause(3500);

await caption("8. Dashboard: plan, repository count and chunks indexed (real counts)");
await page.goto(BASE + "/dashboard"); await card.waitFor(); await pause(800); await shot("d6-06-dashboard-plan-usage"); await pause(2800);
await caption("Done: secrets masked, hostile symlink ignored, incremental re-index, rate limiting, plan limits");
await pause(2500);
await cdp.send("Page.stopScreencast"); fs.writeFileSync(`${OUT}/stamps.json`, JSON.stringify(stamps));
fs.writeFileSync(`${OUT}/facts.json`, JSON.stringify({ first, second, topHit: top, secretLeakedInResults: leaked, rateLimitMessage: limitMsg, hitsAfterMasking: hits.slice(0, 2).map((h) => h.split("\n").slice(0, 1)[0]) }, null, 1));
await browser.close();
console.log("FIRST :", first.replace(/\n/g, " ")); console.log("SECOND:", second.replace(/\n/g, " ")); console.log("TOP HIT for 'create an invoice':", top);
console.log("secret leaked in search results?", leaked); console.log("rate limit message:", limitMsg);
