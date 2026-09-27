/**
 * 챗봇 버튼 표시 규칙 (v2.31.1, 사용자 결정 "스크롤 시 숨김") 회귀.
 *
 * 창을 아래로 8px 이상(방향이 바뀐 뒤 누적) 스크롤하거나 페이지 안 요소가 가로로 스크롤되면 숨기고,
 * 위로 8px 이상 스크롤, 페이지 맨 위(scrollY 16 이하), 맨 아래 도달(innerHeight + scrollY >= scrollHeight - 4),
 * 버튼 포커스, 챗봇 창 열림이면 보인다.
 */
import { describe, expect, test } from "vitest";
import {
  FAB_BOTTOM_SLACK_PX, FAB_SCROLL_DELTA_PX, FAB_TOP_PX,
  initialFabState, isFabVisible, isHorizontalScroll, nextFabState,
  type FabEvent, type FabState,
} from "./fabVisibility";

// A long page: 844px viewport over 5000px of content, so the bottom is at scrollY 4156.
const VIEWPORT = 844;
const HEIGHT = 5000;
const BOTTOM = HEIGHT - VIEWPORT;

const at = (scrollY: number, scrollHeight = HEIGHT, innerHeight = VIEWPORT): FabEvent =>
  ({ type: "window", scrollY, innerHeight, scrollHeight });
const horizontal = (scrollY: number, scrollHeight = HEIGHT, innerHeight = VIEWPORT): FabEvent =>
  ({ type: "horizontal", scrollY, innerHeight, scrollHeight });

/** Window scroll positions applied in order, from a page resting at `start`. */
function scrollThrough(start: number, positions: number[], state: FabState = initialFabState(start)): FabState {
  return positions.reduce((current, y) => nextFabState(current, at(y)), state);
}

const visible = (state: FabState, focused = false, modalOpen = false) => isFabVisible(state, { focused, modalOpen });

describe("상수", () => {
  test("스크롤 임계 8px, 맨 위 16px, 맨 아래 여유 4px", () => {
    expect(FAB_SCROLL_DELTA_PX).toBe(8);
    expect(FAB_TOP_PX).toBe(16);
    expect(FAB_BOTTOM_SLACK_PX).toBe(4);
  });
});

describe("창 세로 스크롤", () => {
  test("처음에는 보인다", () => {
    expect(visible(initialFabState(0))).toBe(true);
    expect(visible(initialFabState(1200))).toBe(true);
  });

  test("아래로 8px 이상이면 숨기고, 7px이면 그대로 보인다", () => {
    expect(visible(scrollThrough(1000, [1007]))).toBe(true);
    expect(visible(scrollThrough(1000, [1008]))).toBe(false);
    expect(visible(scrollThrough(1000, [1600]))).toBe(false);
  });

  test("같은 방향의 작은 스크롤은 누적된다 (3 + 3 + 2 = 8px)", () => {
    expect(visible(scrollThrough(1000, [1003, 1006]))).toBe(true);
    expect(visible(scrollThrough(1000, [1003, 1006, 1008]))).toBe(false);
  });

  test("방향이 바뀌면 누적을 다시 센다", () => {
    // Down 5, up 2, down 5: never 8px in one direction.
    expect(visible(scrollThrough(1000, [1005, 1003, 1008]))).toBe(true);
    // Hidden, then up 5, down 2, up 5: still hidden.
    const hidden = scrollThrough(1000, [1100]);
    expect(visible(hidden)).toBe(false);
    expect(visible(scrollThrough(1100, [1095, 1097, 1092], hidden))).toBe(false);
  });

  test("숨긴 뒤 위로 8px 이상이면 다시 보이고, 7px이면 숨긴 채다", () => {
    const hidden = scrollThrough(1000, [1500]);
    expect(visible(scrollThrough(1500, [1493], hidden))).toBe(false);
    expect(visible(scrollThrough(1500, [1492], hidden))).toBe(true);
    expect(visible(scrollThrough(1500, [1496, 1492], hidden))).toBe(true);
  });

  test("위치가 그대로인 스크롤 이벤트는 상태를 바꾸지 않는다", () => {
    const hidden = scrollThrough(1000, [1500]);
    expect(nextFabState(hidden, at(1500))).toEqual(hidden);
  });

  test("페이지 맨 위(scrollY 16 이하)에서는 아래로 스크롤해도 보인다", () => {
    expect(visible(scrollThrough(0, [16]))).toBe(true);
    expect(visible(scrollThrough(0, [17]))).toBe(false);
    expect(visible(scrollThrough(1000, [1500, 10]))).toBe(true);
    // iOS rubber band above the top.
    expect(visible(scrollThrough(1000, [1500, -30]))).toBe(true);
  });

  test("맨 아래에 닿으면 보인다 (innerHeight + scrollY >= scrollHeight - 4)", () => {
    expect(visible(scrollThrough(1000, [BOTTOM - 5]))).toBe(false);
    expect(visible(scrollThrough(1000, [BOTTOM - 4]))).toBe(true);
    expect(visible(scrollThrough(1000, [BOTTOM]))).toBe(true);
    // Leaving the bottom downward is impossible; a small bounce up keeps it visible.
    expect(visible(scrollThrough(1000, [BOTTOM, BOTTOM - 3]))).toBe(true);
  });

  test("맨 아래에서 다시 위로 올라갔다가 아래로 8px 이상이면 숨긴다", () => {
    expect(visible(scrollThrough(1000, [BOTTOM, BOTTOM - 400, BOTTOM - 392]))).toBe(false);
  });
});

describe("가로 스크롤", () => {
  test("페이지 안 요소가 가로로 스크롤되면 숨긴다 (맨 위에서도)", () => {
    expect(visible(nextFabState(initialFabState(1000), horizontal(1000)))).toBe(false);
    expect(visible(nextFabState(initialFabState(0), horizontal(0)))).toBe(false);
  });

  test("맨 아래에서는 숨기지 않는다 (페이지 끝 여백 덕분에 버튼이 내용을 가리지 않고, 세로로 스크롤할 수 없는 짧은 페이지에서 버튼이 사라진 채로 남지 않는다)", () => {
    expect(visible(nextFabState(initialFabState(BOTTOM), horizontal(BOTTOM)))).toBe(true);
    expect(visible(nextFabState(initialFabState(0), horizontal(0, 600, VIEWPORT)))).toBe(true);
  });

  test("가로 스크롤로 숨긴 뒤에는 위로 8px 이상 스크롤해야 다시 보인다 (그 전 누적은 버린다)", () => {
    const upFirst = scrollThrough(1500, [1495]);
    const hidden = nextFabState(upFirst, horizontal(1495));
    expect(visible(hidden)).toBe(false);
    expect(visible(scrollThrough(1495, [1490], hidden))).toBe(false);
    expect(visible(scrollThrough(1495, [1487], hidden))).toBe(true);
    expect(visible(scrollThrough(1495, [BOTTOM], hidden))).toBe(true);
  });

  test("isHorizontalScroll: 요소의 scrollLeft가 바뀐 경우만 가로 스크롤이다 (처음 본 요소는 0에서 시작)", () => {
    expect(isHorizontalScroll(undefined, 0)).toBe(false);
    expect(isHorizontalScroll(undefined, 40)).toBe(true);
    expect(isHorizontalScroll(40, 40)).toBe(false);
    expect(isHorizontalScroll(40, 0)).toBe(true);
    expect(isHorizontalScroll(0, 0.5)).toBe(true);
  });
});

describe("포커스와 챗봇 창", () => {
  test("포커스를 받은 버튼은 숨긴 상태여도 보인다", () => {
    const hidden = scrollThrough(1000, [1500]);
    expect(visible(hidden, true)).toBe(true);
    expect(visible(nextFabState(initialFabState(1000), horizontal(1000)), true)).toBe(true);
  });

  test("show 이벤트(포커스, 챗봇 창 열고 닫기)는 숨김을 풀고, 이후 아래로 8px 이상이면 다시 숨긴다", () => {
    const shown = nextFabState(scrollThrough(1000, [1500]), { type: "show" });
    expect(visible(shown)).toBe(true);
    expect(visible(scrollThrough(1500, [1507], shown))).toBe(true);
    expect(visible(scrollThrough(1500, [1508], shown))).toBe(false);
  });

  test("챗봇 창이 열려 있는 동안은 보인다", () => {
    const hidden = scrollThrough(1000, [1500]);
    expect(visible(hidden, false, true)).toBe(true);
    expect(visible(hidden, false, false)).toBe(false);
  });
});
