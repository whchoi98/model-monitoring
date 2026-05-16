# ADR-009 — FloatingChat 듀얼 모드 (popup window / iframe modal)

- 상태: Accepted (Phase 10)
- 일자: 2026-05-16

## 배경

챗봇 UI를 popup window로 띄울지 같은 페이지의 iframe modal로 띄울지 결정. 브라우저별 동작 차이가 큼:

- **Firefox / Safari**: `window.open(url, name, "popup=yes,...")`이 popup window로 안정적으로 열림.
- **Chrome / Edge**: Site Engagement Score가 낮으면 popup이 새 탭으로 변환. 사용자 frustration.

## 결정

런타임에 UA를 감지해서 동적으로 분기:

```ts
const isFirefox = /Firefox/i.test(navigator.userAgent);
const isSafari  = /^((?!chrome|android).)*safari/i.test(navigator.userAgent) && !isFirefox;
if (isFirefox || isSafari) {
  const popup = window.open(url, "name", "popup=yes,width=420,height=640");
  if (popup && !popup.closed) return { mode: "popup", popup };
}
return { mode: "iframe" }; // Chrome 등 fallback
```

- popup으로 열리면 `/chat` page route를 새 창에서 렌더.
- iframe modal로 열리면 같은 SPA에 ChatPanel을 overlay.
- popup 차단 / 새 탭 변환 시 자동으로 iframe modal로 fallback.

## 결과

- Firefox/Safari 사용자: 멀티태스킹이 자연스러운 popup.
- Chrome 사용자: Site Engagement Score 무관 일관된 modal UX.
- popup이든 modal이든 같은 `ChatPanel` 컴포넌트 재사용 → 유지보수 1곳.

## 트레이드오프

- UA sniffing은 일반적으로 피해야 할 패턴이지만, popup 차단 동작이 spec이 아니라 휴리스틱이라 부득이.
- popup과 SPA가 localStorage를 공유해야 인증 토큰 동기화 — 같은 origin 보장.

## 검증

- Chrome / Firefox 양쪽에서 수동 회귀 (Phase 10 acceptance).
- popup 차단 켠 상태에서 modal fallback 동작 확인.
