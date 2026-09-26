# ADR-025: OpenAI GPT-5.6 Global CRIS 채널 3개 추가 + 채널별 가격 분리

- **Status**: Accepted
- **Date**: 2026-08-18
- **Related**: ADR-019 (Mantle Path 4), ADR-020 (1P direct Path 5), v2.20.0

## Context

2026-08-17 AWS가 OpenAI 모델의 cross-region inference를 발표했다
(GPT-5.6 세대 Sol/Terra/Luna 한정 — 5.4/5.5는 미지원). Global 프로파일
(`global.openai.gpt-5.6-*`)은 Seoul(ap-northeast-2) 포함 전 상용 리전에서 호출
가능하며, **기존 Mantle in-region 채널과 다른 두 가지 특성**이 있다:

1. **호출 경로**: global 프로파일은 `bedrock-mantle.<region>.api.aws` 호스트가
   지원하지 않는다. `bedrock-runtime.<region>.amazonaws.com/openai/v1`
   (OpenAI-compat) 엔드포인트로만 호출 가능 (기존 `ABSK` bearer 키 재사용 —
   Seoul 엔드포인트 + 기존 키로 라이브 검증 완료).
2. **단가**: Global CRIS가 in-region/Geo보다 저렴 (공식 모델 카드, Standard tier,
   short context ≤272K):

   | 모델 | In-Region/Geo | Global CRIS |
   |------|---------------|-------------|
   | GPT 5.6 Sol | $5.50 / $33.00 | $5.00 / $30.00 |
   | GPT 5.6 Terra | $2.20 / $13.20 | $2.00 / $12.00 |
   | GPT 5.6 Luna | $0.22 / $1.32 | $0.20 / $1.20 |

   조사 과정에서 **기존 in-region 단가 기재가 낡은 것도 발견** — 2026-07-30 AWS
   인하(Luna -80%, Terra -20%, Sol 불변)가 미반영이었다 (구 기재: "1P parity,
   Sol $5/$30, Terra $2.5/$15, Luna $1/$6").

## Decision

- **키 스킴**: `openai:global:global.openai.gpt-5.6-*` — pseudo-region `global`
  (1P의 `1p`와 동일 패턴). 프로파일 id는 in-region id에 `global.` 접두사를
  `_register_openai_models()`가 파생 — 별도 model-id env 불필요.
- **라벨**: `OpenAI GPT 5.6 * (Global)` — Claude 채널의 `(Global)` 대문자 관례와
  동일 (frontend `MODEL_COLORS`/`channelRank` join key).
- **라우팅**: 신규 env `OPENAI_GLOBAL_BASE_URL`
  (`https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1`) —
  CDK AppServices(backend) + Scheduler `buildTaskDef`(autoprober/insights/
  parityrun/gptbench 공유 빌더) 양쪽 주입. Claude `global.*`처럼 Seoul 라우팅이라
  US in-region 채널과 다른 네트워크 경로를 측정한다.
- **가격**: `_normalize_key`가 `openai:global:*`에 `-global` suffix 키를 부여
  (`gpt-5.6-sol-global` 등) — PRICE_TABLE에 Global 단가 3키 추가. in-region
  3키는 2026-07-30 인하 반영으로 교정 (비용은 조회 시점 계산이라 소급 재계산됨 —
  Opus 4.8 단가 교정 때와 동일 정책). Claude의 `global.` collapse(동일 단가)는
  종전대로 유지.

활성 카탈로그 **37 → 40**. reliability/cost/analysis/efficiency/anomalies/챗봇
tools/parity는 전부 동적이라 무변경 자동 편입 (parity는 12h 런당 3모델 × 20셀(2 surface × 적용 피처) = 60셀 자동 추가).

## Consequences

- (+) Global vs in-region의 실측 레이턴시·비용 비교 가능 (Seoul 기준 유일한
  근거리 OpenAI 채널)
- (−) **1P 휴면 채널(`openai:1p:gpt-5.6-*`)은 여전히 in-region 키를 공유** —
  1P 전용 단가 분리는 기존 follow-up 그대로 (휴면/비노출이라 표시 영향 없음)
- (−) gptbench(`_BENCH_SPECS`)는 별도 카탈로그라 `/gpt-on-aws` 벤치에 Global
  채널이 자동 추가되지 않음 — 포함하려면 별도 결정 (15분 주기 비용 증가)
  → **2026-08-18 사용자 승인으로 v2.20.1에서 Terra Global 1채널 편입** (8→9채널,
  ~+$20/일 추정; Sol/Luna는 벤치 대상 자체가 아니라 제외 유지)
- 배포 검증: autoprober 로그에서 Global 3채널 첫 `success` 확인 필수 —
  `bedrock-runtime.ap-northeast-2` 호스트는 기존 Mantle 호스트(NAT egress)와
  달리 **BedrockRuntime interface VPC endpoint를 경유**하므로 로컬 라이브 검증과
  네트워크 경로가 다르다 (endpoint policy는 기본 전체 허용이라 동작 예상)
- env 주입 누락 시 prober가 조용히 skip — 한쪽 스택만 배포하면 대시보드/스케줄
  태스크 간 카탈로그 불일치 (1P 때와 동일 메커니즘, deploy.md 체크리스트 준수)

## 후속 (v2.28.1, 2026-09-23)

- GPT-5.6 Sol 단가를 AWS 프로모션 단가로 교정했다(사용자 결정): In-Region·Geo $4.40/$22, Global CRIS $4/$20
  (위 표의 $5.50/$33, $5/$30은 당시 값). 모델 카드와 `ListFoundationModelAgreementOffers`(offer-gnqokrqqvdbgw)가
  일치하며, 카드에 따르면 프로모션은 최소 2026-11-21까지다 — 종료 후 재확인. Terra, Luna는 변경 없음.
- 1P 재노출 선행 조건(`-1p` 단가 분리)은 그대로다. 다만 방향이 모델마다 다르다: Terra/Luna는 base 키가 1P 정가보다
  10% 높아 과대 산정, Sol은 프로모션 단가가 1P 정가($5/$30)보다 낮아 과소 산정된다. 자세한 기록은 ADR-028 후속(v2.28.1).

## 후속 (v2.30.0, 2026-09-26) — 소급 정책 대체

- 이 ADR의 "비용은 조회 시점 계산이라 소급 재계산됨" 정책은 **ADR-030이 대체했다.** v2.30.0부터 비용은 각 프로브 시각에 유효했던
  단가로 계산하고, 단가는 `price_history` 테이블에 `model_id` 단위 행으로 두며 PricingSync 태스크가 12시간마다 공식 출처에서 갱신한다.
- `PRICE_TABLE`, `_normalize_key`, `-global` / `-us` suffix 키, `get_pricing` prefix fallback은 `backend/pricing.py`와 함께 삭제됐다.
  Global CRIS 단가가 in-region과 다르다는 사실은 그대로이며, 이제 채널마다 별도 단가 행이다.
- 같은 조사에서 `_normalize_key`가 Claude `us.`와 `global.`을 같은 키로 합쳐 Bedrock Claude US 10채널이 Global 단가(공식 US는
  Global × 1.1)로 산정되던 오류를 찾았고, v2.30.0 seed로 과거까지 교정했다(ADR-030 Decision 2).
