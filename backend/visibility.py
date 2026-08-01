"""조회 노출 필터 — DB에는 보존하되 API 응답에서 숨길 모델 라벨 (v2.19.1).

2026-07-31 사용자 결정: OpenAI 1P direct(Path 5) 채널을 비교·모니터링 노출에서 제외.
프로브 코드(prober._OPENAI_1P_MODEL_SPECS)와 과거 DB 행은 그대로 보존 — 이 모듈은
읽기 라우터에서만 적용되는 단일 스위치다.

재노출 방법: env HIDDEN_MODEL_PATTERNS=""(빈 값) 주입 + CDK ENABLE_OPENAI_1P=true
(+ 유효 키를 SSM /bedrock-monitor/openai-1p-api-key 에 저장).
"""

import os

# model_name 라벨 부분일치 패턴 (쉼표 구분). 기본: OpenAI 1P direct 채널.
_DEFAULT_HIDDEN = "(1P)"


def hidden_patterns() -> list[str]:
    raw = os.getenv("HIDDEN_MODEL_PATTERNS", _DEFAULT_HIDDEN)
    return [p.strip() for p in raw.split(",") if p.strip()]


def visible_only(query, model_name_column):
    """쿼리에 숨김 라벨 제외 필터를 적용해 반환. 패턴이 없으면 그대로 반환."""
    for p in hidden_patterns():
        query = query.filter(~model_name_column.contains(p))
    return query
