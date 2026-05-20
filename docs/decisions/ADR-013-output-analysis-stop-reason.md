# ADR-013: Output Analysis Page & stop_reason Capture

- **Status**: Accepted
- **Date**: 2026-05-20
- **Deciders**: Product team

## Context / 배경

기존 Dashboard / Cost / Reliability / Efficiency 페이지는 **성능·비용 메트릭**만 표시. LLM 특화 시그널 (모델이 답변을 왜 멈췄는가, 같은 prompt에 모델별로 출력 길이가 얼마나 다른가)은 노출 안 됨.

운영상 의미 있는 시그널:
- **Stop Reason 분포**: `max_tokens`로 잘리는 비율이 높으면 prompt 설계 문제. `guardrail_intervened` / `content_filtered`는 안전성 시그널.
- **Output Length 분포**: 같은 카테고리에서 모델별로 출력 길이가 크게 다르면 비용·지연 예측에 직접 영향. "Opus는 평균 800토큰, Haiku는 200토큰" 같은 인사이트는 다른 모니터링 도구가 잘 다루지 않음.

## Decision / 결정

1. **Backend `/api/analysis/*` 신규 endpoint 2개**:
   - `GET /api/analysis/stop-reasons?window=7d&category=<id>` — 모델별 stop_reason 분포 (counts + percentages)
   - `GET /api/analysis/output-length?window=7d&category=<id>` — 모델별 output_tokens 통계 (n/mean/median/p50/p95/std/min/max + 7-bin histogram)
2. **`probe_results.stop_reason TEXT` 컬럼 추가** + lifespan `ALTER TABLE ADD COLUMN IF NOT EXISTS`. Bedrock `messageStop.stopReason` + Anthropic `final_message.stop_reason` 양쪽 prober.py에서 capture.
3. **`/analysis` 페이지 신규**: stop reason stacked bar chart + output length histogram table. 카테고리 + 시간 윈도우 필터. 하단에 해석 가이드 박스 (KO/EN bilingual).
4. **Stop reason 정규화**: `_normalize_stop_reason()`이 Bedrock/Anthropic vendor 차이를 흡수 (`end_turn`, `max_tokens`, `stop_sequence`, `tool_use`, `guardrail_intervened`, `content_filtered`, `other`, `unknown`).

## Consequences / 결과

**Pros**:
- LLM 특유 시그널을 정량화 — prompt 설계 / 모델 선택 의사결정 지원
- 추가 호출 / 비용 없음 (Bedrock 응답에 이미 포함된 데이터)
- backend로직은 SQL aggregation만 추가, frontend는 정적 chart

**Cons**:
- 기존 row는 `stop_reason=NULL` → "unknown"으로 표시 (시간이 지나며 자연스럽게 채워짐)
- histogram bin이 hardcoded (`0-100, 100-250, ..., 4000+`) — 동적 조정 미지원

## Implementation / 구현

- `backend/routers/analysis.py` (신규)
- `backend/prober.py`: `stop_reason` 변수 추가 + retry reset + result_data/db_result 저장
- `backend/models.py`, `schemas.py`: `stop_reason` 필드
- `backend/main.py` lifespan: ALTER TABLE
- `frontend/src/components/AnalysisPanel.tsx` (신규)
- `frontend/src/app/analysis/page.tsx` (신규)
- 모든 페이지 nav에 `/analysis` 링크 추가

## References

- 권장 풍선말 6개 중 2건이 이 페이지를 가리킴 ("max_tokens로 잘린 응답이 많은 모델은?", "같은 워크로드에서 출력 길이가 가장 짧은 모델은?")
- 관련: ADR-014 (model expansion 9→13)
