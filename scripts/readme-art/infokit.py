"""infokit: SVG infographic builder (AWS palette, dark/light, NanumSquareOTF metrics, official AWS icons).

aws-infographic 스킬의 빌더를 그대로 가져왔고, 글꼴 폴더와 아이콘 번들 경로만 환경 변수로 받게 고쳤다
(INFOKIT_FONTS 기본 ~/.local/share/fonts, AWS_ICON_BUNDLE 필수).
"""
import base64
import glob
import json
import os
import re
import subprocess

from PIL import ImageFont

# ----------------------------------------------------------------------------- paths
FONT_DIR = os.environ.get("INFOKIT_FONTS", os.path.expanduser("~/.local/share/fonts"))
_NANUM = {300: "NanumSquareL.otf", 400: "NanumSquareR.otf", 700: "NanumSquareB.otf", 800: "NanumSquareEB.otf"}
_NANUM_DIR = next((p for p in (f"{FONT_DIR}/nanumsquare", f"{FONT_DIR}/nanumsquare-otf") if os.path.isdir(p)),
                  f"{FONT_DIR}/nanumsquare")
_D2 = sorted(glob.glob(f"{FONT_DIR}/d2coding/*.tt[cf]"))
_ICONS = os.environ.get("AWS_ICON_BUNDLE")
BUNDLE = json.load(open(_ICONS, encoding="utf-8"))["sets"] if _ICONS else {}

FONT_STACK = ("NanumSquareOTF, '나눔스퀘어OTF', NanumSquare, '나눔스퀘어', 'Apple SD Gothic Neo', "
              "'Malgun Gothic', 'Noto Sans KR', 'Noto Sans CJK KR', Arial, sans-serif")
CODE_FAMILY = "D2Coding, 'D2Coding ligature', Menlo, Consolas, monospace"

# Body is NanumSquareOTF Bold: logical 400 -> Bold(700), 700 -> ExtraBold(800).
WEIGHT_MAP = {300: 300, 400: 700, 500: 700, 600: 700, 700: 800, 800: 800}


def fw(w):
    return WEIGHT_MAP.get(int(w), int(w))


# ----------------------------------------------------------------------------- themes
# Every accent has an "F" (fill) twin. Text on saturated fills: badgetext (blue/purple), onwarm (orange/yellow/green).
THEMES = {
    "dark": dict(bg="#161D26", card="#1C2430", panel="#232D3A", cardline="#2E3947", line2="#3B4757",
                 text="#F3F3F7", text2="#E2E4EC", muted="#A6ABBE", faint="#7B8198", arrow="#A6ABBE",
                 badge="#E2E4EC", badgetext="#161D26", onwarm="#161D26", chipline="#5A667A",
                 blue="#41B3FF", blueF="#41B3FF", yellow="#FBD332", yellowF="#FBD332",
                 orange="#FF9900", orangeF="#FF9900", purple="#AD5CFF", purpleF="#AD5CFF",
                 pink="#FF5C85", pinkF="#FF5C85", green="#8CC63F", greenF="#8CC63F", icon="#E2E4EC"),
    "light": dict(bg="#FFFFFF", card="#F5F7F9", panel="#FFFFFF", cardline="#DFE4EA", line2="#CDD4DD",
                  text="#232F3E", text2="#2E3A4A", muted="#5F6B7A", faint="#8A94A2", arrow="#232F3E",
                  badge="#232F3E", badgetext="#FFFFFF", onwarm="#232F3E", chipline="#9AA5B3",
                  blue="#0972D3", blueF="#2E8CF0", yellow="#A87900", yellowF="#F5C518",
                  orange="#E8710A", orangeF="#FF9900", purple="#7D3FE0", purpleF="#8C4FFF",
                  pink="#D4245F", pinkF="#FF5C85", green="#4F8A10", greenF="#5FA82A", icon=None),
}


# ----------------------------------------------------------------------------- text metrics
_FC = {}


def _fallback_path(weight):
    q = f"Noto Sans CJK KR:weight={'bold' if weight >= 700 else 'regular'}"
    return subprocess.run(["fc-match", "-f", "%{file}", q], capture_output=True, text=True).stdout.strip()


def _font(weight, size):
    w = min(_NANUM, key=lambda k: abs(k - fw(weight)))
    key = (w, int(round(size)))
    if key not in _FC:
        p = f"{_NANUM_DIR}/{_NANUM[w]}"
        _FC[key] = ImageFont.truetype(p if os.path.exists(p) else _fallback_path(w), max(1, key[1]))
    return _FC[key]


def tw(s, size, weight=400):
    return _font(weight, size).getlength(s) * (size / max(1, int(round(size))))


def cw(s, size, bold=False):
    """Width in D2Coding (code text only)."""
    if not _D2:
        return tw(s, size) * 1.05
    key = ("d2", int(round(size)), bold)
    if key not in _FC:
        _FC[key] = ImageFont.truetype(_D2[0], key[1], index=1 if bold else 0)
    return _FC[key].getlength(s)


# rich text: _{sub} ^{sup} **bold** [colorkey]{text}
_RICH = re.compile(r"(_\{[^}]*\}|\^\{[^}]*\}|\*\*[^*]+\*\*|\[[a-zA-Z0-9]+\]\{[^}]*\})")


def parse_rich(s):
    segs = []
    for part in _RICH.split(s):
        if not part:
            continue
        if part.startswith("_{"):
            segs.append((part[2:-1], "sub", None, None))
        elif part.startswith("^{"):
            segs.append((part[2:-1], "sup", None, None))
        elif part.startswith("**"):
            segs.append((part[2:-2], None, 700, None))
        elif part.startswith("[") and (m := re.match(r"\[([a-zA-Z0-9]+)\]\{(.*)\}$", part)):
            segs.append((m.group(2), None, None, m.group(1)))
        else:
            segs.append((part, None, None, None))
    return segs


def rw(s, size, weight=400, ls=0.0):
    """Rendered width of (rich) text in px."""
    total, n = 0.0, 0
    for txt, kind, sw, _ in parse_rich(s):
        total += tw(txt, size * 0.7 if kind else size, sw or weight)
        n += len(txt)
    return total + ls * n


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def F(n, k):
    """Scale a size by the layout factor k (portrait pages use k = 1.1 ~ 1.25)."""
    return round(n * k)


# ----------------------------------------------------------------------------- document
class Doc:
    def __init__(self, W, H, theme):
        self.W, self.H, self.theme, self.t = W, H, theme, THEMES[theme]
        self.out, self.defs, self._markers = [], [], set()

    def c(self, key):
        return self.t.get(key, key) if key else key

    def add(self, s):
        self.out.append(s)

    def rect(self, x, y, w, h, rx=0, fill="none", stroke=None, sw=1.0, dash=None, fo=None, so=None, opacity=None):
        a = f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}"'
        if rx:
            a += f' rx="{rx:.1f}"'
        a += f' fill="{self.c(fill)}"'
        if fo is not None:
            a += f' fill-opacity="{fo:.3f}"'
        if stroke:
            a += f' stroke="{self.c(stroke)}" stroke-width="{sw}"'
            if so is not None:
                a += f' stroke-opacity="{so:.3f}"'
            if dash:
                a += f' stroke-dasharray="{dash}"'
        if opacity is not None:
            a += f' opacity="{opacity:.3f}"'
        self.add(a + "/>")

    def circle(self, cx, cy, r, fill="none", stroke=None, sw=1.0, fo=None):
        a = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{self.c(fill)}"'
        if fo is not None:
            a += f' fill-opacity="{fo:.3f}"'
        if stroke:
            a += f' stroke="{self.c(stroke)}" stroke-width="{sw}"'
        self.add(a + "/>")

    def line(self, x1, y1, x2, y2, stroke="arrow", sw=1.5, dash=None, so=None):
        a = (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{self.c(stroke)}" '
             f'stroke-width="{sw}" stroke-linecap="round"')
        if dash:
            a += f' stroke-dasharray="{dash}"'
        if so is not None:
            a += f' stroke-opacity="{so}"'
        self.add(a + "/>")

    def path(self, d, stroke="arrow", sw=1.5, fill="none", dash=None, marker=None, fo=None, so=None):
        a = f'<path d="{d}" fill="{self.c(fill)}"'
        if fo is not None:
            a += f' fill-opacity="{fo}"'
        if stroke:
            a += f' stroke="{self.c(stroke)}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"'
            if so is not None:
                a += f' stroke-opacity="{so}"'
        if dash:
            a += f' stroke-dasharray="{dash}"'
        if marker:
            a += f' marker-end="url(#{marker})"'
        self.add(a + "/>")

    def marker(self, key):
        mid = f"ah-{key}"
        if mid not in self._markers:
            self.defs.append(f'<marker id="{mid}" viewBox="0 0 10 10" refX="8.6" refY="5" markerWidth="11" '
                             f'markerHeight="11" markerUnits="userSpaceOnUse" orient="auto">'
                             f'<path d="M0,0.6 L10,5 L0,9.4 z" fill="{self.c(key)}"/></marker>')
            self._markers.add(mid)
        return mid

    def arrow(self, pts, color="arrow", sw=1.8, dash=None, r=10, head=True):
        self.path(poly_d(pts, r), stroke=color, sw=sw, dash=dash, marker=self.marker(color) if head else None)

    def text(self, x, y, s, size=16, weight=400, color="text", anchor="start", ls=None, opacity=None, box=None,
             family=None):
        """Rich text. Pass box=(x, y, w, h) of the enclosing card so QA can detect overflow."""
        parts, shift = [], 0.0
        for txt, kind, sw, sc in parse_rich(s):
            target = size * 0.30 if kind == "sub" else (-size * 0.42 if kind == "sup" else 0.0)
            attrs = ""
            if abs(target - shift) > 1e-6:
                attrs += f' dy="{target - shift:.2f}"'
                shift = target
            if kind:
                attrs += f' font-size="{size * 0.7:.1f}"'
            if sw:
                attrs += f' font-weight="{fw(sw)}"'
            if sc:
                attrs += f' fill="{self.c(sc)}"'
            parts.append(f"<tspan{attrs}>{esc(txt)}</tspan>" if attrs else esc(txt))
        a = f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{fw(weight)}" fill="{self.c(color)}"'
        if anchor != "start":
            a += f' text-anchor="{anchor}"'
        if ls:
            a += f' letter-spacing="{ls}"'
        if opacity is not None:
            a += f' opacity="{opacity}"'
        if family:
            a += f' font-family="{family}"'
        if box:
            a += f' data-box="{box[0]:.0f},{box[1]:.0f},{box[2]:.0f},{box[3]:.0f}"'
        self.add(a + ">" + "".join(parts) + "</text>")

    def runs(self, x, y, runs, anchor="start", box=None):
        """One line of differently styled runs: (text, size, weight, color[, dx[, letter_spacing]])."""
        parts = []
        for r in runs:
            txt, size, weight, color = r[:4]
            a = f' font-size="{size}" font-weight="{fw(weight)}" fill="{self.c(color)}"'
            if len(r) > 4 and r[4]:
                a += f' dx="{r[4]}"'
            if len(r) > 5 and r[5]:
                a += f' letter-spacing="{r[5]}"'
            parts.append(f"<tspan{a}>{esc(txt)}</tspan>")
        a = f'<text x="{x:.1f}" y="{y:.1f}"'
        if anchor != "start":
            a += f' text-anchor="{anchor}"'
        if box:
            a += f' data-box="{box[0]:.0f},{box[1]:.0f},{box[2]:.0f},{box[3]:.0f}"'
        self.add(a + ">" + "".join(parts) + "</text>")

    def icon(self, ref, x, y, size):
        """Official AWS icon from the aws-diagram bundle, e.g. 'service/Amazon-Bedrock' (find_icon.py)."""
        setname, name = ref.split("/", 1)
        e = BUNDLE[setname][name]
        if e["type"] == "svg":
            data = e["data"]
            if self.t.get("icon"):  # dark theme: lighten squid-ink glyphs
                data = re.sub(r"#2[34]2F3[DE]", self.t["icon"], data)
            uri = "data:image/svg+xml;base64," + base64.b64encode(data.encode()).decode()
        else:
            uri = "data:image/png;base64," + e["data"]
        self.add(f'<image href="{uri}" xlink:href="{uri}" x="{x:.1f}" y="{y:.1f}" width="{size:.1f}" '
                 f'height="{size:.1f}"/>')

    def svg(self):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'viewBox="0 0 {self.W} {self.H}" width="{self.W}" height="{self.H}" font-family="{FONT_STACK}">')
        return head + "\n<defs>" + "".join(self.defs) + "</defs>\n" + "\n".join(self.out) + "\n</svg>\n"


def poly_d(pts, r=10):
    if len(pts) == 2 or r <= 0:
        return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        l1, l2 = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5, ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        rr = min(r, l1 / 2, l2 / 2)
        ax, ay = x1 - (x1 - x0) / l1 * rr, y1 - (y1 - y0) / l1 * rr
        bx, by = x1 + (x2 - x1) / l2 * rr, y1 + (y2 - y1) / l2 * rr
        d += f" L{ax:.1f},{ay:.1f} Q{x1:.1f},{y1:.1f} {bx:.1f},{by:.1f}"
    return d + f" L{pts[-1][0]:.1f},{pts[-1][1]:.1f}"


# ----------------------------------------------------------------------------- text layout
def wrap(s, size, weight, maxw):
    words, lines, cur = s.split(" "), [], ""
    for wd in words:
        cand = wd if not cur else cur + " " + wd
        if rw(cand, size, weight) <= maxw or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = wd
    return lines + ([cur] if cur else [])


def wrap_balanced(s, size, weight, maxw):
    """Greedy wrap; two-line results are rebalanced (prefer breaking after ',', never after ':' or '(')."""
    lines = wrap(s, size, weight, maxw)
    if len(lines) != 2:
        return lines
    words, best = s.split(" "), None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        wa, wb = rw(a, size, weight), rw(b, size, weight)
        score = max(wa, wb) - (24 if a.endswith(",") else 0) + (60 if a.endswith((":", "(")) else 0)
        if wa <= maxw and wb <= maxw and (best is None or score < best[0]):
            best = (score, [a, b])
    return best[1] if best else lines


def nlines(text, size, w, weight=400):
    return len(wrap_balanced(text, size, weight, w)) if rw(text, size, weight) > w else 1


def para(d, x, y, w, text, size=16, lh=None, weight=400, color="text2", box=None, anchor="start", maxl=4):
    """Wrapped paragraph starting at baseline y. Returns the baseline of the last line."""
    lh = lh or round(size * 1.45)
    lines = (wrap_balanced(text, size, weight, w) if rw(text, size, weight) > w else [text])[:maxl]
    for i, ln in enumerate(lines):
        d.text(x, y + i * lh, ln, size, weight, color, anchor, box=box)
    return y + (len(lines) - 1) * lh


def cell(d, x, mid, w, text, size, lh, weight, color, box, k=1.0):
    """Table cell text vertically centered on mid (handles 1-2 wrapped lines)."""
    lines = wrap_balanced(text, size, weight, w) if rw(text, size, weight) > w else [text]
    y0 = mid + 5 * k - (len(lines) - 1) * lh / 2
    for i, ln in enumerate(lines):
        d.text(x, y0 + i * lh, ln, size, weight, color, box=box)


def dot_list(d, x, y, w, items, size=15, lh=None, gap=None, color="text2", dot="muted", box=None):
    """Bulleted list from baseline y. Returns the baseline of the last line."""
    lh = lh or round(size * 1.42)
    gap = gap if gap is not None else round(size * 0.55)
    yy = last = y
    for it in items:
        d.circle(x + 4, yy - size * 0.33, 2.8, fill=dot)
        last = para(d, x + 16, yy, w - 16, it, size, lh, 400, color, box=box)
        yy = last + lh + gap
    return last


def items_h(items, w, size, lh, gap):
    """Height of a dot_list block (for vertical centering)."""
    return sum(nlines(it, size, w - 16) for it in items) * lh + (len(items) - 1) * gap


# ----------------------------------------------------------------------------- components
def card(d, x, y, w, h, stroke="cardline", sw=1.2, fill="card", rx=14, dashed=False):
    d.rect(x, y, w, h, rx=rx, fill=fill, stroke=stroke, sw=sw, dash="8 6" if dashed else None)


def badge(d, cx, cy, num, r=15, size=16):
    d.circle(cx, cy, r, fill="badge")
    d.text(cx, cy + size * 0.35, str(num), size, 700, "badgetext", "middle")


def tag(d, x, y, text, color="green", size=13, h=24, pad=10, fill_op=0.14, box=None):
    """Rounded label chip. Returns its width."""
    w = rw(text, size, 700) + 2 * pad
    d.rect(x, y, w, h, rx=h / 2, fill=color + "F", fo=fill_op, stroke=color, sw=1.1)
    d.text(x + w / 2, y + h / 2 + size * 0.36, text, size, 700, color, "middle", box=box)
    return w


def pill(d, x, y, w, h, text, color="blue", size=15, weight=700, fo=0.14, txt="text", sw=1.3, dash=None):
    d.rect(x, y, w, h, rx=min(h / 2, 12), fill=color + "F", fo=fo, stroke=color, sw=sw, dash=dash)
    d.text(x + w / 2, y + h / 2 + size * 0.36, text, size, weight, txt, "middle")


def callout(d, x, y, w, title, body, k=1.0, color="orange", box=None):
    """Key-insight box (max one per section). Returns bottom y."""
    h = 58 * k
    d.rect(x, y, w, h, rx=10, fill=color + "F", fo=0.08, stroke=color, sw=1.2)
    d.text(x + 16, y + 25 * k, title, F(15, k), 700, "text", box=box)
    para(d, x + 16, y + 46 * k, w - 32, body, F(13, k), None, 400, "text2", box=box)
    return y + h


def check(d, x, y, s, color="green", sw=2.4):
    d.path(f"M{x:.1f},{y + s * 0.55:.1f} L{x + s * 0.38:.1f},{y + s * 0.9:.1f} L{x + s:.1f},{y + s * 0.12:.1f}",
           stroke=color, sw=sw)


def cross(d, x, y, s, color="pink", sw=2.4):
    d.path(f"M{x:.1f},{y:.1f} L{x + s:.1f},{y + s:.1f} M{x + s:.1f},{y:.1f} L{x:.1f},{y + s:.1f}", stroke=color, sw=sw)


def header(d, x, y, title, sub_en, sub_ko, tsize=42, ssize=21, kosize=18):
    d.text(x, y, title, tsize, 700, "text", ls=0.2)
    d.runs(x, y + round(tsize * 0.92), [(sub_en, ssize, 700, "orange"), (sub_ko, kosize, 400, "muted", 16)])


def series_nav(d, x, y, parts, current, size=13, anchor="end"):
    """Chips for a multi-part series. parts = [("0", "개요"), ("1", "..."), ...]."""
    items = [f"{n} {t}" for n, t in parts]
    widths = [rw(t, size, 700) + 24 for t in items]
    lab = rw("SERIES", 11, 700, 1.2)
    total = sum(widths) + 8 * (len(items) - 1) + lab + 12
    cx = x - total if anchor == "end" else x
    d.text(cx, y + 17, "SERIES", 11, 700, "faint", ls=1.2)
    cx += lab + 12
    for (n, _), t, wdt in zip(parts, items, widths):
        on = n == current
        d.rect(cx, y, wdt, 26, rx=13, fill="orangeF" if on else "card", fo=0.9 if on else None,
               stroke="orange" if on else "line2", sw=1.1)
        d.text(cx + wdt / 2, y + 17.5, t, size, 700, "badgetext" if on else "muted", "middle")
        cx += wdt + 8


def section(d, x, y, w, h, num, title, take=None, tsize=21, ksize=15, inline=True):
    """Numbered card with a title and a one-line takeaway. Returns the y where content starts."""
    box = (x, y, w, h)
    card(d, x, y, w, h)
    badge(d, x + 34, y + 33, num, r=15, size=16)
    if take and inline:
        d.runs(x + 58, y + 40, [(title, tsize, 700, "text", 0, 0.2), (take, ksize, 400, "muted", 14)], box=box)
        return y + 66
    d.text(x + 58, y + 40, title, tsize, 700, "text", ls=0.2, box=box)
    if take:
        d.text(x + 58, y + 66, take, ksize, 400, "muted", box=box)
        return y + 88
    return y + 66


def footer_note(d, x, y, text, size=13, anchor="end"):
    d.text(x, y, text, size, 400, "faint", anchor)
