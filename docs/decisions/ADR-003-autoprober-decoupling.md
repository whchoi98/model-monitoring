# ADR-003 — Auto-prober를 EventBridge Scheduler + Fargate Task로 분리

- 상태: Accepted
- 일자: 2026-05-16

## 배경

v1의 auto-prober는 FastAPI backend 프로세스 내부 데몬 스레드였다. v2에서 backend가 ECS Fargate로 옮겨가면서 desiredCount=N으로 스케일링되면 데몬 스레드가 N개 인스턴스에서 동시에 돌아 중복 프로빙이 발생.

## 결정

`backend/auto_prober.py`의 데몬 스레드 제거. `run_cycle()` 함수만 유지하고 두 가지 호출 경로로 노출:

1. **EventBridge Scheduler `rate(5 minutes)` → ECS RunTask Fargate Task** (`python -m auto_prober_runner --once`) — 표준 경로.
2. **`POST /api/auto-probe/trigger`** — 수동 디버깅용, backend 프로세스 내부 thread로 단발 실행.

Insights 잡도 동일 패턴: `rate(30 minutes)` → `python -m insights_runner --window 6h`.

## 결과

- backend 인스턴스 수와 무관하게 정확히 5분에 1번 실행 보장.
- 잡 실패가 backend 가용성에 영향 없음 (격리된 task).
- EventBridge가 retry/dead-letter/timezone-aware cron을 first-class로 제공.

## 트레이드오프

- 이미지 1개를 backend Service + AutoProber + Insights task에서 모두 재사용 → CMD override로 분기. 빌드는 1번, 실행 컨텍스트는 3가지.
- 수동 trigger는 backend 프로세스 내 thread라 backend desiredCount=1이 아니면 어느 인스턴스에서 실행될지 알 수 없음 — 정상 경로는 어디까지나 Scheduler.
