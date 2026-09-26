"""CSV, Markdown and JSON downloads of the /api/pricing payload (v2.30.0) — pure functions.

Every format keeps the payload's order and footnote numbers (never re-sorted or renumbered) and carries
the disclaimer. Markdown and CSV prices use pricing_payload.price_text (at most 6 decimals, trailing zeros
removed); only the web screen fixes two decimals.
"""

import csv
import io
import json
from datetime import date

from pricing_payload import price_text
from pricing_sources import note_source_id

EXPORT_FORMATS = ("csv", "md", "json")
BOM = chr(0xFEFF)  # UTF-8 BOM so Excel opens the Korean CSV correctly
LANGS = ("ko", "en")

PROVIDER_TITLES = {"anthropic": "Anthropic Claude", "amazon": "Amazon Nova", "openai": "OpenAI"}
TIER_KEYS = ("cp", "global", "us", "in_region")

CSV_HEADER = ["provider", "family", "channel", "regions", "model_ids", "input_usd_per_1m", "output_usd_per_1m",
              "verification", "observed_at", "footnotes", "source_ids"]
CSV_REFERENCE_HEADER = ["reference_n", "reference_id", "kind", "title", "url", "as_of"]

_TEXT = {
    "ko": {
        "title": "비용 단가",
        "unit": "통화와 단위: USD, 1M 토큰당, 입력 / 출력",
        "generated": "생성 시각",
        "last_sync": "마지막 자동 확인",
        "never": "없음",
        "pending": "검토 대기",
        "columns": ["모델", "Claude Platform on AWS", "Global", "US", "In-Region"],
        "unverified": "자동 확인 안 됨",
        "notes": "참고 사항",
        "official": "최종 가격은 공식 요금 페이지에서 확인한다",
        "references": "참고 자료",
        "checked": "확인일",
        "manual": "수동 메모",
        "fixed_notes": [
            "단가는 USD, 1M 토큰당, Standard 등급 입력과 출력 기준이다.",
            "Global 채널 단가는 같은 모델의 US, In-Region 채널과 다를 수 있다.",
            "OpenAI는 입력 272K 이하 기준이다.",
            "캐시, batch, long-context, priority 단가는 포함하지 않는다.",
            "비용 화면은 각 프로브 시각의 단가로 계산한다.",
        ],
    },
    "en": {
        "title": "Unit prices",
        "unit": "Currency and unit: USD per 1M tokens, input / output",
        "generated": "Generated",
        "last_sync": "Last automatic check",
        "never": "none",
        "pending": "Pending review",
        "columns": ["Model", "Claude Platform on AWS", "Global", "US", "In-Region"],
        "unverified": "not verified automatically",
        "notes": "Notes",
        "official": "Confirm final prices on the official pricing pages",
        "references": "References",
        "checked": "checked",
        "manual": "Manual note",
        "fixed_notes": [
            "Prices are in USD per 1M tokens, Standard tier input and output.",
            "Global channel prices can differ from the US and In-Region channels of the same model.",
            "OpenAI prices apply to inputs of 272K tokens or fewer.",
            "Cache, batch, long-context and priority prices are not included.",
            "The cost pages use the price in effect at each probe's time.",
        ],
    },
}


def _lang(lang: str) -> str:
    if lang not in LANGS:
        raise ValueError(f"unsupported lang: {lang!r}")
    return lang


def export_filename(fmt: str, today: date) -> str:
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"unsupported export format: {fmt!r}")
    return f"llm-monitor-unit-prices-{today.isoformat()}.{fmt}"


def _cells(family: dict):
    """(tier key, cell) in display order: cp, global, us, then each in_region element."""
    for tier in TIER_KEYS[:3]:
        if family["tiers"][tier] is not None:
            yield tier, family["tiers"][tier]
    for element in family["tiers"]["in_region"]:
        yield "in_region", element


def to_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _md_cell(cell: dict, t: dict) -> str:
    text = f"{price_text(cell['input'])} / {price_text(cell['output'])}"
    if cell.get("regions"):
        text += " " + ", ".join(cell["regions"])
    if cell["verification"] in ("stale", "seed_only"):
        text += f" ({t['unverified']})"
    if cell["pending"] is not None:
        text += f" ({t['pending']} {price_text(cell['pending']['input'])} / {price_text(cell['pending']['output'])})"
    return text + "".join(f"[^{n}]" for n in cell["footnotes"])


def to_markdown(payload: dict, lang: str) -> str:
    t = _TEXT[_lang(lang)]
    disclaimer = payload["disclaimer"][lang]
    title_key = f"title_{lang}"
    lines = [f"> {disclaimer}", "", f"# {t['title']}", "", f"- {t['unit']}", f"- {t['generated']}: {payload['generated_at']}"]
    sync = payload["last_sync"]
    lines.append(f"- {t['last_sync']}: " + (f"{sync['finished_at']} ({sync['status']})" if sync else t["never"]))
    if payload["pending_review"] > 0:
        lines.append(f"- {t['pending']}: {payload['pending_review']}")

    provider = None
    for family in payload["families"]:
        if family["provider"] != provider:
            provider = family["provider"]
            lines += ["", f"## {PROVIDER_TITLES.get(provider, provider)}", "",
                      "| " + " | ".join(t["columns"]) + " |", "|---|---|---|---|---|"]
        tiers = family["tiers"]
        row = [family["family"]]
        for tier in TIER_KEYS[:3]:
            row.append(_md_cell(tiers[tier], t) if tiers[tier] is not None else "—")
        row.append("<br>".join(_md_cell(e, t) for e in tiers["in_region"]) or "—")
        lines.append("| " + " | ".join(row) + " |")

    official = [r for r in payload["references"] if r["kind"] == "official_page"]
    notes = [(family, note) for family in payload["families"] for note in family["notes"]]
    note_n = {r["id"]: r["n"] for r in payload["references"] if r["kind"] == "manual_note"}
    lines += ["", f"## {t['notes']}", ""]
    items = list(t["fixed_notes"])
    if official:
        # Referenced before the manual notes so Markdown renderers number footnotes in payload order.
        items.append(t["official"] + "".join(f"[^{r['n']}]" for r in official) + ".")
    for family, note in notes:
        items.append(f"{family['family']}: {note[f'text_{lang}']}[^{note_n[note_source_id(note['family_key'])]}]")
    lines += [f"{i}. {item}" for i, item in enumerate(items, start=1)]

    lines += ["", f"## {t['references']}", ""]
    for ref in payload["references"]:
        parts = [ref[title_key] if ref["kind"] != "manual_note" else f"{t['manual']}: {ref[title_key]}"]
        if ref["url"]:
            parts.append(ref["url"])
        if ref["as_of"]:
            parts.append(f"{t['checked']} {ref['as_of']}")
        lines.append(f"[^{ref['n']}]: " + ", ".join(parts))
    lines += ["", f"> {disclaimer}", ""]
    return "\n".join(lines)


def to_csv(payload: dict, lang: str) -> str:
    """UTF-8 BOM (Excel), a "# <disclaimer>" first line, the price rows, a blank line, the references.

    The disclaimer line is one quoted CSV field, so the commas in its text never split it into columns.
    """
    _lang(lang)
    buf = io.StringIO()
    buf.write(BOM)
    csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_ALL).writerow(["# " + payload["disclaimer"][lang]])
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for family in payload["families"]:
        for tier, cell in _cells(family):
            writer.writerow([
                family["provider"], family["family"], tier, " ".join(cell.get("regions", [])),
                " ".join(cell["model_ids"]), price_text(cell["input"]), price_text(cell["output"]),
                cell["verification"], cell["observed_at"] or "", " ".join(str(n) for n in cell["footnotes"]),
                " ".join(cell["source_ids"]),
            ])
    writer.writerow([])
    writer.writerow(CSV_REFERENCE_HEADER)
    for ref in payload["references"]:
        writer.writerow([ref["n"], ref["id"], ref["kind"], ref[f"title_{lang}"], ref["url"] or "", ref["as_of"] or ""])
    return buf.getvalue()
