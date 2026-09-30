"""골든 비교 — Python 3.11과 3.12의 float sum() 마지막 자리 차이만 흡수하고 나머지는 정확히 비교한다.

tests/test_read_scan_bounds.py의 응답 골든(fixtures/read_goldens_v2320.json)과 tests/test_insights_scan_bounds.py의
인사이트 프롬프트 골든(fixtures/insights_prompts_v2320.json)이 쓴다. pytest가 모으지 않는 공용 모듈이다(파일 이름이
test_로 시작하지 않는다).

왜: Python 3.12부터 내장 sum()은 float을 Neumaier 보정 합산으로 더하고, 3.11은 앞에서부터 그냥 더한다. 같은 값 목록의
평균이 마지막 비트에서 갈라져 round(…, 2) 뒤 0.01 차이가 난다(2026-09-30 PR #70 CI — 63.47과 63.48, 1506.23과 1506.22).
운영 이미지(python:3.11-slim)와 CI가 3.11이므로 골든은 3.11에서 v2.32.0(98af18e) 코드로 만들었다(골든 파일은
GOLDEN_PYTHON에서만 다시 만든다).

규칙:
- GOLDEN_PYTHON(3.11)에서 돌 때는 바이트 단위로 같아야 한다(dict 키 순서까지) — 운영 런타임에서는 느슨하게 보지 않는다.
- 다른 버전(로컬 3.12)에서는 구조를 정확히 비교한다: dict 키와 키 순서, list 길이와 순서, str, int, bool, None,
  float과 int의 구분. float만 같거나 "마지막 자리 한 단위" 차이까지 받는다 — 두 값의 표기(repr) 중 더 긴 소수 자릿수 d가
  2 이상이고 |a - b| <= 10**-d일 때다. 소수 한 자리 이하(예: 33.3, 20.0)는 정확히 같아야 한다.
- 프롬프트 텍스트는 ```json 블록 밖을 정확히 비교하고, 블록 안은 숫자를 가린 텍스트를 정확히 비교한 뒤 파싱한 JSON을 위
  규칙으로 비교한다.
- 권위 있는 비교는 3.11의 바이트 비교다(CI가 3.11). 3.12 실행은 확인용이다 — 허용 오차는 3.12 자신의 값 기준이라, 3.12 값이
  이미 골든과 0.01 다른 자리에서는 골든 쪽 두 단위(0.02) 변경이나 합산 순서 변경을 3.12가 놓친다(v2.32.1 리뷰 변이 검사).
  합산 순서나 평균 계산을 건드렸으면 푸시 전에 3.11(docker)에서 돌린다.
"""

from __future__ import annotations

import json
import math
import re
import sys
from decimal import Decimal
from typing import Any

GOLDEN_PYTHON = (3, 11)  # 골든을 만든 파이썬 = 운영 이미지 python:3.11-slim, CI
GOLDEN_PYTHON_LABEL = ".".join(map(str, GOLDEN_PYTHON))
ON_GOLDEN_PYTHON = sys.version_info[:2] == GOLDEN_PYTHON

_FENCE_OPEN = "```json\n"
_FENCE_CLOSE = "\n```"
# JSON 문자열 리터럴 또는 숫자 토큰 — 문자열 안의 숫자(예: "GPT 6.1 Sol")는 가리지 않는다
_JSON_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?')


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decimals(x: float) -> int:
    exponent = Decimal(repr(x)).as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def floats_close(a: float, b: float) -> bool:
    """같거나, 더 긴 소수 자릿수 d가 2 이상이고 차이가 마지막 자리 한 단위(10**-d) 이하."""
    if a == b:
        return True
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    d = max(_decimals(a), _decimals(b))
    return d >= 2 and abs(Decimal(repr(a)) - Decimal(repr(b))) <= Decimal(10) ** -d


def _diff(got: Any, golden: Any, path: str) -> str | None:
    """첫 차이의 설명, 같으면 None."""
    if type(got) is not type(golden):
        return f"{path}: 타입 {type(got).__name__} != {type(golden).__name__} ({got!r} vs {golden!r})"
    if isinstance(golden, dict):
        if list(got) != list(golden):
            return f"{path}: 키(순서 포함) {list(got)} != {list(golden)}"
        for key in golden:
            found = _diff(got[key], golden[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(golden, list):
        if len(got) != len(golden):
            return f"{path}: 길이 {len(got)} != {len(golden)}"
        for i, (g, e) in enumerate(zip(got, golden)):
            found = _diff(g, e, f"{path}[{i}]")
            if found:
                return found
        return None
    if isinstance(golden, float):
        return None if floats_close(got, golden) else f"{path}: {got!r} != {golden!r}"
    return None if got == golden else f"{path}: {got!r} != {golden!r}"


def assert_matches_golden(got: Any, golden: Any, path: str = "$") -> None:
    """JSON 값(응답 body, model_breakdown …)을 골든과 비교한다. 3.11에서는 바이트 단위로 같아야 한다."""
    found = _diff(got, golden, path)
    assert found is None, found
    if ON_GOLDEN_PYTHON:
        assert canonical(got) == canonical(golden), (
            f"{path}: Python {GOLDEN_PYTHON_LABEL}에서는 바이트 단위로 같아야 한다")


def mask_json_numbers(text: str) -> str:
    """JSON 텍스트의 숫자 토큰(문자열 리터럴 밖)을 <n>으로 바꾼다."""
    return _JSON_TOKEN.sub(lambda m: m.group(0) if m.group(0).startswith('"') else "<n>", text)


def _split_json_block(text: str) -> tuple[str, str | None, str]:
    start = text.find(_FENCE_OPEN)
    if start < 0:
        return text, None, ""
    body_start = start + len(_FENCE_OPEN)
    end = text.index(_FENCE_CLOSE, body_start)
    return text[:body_start], text[body_start:end], text[end:]


def assert_prompt_matches_golden(got: str, golden: str, path: str = "prompt") -> None:
    """프롬프트 텍스트 비교 — ```json 블록 밖은 정확히, 블록 안은 숫자를 가린 텍스트를 정확히 + 파싱한 값을 규칙대로."""
    if ON_GOLDEN_PYTHON or not isinstance(got, str) or not isinstance(golden, str):
        assert got == golden, f"{path}: 골든과 바이트 단위로 다르다"  # 3.11 또는 문자열이 아닌 값
        return
    got_head, got_block, got_tail = _split_json_block(got)
    head, block, tail = _split_json_block(golden)
    assert got_head == head, f"{path}: JSON 블록 앞 텍스트가 다르다"
    assert got_tail == tail, f"{path}: JSON 블록 뒤 텍스트가 다르다"
    assert (got_block is None) == (block is None), f"{path}: JSON 블록 유무가 다르다"
    if block is None:
        return
    assert mask_json_numbers(got_block) == mask_json_numbers(block), f"{path}: 숫자 밖의 JSON 텍스트가 다르다"
    assert_matches_golden(json.loads(got_block), json.loads(block), f"{path}.json")


def assert_calls_match_golden(got: list[dict], golden: list[dict], path: str = "calls") -> None:
    """Bedrock 대역이 모은 [{"system", "user"}] 목록 비교."""
    assert len(got) == len(golden), f"{path}: 호출 수 {len(got)} != {len(golden)}"
    for i, (g, e) in enumerate(zip(got, golden)):
        assert list(g) == list(e), f"{path}[{i}]: 키 {list(g)} != {list(e)}"
        for key in e:
            assert_prompt_matches_golden(g[key], e[key], f"{path}[{i}].{key}")
