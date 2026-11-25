#!/usr/bin/env python3
"""README 인포그래픽 "Amazon Bedrock LLM Monitor 한눈에 보기" SVG 4종을 만든다 (16:9, KO와 EN × dark와 light).

사용: AWS_ICON_BUNDLE=<aws-diagram 스킬>/assets/icons.json python3 glance.py <out_dir>
채널 행렬(CLAUDE, NOVA, GPT)과 T의 수치를 고친 뒤 build.sh로 다시 만든다. s1의 assert가 합계 51과 열 합계를 확인한다.
"""
import html
import re
import sys
from pathlib import Path

from infokit import CODE_FAMILY, Doc, card, cell, footer_note, header, pill, rw, section, tag

# 채널 행렬. 열: Claude Platform on AWS, Bedrock Global CRIS, Bedrock US CRIS, Bedrock In-Region
# 값: 1 = 채널 있음, "seoul" = 서울 온디맨드, "use1" = Bedrock Mantle us-east-1
CLAUDE = [
    ("Claude Fable 5.2", (1, 1, 1, 0)),
    ("Claude Fable 5.1", (1, 1, 1, 0)),
    ("Claude Opus 5.5", (1, 1, 1, 0)),
    ("Claude Opus 5", (1, 1, 1, "seoul")),
    ("Claude Sonnet 5.5", (1, 1, 1, 0)),
    ("Claude Sonnet 5", (1, 1, 1, "seoul")),
    ("Claude Haiku 5.5", (1, 1, 1, 0)),
]
NOVA = [("Nova 2.0 Lite", (0, 0, 1, 0))]
GPT = [(name, (0, 1, 1, "use1")) for name in (
    "GPT 6.2 Astra", "GPT 6.2 Sol", "GPT 6.1 Sol", "GPT 6.1 Terra", "GPT 6 Astra", "GPT 6 Sol", "GPT 6 Luna")]
# GPT 5.6 세대(v2.45.0 복귀)는 Global CRIS와 Mantle us-east-1 두 채널이다 — US CRIS 채널이 없다
GPT += [(name, (0, 1, 0, "use1")) for name in ("GPT 5.6 Sol", "GPT 5.6 Terra", "GPT 5.6 Luna")]
GROUPS = [("Anthropic Claude", "orange", CLAUDE), ("Amazon Nova", "orange", NOVA), ("OpenAI GPT", "blue", GPT)]
VERSION = "v2.45"
AS_OF = "2026-11-25"

T = {
    "ko": dict(
        title="Amazon Bedrock LLM Monitor 한눈에 보기",
        sub_en="Production at a Glance",
        sub_ko=f"운영 구성 요약, {VERSION}",
        kpi=[
            ("51", "모니터링 채널", "Bedrock 17, GPT 27, CP 7"),
            ("18", "모델 패밀리", "Claude 7, GPT 10, Nova 1"),
            ("5분", "프로브 주기", "사이클마다 51채널 호출"),
            ("7", "예약 태스크", "EventBridge Scheduler, Fargate"),
            ("11", "모니터링 화면", "한국어, 영어 지원"),
            ("8", "CDK 스택", "서울 리전 배포"),
        ],
        s1=("모델 패밀리별 채널", "패밀리 18개, 호출 경로 4종, 채널 51개"),
        legend=["Amazon Bedrock (Claude, Nova) 17", "OpenAI GPT on Bedrock 27", "Claude Platform on AWS 7"],
        cols=[("Claude Platform", "on AWS"), ("Bedrock", "Global CRIS"), ("Bedrock", "US CRIS"),
              ("Bedrock", "In-Region")],
        total="합계",
        seoul="서울",
        sum="채널 합계",
        s1_note="In-Region: Claude는 서울 온디맨드, GPT는 Bedrock Mantle us-east-1",
        s2=("수집 주기", "EventBridge Scheduler가 실행하는 Fargate 태스크 7개"),
        tasks=[
            ("5분", "orange", "AutoProber", "51채널에 워크로드 1종 스트리밍 호출", "사이클당 51행"),
            ("5분", "orange", "Insights", "Claude Haiku 5.5의 최근 6시간 요약", "한국어, 영어 요약"),
            ("15분", "yellow", "GptBench", "GPT 23채널, 채널당 10회 TTFB와 TTFT 측정", "사이클당 230행"),
            ("12시간", "blue", "ParityRun", "모델별 API surface 6개, 피처 20개 실행 증거 수집", "51개 모델"),
            ("12시간", "blue", "PricingSync", "공식 출처 4곳의 단가 동기화, 50% 초과 변경은 승인 대기", "61개 단가 채널"),
            ("매일 17:30 UTC", "purple", "FeaturesVerify", "Claude API 피처 39행, surface 5개, 대표 모델 7개 검증", "1,365셀"),
            ("매일 18:00 UTC", "purple", "ExplorerVerify", "모델 탐색 코드 예제 실행 검증", "예제 83건"),
        ],
        s3=("워크로드와 지표", "6종 순환, 같은 종류는 30분마다 반복"),
        workloads=[("짧은 대화", "chat-short"), ("추론", "reasoning"), ("코드 생성", "code-gen"),
                   ("요약", "summarize"), ("JSON 추출", "structured"), ("번역", "translate")],
        metrics_label="수집 지표",
        metrics=["TTFT", "총 응답시간", "서버 처리시간", "TPS", "입력, 출력 토큰", "Stop reason"],
        grade=("카드 값 등급", ["양호", "경고", "위험"]),
        s4=("모니터링 화면", "확인할 항목별 화면 11개"),
        pages=[
            ("속도", "orange", "대시보드, GPT on AWS"),
            ("신뢰성, 품질", "green", "신뢰성, 효율성, 분석"),
            ("비용", "yellow", "비용, 비용 단가"),
            ("API 호환성", "purple", "모델 탐색, 패리티 런, Claude API 기능"),
            ("도구", "blue", "프롬프트"),
        ],
        ai=("AI 챗봇, AI 인사이트", "Claude Haiku 5.5, 조회 도구 4개"),
        note=f"{AS_OF} 운영 기준, {VERSION}, 수치 출처는 저장소 코드와 운영 API",
    ),
    "en": dict(
        title="Amazon Bedrock LLM Monitor at a Glance",
        sub_en="Production configuration",
        sub_ko=f"{VERSION}, deployed in ap-northeast-2 (Seoul)",
        kpi=[
            ("51", "Monitored channels", "Bedrock 17, GPT 27, CP 7"),
            ("18", "Model families", "Claude 7, GPT 10, Nova 1"),
            ("5 min", "Probe cycle", "All 51 channels"),
            ("7", "Scheduled tasks", "EventBridge Scheduler, Fargate"),
            ("11", "Monitoring pages", "Korean and English UI"),
            ("8", "CDK stacks", "Deployed in Seoul"),
        ],
        s1=("Channels by model family", "18 families, 4 call paths, 51 channels"),
        legend=["Amazon Bedrock (Claude, Nova) 17", "OpenAI GPT on Bedrock 27", "Claude Platform on AWS 7"],
        cols=[("Claude Platform", "on AWS"), ("Bedrock", "Global CRIS"), ("Bedrock", "US CRIS"),
              ("Bedrock", "In-Region")],
        total="Total",
        seoul="Seoul",
        sum="Channels",
        s1_note="In-Region: Seoul on-demand for Claude, Bedrock Mantle us-east-1 for GPT",
        s2=("Collection cadence", "7 Fargate tasks run by EventBridge Scheduler"),
        tasks=[
            ("5 min", "orange", "AutoProber", "One streaming call per channel with one workload category",
             "51 rows per cycle"),
            ("5 min", "orange", "Insights", "Claude Haiku 5.5 summary of the last 6 hours", "Korean, English"),
            ("15 min", "yellow", "GptBench", "TTFB and TTFT on 23 GPT channels, 10 runs each", "230 rows per cycle"),
            ("12 h", "blue", "ParityRun", "Execution evidence per model: 6 API surfaces, 20 features", "51 models"),
            ("12 h", "blue", "PricingSync", "Unit prices from 4 official sources, changes above 50% wait for approval",
             "61 price channels"),
            ("Daily 17:30 UTC", "purple", "FeaturesVerify", "39 Claude API feature rows on 5 surfaces for 7 models",
             "1,365 cells"),
            ("Daily 18:00 UTC", "purple", "ExplorerVerify", "Runs every Model Explorer code example", "83 examples"),
        ],
        s3=("Workloads and metrics", "6 categories in rotation, each repeats every 30 min"),
        workloads=[("Short chat", "chat-short"), ("Reasoning", "reasoning"), ("Code generation", "code-gen"),
                   ("Summarization", "summarize"), ("JSON extraction", "structured"), ("Translation", "translate")],
        metrics_label="Collected metrics",
        metrics=["TTFT", "Total latency", "Server latency", "TPS", "Tokens in/out", "Stop reason"],
        grade=("Card value grades", ["Normal", "Warning", "Critical"]),
        s4=("Monitoring pages", "11 pages by what you check"),
        pages=[
            ("Speed", "orange", "Dashboard, GPT on AWS"),
            ("Quality", "green", "Reliability, Efficiency, Analysis"),
            ("Cost", "yellow", "Cost, Unit Prices"),
            ("Compatibility", "purple", "Model Explorer, Parity Run, Claude API Features"),
            ("Tools", "blue", "Prompts"),
        ],
        ai=("AI chatbot and AI insights", "Claude Haiku 5.5 with 4 query tools"),
        note=f"Production as of {AS_OF}, {VERSION}. Figures come from the repository code and the production API.",
    ),
}


def kpis(d, x, y, w, h, L):
    n, gap = len(L["kpi"]), 16
    tw_ = (w - gap * (n - 1)) / n
    for i, (num, label, cap) in enumerate(L["kpi"]):
        tx = x + i * (tw_ + gap)
        box = (tx, y, tw_, h)
        card(d, tx, y, tw_, h)
        d.text(tx + 22, y + h / 2 + 15, num, 42, 700, "orange", box=box)
        nx = tx + 22 + rw(num, 42, 700) + 14
        d.text(nx, y + h / 2 - 4, label, 17, 700, "text", box=box)
        d.text(nx, y + h / 2 + 18, cap, 12.5, 400, "muted", box=box)


def s1(d, x, y, w, h, L):
    cy = section(d, x, y, w, h, 1, *L["s1"])
    box = (x, y, w, h)
    ix, iw = x + 24, w - 48

    # 제공 경로별 비중 막대
    by, bh, sx = cy + 4, 34, ix
    for color, n, tc in (("orange", 17, "onwarm"), ("blue", 27, "badgetext"), ("purple", 7, "badgetext")):
        sw_ = iw * n / 51
        d.rect(sx, by, sw_ - 3, bh, rx=6, fill=color + "F")
        d.text(sx + (sw_ - 3) / 2, by + 23.5, str(n), 17, 700, tc, "middle")
        sx += sw_
    ly, lx = by + bh + 22, ix
    for color, label in zip(("orange", "blue", "purple"), L["legend"]):
        d.circle(lx + 6, ly - 5, 6, fill=color + "F")
        d.text(lx + 18, ly, label, 13, 400, "text2", box=box)
        lx += 18 + rw(label, 13) + 26

    # 패밀리 × 경로 행렬
    my = ly + 20
    fam_w, tot_w = 232, 64
    cw_ = (iw - fam_w - tot_w) / 4
    cols_x = [ix + fam_w + i * cw_ + cw_ / 2 for i in range(4)]
    tot_x = ix + iw - tot_w / 2
    for cx, (l1, l2) in zip(cols_x, L["cols"]):
        d.text(cx, my + 16, l1, 12.5, 700, "text", "middle", box=box)
        d.text(cx, my + 32, l2, 12.5, 400, "muted", "middle", box=box)
    d.text(tot_x, my + 24, L["total"], 12.5, 700, "muted", "middle", box=box)

    ry, rh, gh = my + 44, 25, 24  # 패밀리 18행(v2.45.0) — 15행일 때는 행 높이 30이었다(18 × 25 = 15 × 30)
    col_tot = [0, 0, 0, 0]
    for gname, gcolor, rows in GROUPS:
        gsum = sum(sum(1 for c in cells if c) for _, cells in rows)
        d.rect(ix, ry + 2, iw, gh - 4, rx=6, fill="line2", fo=0.45)
        d.text(ix + 10, ry + 16.5, gname, 12.5, 700, "text2", box=box)
        d.text(tot_x, ry + 16.5, str(gsum), 12.5, 700, "text2", "middle", box=box)
        ry += gh
        for fam, cells in rows:
            mid = ry + rh / 2
            d.text(ix + 10, mid + 5, fam, 14.5, 400, "text", box=box)
            for i, c in enumerate(cells):
                color = "purple" if i == 0 else gcolor
                if not c:
                    d.line(cols_x[i] - 5, mid, cols_x[i] + 5, mid, stroke="line2", sw=1.6)
                    continue
                col_tot[i] += 1
                if c == 1:
                    d.circle(cols_x[i], mid, 7, fill=color + "F")
                else:
                    label = L["seoul"] if c == "seoul" else "us-east-1"
                    tw_ = rw(label, 12, 700) + 16
                    tag(d, cols_x[i] - tw_ / 2, mid - 11, label, color, 12, 22, 8, box=box)
            d.text(tot_x, mid + 5, str(sum(1 for c in cells if c)), 14.5, 700, "text2", "middle", box=box)
            d.line(ix, ry + rh, ix + iw, ry + rh, stroke="cardline", sw=1)
            ry += rh

    # 합계 행
    ry += 4
    d.rect(ix, ry, iw, 34, rx=8, fill="orangeF", fo=0.10, stroke="orange", sw=1.1)
    d.text(ix + 10, ry + 22.5, L["sum"], 14.5, 700, "text", box=box)
    for cx, n in zip(cols_x, col_tot):
        d.text(cx, ry + 22.5, str(n), 15, 700, "text", "middle", box=box)
    d.text(tot_x, ry + 23.5, str(sum(col_tot)), 18, 700, "orange", "middle", box=box)
    d.text(ix, ry + 34 + 22, L["s1_note"], 12.5, 400, "muted", box=box)
    assert sum(col_tot) == 51 and col_tot == [7, 17, 15, 12], col_tot


def s2(d, x, y, w, h, L):
    cy = section(d, x, y, w, h, 2, *L["s2"])
    box = (x, y, w, h)
    ix, iw = x + 24, w - 48
    d.icon("service/Amazon-EventBridge", x + w - 24 - 80, y + 14, 36)
    d.icon("service/AWS-Fargate", x + w - 24 - 36, y + 14, 36)
    rows = L["tasks"]
    rh = (y + h - 14 - cy) / len(rows)
    pw, name_w, out_w = 158, 150, 176
    name_x = ix + pw + 18
    desc_x = name_x + name_w
    for i, (cad, color, name, desc, outp) in enumerate(rows):
        top = cy + i * rh
        mid = top + rh / 2
        if i:
            d.line(ix, top, ix + iw, top, stroke="cardline", sw=1)
        pill(d, ix, mid - 15, pw, 30, cad, color, 14)
        d.text(name_x, mid + 5.5, name, 16, 700, "text", box=box)
        cell(d, desc_x, mid, iw - (desc_x - ix) - out_w - 12, desc, 14.5, 19, 400, "text2", box)
        tw_ = rw(outp, 13, 700) + 20
        tag(d, ix + iw - tw_, mid - 12, outp, "green", 13, 24, 10, box=box)


def s3(d, x, y, w, h, L):
    cy = section(d, x, y, w, h, 3, *L["s3"], inline=False)
    box = (x, y, w, h)
    ix, iw = x + 24, w - 48
    gap, ch = 10, 44
    cw_ = (iw - gap) / 2
    for i, (label, cid) in enumerate(L["workloads"]):
        r, c = divmod(i, 2)
        cx0, cy0 = ix + c * (cw_ + gap), cy + r * (ch + 8)
        d.rect(cx0, cy0, cw_, ch, rx=10, fill="panel", stroke="line2", sw=1.1)
        d.circle(cx0 + 20, cy0 + ch / 2, 11, fill="orangeF")
        d.text(cx0 + 20, cy0 + ch / 2 + 4.5, str(i + 1), 12.5, 700, "onwarm", "middle")
        d.text(cx0 + 40, cy0 + ch / 2 + 5, label, 14.5, 700, "text", box=box)
        d.text(cx0 + cw_ - 12, cy0 + ch / 2 + 4, cid, 11.5, 400, "muted", "end", box=box, family=CODE_FAMILY)
    my = cy + 3 * (ch + 8) + 20
    d.text(ix, my, L["metrics_label"], 13, 700, "muted", box=box)
    tx, ty = ix, my + 10
    for m in L["metrics"]:
        tw_ = rw(m, 13, 700) + 20
        if tx + tw_ > ix + iw:
            tx, ty = ix, ty + 32
        tag(d, tx, ty, m, "blue", 13, 24, 10, box=box)
        tx += tw_ + 8
    gy = ty + 24 + 24
    title, names = L["grade"]
    d.text(ix, gy, title, 13, 700, "muted", box=box)
    gx = ix + rw(title, 13, 700) + 18
    for color, name in zip(("blue", "yellow", "pink"), names):
        d.circle(gx + 6, gy - 4.5, 6, fill=color + "F")
        d.text(gx + 17, gy, name, 13, 400, "text2", box=box)
        gx += 17 + rw(name, 13) + 18


def s4(d, x, y, w, h, L):
    cy = section(d, x, y, w, h, 4, *L["s4"], inline=False)
    box = (x, y, w, h)
    ix, iw = x + 24, w - 48
    rows = L["pages"]
    rh = 40
    tagcol = max(rw(g, 13, 700) for g, _, _ in rows) + 20 + 14
    for i, (g, color, pages) in enumerate(rows):
        top = cy + i * rh
        mid = top + rh / 2
        if i:
            d.line(ix, top, ix + iw, top, stroke="cardline", sw=1)
        tag(d, ix, mid - 12, g, color, 13, 24, 10, box=box)
        cell(d, ix + tagcol, mid, iw - tagcol, pages, 14.5, 19, 400, "text2", box)
    ay = cy + len(rows) * rh + 14
    d.line(ix, ay - 14, ix + iw, ay - 14, stroke="cardline", sw=1)
    d.icon("service/Amazon-Bedrock", ix, ay, 40)
    d.text(ix + 52, ay + 17, L["ai"][0], 15, 700, "text", box=box)
    d.text(ix + 52, ay + 36, L["ai"][1], 13, 400, "text2", box=box)


def landscape(theme, lang):
    L = T[lang]
    d = Doc(1920, 1080, theme)
    d.rect(0, 0, 1920, 1080, fill="bg")
    header(d, 48, 76, L["title"], L["sub_en"], L["sub_ko"])
    kpis(d, 48, 140, 1824, 92, L)
    s1(d, 48, 252, 820, 792, L)
    s2(d, 888, 252, 984, 392, L)
    s3(d, 888, 664, 530, 380, L)
    s4(d, 1438, 664, 434, 380, L)
    footer_note(d, 1872, 1064, L["note"])
    return d.svg()


BANNED = "·—–"
POLITE = re.compile(r"(입니다|합니다|됩니다|습니다)")
PLAIN_END = re.compile(r"다[.!?]?$")
QUESTION = re.compile(r"(\?|[는은인린한된할을]가|[가-힣]나)$")


def lint(svg, lang):
    """슬라이드 문구 규칙: 가운뎃점과 긴 대시 금지, 한국어는 명사형 종결, 질문형 제목 금지."""
    s = re.sub(r'href="data:[^"]+"', "", svg)
    issues = []
    for t in re.findall(r"<text[^>]*>(.*?)</text>", s, flags=re.S):
        t = html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
        if any(ch in t for ch in BANNED):
            issues.append(("banned-char", t))
        if lang == "ko" and (POLITE.search(t) or PLAIN_END.search(t)):
            issues.append(("ending", t))
        if lang == "ko" and QUESTION.search(t):
            issues.append(("question", t))
    return issues


if __name__ == "__main__":
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for lang in ("en", "ko"):
        for theme in ("light", "dark"):
            svg = landscape(theme, lang)
            (out / f"infographic-{lang}-{theme}.svg").write_text(svg, encoding="utf-8")
            issues = lint(svg, lang)
            bad += len(issues)
            print(f"infographic-{lang}-{theme}.svg: lint {len(issues)}")
            for it in issues:
                print("   ", it)
    sys.exit(1 if bad else 0)
