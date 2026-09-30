"""tests/_golden_compare.py의 비교 규칙 고정 — PR #70 CI(Python 3.11) 골든 실패 후속.

골든(fixtures/read_goldens_v2320.json, insights_prompts_v2320.json)은 운영 런타임 Python 3.11에서 만들었다. 3.12의
내장 sum()은 float을 Neumaier 보정 합산으로 더해 평균이 round(…, 2) 뒤 0.01씩 갈라진다(예: 63.47과 63.48). 비교 도우미는
3.11에서는 바이트 단위로, 다른 버전에서는 float의 마지막 자리 한 단위만 받는다. 이 모듈은 그 허용이 넓어지지 않았는지
(두 단위, 소수 한 자리 값, 정수, 키 순서, 문자열, 프롬프트의 JSON 블록 밖 숫자) 버전과 상관없이 고정한다.
"""

import json

import pytest

from tests import _golden_compare as gc


@pytest.fixture()
def off_golden_python(monkeypatch):
    """3.12처럼 허용 규칙을 쓰는 버전으로 돈다."""
    monkeypatch.setattr(gc, "ON_GOLDEN_PYTHON", False)


@pytest.fixture()
def on_golden_python(monkeypatch):
    monkeypatch.setattr(gc, "ON_GOLDEN_PYTHON", True)


@pytest.mark.parametrize(("a", "b"), [
    (63.47, 63.48), (1506.23, 1506.22), (676.28, 676.27), (1474.8, 1474.81),  # PR #70 CI의 차이, 끝자리 0 생략
    (0.1234, 0.1235), (0.000123, 0.000124), (0.12, 0.13), (20.0, 20.01), (5.0, 5.0),
])
def test_floats_within_one_unit_of_the_last_decimal_are_close(a, b):
    assert gc.floats_close(a, b) and gc.floats_close(b, a)


@pytest.mark.parametrize(("a", "b"), [
    (63.47, 63.49),      # 두 단위
    (1474.8, 1474.9),    # 둘 다 소수 한 자리로 보이면 한 단위가 0.1 — 받지 않는다
    (33.3, 33.4),        # 소수 한 자리 값(백분율, mean)은 정확히
    (20.0, 21.0),
    (0.1234, 0.1236),    # 소수 넷째 자리 두 단위
    (0.123, 0.1245),     # 더 긴 자릿수(넷째)의 한 단위를 넘는다
    (1e16, 1.0000000000000002e16),
    (float("inf"), 1e308), (float("nan"), float("nan")),
])
def test_floats_further_apart_or_with_fewer_decimals_are_not_close(a, b):
    assert not gc.floats_close(a, b) and not gc.floats_close(b, a)


@pytest.mark.parametrize(("got", "golden"), [
    ({"b": 1, "a": 2}, {"a": 2, "b": 1}),                 # 키 순서
    ({"a": 1}, {"a": 1, "b": 2}),                         # 키 집합
    ([1, 2], [2, 1]),                                     # list 순서
    ([1.0, 2.0], [1.0, 2.0, 3.0]),                        # list 길이
    ({"n": 5}, {"n": 6}),                                 # int는 정확히
    ({"n": 5}, {"n": 5.0}),                               # int와 float 구분
    ({"v": None}, {"v": 0.0}),
    ({"ok": True}, {"ok": 1}),                            # bool과 int 구분
    ({"name": "GPT 6.1 Sol"}, {"name": "GPT 6.2 Sol"}),   # 문자열 안의 숫자도 정확히
    ({"avg": 63.47}, {"avg": 63.49}),
])
def test_structure_strings_ints_and_order_stay_exact(off_golden_python, got, golden):
    with pytest.raises(AssertionError):
        gc.assert_matches_golden(got, golden)


def test_last_digit_float_difference_passes_off_the_golden_python_only(off_golden_python, monkeypatch):
    got = {"families": [{"family": "Claude Sonnet 5", "avg_tps": 63.48, "samples": 12, "p95": None}]}
    golden = {"families": [{"family": "Claude Sonnet 5", "avg_tps": 63.47, "samples": 12, "p95": None}]}
    gc.assert_matches_golden(got, golden)
    monkeypatch.setattr(gc, "ON_GOLDEN_PYTHON", True)  # 운영 런타임(3.11)에서는 바이트 단위
    with pytest.raises(AssertionError):
        gc.assert_matches_golden(got, golden)
    gc.assert_matches_golden(golden, json.loads(json.dumps(golden)))


def _prompt(label: str, stats: dict, indent: int = 2) -> str:
    block = json.dumps(stats, ensure_ascii=False, indent=indent)
    return f"다음은 최근 {label} 동안의 통계입니다.\n\n```json\n{block}\n```\n\n출력 형식: 마크다운."


_STATS = {"OpenAI GPT 6.1 Sol (Global)": {"total": 5, "error_rate": 0.0, "tps": {"n": 5, "avg": 57.93}}}


def _with_avg(avg: float) -> dict:
    return {"OpenAI GPT 6.1 Sol (Global)": {"total": 5, "error_rate": 0.0, "tps": {"n": 5, "avg": avg}}}


def test_prompt_json_block_float_takes_one_last_digit_unit(off_golden_python):
    gc.assert_prompt_matches_golden(_prompt("6h", _with_avg(57.92)), _prompt("6h", _STATS))
    with pytest.raises(AssertionError):
        gc.assert_prompt_matches_golden(_prompt("6h", _with_avg(57.91)), _prompt("6h", _STATS))


@pytest.mark.parametrize("got", [
    _prompt("7h", _STATS),                                                  # 블록 밖 숫자는 정확히
    _prompt("6h", _STATS, indent=1),                                        # 블록의 서식
    _prompt("6h", {"OpenAI GPT 6.2 Sol (Global)": _STATS["OpenAI GPT 6.1 Sol (Global)"]}),  # 키 안의 숫자
    _prompt("6h", {"OpenAI GPT 6.1 Sol (Global)": {"total": 6, "error_rate": 0.0, "tps": {"n": 5, "avg": 57.93}}}),
    _prompt("6h", _STATS).replace("마크다운", "markdown"),                  # 블록 뒤 텍스트
])
def test_prompt_text_outside_the_float_rule_stays_exact(off_golden_python, got):
    with pytest.raises(AssertionError):
        gc.assert_prompt_matches_golden(got, _prompt("6h", _STATS))


def test_prompt_is_byte_exact_on_the_golden_python(on_golden_python):
    with pytest.raises(AssertionError):
        gc.assert_prompt_matches_golden(_prompt("6h", _with_avg(57.92)), _prompt("6h", _STATS))
    gc.assert_prompt_matches_golden(_prompt("6h", _STATS), _prompt("6h", _STATS))


def test_mask_json_numbers_keeps_string_literals():
    text = '{\n  "GPT 6.1 Sol": {\n    "n": 5,\n    "avg": -57.93,\n    "big": 1e+16\n  }\n}'
    assert gc.mask_json_numbers(text) == '{\n  "GPT 6.1 Sol": {\n    "n": <n>,\n    "avg": <n>,\n    "big": <n>\n  }\n}'


def test_calls_compare_count_keys_and_each_prompt(off_golden_python):
    golden = [{"system": "시스템", "user": _prompt("6h", _STATS)}]
    gc.assert_calls_match_golden([{"system": "시스템", "user": _prompt("6h", _with_avg(57.94))}], golden)
    user = golden[0]["user"]
    for bad in ([], golden * 2, [{"user": user, "system": "시스템"}], [{"system": "시스템!", "user": user}]):
        with pytest.raises(AssertionError):
            gc.assert_calls_match_golden(bad, golden)
