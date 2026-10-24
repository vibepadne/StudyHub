import fs from "node:fs";
import path from "node:path";
const PORT = 9222, BASE = "http://127.0.0.1:8010", SESSIONID = process.env.SESSIONID;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const res = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: "PUT" });
const target = await res.json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.addEventListener("open", resolve, { once: true }); ws.addEventListener("error", reject, { once: true }); });
let id = 0; const pending = new Map();
ws.addEventListener("message", (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); } });
const send = (method, params = {}) => new Promise((resolve, reject) => { const i = ++id; pending.set(i, { resolve, reject }); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expression) => { const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.text); return r.result.value; };
await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Network.setCacheDisabled", { cacheDisabled: true });
await send("Network.setCookie", { name: "sessionid", value: SESSIONID, domain: "127.0.0.1", path: "/", httpOnly: true });
const viewport = async (w, h) => { await send("Emulation.setTouchEmulationEnabled", { enabled: w < 768, maxTouchPoints: w < 768 ? 5 : 1 }); await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: w < 768 ? 2 : 1, mobile: w < 768 }); };
const goto = async () => { await send("Page.navigate", { url: BASE + "/shared/" }); for (let i = 0; i < 80; i++) { await sleep(100); if ((await ev("document.readyState")) === "complete") break; } await sleep(700); };
const metrics = () => ev(`(() => {
  const rect = (sel) => { const el = document.querySelector(sel); if (!el) return null; const r = el.getBoundingClientRect(); return { left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width), center: Math.round(r.left + r.width / 2) }; };
  return { vw: innerWidth, sidebar: rect('#shared-sidebar'), container: rect('.container'), head: rect('.page-head'), main: rect('.shared-main-content'), group: rect('.share-group'), sectionTitle: rect('.share-section h2'), body: document.body.className, docW: document.documentElement.scrollWidth };
})()`);
const report = {};
for (const width of [1440, 1200, 1101, 1100, 768]) {
  await viewport(width, width > 768 ? 1000 : 900);
  await goto();
  report[width] = await metrics();
}
// Desktop collapsed state
await viewport(1440, 1000);
await goto();
if (!(await ev("document.body.classList.contains('shared-sidebar-collapsed')"))) {
  await ev("document.getElementById('sidebar-toggle').click()");
}
await sleep(350);
report.collapsed1440 = await metrics();
const s = await send("Page.captureScreenshot", { format: "png" });
fs.mkdirSync(path.resolve("_ui5/shots"), { recursive: true });
fs.writeFileSync(path.resolve("_ui5/shots/shared-collapsed.png"), Buffer.from(s.data, "base64"));
// Expanded screenshot
await ev("document.getElementById('sidebar-toggle').click()");
await sleep(400);
const s2 = await send("Page.captureScreenshot", { format: "png" });
fs.writeFileSync(path.resolve("_ui5/shots/shared-expanded.png"), Buffer.from(s2.data, "base64"));
console.log(JSON.stringify(report, null, 2));
ws.close(); process.exit(0);
