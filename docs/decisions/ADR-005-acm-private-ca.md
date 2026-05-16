# ADR-005 — ACM Private CA 인증서 (외부 lifecycle 관리)

- 상태: Accepted
- 일자: 2026-05-16

## 배경

ALB internal listener는 HTTPS:443만이므로 cert가 필요. 도메인 미보유 → 공인 cert 불가. 옵션:

1. ACM Private CA로 cert 발급
2. self-signed cert (수동 import)

## 결정

**ACM Private CA 발급 cert를 사용**하되, **CA 생성 자체는 CDK 밖에서 처리**한다.

- AppServicesStack은 `albCertificateArn` context로 cert ARN을 받는다.
- context 미주입 시 dummy placeholder ARN으로 synth (deploy 시 반드시 실 cert ARN 필요).
- CA 생성/활성화는 별도 prerequisite — Console / CLI에서 사전 작업.

## 결과

- CDK는 cert "참조"만 — Private CA 비용($400/month)이 CDK 진입 시점에 강제로 발생하지 않음.
- 운영자가 기존 사내 PCA가 있으면 그대로 활용 가능.
- cert 만료/갱신은 ACM이 자동 처리.

## 트레이드오프

- CDK가 cert 생성 lifecycle을 추적하지 않음 → 운영자가 manual 추적 필요. README runbook에 prerequisite 명시.
- placeholder ARN으로 synth 가능하지만 deploy는 실패 — synth ≠ deploy guarantee.

## 대안 검토

- **self-signed cert**: 비용 0이나 CloudFront origin SSL이 trust하지 않음 → 또 다른 secret hop 필요.
- **CDK가 PCA 생성**: PCA Activation은 root cert를 import해야 하는데 CDK 단독으로는 Custom Resource 없이 불가. 운영 복잡도 ↑.
