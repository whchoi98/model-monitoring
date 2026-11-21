// SVG를 헤드리스 Chromium으로 PNG로 뽑는다. frontend/ 에서 실행한다 (frontend/node_modules의 playwright 사용).
//   node ../scripts/readme-art/render.js <in.svg> <out.png> [scale=1] [--qa]
// --qa: data-box가 있는 글자의 넘침, 글자끼리 겹침, 캔버스 이탈을 검사하고 문제가 있으면 종료 코드 1.
const { chromium } = require(process.cwd() + "/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const QA = () => {
  const out = [];
  const texts = Array.from(document.querySelectorAll("text")).filter(t => !t.getAttribute("transform"));
  const items = texts.map(t => ({ t, b: t.getBBox(), txt: t.textContent }));
  const vb = document.documentElement.viewBox.baseVal;
  for (const { t, b, txt } of items) {
    if (b.x < 0 || b.y < 0 || b.x + b.width > vb.width || b.y + b.height > vb.height) out.push({ type: "canvas", txt });
    const db = t.getAttribute("data-box");
    if (!db) continue;
    const [x, y, w, h] = db.split(",").map(Number);
    const over = [];
    if (b.x < x + 6) over.push("L" + (x + 6 - b.x).toFixed(1));
    if (b.x + b.width > x + w - 6) over.push("R" + (b.x + b.width - (x + w - 6)).toFixed(1));
    if (b.y < y + 1) over.push("T" + (y + 1 - b.y).toFixed(1));
    if (b.y + b.height > y + h - 1) over.push("B" + (b.y + b.height - (y + h - 1)).toFixed(1));
    if (over.length) out.push({ type: "overflow", txt, over: over.join(" ") });
  }
  for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
    const a = items[i].b, c = items[j].b;
    const ix = Math.min(a.x + a.width, c.x + c.width) - Math.max(a.x, c.x);
    const iy = Math.min(a.y + a.height, c.y + c.height) - Math.max(a.y, c.y);
    if (ix > 1 && iy > 4) out.push({ type: "overlap", a: items[i].txt, b: items[j].txt, ix: +ix.toFixed(1), iy: +iy.toFixed(1) });
  }
  return out;
};

(async () => {
  const args = process.argv.slice(2);
  const qa = args.includes("--qa");
  const [src, out, scaleArg] = args.filter(a => a !== "--qa");
  const scale = Number(scaleArg || 1);
  const svg = fs.readFileSync(src, "utf8");
  const m = svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/);
  const width = Math.round(Number(m[1]));
  const height = Math.round(Number(m[2]));
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: scale });
  await page.goto("file://" + path.resolve(src));
  await page.waitForTimeout(300);
  await page.screenshot({ path: out, clip: { x: 0, y: 0, width, height } });
  const issues = qa ? await page.evaluate(QA) : [];
  await browser.close();
  console.log(`${path.basename(out)} ${width * scale}x${height * scale}${qa ? `, qa ${issues.length}` : ""}`);
  for (const it of issues) console.log("   ", JSON.stringify(it));
  process.exit(issues.length ? 1 : 0);
})();
