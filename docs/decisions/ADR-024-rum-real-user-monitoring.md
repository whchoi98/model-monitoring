# ADR-024: RUM(Real User Monitoring) 통합 — aws-rum-pipeline + 자체 호스팅 SDK

- **Status**: Accepted
- **Date**: 2026-07-12
- **Related**: Observability 스택 (CloudWatch Alarms/Dashboard), v2.16.5

## Context

서버측 관측(CloudWatch)만으로는 실사용자 관점의 페이지뷰·체류시간·Web Vitals·JS 에러를
볼 수 없다. CloudFront 뒤 Next.js 프론트에 실사용자 모니터링이 필요했다.

## Decision

aws-rum-pipeline 수집 엔드포인트로 전송하는 **자체 호스팅 `public/rum-sdk.min.js`** 를
`RumProvider`(next/script onReady)로 로드한다. appName=llm-monitor 스탬핑.

- 수집 설정(`NEXT_PUBLIC_RUM_ENDPOINT`/`_API_KEY`)은 **빌드 타임 주입** —
  `NEXT_PUBLIC_*`은 번들에 인라인되므로 frontend Dockerfile `ARG`/`ENV`로 전달.
- 미설정 빌드는 수집이 조용히 비활성화된다 (개발/포크 안전 기본값).

## Consequences

- (+) 외부 CDN 의존 없음(자체 호스팅), 키 미설정 시 무해
- (−) **frontend docker build에 `--build-arg NEXT_PUBLIC_RUM_*` 누락 시 RUM 꺼진
  이미지가 배포됨** — 배포 체인/런북에 build args 필수 (deploy.md §2 반영)
- 배포 검증 항목 추가: 배포 후 브라우저 네트워크 탭에서 RUM 엔드포인트 POST 확인
