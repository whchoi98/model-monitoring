# ADR-007 — SSE 패턴: VIEWER_REQUEST only + simulateStreaming

- 상태: Accepted
- 일자: 2026-05-16

## 배경

CloudFront 뒤에서 SSE는 자주 깨진다. 원인:

1. **ORIGIN_RESPONSE Lambda@Edge**는 응답 body 전체를 버퍼링한 뒤 처리 → SSE chunked transfer 깨짐.
2. **CloudFront idle timeout 30s** — 토큰 출력이 sparse하면 끊김.
3. **AgentCore Runtime은 스트리밍 미지원** — invoke는 완성된 텍스트 반환.

## 결정

다섯 가지 원칙으로 SSE를 안전하게 보존:

1. **Lambda@Edge는 VIEWER_REQUEST 단계에만 부착** — 인증/리다이렉트는 OK. ORIGIN_RESPONSE는 절대 금지.
2. **Bedrock `converse_stream` 사용** — `contentBlockDelta`마다 즉시 `delta` SSE 이벤트 emit. 5초 안에 청크가 흘러 CloudFront 키프얼라이브 유지.
3. **CloudFront `/api/*` behavior는 `CACHING_DISABLED` + `ALL_VIEWER_EXCEPT_HOST_HEADER`** — 응답 변형 0 + 모든 viewer header 전달.
4. **`final` 이벤트 try/finally** — 정상/예외 모두에서 정확히 1회. `stream_with_final()` 헬퍼가 강제.
5. **AgentCore Runtime 응답은 `simulate_streaming()`** — 50자/15ms 청크로 SSE 변환.
6. **`max_tokens` 시나리오별 분리** — 챗봇 1024, 인사이트 2048 등. 일률 8192 금지.

## 결과

- 30초 이상 long-running 응답도 keep-alive 유지.
- 클라이언트는 `final` 이벤트로 정상/오류 상태 명확히 인식.
- 백엔드 예외 시 CloudWatch에 스택트레이스, 클라이언트엔 `{"ok":false,"error":...}`.

## 검증

- `curl --no-buffer -N -X POST .../api/chat/stream -H ...` 로 청크 단위 수신 확인.
- backend `tests/test_streaming.py` 4건이 헬퍼의 정상/예외 emit을 검증.
