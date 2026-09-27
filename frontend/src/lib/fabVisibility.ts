/**
 * 우하단 챗봇 버튼 표시 규칙 (v2.31.1, 사용자 결정 "스크롤 시 숨김") — 순수 함수, vitest(fabVisibility.test.ts).
 * 버튼이 표 글자를 가리지 않게 한다(390px /pricing에서 GPT 5.6 Luna In Region 긴 컨텍스트 줄을 가린 신고).
 *
 * 숨김: 창을 아래로 FAB_SCROLL_DELTA_PX 이상 스크롤(방향이 바뀐 뒤 누적), AppShell <main> 안 요소의 가로 스크롤(가격표).
 * <main> 밖의 가로 스크롤은 숨기지 않는다: 헤더 메뉴는 페이지가 열릴 때 활성 항목을 보이려고 스스로 가로 스크롤하는데,
 * 이것은 사용자가 한 스크롤이 아니어서 맨 위에서 버튼이 사라지면 안 된다(iPad 세로 768~834px 실측).
 * 보임: 창을 위로 FAB_SCROLL_DELTA_PX 이상 스크롤, 맨 위(scrollY <= FAB_TOP_PX), 맨 아래 도달
 * (innerHeight + scrollY >= scrollHeight - FAB_BOTTOM_SLACK_PX), 버튼 포커스, 챗봇 창 열림.
 * 맨 아래에서는 가로 스크롤도 숨기지 않는다: AppShell <main>의 아래 여백 덕분에 버튼이 내용을 가리지 않고,
 * 세로로 스크롤할 수 없는 짧은 페이지(항상 맨 아래)에서 버튼이 다시 나타나지 않는 상태를 막는다.
 * 이벤트 연결은 hooks/useChatFabVisibility.ts가 맡는다.
 */

/** Window scroll distance in one direction (px, since the last direction change) that hides (down) or shows (up) the button. */
export const FAB_SCROLL_DELTA_PX = 8;
/** At or above this scrollY the page is at its top, where the button always shows. */
export const FAB_TOP_PX = 16;
/** Slack for fractional heights when deciding that the page bottom is reached. */
export const FAB_BOTTOM_SLACK_PX = 4;

export type FabState = {
  /** Hidden by scrolling; focus and an open chat window still show it (isFabVisible). */
  hidden: boolean;
  /** The last window scrollY seen. */
  lastY: number;
  /** Direction of the current run of window scrolling: 1 down, -1 up, 0 none yet. */
  direction: 1 | -1 | 0;
  /** Distance scrolled in `direction` since it last changed. */
  distance: number;
};

/** Window metrics read with every event: scrollY, innerHeight and the document's scrollHeight. */
export type WindowMetrics = { scrollY: number; innerHeight: number; scrollHeight: number };

export type FabEvent =
  | ({ type: "window" } & WindowMetrics)
  | ({ type: "horizontal" } & WindowMetrics)
  | { type: "show" };

export function initialFabState(scrollY: number): FabState {
  return { hidden: false, lastY: scrollY, direction: 0, distance: 0 };
}

export function atPageTop(scrollY: number): boolean {
  return scrollY <= FAB_TOP_PX;
}

export function atPageBottom({ scrollY, innerHeight, scrollHeight }: WindowMetrics): boolean {
  return innerHeight + scrollY >= scrollHeight - FAB_BOTTOM_SLACK_PX;
}

/** The state after one event: a window scroll, a horizontal scroll inside `<main>`, or a show (focus, chat window open or closed). */
export function nextFabState(state: FabState, event: FabEvent): FabState {
  if (event.type === "show") return { ...state, hidden: false, direction: 0, distance: 0 };
  if (event.type === "horizontal") {
    // A fresh run: after this, the button comes back only with a full FAB_SCROLL_DELTA_PX scroll up (or top, bottom, focus).
    return { ...state, hidden: !atPageBottom(event), direction: 0, distance: 0 };
  }
  const delta = event.scrollY - state.lastY;
  if (delta === 0) return state;
  const step: 1 | -1 = delta > 0 ? 1 : -1;
  const distance = step === state.direction ? state.distance + Math.abs(delta) : Math.abs(delta);
  let hidden = state.hidden;
  if (atPageTop(event.scrollY) || atPageBottom(event)) hidden = false;
  else if (distance >= FAB_SCROLL_DELTA_PX) hidden = step === 1;
  return { hidden, lastY: event.scrollY, direction: step, distance };
}

/** Keyboard users must always see the focused button, and it stays while the chat window is open. */
export function isFabVisible(state: Pick<FabState, "hidden">, { focused, modalOpen }: { focused: boolean; modalOpen: boolean }): boolean {
  return !state.hidden || focused || modalOpen;
}

/** A scroll event on an element is horizontal when its scrollLeft changed; an element seen for the first time starts at 0. */
export function isHorizontalScroll(previousLeft: number | undefined, scrollLeft: number): boolean {
  return scrollLeft !== (previousLeft ?? 0);
}
