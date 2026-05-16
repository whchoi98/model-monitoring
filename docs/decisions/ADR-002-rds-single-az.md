# ADR-002 — RDS t4g.micro Single-AZ

- 상태: Accepted
- 일자: 2026-05-16

## 배경

v2 DB 옵션을 검토하면서 (1) Postgres on ECS Fargate + EBS/EFS, (2) RDS, (3) Aurora Serverless v2를 비교했다. 사용자는 매니지드 부담 최소화 + 저렴함을 선택.

## 결정

**RDS PostgreSQL 16.3 t4g.micro**, **Single-AZ**, 20GB gp3, 7d 자동 백업, deletion protection ON, snapshot removal policy.

## 결과

- RDS 매니지드 백업/패치/모니터링 즉시 활용.
- 월 비용 ~$13 + 스토리지.
- Performance Insights ON.

## 트레이드오프

- Single-AZ → RDS 장애 시 frontend/backend(Multi-AZ Fargate)가 모두 영향. 모니터링 시계열 데이터는 손실 허용으로 정당화 (spec C-7/OOS-2).
- t4g.micro의 max_connections는 기본 ~85 → backend AS 1~3 × connection pool 고려 시 빠듯 → Connections > 80 알람.

## 후속

- 운영 트래픽이 늘면 Multi-AZ로 전환 + read replica 검토.
- cdk-nag RDS3 (Multi-AZ 권고)는 본 ADR을 사유로 명시적 suppress.
