"""이상 징후 요약 (v2.12.0) — 최근 N시간 프로브 실패를 모델별로 집계하는 순수 로직."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anomalies import summarize_anomalies  # noqa: E402

T = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def test_no_failures_returns_zero_summary():
    rows = [("Bedrock Claude Haiku 4.5 (US)", "success", None, T)]
    s = summarize_anomalies(rows)
    assert s["total_failures"] == 0
    assert s["total_probes"] == 1
    assert s["models"] == []


def test_failures_grouped_by_model_sorted_desc_with_last_error():
    rows = [
        ("A", "error", "throttled", datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)),
        ("A", "error", "timeout", datetime(2026, 7, 11, 11, 0, tzinfo=timezone.utc)),
        ("A", "success", None, T),
        ("B", "error", "500", T),
    ]
    s = summarize_anomalies(rows)
    assert s["total_failures"] == 3
    assert s["total_probes"] == 4
    assert [m["model_name"] for m in s["models"]] == ["A", "B"]  # 실패 많은 순
    a = s["models"][0]
    assert a["failures"] == 2 and a["total"] == 3
    assert a["last_error"] == "timeout"  # 가장 최근 실패의 오류
