# 모델 모니터링 UX 리뷰와 개선 기록

리뷰 기준: 2026-09-22, `b1027a9`에서 시작한 작업 트리.

목표는 모델 상태를 빠르게 판단할 수 있게 하고, 조회·탐색·로그인·오류 복구의 동작을 화면 전반에서 일관되게 만드는 것이다. 기존 2026-09-07 장기 백로그는 문제를 찾는 참고 자료로 사용했다.

## 확인한 문제와 반영 내용

| 문제 | 반영 내용 | 주요 근거 |
|---|---|---|
| 조회 실패가 빈 데이터처럼 표시됨 | 오류·최초 로딩·정상 빈 응답·실패한 재조회 구분, 같은 조건의 마지막 결과 유지, 재시도 제공 | `useAsyncResource`, `DataState`, 각 패널의 독립 리소스 |
| 기간/카테고리를 빠르게 바꾸면 늦은 응답이 최신 선택을 덮어씀 | 이전 요청 취소와 요청 식별, 데이터와 조회 조건 결합 | `useAsyncResource`, `e2e/analytics.spec.ts` |
| 최신 성공 결과가 오래되어도 정상처럼 보임 | 정상·오류·과부하·수집 지연·미수집 구분, 실제 수집 시각과 확인 시각 표시 | `monitoring.ts`, `format.ts`, `AutoDashboard` |
| 수집되지 않은 채널이 화면에서 빠짐 | 모델 목록과 최신 결과를 결합, 목록 조회 실패 시 수집기의 예상 채널 수 활용 | `buildMonitoringRows`, `summarizeMonitoring` |
| 목록 실패 시 일부 관측 결과를 전체로 오인 | 예상 수가 있으면 미확인 채널을 요약에 포함하고, 수를 알 수 없으면 전체 수/문제 수를 미확정으로 표시 | `MonitoringOverview`, `e2e/monitoring.spec.ts` |
| 모델 카드가 길게 나열되어 문제를 찾기 어려움 | 첫 화면 상태 요약, 채널 상태 표시, 검색, 상태 필터, 문제/TTFT 정렬, 추세 이동 | `AutoDashboard`, `ModelStatusGrid` |
| 실패·수집 중단 구간을 그래프가 연결함 | 실제 시간 간격 사용, 모델별 시계열과 명시적 결측 구간, 성공 값만 집계 | `pivotTrend.ts`, `TrendChart`, `GptOnAwsPanel`, `_downsample_hourly` |
| 많은 포인트에서 고립된 성공 값이 사라짐 | 일반 마커를 생략하는 조밀한 그래프에서도 고립된 측정점은 유지 | `isolatedSampleTimes`, 브라우저 840포인트 재현 |
| 작은 화면에서 메뉴·기간 버튼·범례가 넘침 | 두 줄 공용 헤더, 모바일 메뉴, 줄바꿈 컨트롤, 플롯 밖 범례, 첫 화면의 확인 필요 요약 | `AppHeader`, 390/1024/1280/1440px 브라우저 검사 |
| 페이지마다 로그인/언어 상태가 달라짐 | 루트 공용 Provider, 네트워크 오류 시 세션 유지, 문서 언어·페이지 제목 동기화 | `auth-context`, `i18n-context`, `AppShell` |
| 다른 페이지에서 수동 프로브 메뉴를 누르면 대시보드가 열림 | `/?view=manual`로 직접 탐색·새로고침·뒤로 가기 지원 | 루트 페이지, `e2e/shell.spec.ts` |
| 모델 상세와 증거 화면의 닫기/포커스 동작이 불일치 | 공용 네이티브 대화상자, Escape, 배경 비활성화, 닫은 뒤 포커스 복귀 | `Dialog`, 모델 탐색·증거·이력·삭제 확인 |
| 수집 상태가 별도 Fargate 실행을 반영하지 못함 | DB 실행 예약으로 진행·완료·실패·지연 판별, 오래된 예약 만료 | `backend/auto_prober.py`, `routers/auto_probe.py` |
| 자동 실행 요청이 미인증·중복으로 접수됨 | JWT 필수, 예약 후 202 응답, 중복 409, 스케줄러/수동 공통 진입 검사 | `test_auto_probe_status.py` |
| 최근 실패 수에 수동 테스트가 섞임 | 자동 실행만 집계, 워크로드 필터 일치 | `/api/auto-probe/anomalies` |
| 비용 예측이 다른 기간의 합계로 계산될 수 있음 | 응답 데이터의 기간을 분모로 사용, 독립된 요약·채널 조회 | `costProjection.ts`, 비용 기간 전환 테스트 |
| 수동 스트림이 중간에 끝나면 실행 중으로 남음 | 완료/오류 이벤트 판별, 연결 종료 오류, 부분 결과 유지, 이전 실행 콜백 차단 | `probeStream.test.ts`, `useProbeStream` |
| 한글 조합 중 Enter가 메시지를 전송함 | IME 조합 확인, KO/EN 입력 문구 일치 | `ChatInput`, `e2e/visibility.spec.ts` |
| 프레임워크/종속성 보안 패치 누락 | Next.js 16.3.5와 호환 종속성 수정, 비동기 쿠키와 `proxy.ts` 규약 적용 | `package.json`, 잠금 파일, 감사 및 프로덕션 빌드 |

## 상태 해석

- **정상**: 해당 채널의 최근 결과가 성공이고 예상 수집 주기와 유예 시간 안에 있음.
- **수집 지연**: 예상 주기 + 최대 5분 유예 초과. 기본 자동 수집은 10분, 현재 6개 워크로드의 카테고리 조회는 35분 기준이다.
- **미수집/미확인**: 선택한 조건의 결과 또는 유효한 수집 시각이 없음. 정상으로 집계하지 않는다.
- **최신 실행 성공률**: 관측된 채널의 마지막 결과 중 성공 비율이다. 미수집 채널은 커버리지와 확인 필요 수에 별도로 표시한다.
- **마지막 확인**은 API 조회 시각이고, 카드/런의 **수집 시각**과 구분한다. 갱신을 멈춰도 오래된 실행/결과를 계속 현재 상태로 간주하지 않는다.
- `/status`는 DB에서 관측된 활동을 제공한다. EventBridge 설정을 직접 조회하는 상태가 아니다. 상세 응답과 인증 계약은 `docs/api-reference.md`에 기록했다.

## 검증 절차

```bash
make verify
cd frontend
npm ci
npm run build
PLAYWRIGHT_USE_PRODUCTION=1 npm run test:e2e
npm audit --audit-level=high
```

브라우저 검증은 모의 API를, 백엔드 회귀 검증은 인메모리 DB와 가짜 전송기를 사용한다. 브라우저의 정상·실패·빈 응답·재시도·기간 경쟁·로그인·포커스·다국어·다크/라이트·모바일 동작을 확인한다. 대시보드와 셸의 주요 흐름은 WebKit도 검사한다.

스크린샷은 `screenshots/monitoring-1440-ko-dark-chromium.png`, `screenshots/monitoring-390-en-light-chromium.png` 등으로 생성된다. 46채널 스크린샷의 수치와 모델 ID는 검증용 데이터다.

## 최종 검증 결과

2026-09-22 현재 작업 트리와 Next.js 16.3.5 프로덕션 번들에서 확인했다.

| 검사 | 결과 |
|---|---|
| `make verify` | 통과 |
| CDK 린트·타입·합성 / Jest | 통과 / 75개 통과 |
| 백엔드 Ruff / pytest | 통과 / 288개 통과 |
| 프론트엔드 라우트 타입 생성·TypeScript / Vitest | 통과 / 138개 통과 |
| `npm run build` | Next.js 16.3.5 프로덕션 빌드 통과 |
| 프로덕션 Chromium·WebKit | 106개 통과 |
| HTML·정적 자산·PWA | HTML no-store, 버전별 자산 immutable, 매니페스트·아이콘·safe-area 메타 확인 |
| 프론트엔드 `npm audit --audit-level=high` | 보고된 취약점 0개 |
| `git diff --check` | 통과 |

브라우저 검증 환경은 공식 `mcr.microsoft.com/playwright:v1.63.0-noble` 이미지다. 네트워크를 차단하고 소스는 읽기 전용으로 마운트했으며, 결과와 스크린샷만 기록했다. 이 환경에서 제목의 스트리밍 메타데이터 경쟁 문제까지 수정·재검증했다.

호스트 브라우저 라이브러리 설치 없이 같은 검증을 실행하려면 저장소 루트에서 다음 명령을 사용할 수 있다. 먼저 프론트엔드 의존성을 설치하고 빌드를 완료한다.

```bash
mkdir -p frontend/test-results screenshots
docker run --rm --network none --shm-size=1g --user "$(id -u):$(id -g)" \
  -e PLAYWRIGHT_USE_PRODUCTION=1 -e NPM_CONFIG_CACHE=/tmp/npm-cache \
  --mount "type=bind,src=$PWD/frontend,dst=/project/frontend,readonly" \
  --mount "type=bind,src=$PWD/frontend/test-results,dst=/artifacts" \
  --mount "type=bind,src=$PWD/screenshots,dst=/project/screenshots" \
  -w /project/frontend mcr.microsoft.com/playwright:v1.63.0-noble \
  npm run test:e2e -- --output=/artifacts/results
```

## 운영 반영 시 확인할 계약

- 자동 실행 POST 호출자는 JWT를 보내야 한다. 완료 응답이 아니라 **접수(202)** 응답이며, 결과는 이후 조회로 확인한다.
- API와 스케줄러가 같은 DB 예약 진입 로직을 사용하므로 두 실행 경로에 같은 백엔드 버전을 적용한다.
- 원본 모델 호출·가격표·카탈로그·데이터 보존 정책의 의미는 기존 구현을 따른다. 기존 장기 백로그의 비용 집계 확장, 관리자 기능 등은 별도 제품 과제로 관리할 수 있다.
