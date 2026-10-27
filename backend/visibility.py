"""조회 노출 필터 — DB에는 보존하되 API 응답에서 숨길 모델 라벨 (v2.19.1).

2026-07-31 사용자 결정: OpenAI 1P direct(Path 5) 채널을 비교·모니터링 노출에서 제외.
프로브 코드(prober._OPENAI_1P_MODEL_SPECS)와 과거 DB 행은 그대로 보존 — 이 모듈은
읽기 라우터에서만 적용되는 단일 스위치다.

2026-10-27 사용자 결정(v2.39.0, ADR-034): Claude Opus 4.7, Opus 4.6, Sonnet 4.6, Haiku 4.5와 GPT 5.4를 모니터링에서
빼고 화면 메뉴에서도 지운다. 카탈로그(prober, gptbench, 단가 seed)에서 빼고, 남은 DB 행(프로브, 벤치, 패리티)은 이
패턴으로 모든 조회에서 숨긴다. 활성 라벨은 이 패턴을 포함하지 않는다(tests가 고정).

재노출 방법: env HIDDEN_MODEL_PATTERNS=""(빈 값) 주입 + CDK ENABLE_OPENAI_1P=true
(+ 유효 키를 SSM /bedrock-monitor/openai-1p-api-key 에 저장). env를 주면 기본값 전체를 대신하므로
1P만 다시 보이려면 나머지 패턴은 그대로 적는다.
"""

import os

# model_name 라벨 부분일치 패턴 (쉼표 구분). 기본: OpenAI 1P direct 채널과 v2.39.0에 모니터링에서 뺀 다섯 패밀리.
_DEFAULT_HIDDEN = "(1P),Claude Opus 4.7,Claude Opus 4.6,Claude Sonnet 4.6,Claude Haiku 4.5,GPT 5.4"


def hidden_patterns() -> list[str]:
    raw = os.getenv("HIDDEN_MODEL_PATTERNS", _DEFAULT_HIDDEN)
    return [p.strip() for p in raw.split(",") if p.strip()]


def visible_only(query, model_name_column):
    """쿼리에 숨김 라벨 제외 필터를 적용해 반환. 패턴이 없으면 그대로 반환."""
    for p in hidden_patterns():
        query = query.filter(~model_name_column.contains(p))
    return query
