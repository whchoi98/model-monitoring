// README 스크린샷(docs/images/ui/)을 운영 화면에서 다시 찍는다: 9개 화면 × EN, KO, 다크 테마, 1440x900.
// frontend/ 에서 실행한다 (frontend/node_modules의 playwright 사용).
//   node ../scripts/readme-art/capture.js ../docs/images/ui [en] [ko]
//   BASE=https://<도메인> 으로 대상 주소를, ONLY=dashboard-cards,parity 로 화면을 고른다.
// 언어는 lang 쿠키와 localStorage 둘 다 넣는다 (layout.tsx가 쿠키를 서버에서 읽는다).
// 대시보드는 주기적으로 요청을 보내므로 networkidle을 기다리지 않는다 (2026-11-21에 빈 화면이 찍혔다).
const { chromium } = require(process.cwd() + "/node_modules/playwright");
const BASE = process.env.BASE || "https://d36s7ml54xwemr.cloudfront.net";
const OUT = process.argv[2];
const LANGS = process.argv.slice(3).length ? process.argv.slice(3) : ["en", "ko"];

const top = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); return e.getBoundingClientRect().top + window.scrollY; })()`;
// name, path, 기다릴 selector, 준비 동작, 스크롤 y 식
const VIEWS = [
  ["dashboard", "/", "[data-grade]", null, "0"],
  ["dashboard-cards", "/", "[data-grade]", async page => {
    await page.getByRole("button", { name: /^(Cards|카드로)$/ }).first().click();
    await page.waitForTimeout(1500);
  }, `(() => { const h = Array.from(document.querySelectorAll("h3")).find(e => /Claude Fable 5\.1/.test(e.innerText)); return h.getBoundingClientRect().top + window.scrollY - 182; })()`],
  ["dashboard-trend", "/", ".recharts-wrapper", null,
    `(() => { const h = Array.from(document.querySelectorAll("h3")).find(e => /TTFT/.test(e.innerText)); return h.getBoundingClientRect().top + window.scrollY - 176; })()`],
  ["gpt-on-aws", "/gpt-on-aws", "h1", null, "0"],
  ["claude-features", "/claude-features", "div[role='img']", null, `${top("div[role='img']")} - 345`],
  ["parity", "/parity", "div[role='img']", null, `${top("div[role='img']")} - 275`],
  ["cost", "/cost", "h1", null, "0"],
  ["reliability", "/reliability", "h1", null, "0"],
  ["pricing", "/pricing", "table", null, "0"],
];

const ONLY = (process.env.ONLY || "").split(",").filter(Boolean);

(async () => {
  const browser = await chromium.launch();
  for (const lang of LANGS) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    await ctx.addCookies([{ name: "lang", value: lang, url: BASE }]);
    await ctx.addInitScript(l => { try { localStorage.setItem("lang", l); localStorage.setItem("theme", "dark"); } catch {} }, lang);
    for (const [name, path, sel, prep, yexpr] of VIEWS.filter(v => !ONLY.length || ONLY.includes(v[0]))) {
      let ok = false, note = "";
      for (let attempt = 1; attempt <= 3 && !ok; attempt++) {
        const page = await ctx.newPage();
        try {
          await page.goto(BASE + path, { waitUntil: "domcontentloaded", timeout: 45000 });
          await page.waitForSelector(sel, { timeout: 30000 });
          await page.waitForTimeout(3500);
          if (prep) await prep(page);
          const y = await page.evaluate(yexpr);
          await page.evaluate(v => window.scrollTo(0, Math.max(0, Math.round(v))), y);
          await page.waitForTimeout(1500);
          const ver = await page.evaluate(() => (document.body.innerText.match(/v2\.\d+\.\d+/) || [null])[0]);
          await page.screenshot({ path: `${OUT}/${name}-${lang}.png`, fullPage: false });
          ok = true;
          note = `y=${Math.round(y)} ver=${ver} attempt=${attempt}`;
        } catch (e) {
          note = `attempt ${attempt}: ${String(e).slice(0, 140)}`;
        }
        await page.close();
      }
      console.log(`${ok ? "ok  " : "FAIL"} ${lang} ${name} ${note}`);
    }
    await ctx.close();
  }
  await browser.close();
})();
