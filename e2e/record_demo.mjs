// Records a real-time video of GitContext running in Chromium (Chrome DevTools screencast), with captions.
// Run: IGNORE_TLS=1 node record_demo.mjs https://localhost:8443 ./rec   then: python build_video.py ./rec out.mp4
import chromium from "@sparticuz/chromium";
import { chromium as pw } from "playwright-core";
import fs from "node:fs";

const BASE = process.argv[2] ?? "http://localhost:3000";
const OUT = process.argv[3] ?? "./rec";
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(`${OUT}/frames`, { recursive: true });
const email = `demo-${Date.now()}@example.com`, password = "correct-horse-1";
const browser = await pw.launch({ executablePath: await chromium.executablePath(), args: chromium.args, headless: true });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, ignoreHTTPSErrors: process.env.IGNORE_TLS === "1" });
const page = await ctx.newPage();

await page.addInitScript(() => {  // overlay: caption bar + address + mouse cursor (re-created after every navigation)
  const mk = (id, parent, css) => { let e = document.getElementById(id); if (!e) { e = document.createElement("div"); e.id = id; Object.assign(e.style, css); parent.appendChild(e); } return e; };
  const ensure = () => {
    const root = document.documentElement; if (!root || document.readyState !== "complete") return;
    const bar = mk("__cap", root, { position: "fixed", left: "0", right: "0", bottom: "0", padding: "10px 16px", background: "rgba(2,6,23,.94)", borderTop: "2px solid #059669", font: "600 17px system-ui,sans-serif", zIndex: "2147483647", pointerEvents: "none", display: "flex", justifyContent: "space-between", gap: "16px" });
    mk("__capt", bar, { color: "#34d399" }).textContent = sessionStorage.getItem("__cap") || "";
    mk("__url", bar, { color: "#cbd5e1", font: "13px ui-monospace,monospace", whiteSpace: "nowrap", alignSelf: "center" }).textContent = (location.protocol === "https:" ? "🔒 " : "") + location.host + location.pathname;
    mk("__cur", root, { position: "fixed", width: "18px", height: "18px", border: "3px solid #f59e0b", borderRadius: "50%", background: "rgba(245,158,11,.25)", zIndex: "2147483647", pointerEvents: "none", left: "-60px", top: "-60px", transform: "translate(-50%,-50%)" });
  };
  setInterval(ensure, 200);
  document.addEventListener("mousemove", (e) => { const c = document.getElementById("__cur"); if (c) { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; } }, true);
});

const cdp = await ctx.newCDPSession(page);
const stamps = []; let n = 0;
cdp.on("Page.screencastFrame", async (f) => {
  fs.writeFileSync(`${OUT}/frames/${String(n++).padStart(5, "0")}.jpg`, Buffer.from(f.data, "base64"));
  stamps.push(f.metadata.timestamp);
  try { await cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }); } catch {}
});
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 85, maxWidth: 1280, maxHeight: 720, everyNthFrame: 1 });

const pause = (ms) => page.waitForTimeout(ms);
const caption = (t) => page.evaluate((t) => { sessionStorage.setItem("__cap", t); const c = document.getElementById("__capt"); if (c) c.textContent = t; }, t);
const moveTo = async (loc) => { await loc.scrollIntoViewIfNeeded(); const b = await loc.boundingBox(); if (b) await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 20 }); };
const click = async (loc) => { await moveTo(loc); await pause(250); await loc.click(); };
const type = async (loc, text, delay = 40) => { await moveTo(loc); await loc.click(); await loc.fill(""); await loc.pressSequentially(text, { delay }); };
const scroll = (y) => page.evaluate((y) => window.scrollBy({ top: y, behavior: "smooth" }), y);

await page.goto(BASE + "/"); await pause(600);
await caption("1. Open GitContext (production build, real HTTPS)"); await pause(2200);
await caption("2. Create an account");
await click(page.getByRole("link", { name: "Get started" })); await page.waitForURL("**/signup"); await pause(700);
await type(page.getByPlaceholder("Email"), email);
await type(page.getByPlaceholder("Password (8+ characters)"), password, 35); await pause(500);
await click(page.getByRole("button", { name: "Sign up" })); await page.waitForURL("**/dashboard");
await caption("3. Signed in: new account, empty dashboard"); await pause(2500);
await caption("4. Connect a real public GitHub repository: pallets/click");
await type(page.getByLabel("GitHub repository URL"), "https://github.com/pallets/click", 30); await pause(600);
await click(page.getByRole("button", { name: "Connect repository" }));
const card = page.locator("li", { hasText: "pallets/click" }).first(); await card.waitFor();
let last = ""; const t0 = Date.now();
while (Date.now() - t0 < 150000) {   // show the REAL backend status as it changes
  const m = (await card.innerText().catch(() => "")).match(/(pending|indexing[^\n]*|ready|failed)/); const s = m ? m[0].trim() : "";
  if (s && s !== last) { last = s; await caption("5. Real indexing in the backend. Status: " + s); }
  if (s.startsWith("ready") || s.startsWith("failed")) break;
  await pause(100);
}
await pause(2800);
await caption("6. Open the repository workspace"); await click(card.getByRole("link", { name: "Open workspace" }));
await page.getByRole("heading", { name: "pallets/click" }).waitFor(); await pause(3000);
await caption("7. Ask a question: the answer cites real files and exact lines");
await type(page.getByLabel("Your question"), "How do I ask the user a yes or no confirmation question?", 28); await pause(500);
await click(page.getByRole("button", { name: "Ask", exact: true })); await page.locator("[data-testid=answer]").waitFor(); await pause(2000);
await scroll(420); await pause(3000); await scroll(420); await pause(2500);
await caption("8. Ask something the repository cannot answer: it refuses instead of guessing");
await type(page.getByLabel("Your question"), "How are Stripe payments processed?", 35); await pause(500);
await click(page.getByRole("button", { name: "Ask", exact: true })); await page.locator("[data-testid=refusal]").waitFor(); await pause(3500);
await caption("9. Hybrid code search with file:line citations");
await type(page.getByLabel("Search query"), "how is a progress bar rendered", 30); await pause(400);
await click(page.getByRole("button", { name: "Search", exact: true })); await page.locator("[data-testid=hit]").first().waitFor(); await pause(2000);
await scroll(380); await pause(3000);
await caption("10. Log out: protected pages now redirect to the login page");
await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" })); await pause(900);
await click(page.getByRole("button", { name: "Log out" })); await page.waitForURL("**/login"); await pause(1500);
await page.goto(BASE + "/dashboard"); await page.waitForURL("**/login**"); await pause(2200);
await caption("11. Log in again: the repository and history are still there");
await type(page.getByPlaceholder("Email"), email); await type(page.getByPlaceholder("Password"), password, 35);
await click(page.getByRole("button", { name: "Log in" })); await page.waitForURL("**/dashboard"); await card.waitFor(); await pause(3000);
await caption("Done. Everything above ran against the real backend, PostgreSQL and indexing pipeline."); await pause(3000);

await cdp.send("Page.stopScreencast");
fs.writeFileSync(`${OUT}/stamps.json`, JSON.stringify(stamps));
await browser.close();
console.log(`recorded ${stamps.length} frames over ${(stamps.at(-1) - stamps[0]).toFixed(1)}s`);
