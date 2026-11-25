#!/usr/bin/env python3
"""README 아키텍처 다이어그램 SVG를 만든다 (EN, KO).

사용: AWS_ICON_BUNDLE=<aws-diagram 스킬>/assets/icons.json python3 architecture.py <en|ko> <out.svg>
아이콘은 번들에서 읽어 data URI로 넣으므로 결과 SVG는 외부 파일 없이 열린다.
채널 수나 예약 태스크가 바뀌면 아래 T의 문구를 고치고 build.sh로 다시 만든다.
"""
import base64
import html
import json
import os
import sys

LANG = sys.argv[1]
OUT = sys.argv[2]
VERSION = "v2.45"
BUNDLE = json.load(open(os.environ["AWS_ICON_BUNDLE"], encoding="utf-8"))["sets"]

W, H = 1440, 1070
INK = "#232F3E"
GRAY = "#545B64"
TEAL = "#00A4A6"
GREEN = "#7AA116"
ORANGE = "#ED7100"
LINE = "#D5DBDB"

T = {
    "title": {"en": "Amazon Bedrock LLM Monitor: production architecture",
              "ko": "Amazon Bedrock LLM Monitor 운영 아키텍처"},
    "subtitle": {"en": f"{VERSION}, 51 monitored channels, 8 CDK stacks, deployed in ap-northeast-2 (Seoul)",
                 "ko": f"{VERSION}, 모니터링 51채널, CDK 스택 8개, 서울 리전(ap-northeast-2) 배포"},
    "users": {"en": "Users", "ko": "사용자"},
    "users_s1": {"en": "Browser", "ko": "브라우저"},
    "users_s2": {"en": "iPhone, iPad PWA", "ko": "iPhone, iPad PWA"},
    "cf_s1": {"en": "viewer TLS 1.2", "ko": "뷰어 TLS 1.2"},
    "cf_s2": {"en": "VPC Origin, HTTP 80", "ko": "VPC Origin, HTTP 80"},
    "region_seoul": {"en": "Region: ap-northeast-2 (Seoul)", "ko": "리전: ap-northeast-2 (서울)"},
    "app_subnets": {"en": "App subnets (private)", "ko": "App 서브넷 (프라이빗)"},
    "data_subnets": {"en": "Data subnets", "ko": "Data 서브넷"},
    "public_subnets": {"en": "Public subnets", "ko": "퍼블릭 서브넷"},
    "alb": {"en": "Internal ALB", "ko": "내부 ALB"},
    "alb_s": {"en": "ports 443, 80", "ko": "포트 443, 80"},
    "cluster": {"en": "Amazon ECS cluster on AWS Fargate", "ko": "Amazon ECS 클러스터 (AWS Fargate)"},
    "fe": {"en": "frontend service", "ko": "frontend 서비스"},
    "fe_s": {"en": "Next.js 16, port 3000, 11 monitoring pages", "ko": "Next.js 16, 포트 3000, 모니터링 화면 11개"},
    "be": {"en": "backend service", "ko": "backend 서비스"},
    "be_s": {"en": "FastAPI, port 8000, REST and SSE, chatbot", "ko": "FastAPI, 포트 8000, REST와 SSE, 챗봇"},
    "tasks": {"en": "Scheduled Fargate tasks ×7 (backend image)", "ko": "예약 Fargate 태스크 7개 (backend 이미지)"},
    "t_auto": {"en": "every 5 min, 51 channels", "ko": "5분마다, 51채널"},
    "t_ins": {"en": "every 5 min, KO and EN", "ko": "5분마다, 한국어와 영어"},
    "t_bench": {"en": "every 15 min, 23 channels", "ko": "15분마다, 23채널"},
    "t_parity": {"en": "every 12 h, 6 surfaces", "ko": "12시간마다, surface 6개"},
    "t_price": {"en": "every 12 h, 4 sources", "ko": "12시간마다, 출처 4곳"},
    "t_feat": {"en": "daily 17:30 UTC, 1,365 cells", "ko": "매일 17:30 UTC, 1,365셀"},
    "t_expl": {"en": "daily 18:00 UTC, 83 examples", "ko": "매일 18:00 UTC, 예제 83건"},
    "rds_s1": {"en": "PostgreSQL 16", "ko": "PostgreSQL 16"},
    "rds_s2": {"en": "t4g.micro", "ko": "t4g.micro"},
    "rds_s3": {"en": "Single-AZ", "ko": "단일 AZ"},
    "nat": {"en": "NAT gateway", "ko": "NAT 게이트웨이"},
    "sched_s": {"en": "7 schedules", "ko": "스케줄 7개"},
    "runtask": {"en": "RunTask", "ko": "RunTask"},
    "vpce": {"en": "VPC endpoint", "ko": "VPC 엔드포인트"},
    "via_nat": {"en": "HTTPS egress through the NAT gateway", "ko": "NAT 게이트웨이를 거치는 HTTPS 외부 호출"},
    "br_seoul": {"en": "Amazon Bedrock Runtime", "ko": "Amazon Bedrock Runtime"},
    "br_seoul_1": {"en": "Claude Global CRIS ×7, Seoul in-region ×2", "ko": "Claude Global CRIS 7, 서울 in-region 2"},
    "br_seoul_2": {"en": "OpenAI GPT Global CRIS ×10 (/openai/v1)", "ko": "OpenAI GPT Global CRIS 10 (/openai/v1)"},
    "br_seoul_3": {"en": "Claude Haiku 5.5: chatbot, AI insights", "ko": "Claude Haiku 5.5: 챗봇, AI 인사이트"},
    "ecr_s": {"en": "digest-pinned images", "ko": "digest 고정 이미지"},
    "ssm_l2": {"en": "Parameter Store", "ko": "Parameter Store"},
    "ssm_s": {"en": "API keys, JWT key", "ko": "API 키, JWT 키"},
    "sm_s": {"en": "DB credentials", "ko": "DB 자격 증명"},
    "mem_s": {"en": "chatbot memory, 30 days", "ko": "챗봇 대화 기억, 30일"},
    "cw_s": {"en": "logs, 7 alarms, SNS", "ko": "로그, 알람 7개, SNS"},
    "region_use1": {"en": "Region: us-east-1 (N. Virginia)", "ko": "리전: us-east-1 (버지니아 북부)"},
    "region_use2": {"en": "Region: us-east-2 (Ohio)", "ko": "리전: us-east-2 (오하이오)"},
    "br_us": {"en": "Amazon Bedrock Runtime", "ko": "Amazon Bedrock Runtime"},
    "br_us_1": {"en": "Claude US CRIS ×7, Nova 2.0 Lite ×1", "ko": "Claude US CRIS 7, Nova 2.0 Lite 1"},
    "br_us_2": {"en": "OpenAI GPT US CRIS ×7 (/openai/v1)", "ko": "OpenAI GPT US CRIS 7 (/openai/v1)"},
    "br_us_3": {"en": "OptimizePrompt for /prompts", "ko": "/prompts의 OptimizePrompt"},
    "mantle": {"en": "Amazon Bedrock Mantle", "ko": "Amazon Bedrock Mantle"},
    "mantle_1": {"en": "OpenAI GPT in-region ×10 (/openai/v1)", "ko": "OpenAI GPT 인리전 10 (/openai/v1)"},
    "mantle_2": {"en": "/anthropic: parity, Claude API Features", "ko": "/anthropic: 패리티, Claude API 기능"},
    "priceapi": {"en": "Price catalogs for PricingSync", "ko": "PricingSync가 읽는 단가 카탈로그"},
    "priceapi_1": {"en": "Bedrock agreement offers,", "ko": "Bedrock 약정 오퍼,"},
    "priceapi_2": {"en": "AWS Price List API", "ko": "AWS Price List API"},
    "ses_s": {"en": "sign-up approval e-mail", "ko": "가입 승인 메일"},
    "cp": {"en": "Claude Platform on AWS", "ko": "Claude Platform on AWS"},
    "cp_1": {"en": "Anthropic Messages API ×7", "ko": "Anthropic Messages API 7"},
    "cp_2": {"en": "workspace ID header", "ko": "workspace ID 헤더"},
    "sum_title": {"en": "51 monitored channels", "ko": "모니터링 51채널"},
    "sum_1": {"en": "Amazon Bedrock (Claude, Nova)", "ko": "Amazon Bedrock (Claude, Nova)"},
    "sum_1s": {"en": "Global CRIS 7, US CRIS 8, Seoul in-region 2", "ko": "Global CRIS 7, US CRIS 8, 서울 in-region 2"},
    "sum_2": {"en": "OpenAI GPT on Bedrock", "ko": "OpenAI GPT on Bedrock"},
    "sum_2s": {"en": "Mantle us-east-1 10, Global CRIS 10, US CRIS 7", "ko": "Mantle us-east-1 10, Global CRIS 10, US CRIS 7"},
    "sum_3": {"en": "Claude Platform on AWS", "ko": "Claude Platform on AWS"},
    "sum_3s": {"en": "Messages API in us-east-2", "ko": "us-east-2의 Messages API"},
    "ext": {"en": "Official price pages (outside AWS)", "ko": "공식 요금 문서 (AWS 밖)"},
    "ext_1": {"en": "Anthropic pricing.md, OpenAI pricing.md", "ko": "Anthropic pricing.md, OpenAI pricing.md"},
    "note": {"en": "Not drawn: S3 access-log buckets, KMS keys, the RUM pipeline.",
             "ko": "그리지 않은 것: S3 액세스 로그 버킷, KMS 키, RUM 파이프라인."},
}


def t(key: str) -> str:
    return html.escape(T[key][LANG])


def uri(ref: str) -> str:
    """번들 아이콘(set/name)을 data URI로 바꾼다. 이름은 aws-diagram 스킬의 find_icon.py로 찾는다."""
    setname, name = ref.split("/", 1)
    e = BUNDLE[setname][name]
    if e["type"] == "svg":
        return "data:image/svg+xml;base64," + base64.b64encode(e["data"].encode("utf-8")).decode("ascii")
    return "data:image/png;base64," + e["data"]


out: list[str] = []
add = out.append


def text(x, y, s, size=12, fill=INK, weight=None, anchor=None, halo=False):
    attrs = [f'x="{x}"', f'y="{y}"', f'font-size="{size}"', f'fill="{fill}"']
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    if halo:
        attrs.append('paint-order="stroke" stroke="#FFFFFF" stroke-width="4" stroke-linejoin="round"')
    add(f"<text {' '.join(attrs)}>{s}</text>")


def group(x, y, w, h, stroke, label, icon=None, fill="none", dash=None, label_fill=None, sw=2):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')
    tx = x + 12
    if icon:
        add(f'<image href="{uri(icon)}" x="{x + 10}" y="{y + 9}" width="24" height="24"/>')
        tx = x + 42
    text(tx, y + 26, label, 13, label_fill or stroke, 600)


def node(cx, y, icon, label, subs=(), size=56, label2=None):
    """아이콘 위, 라벨 아래 (가운데 정렬)."""
    add(f'<image href="{uri(icon)}" x="{cx - size / 2}" y="{y}" width="{size}" height="{size}"/>')
    ty = y + size + 17
    text(cx, ty, label, 13, INK, 600, "middle")
    if label2:
        ty += 16
        text(cx, ty, label2, 13, INK, 600, "middle")
    for s in subs:
        ty += 15
        text(cx, ty, s, 11.5, GRAY, None, "middle")


def card(x, y, w, h, icon, title, lines, size=44, tag=None):
    """아이콘 왼쪽, 글 오른쪽."""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#FFFFFF" stroke="{LINE}" stroke-width="1.5"/>')
    add(f'<image href="{uri(icon)}" x="{x + 12}" y="{y + (h - size) / 2}" width="{size}" height="{size}"/>')
    tx = x + 12 + size + 12
    n = len(lines)
    ty = y + h / 2 - (n * 15) / 2 + 2
    text(tx, ty, title, 13, INK, 600)
    if tag:
        text(x + w - 12, ty, tag, 11, TEAL, 600, "end")
    for s in lines:
        ty += 15.5
        text(tx, ty, s, 11.5, GRAY)


def arrow(d, label=None, lx=None, ly=None, anchor="middle", dash=None):
    ds = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="1.6"{ds} marker-end="url(#arrow)"/>')
    if label:
        text(lx, ly, label, 11.5, GRAY, 600, anchor, halo=True)


def line(d):
    add(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="1.6"/>')


add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
    f'font-family="\'Amazon Ember\', Arial, \'Pretendard\', \'Noto Sans KR\', \'Noto Sans CJK KR\', '
    f'\'Apple SD Gothic Neo\', \'Malgun Gothic\', sans-serif">')
add(f"<title>{t('title')}</title>")
add('<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">'
    f'<path d="M0,0 L8,3 L0,6 Z" fill="{INK}"/></marker></defs>')
add(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#FFFFFF"/>')

# ── 제목 ────────────────────────────────────────────────────────────────
text(32, 40, t("title"), 22, INK, 700)
text(32, 62, t("subtitle"), 13, GRAY)

# ── 컨테이너 ────────────────────────────────────────────────────────────
group(140, 82, 1276, 888, INK, "AWS Cloud", "group/AWS-Cloud_32")
group(300, 122, 740, 832, TEAL, t("region_seoul"), "group/Region_32", dash="6 4")
group(320, 162, 700, 540, GREEN, "VPC", "group/Virtual-private-cloud-VPC_32")
group(340, 202, 510, 480, TEAL, t("app_subnets"), "group/Private-subnet_32", fill="#E6F2F8", sw=1.5)
group(870, 202, 130, 372, TEAL, t("data_subnets"), None, fill="#E6F2F8", sw=1.5)
group(870, 592, 130, 90, GREEN, t("public_subnets"), None, fill="#E9F3E6", sw=1.5)

# ── 사용자, CloudFront, ALB ─────────────────────────────────────────────
node(72, 306, "resource/Users", t("users"), (t("users_s1"), t("users_s2")), size=48)
node(222, 302, "service/Amazon-CloudFront", "Amazon CloudFront", (t("cf_s1"), t("cf_s2")))
node(384, 302, "service/Elastic-Load-Balancing", t("alb"), (t("alb_s"),))
arrow("M 100 330 H 190", "HTTPS", 145, 322)
arrow("M 252 330 H 354")

# ── ECS 클러스터 ────────────────────────────────────────────────────────
add(f'<rect x="470" y="238" width="365" height="430" rx="8" fill="#FFFFFF" stroke="{ORANGE}" stroke-width="1.5"/>')
add(f'<image href="{uri("service/Amazon-Elastic-Container-Service")}" x="480" y="246" width="22" height="22"/>')
text(510, 262, t("cluster"), 12.5, "#C45500", 600)

card(486, 278, 333, 58, "service/AWS-Fargate", t("fe"), (t("fe_s"),), size=40)
card(486, 348, 333, 58, "service/AWS-Fargate", t("be"), (t("be_s"),), size=40)

# ALB → frontend, backend
line("M 414 330 H 428")
arrow("M 428 330 V 307 H 484", "/*", 449, 300, "middle")
arrow("M 428 330 V 377 H 484", "/api/*", 449, 393, "middle")

# 예약 태스크 상자
add(f'<rect x="486" y="424" width="333" height="230" rx="8" fill="#FFF8F0" stroke="{ORANGE}" stroke-width="1.2" stroke-dasharray="5 3"/>')
add(f'<image href="{uri("service/AWS-Fargate")}" x="496" y="432" width="22" height="22"/>')
text(526, 448, t("tasks"), 12.5, INK, 600)
entries = [
    ("AutoProber", "t_auto"), ("Insights", "t_ins"), ("GptBench", "t_bench"), ("ParityRun", "t_parity"),
    ("PricingSync", "t_price"), ("FeaturesVerify", "t_feat"), ("ExplorerVerify", "t_expl"),
]
for i, (name, key) in enumerate(entries):
    y = 478 + i * 25
    text(502, y, name, 12.5, INK, 600)
    text(612, y, t(key), 11.5, GRAY)

# ── RDS, NAT ────────────────────────────────────────────────────────────
node(935, 414, "service/Amazon-RDS", "Amazon RDS", (t("rds_s1"), t("rds_s2"), t("rds_s3")))
arrow("M 819 377 H 935 V 412")
arrow("M 819 442 H 905")
add(f'<rect x="884" y="630" width="102" height="34" rx="6" fill="#FFFFFF" stroke="{GREEN}" stroke-width="1.5"/>')
text(935, 652, t("nat"), 12, INK, 600, "middle")
arrow("M 835 647 H 882")

# ── 서울 리전 서비스 ────────────────────────────────────────────────────
card(470, 738, 365, 84, "service/Amazon-Bedrock", t("br_seoul"),
     (t("br_seoul_1"), t("br_seoul_2"), t("br_seoul_3")), size=48)
arrow("M 720 668 V 736", t("vpce"), 728, 718, "start")

node(384, 730, "service/Amazon-EventBridge", "Amazon EventBridge", (t("sched_s"),), size=48, label2="Scheduler")
arrow("M 384 728 V 540 H 484", t("runtask"), 392, 712, "start")

# 지원 서비스 줄
node(384, 852, "service/Amazon-Elastic-Container-Registry", "Amazon ECR", (t("ecr_s"),), size=44)
node(530, 852, "service/AWS-Systems-Manager", t("ssm_l2"), (t("ssm_s"),), size=44)
node(676, 852, "service/AWS-Secrets-Manager", "AWS Secrets Manager", (t("sm_s"),), size=44)
node(822, 852, "agentcore-dark/Memory", "AgentCore Memory", (t("mem_s"),), size=44)
node(968, 852, "service/Amazon-CloudWatch", "Amazon CloudWatch", (t("cw_s"),), size=44)

# ── 다른 리전 ───────────────────────────────────────────────────────────
group(1086, 122, 318, 408, TEAL, t("region_use1"), "group/Region_32", dash="6 4")
card(1100, 164, 290, 84, "service/Amazon-Bedrock", t("br_us"), (t("br_us_1"), t("br_us_2"), t("br_us_3")), size=44)
card(1100, 260, 290, 70, "service/Amazon-Bedrock", t("mantle"), (t("mantle_1"), t("mantle_2")), size=44)
card(1100, 342, 290, 84, "resource/Data-Table", t("priceapi"), (t("priceapi_1"), t("priceapi_2")), size=40)
card(1100, 438, 290, 76, "service/Amazon-Simple-Email-Service", "Amazon SES", (t("ses_s"),), size=40)

group(1086, 546, 318, 132, TEAL, t("region_use2"), "group/Region_32", dash="6 4")
card(1100, 588, 290, 74, "category/Artificial-Intelligence", t("cp"), (t("cp_1"), t("cp_2")), size=44)

# 채널 요약
add(f'<rect x="1086" y="694" width="318" height="260" rx="8" fill="#F7F8F9" stroke="{LINE}" stroke-width="1.5"/>')
text(1102, 722, t("sum_title"), 15, INK, 700)
rows = [("17", "sum_1", "sum_1s"), ("27", "sum_2", "sum_2s"), ("7", "sum_3", "sum_3s")]
for i, (num, k1, k2) in enumerate(rows):
    y = 762 + i * 66
    add(f'<rect x="1102" y="{y - 24}" width="46" height="46" rx="8" fill="{INK}"/>')
    text(1125, y + 7, num, 20, "#FFFFFF", 700, "middle")
    text(1160, y - 5, t(k1), 13, INK, 600)
    text(1160, y + 12, t(k2), 11.5, GRAY)

# ── AWS 밖: 공식 요금 문서 ──────────────────────────────────────────────
card(1086, 990, 318, 62, "resource/Documents", t("ext"), (t("ext_1"),), size=36)

# ── NAT 출구 줄기 ───────────────────────────────────────────────────────
line("M 986 647 H 1060")
line("M 1060 206 V 1021")
for y in (206, 295, 384, 476, 625):
    arrow(f"M 1060 {y} H 1098")
arrow("M 1060 1021 H 1084")
add(f'<text transform="translate(1078 835) rotate(-90)" font-size="11.5" fill="{GRAY}" font-weight="600" '
    f'text-anchor="middle">{t("via_nat")}</text>')

text(32, 1046, t("note"), 11.5, GRAY)
add("</svg>")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")
print(f"wrote {OUT}")
