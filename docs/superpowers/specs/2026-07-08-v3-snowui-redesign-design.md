# v3.0.0 — SnowUI 스타일 풀 리디자인 설계서

- **작성일**: 2026-07-08
- **현재 버전**: v2.6.1 → **목표 버전: v3.0.0** (메이저)
- **참조 디자인**: SnowUI Dashboard UI Kit (ByeWind, Figma Community file 1210542873091115123, CC BY 4.0)
- **상태**: 사용자 승인 완료 (2026-07-08)

## 1. 목표와 범위

Bedrock LLM Monitor 프론트엔드를 SnowUI 스타일로 풀 리디자인한다.

| 항목 | 결정 |
|------|------|
| 범위 | 풀 리디자인 — 좌측 사이드바 레이아웃 + SnowUI 카드/차트 스타일 |
| 테마 | **화이트 기본** + 블랙 토글, localStorage 저장 |
| 차트 색상 | SnowUI 톤 채널별 색군으로 재설계 |
| 클래식 UI | 인앱 토글 **없음** — v2.6.1 이미지 보관으로 운영자 롤백 |
| 백엔드 | 변경 없음 (순수 프론트엔드 프레젠테이션 레이어) |

### 범위 제외 (Non-goals)

- 백엔드 API·스키마·데이터 로직 변경
- `i18n.ts` 문구 변경, `sortModels.ts` 정렬 로직 변경, `pricing.ts` 로직 변경
- 인앱 클래식(v2) 테마 토글
- 신규 페이지/기능 추가

## 2. 테마 아키텍처 — 시맨틱 토큰

### CSS 변수 2세트 (`globals.css`)

```css
:root {          /* 화이트 (기본) */
  --bg: #FFFFFF;
  --card: #F7F9FB;
  --text-1: #1C1C1C;   /* primary text */
  --text-2: #1C1C1C66; /* secondary text */
  --border: #1C1C1C1A;
  /* SnowUI 파스텔 액센트 */
  --accent-blue: #E3F5FF;    /* KPI 카드 배경 */
  --accent-indigo: #E5ECF6;  /* KPI 카드 배경 2 */
  --accent-purple: #95A4FC;  /* 차트/포인트 */
  --accent-mint: #BAEDBD;    /* 차트/포인트 */
  --accent-cyan: #A8C5DA;    /* 차트/포인트 */
}
html.dark {      /* 블랙 */
  --bg: #1C1C1C;
  --card: #FFFFFF0D;
  --text-1: #FFFFFF;
  --text-2: #FFFFFF66;
  --border: #FFFFFF1A;
}
```

### Tailwind 매핑 (`tailwind.config.ts`)

```ts
colors: {
  bg: 'var(--bg)',
  card: 'var(--card)',
  // text-primary / text-secondary / border-default 등 시맨틱 이름
}
```

- 기존 **약 495곳 / 30개 파일**의 `bg-gray-950`·`text-gray-100`·`border-gray-800` 등 원시 gray 클래스를 시맨틱 클래스로 전면 치환한다.
- 컴포넌트 코드는 테마를 모른다 — `dark:` 변형을 쓰지 않는다. 테마 조정은 CSS 변수만 수정.

### ThemeProvider (자체 구현, ~40줄)

- React Context + `localStorage('theme')` + `<html>` 클래스 토글. `next-themes` 의존성 추가하지 않음.
- FOUC 방지: `layout.tsx` `<head>`에 inline script(`dangerouslySetInnerHTML`)로 하이드레이션 전에 localStorage를 읽어 `dark` 클래스 선반영.
- 기본값: 화이트. `prefers-color-scheme`는 사용하지 않는다(명시적 화이트 기본).

## 3. 레이아웃 — 좌측 사이드바

- 신규 `Sidebar.tsx`: 로고 + 메뉴 7개(대시보드/비용/신뢰성/효율/분석/프롬프트/챗) + 하단 유틸(테마 토글 ☀/🌙, KO/EN 토글, 로그인 상태).
- 활성 메뉴: SnowUI 스타일 연한 배경 pill 하이라이트.
- 반응형: `lg` 미만 사이드바 숨김 → 햄버거 버튼 + 오버레이 드로어.
- 기존 상단 sticky 헤더는 슬림한 페이지 타이틀 바(페이지명 + 자동새로고침 상태)로 축소.
- 사이드바는 `app/layout.tsx`에 배치해 6개 페이지 공통 적용(페이지별 중복 제거).
- 챗(FloatingChat)은 기존 플로팅 방식 유지.

## 4. 컴포넌트 리스타일 (~30개 파일)

- 카드: `rounded-2xl` + `bg-card`, 테두리 최소화(배경 대비로 구분 — SnowUI 방식).
- KPI 스탯 카드(`StatsCards.tsx` 등): 파스텔 배경 변형(연블루/연퍼플).
- 테이블·입력·버튼·모달·스크롤바: 시맨틱 토큰 기반 치환. 스크롤바는 테마별 CSS 변수로.
- 상태 색(성공/실패/경고)은 라이트/다크 대비 검증된 값으로 토큰화.

## 5. 차트 (Recharts) — 테마 인식

### MODEL_COLORS 채널별 색군 재설계 (`TrendChart.tsx` 등)

| 채널 | 색군 |
|------|------|
| Anthropic CP on AWS | 퍼플 계열 |
| Bedrock Global | 블루 계열 |
| Bedrock US | 민트/그린 계열 |
| OpenAI (Mantle + 1P) | 그레이·블랙 계열 |

- 같은 색군 내 모델 구분은 명도 단계(예: 블루 900→300)로.
- 28개 모델 전부 라이트/다크 배경 대비 검증.
- 그리드·축·툴팁·범례 색은 `useTheme()` 훅으로 분기 (Recharts는 JS 상수 색상이라 CSS 변수 직접 적용 불가).

## 6. 버전·롤백·문서

- `frontend/src/lib/version.ts` → `v3.0.0`, `CHANGELOG.md` 갱신.
- 배포 전 운영 중인 v2.6.1 **이미지 digest + ECS task definition revision 번호를 `docs/runbooks/rollback.md`에 기록** — 문제 시 task def revision 교체로 즉시 복귀.
- ADR 신규 작성: 시맨틱 토큰 테마 아키텍처 결정.
- ECR immutable tag 정책 준수 (`v<timestamp>`, `:latest` 금지).

## 7. 검증 계획

1. `npm run build` (standalone) 통과.
2. 로컬 dev 서버에서 6개 페이지 × 2테마 = 12조합 시각 확인(스크린샷).
3. 테마 전환 → 새로고침 시 localStorage 유지 확인.
4. KO/EN 토글 정상 동작 확인.
5. `lg` 미만 뷰포트에서 드로어 동작 확인.
6. 원시 gray 클래스 잔존 검사: `grep -r "bg-gray-9\|text-gray-[1-4]00" src/` 0건 목표(의도적 예외는 주석 명시).

## 8. 구현 순서 (개요)

1. 토큰 정의 + Tailwind 매핑 + ThemeProvider + FOUC 스크립트
2. Sidebar + layout.tsx 재구성
3. 페이지/컴포넌트 시맨틱 토큰 치환 (페이지 단위로 진행)
4. 차트 색상 재설계 + 테마 인식 훅
5. 버전/CHANGELOG/ADR/런북
6. 검증 (7절)
