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
- 배포 검증: autoprober 로그에서 Global 3채널 첫 `success` 확인 필수 —
  `bedrock-runtime.ap-northeast-2` 호스트는 기존 Mantle 호스트(NAT egress)와
  달리 **BedrockRuntime interface VPC endpoint를 경유**하므로 로컬 라이브 검증과
  네트워크 경로가 다르다 (endpoint policy는 기본 전체 허용이라 동작 예상)
- env 주입 누락 시 prober가 조용히 skip — 한쪽 스택만 배포하면 대시보드/스케줄
  태스크 간 카탈로그 불일치 (1P 때와 동일 메커니즘, deploy.md 체크리스트 준수)
