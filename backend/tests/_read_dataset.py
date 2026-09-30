"""읽기 조회 테스트가 함께 쓰는 고정 시계 SQLite 데이터셋 — 2026-09-30 /analysis OOM 회귀 테스트.

tests/test_read_scan_bounds.py의 v2.32.0 응답 골든(fixtures/read_goldens_v2320.json)이 이 데이터셋에서 나왔다.
값을 바꾸면 골든이 달라지므로 응답을 의도적으로 바꾸는 변경이 아니면 고치지 않는다. 시각은 FROZEN_NOW 기준이고,
행은 오래된 것부터 넣는다(id 순서 = 시각 순서). pytest가 모으지 않는 공용 모듈이다(파일 이름이 test_로 시작하지 않는다).
"""

from datetime import datetime, timedelta, timezone

import models
from pricing_sources import EPOCH

FROZEN_NOW = datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)
CATEGORIES = ("chat-short", "reasoning", "code-gen", "summarize", "structured", "translate")

G = ("global.anthropic.claude-sonnet-5", "Bedrock Claude Sonnet 5 (Global)")
G_STALE_LABEL = "Bedrock Claude Sonnet 5 (global)"  # 500h 이전 행의 옛 라벨 — stats는 카탈로그 라벨을 쓴다
US = ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "Bedrock Claude Haiku 4.5 (US)")
IR = ("bedrock:ap-northeast-2:anthropic.claude-opus-5", "Bedrock Claude Opus 5 (ap-northeast-2)")
CP = ("anthropic:claude-sonnet-5", "Anthropic Claude Sonnet 5 (US)")
# 같은 라벨, 다른 id — model_name 정렬 동률. 옛 id(A)는 100h 이전, 새 id(B)는 그 뒤에만 있다.
TWIN_A = ("anthropic:claude-haiku-4-5", "Anthropic Claude Haiku 4.5 (US)")
TWIN_B = ("anthropic:claude-haiku-4-5-20251001", "Anthropic Claude Haiku 4.5 (US)")
OA = ("openai:us-east-1:openai.gpt-6.1-sol", "OpenAI GPT 6.1 Sol (us-east-1)")
OG = ("openai:global:global.openai.gpt-6.1-sol", "OpenAI GPT 6.1 Sol (Global)")
ODD = ("mystery.model-v9", "weird-label")  # 라벨 형식 밖(reliability "Other"), 단가 없음
HIDDEN = ("openai:1p:gpt-5.4", "OpenAI GPT 5.4 (1P)")  # 조회에서 숨김
RENAMED = ("mystery.model-v8", None)  # 카탈로그 밖 id, 13h 이전은 옛 라벨
RENAMED_OLD, RENAMED_NEW = "Bedrock Mystery 8 (Global)", "Bedrock Mystery 8b (Global)"
MODELS = (G, US, IR, CP, TWIN_A, TWIN_B, OA, OG, ODD, HIDDEN, RENAMED)
CATALOG = {G[0]: G[1], US[0]: US[1], IR[0]: IR[1]}  # results/stats 라벨 기준(prober.AVAILABLE_MODELS 대역)

# 오래된 것부터 넣는다 — id 순서 = 시각 순서. 창 경계(6h, 24h, 7d = 168h, 30d = 720h) 양쪽에 행이 있다.
OFFSETS_H = (960, 725, 719, 500, 300, 170, 160, 100, 50, 30, 23, 20, 13, 11, 7, 5, 3, 2, 1, 0.25)
STOP_REASONS = ("end_turn", "endTurn", "max_tokens", "END-TURN", None, "tool_use", "maxTokens", "",
                "stop_sequence", "weird_reason", "end_turn", "guardrail_intervened", "content_filtered",
                "max_tokens", "end_turn")
OUT_TOKENS = (0, 42, 99, 100, 180, 249, 250, 380, 499, 500, 777, 999, 1000, 1500, 1999, 2000, 3100,
              3999, 4000, 5200, 512, 512, 80, 80, 400)
ERRORS = ("ThrottlingException: Rate exceeded", "ServiceUnavailableException", None,
          "ModelStreamErrorException: stream broke", "Connection reset by peer",
          "WallClockTimeout: probe exceeded 90s wall-clock", "Model is overloaded", "weird failure",
          "Internal server error (500)")


class FrozenDatetime(datetime):
    """라우터 모듈의 datetime.now만 FROZEN_NOW로 고정한다(나머지는 datetime 그대로)."""

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW.astimezone(tz) if tz is not None else FROZEN_NOW.replace(tzinfo=None)


def row_values(k: int, i: int, j: int, model: tuple) -> dict:
    """행 번호 k(전체), 시각 번호 i, 모델 번호 j로 정한 결정적 값."""
    offset = OFFSETS_H[i]
    model_id, label = model
    if model is G and offset >= 500:
        label = G_STALE_LABEL
    if model is RENAMED:
        label = RENAMED_OLD if offset >= 13 else RENAMED_NEW
    status = "error" if k % 9 == 4 else ("overloaded" if k % 13 == 6 else "success")
    ok = status == "success"
    ttft = None if k % 11 == 2 else round(300 + 17.3 * ((k * 7) % 41), 1)
    total = None if k % 14 == 5 else round((ttft or 250.0) + 900.5 + 13.1 * (k % 17), 1)
    out_tok = OUT_TOKENS[(k * 7 + i * 3) % len(OUT_TOKENS)]
    if k % 19 == 7:
        out_tok = None
    elif k % 23 == 11:
        out_tok = -1
    return dict(
        run_id=2 if i >= 17 and j in (0, 3) else 1,
        model_id=model_id,
        model_name=label,
        timestamp=FROZEN_NOW - timedelta(hours=offset),
        prompt=f"prompt {k} " + "x" * 200,
        status=status,
        ttft_ms=ttft if ok else None,
        total_latency_ms=total if ok else None,
        server_latency_ms=(None if k % 5 == 1 else round(total * 0.8, 2)) if ok and total else None,
        input_tokens=(500 + 37 * (k % 29)) if ok else None,
        output_tokens=out_tok if ok else None,
        tps=(None if k % 12 == 9 else round(20 + 3.7 * (k % 23), 2)) if ok else None,
        output_text=f"output {k} " + "y" * 400 if ok else None,
        error_message=None if ok else ERRORS[(k * 5 + i) % len(ERRORS)],
        category=None if k % 17 == 3 else CATEGORIES[(i + j) % len(CATEGORIES)],
        stop_reason=STOP_REASONS[(k * 4 + i) % len(STOP_REASONS)] if ok else None,
    )


def seed(factory) -> None:
    with factory() as db:
        db.add(models.ProbeRun(id=1, prompt="auto", status="completed", is_auto=1, created_at=FROZEN_NOW))
        db.add(models.ProbeRun(id=2, prompt="manual", status="completed", is_auto=0, created_at=FROZEN_NOW))
        prices = {G[0]: (2.0, 10.0), US[0]: (1.1, 5.5), IR[0]: (5.5, 27.5), CP[0]: (2.0, 10.0),
                  TWIN_A[0]: (1.0, 5.0), TWIN_B[0]: (1.0, 5.0), OA[0]: (2.2, 11.0), OG[0]: (2.0, 10.0),
                  HIDDEN[0]: (2.75, 16.5)}
        for model_id, (inp, out) in prices.items():
            db.add(models.PriceHistory(model_id=model_id, family_key="test", channel="global",
                                       input_per_mtok=inp, output_per_mtok=out, effective_from=EPOCH,
                                       source_id="seed", status="seed", observed_at=None))
        # 창 안의 단가 변경 — 12시간 전부터 G는 $3/$15
        change_at = FROZEN_NOW - timedelta(hours=12)
        db.add(models.PriceHistory(model_id=G[0], family_key="test", channel="global", input_per_mtok=3.0,
                                   output_per_mtok=15.0, effective_from=change_at, source_id="offer:test",
                                   status="verified", observed_at=change_at))
        db.commit()
        k = 0
        for i, offset in enumerate(OFFSETS_H):
            for j, model in enumerate(MODELS):
                if (model is TWIN_A and offset < 100) or (model is TWIN_B and offset >= 100):
                    continue
                db.add(models.ProbeResult(**row_values(k, i, j, model)))
                k += 1
        db.commit()
