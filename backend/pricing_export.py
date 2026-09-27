"""CSV, Markdown and JSON downloads of the /api/pricing payload (v2.30.0, extra price fields v2.31.0) — pure functions.

Every format keeps the payload's order and footnote numbers (never re-sorted or renumbered) and carries
the disclaimer. Markdown and CSV prices use pricing_payload.price_text (at most 6 decimals, trailing zeros
removed); only the web screen fixes two decimals.

- CSV: one row per cell (tier element) in TIER_KEYS order, the seven extra prices as their own columns (empty
  when the cell has no such price).
- Markdown: one table per provider with that provider's columns (PROVIDER_COLUMNS; each table stands alone, so
  Amazon Nova has no blank first column). A cell is up to three lines joined by <br>: the input / output pair
  with its footnotes, the prompt-caching prices, the long-context prices.
"""

import csv
import io
import json
from datetime import date
from typing import Optional

from pricing_payload import price_text

EXPORT_FORMATS = ("csv", "md", "json")
BOM = chr(0xFEFF)  # UTF-8 BOM so Excel opens the Korean CSV correctly
LANGS = ("ko", "en")

PROVIDER_TITLES = {"anthropic": "Anthropic Claude", "openai": "OpenAI", "amazon": "Amazon Nova"}
TIER_KEYS = ("cp", "openai_list", "global", "us", "in_region")
PROVIDER_COLUMNS: dict[str, tuple[str, ...]] = {
    "anthropic": ("cp", "global", "us", "in_region"),
    "openai": ("openai_list", "global", "us", "in_region"),
    "amazon": ("global", "us", "in_region"),
}
TIER_TITLES: dict[str, dict[str, str]] = {
    "ko": {
        "cp": "Claude Platform on AWS",
        "openai_list": "OpenAI 공식 가격",
        "global": "AWS Bedrock - Global CRIS",
        "us": "AWS Bedrock - US CRIS",
        "in_region": "AWS Bedrock - In Region",
    },
    "en": {
        "cp": "Claude Platform on AWS",
        "openai_list": "OpenAI official price",
        "global": "AWS Bedrock - Global CRIS",
        "us": "AWS Bedrock - US CRIS",
        "in_region": "AWS Bedrock - In Region",
    },
}

CSV_HEADER = ["provider", "family", "channel", "regions", "model_ids", "input_usd_per_1m", "output_usd_per_1m",
              "cache_read_usd_per_1m", "cache_write_usd_per_1m", "cache_write_1h_usd_per_1m",
              "long_input_usd_per_1m", "long_output_usd_per_1m", "long_cache_read_usd_per_1m",
              "long_cache_write_usd_per_1m", "verification", "observed_at", "footnotes", "source_ids"]
CSV_REFERENCE_HEADER = ["reference_n", "reference_id", "kind", "title", "url", "as_of"]

_TEXT = {
    "ko": {
        "title": "비용 단가",
        "unit": "통화와 단위: USD, 1M 토큰당, 입력 / 출력. 둘째 줄은 프롬프트 캐싱, GPT 셋째 줄은 긴 컨텍스트 단가다",
        "generated": "생성 시각",
        "last_sync": "마지막 자동 확인",
        "never": "없음",
        "pending": "검토 대기",
        "model": "모델",
        "unverified": "자동 확인 안 됨",
        "cache_read": "캐시 읽기",
        "cache_write": "쓰기",
        "cache_write_1h": "1시간 쓰기",
        "long": "긴 컨텍스트",
        "notes": "참고 사항",
        "official": "최종 가격은 공식 요금 페이지에서 확인한다",
        "references": "참고 자료",
        "checked": "확인일",
        "fixed_notes": [
            "단가는 USD, 1M 토큰당, Standard 등급 기준이다.",
            "AWS Bedrock - Global CRIS 단가는 같은 모델의 US CRIS, In Region 단가와 다를 수 있다.",
            "캐시 쓰기는 Claude의 5분 캐시, OpenAI 공식 문서의 cache writes, Nova의 캐시 쓰기 단가이고, "
            "1시간 쓰기는 Claude의 1시간 캐시 단가다.",
            "GPT의 긴 컨텍스트 요금은 OpenAI가 정한 짧은 컨텍스트 한도(GPT 5.4, 5.5는 272K)를 넘는 요청에 적용된다.",
            "OpenAI 공식 가격은 OpenAI 직접 API 단가이며 비용 계산에 쓰지 않는다.",
            "캐시와 긴 컨텍스트 단가는 표시만 하며, 비용 화면은 입력과 출력 단가로 계산한다.",
            "batch, flex, priority(fast) 단가는 포함하지 않는다.",
            "비용 화면은 각 프로브 시각의 단가로 계산한다.",
        ],
    },
    "en": {
        "title": "Unit prices",
        "unit": "Currency and unit: USD per 1M tokens, input / output. The second line is prompt caching, "
                "and the third line on GPT rows is long context",
        "generated": "Generated",
        "last_sync": "Last automatic check",
        "never": "none",
        "pending": "Pending review",
        "model": "Model",
        "unverified": "not verified automatically",
        "cache_read": "cache read",
        "cache_write": "write",
        "cache_write_1h": "1h write",
        "long": "long context",
        "notes": "Notes",
        "official": "Confirm final prices on the official pricing pages",
        "references": "References",
        "checked": "checked",
        "fixed_notes": [
            "Prices are in USD per 1M tokens, Standard tier.",
            "AWS Bedrock - Global CRIS prices can differ from the same model's US CRIS and In Region prices.",
            "Cache write is the Claude 5-minute cache price, OpenAI's cache writes price and the Nova cache write "
            "price, and 1h write is the Claude 1-hour cache price.",
            "GPT long-context prices apply to requests above OpenAI's short-context limit (272K for GPT 5.4 and 5.5).",
            "The OpenAI official price is OpenAI's direct API price and is not used for cost calculations.",
            "Cache and long-context prices are shown for reference, and the cost pages use input and output prices.",
            "Batch, flex and priority (fast) prices are not included.",
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


def _optional_text(v: Optional[float]) -> str:
    """price_text, or an empty field when the cell has no such price (0 is a price: "0")."""
    return "" if v is None else price_text(v)


def _cells(family: dict):
    """(tier key, cell) in TIER_KEYS order: cp, openai_list, global, us, then each in_region element."""
    for tier in TIER_KEYS[:-1]:
        if family["tiers"].get(tier) is not None:
            yield tier, family["tiers"][tier]
    for element in family["tiers"]["in_region"]:
        yield "in_region", element


def to_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _cache_line(cell: dict, t: dict) -> Optional[str]:
    """Line 2: "캐시 읽기 0.2, 쓰기 5, 1시간 쓰기 8" with only the prices the cell has, or None."""
    items = [f"{t[key]} {price_text(cell[key])}" for key in ("cache_read", "cache_write", "cache_write_1h")
             if cell.get(key) is not None]
    return ", ".join(items) if items else None


def _long_line(cell: dict, t: dict) -> Optional[str]:
    """Line 3 (GPT): "긴 컨텍스트 20 / 75, 캐시 읽기 2, 쓰기 25", or None without long-context prices."""
    long = cell.get("long")
    if long is None:
        return None
    items = [f"{t['long']} {price_text(long['input'])} / {price_text(long['output'])}"]
    items += [f"{t[key]} {price_text(long[key])}" for key in ("cache_read", "cache_write") if long[key] is not None]
    return ", ".join(items)


def _pending_text(cell: dict, t: dict) -> str:
    """What the pending row changes, by the screen's pendingDetail rule: the pair when input or output differs, then
    each cache price that differs (and is set on the pending row), then the pending value's whole long-context line
    when `long` differs; the pair when nothing differs. "9 / 45, 캐시 읽기 0.9, 긴 컨텍스트 18 / 67.5"."""
    new = cell["pending"]
    pair = f"{price_text(new['input'])} / {price_text(new['output'])}"
    items = [pair] if (new["input"], new["output"]) != (cell["input"], cell["output"]) else []
    items += [f"{t[key]} {price_text(new[key])}" for key in ("cache_read", "cache_write", "cache_write_1h")
              if new.get(key) is not None and new.get(key) != cell.get(key)]
    if new.get("long") is not None and new.get("long") != cell.get("long"):
        items.append(_long_line(new, t))
    return ", ".join(items or [pair])


def _md_cell(cell: dict, t: dict) -> str:
    text = f"{price_text(cell['input'])} / {price_text(cell['output'])}"
    if cell.get("regions"):
        text += " " + ", ".join(cell["regions"])
    if cell["verification"] in ("stale", "seed_only"):
        text += f" ({t['unverified']})"
    if cell["pending"] is not None:
        text += f" ({t['pending']} {_pending_text(cell, t)})"
    lines = [text + "".join(f"[^{n}]" for n in cell["footnotes"])]
    lines += [line for line in (_cache_line(cell, t), _long_line(cell, t)) if line is not None]
    return "<br>".join(lines)


def _md_tier(tiers: dict, tier: str, t: dict) -> str:
    if tier == "in_region":
        return "<br><br>".join(_md_cell(e, t) for e in tiers["in_region"]) or "—"
    return _md_cell(tiers[tier], t) if tiers.get(tier) is not None else "—"


def to_markdown(payload: dict, lang: str) -> str:
    t = _TEXT[_lang(lang)]
    titles = TIER_TITLES[lang]
    disclaimer = payload["disclaimer"][lang]
    title_key = f"title_{lang}"
    lines = [f"> {disclaimer}", "", f"# {t['title']}", "", f"- {t['unit']}", f"- {t['generated']}: {payload['generated_at']}"]
    sync = payload["last_sync"]
    lines.append(f"- {t['last_sync']}: " + (f"{sync['finished_at']} ({sync['status']})" if sync else t["never"]))
    if payload["pending_review"] > 0:
        lines.append(f"- {t['pending']}: {payload['pending_review']}")

    provider = None
    columns: tuple[str, ...] = ()
    for family in payload["families"]:
        if family["provider"] != provider:
            provider = family["provider"]
            columns = PROVIDER_COLUMNS.get(provider, TIER_KEYS)
            header = [t["model"], *(titles[c] for c in columns)]
            lines += ["", f"## {PROVIDER_TITLES.get(provider, provider)}", "",
                      "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        row = [family["family"], *(_md_tier(family["tiers"], c, t) for c in columns)]
        lines.append("| " + " | ".join(row) + " |")

    official = [r for r in payload["references"] if r["kind"] == "official_page"]
    notes = [(family, note) for family in payload["families"] for note in family["notes"]]
    ref_n = {r["id"]: r["n"] for r in payload["references"]}
    lines += ["", f"## {t['notes']}", ""]
    items = list(t["fixed_notes"])
    if official:
        # Referenced before the manual notes so Markdown renderers number footnotes in payload order.
        items.append(t["official"] + "".join(f"[^{r['n']}]" for r in official) + ".")
    for family, note in notes:
        items.append(f"{family['family']}: {note[f'text_{lang}']}[^{ref_n[note['source_id']]}]")
    lines += [f"{i}. {item}" for i, item in enumerate(items, start=1)]

    lines += ["", f"## {t['references']}", ""]
    for ref in payload["references"]:
        parts = [ref[title_key]]  # a manual note's title already says "(manual note, …)"
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
            long = cell.get("long") or {}
            writer.writerow([
                family["provider"], family["family"], tier, " ".join(cell.get("regions", [])),
                " ".join(cell["model_ids"]), price_text(cell["input"]), price_text(cell["output"]),
                _optional_text(cell.get("cache_read")), _optional_text(cell.get("cache_write")),
                _optional_text(cell.get("cache_write_1h")), _optional_text(long.get("input")),
                _optional_text(long.get("output")), _optional_text(long.get("cache_read")),
                _optional_text(long.get("cache_write")),
                cell["verification"], cell["observed_at"] or "", " ".join(str(n) for n in cell["footnotes"]),
                " ".join(cell["source_ids"]),
            ])
    writer.writerow([])
    writer.writerow(CSV_REFERENCE_HEADER)
    for ref in payload["references"]:
        writer.writerow([ref["n"], ref["id"], ref["kind"], ref[f"title_{lang}"], ref["url"] or "", ref["as_of"] or ""])
    return buf.getvalue()
