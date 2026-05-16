# ADR-001 — CloudFront VPC Origin (internet-facing ALB 회피)

- 상태: Accepted
- 일자: 2026-05-16
- 결정자: WooHyung Choi

## 배경

v1은 CloudFront가 internet-facing ALB의 prefix-list ingress만 허용하는 방식이었다. 외부에서 ALB DNS를 알면 직접 접근이 이론적으로 가능했고, prefix-list가 잘못 적용되면 노출 위험이 컸다.

## 결정

v2에서는 **CloudFront VPC Origin** (2024-11 GA)을 채택한다.
- ALB는 `scheme=internal`.
- CloudFront가 private subnet에 ENI를 직접 생성해 ALB와 통신.
- Origin protocol은 `HTTPS_ONLY`로 강제.

## 결과

- 인터넷에서 ALB로의 라우팅이 **물리적으로 불가능**해진다.
- prefix-list 관리 부담 제거.
- WAF는 CloudFront 단에서 단 한 곳만 관리.

## 트레이드오프

- VPC Origin의 ENI가 사용하는 SG를 우리가 좁힐 수 없어 ALB SG는 `0.0.0.0/0`(VPC 내부에서만 라우팅 가능) 상태가 됨 — cdk-nag EC23은 의미 없는 경고이므로 명시적 suppress.
- VPC Origin은 2024-11 GA로 비교적 신생 — L1 wiring 일부 우회 필요.

## 대안 검토

- **Internet-facing ALB + prefix-list ingress**: v1 방식. 단순하지만 노출 위험.
- **ALB → CloudFront Origin Access Control(헤더)**: HMAC 검증으로 보안 보강 가능하나 ALB가 여전히 internet-facing.
