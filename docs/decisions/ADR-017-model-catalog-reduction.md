# ADR-017: Model Catalog Reduction — Opus 4.5 / Sonnet 4.5 제외

- **Status**: Accepted
- **Date**: 2026-05-20
- **Deciders**: Product team

## Context / 배경

v2.1.0 초기 모델 catalog 확장(9 → 13개)에서 Opus 4.5 / Sonnet 4.5 (Global, US 각 1개씩 = 4개) 추가했다. 운영 중 사용자가 다음과 같이 정렬 요구사항을 명시:

```
Anthropic Claude Opus 4.7 (US) - Bedrock Opus 4.7 (Global) - Bedrock Opus 4.7 (US)
Bedrock Opus 4.6 (Global) - Bedrock Opus 4.6 (US)
Anthropic Sonnet 4.6 (US) - Bedrock Sonnet 4.6 (Global) - Bedrock Sonnet 4.6 (US)
Anthropic Haiku 4.5 (US) - Bedrock Haiku 4.5 (Global) - Bedrock Haiku 4.5 (US)
Bedrock Nova 2.0 Lite (US)
= 12개
```

Opus 4.5 / Sonnet 4.5는 제외. 이유:
- 운영 우선순위 — Opus는 4.6 / 4.7 두 세대로 충분 (성능 비교).
- Sonnet은 4.6만 — 4.5는 4.6과 거의 동등하여 모니터링 가치 낮음.
- 모델당 5분 cycle × 6 카테고리 = 운영 비용 부담. 12개로 줄이면 ~14% 절감.

## Decision / 결정

`backend/prober.py` `AVAILABLE_MODELS`에서 Opus 4.5 / Sonnet 4.5 4개 entry 제거. 9개 Bedrock + (Anthropic CP discovery로) 3개 = 12개 모델 monitoring.

**관련 변경**:
1. `backend/prober.py`: AVAILABLE_MODELS 정리
2. `backend/main.py` lifespan: `DELETE FROM probe_results WHERE model_name LIKE '%Opus 4.5%' OR LIKE '%Sonnet 4.5%'` — 옛 row 일괄 삭제 (idempotent)
3. `backend/main.py` `_label_renames`: 4.5 rename 4 lines 제거
4. `frontend/src/lib/sortModels.ts` `FAMILY_ORDER`: 4.5 family 제거
5. `frontend/src/components/TrendChart.tsx` `MODEL_COLORS`: 4.5 색상 entries 제거 + fallback palette 정리
6. `frontend/src/components/StreamingView.tsx`: 4.5 reference 정리, Opus 4.7 / Sonnet 4.6 추가
7. `frontend/src/components/AutoDashboard.tsx`: hard-filter 안전망 — `EXCLUDED = ["Opus 4.5", "Sonnet 4.5"]`. backend silent bug 시에도 UI 숨김.

## Consequences / 결과

**Pros**:
- 운영 cost 절감 (Bedrock 호출 + 토큰 비용 -14%)
- UI 일관성 (12개 카드 안정적 표시)
- Catalogue 변경 시 7곳 동기화 절차가 표준화됨

**Cons**:
- 4.5 모델 historical data는 row 삭제로 사라짐 (lifespan migration 실행 후 복구 불가). 향후 4.5 추가 필요 시 새 cycle부터 시작.
- frontend hard-filter는 임시 안전망 — backend가 정상이면 불필요하지만 silent bug 안전성 보강.

## References

- 사용자 요구사항: 2026-05-20 chat thread "12개입니다."
- 관련: ADR-018 (ECR repository swap)
- 관련: ADR-012 (옛 model expansion 결정 — 이 ADR이 일부 무효화)
