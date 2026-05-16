# ADR-004 — ALB → ECS 통신은 HTTP (intra-VPC)

- 상태: Accepted
- 일자: 2026-05-16

## 배경

v2 spec NFR-1은 "HTTP:80 listener 절대 생성 금지"를 못박았다. 이를 ALB→ECS 통신까지 HTTPS로 확장할지 검토.

## 결정

**ALB listener는 HTTPS:443만**, 그러나 **ALB→ECS target group은 HTTP**.

- ALB Listener port=443 protocol=HTTPS, cert는 ACM Private CA.
- Target Group protocol=HTTP, port=8000(backend) / 3000(frontend).
- 통신 구간은 ALB SG ↔ ECS SG로 한정 (awsvpc 내부 격리).

## 결과

- Listener 레벨 보안 요구 충족.
- ECS 컨테이너에서 TLS 종료 부담 없음 — Next.js / FastAPI 모두 stock 설정.
- 인증서 lifecycle 1곳(ALB)만 관리.

## 트레이드오프

- intra-VPC 평문 트래픽 — VPC traffic mirroring으로 inspectable. 모든 SG가 명시 SG 기반(CIDR 미사용)이므로 외부 노출 0.
- 향후 zero-trust(mTLS) 요구가 생기면 App Mesh / Service Connect로 전환 필요.

## 대안 검토

- **ALB→ECS도 HTTPS**: self-signed cert + Listener `routing.http2.enabled` 조정 필요. 운영 복잡도 ↑.
- **모든 트래픽 HTTPS + service mesh**: 본 monitoring 도구 규모엔 과한 설계.
