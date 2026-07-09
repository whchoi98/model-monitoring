// 트렌드 차트 기본 선택·URL 상태 헬퍼 (v2.7.1 가독성 개선).
//
// 28개 모델 라인 동시 표시는 판독 불가 → 첫 방문 기본값은 패밀리별 대표 1개(~10라인).
// 선택 상태(models/hours/category)는 URL query로 직렬화해 새로고침 유지 + 링크 공유 지원.
import { channelRank, familyRank } from "./sortModels";

/** 패밀리별 대표 모델 1개(채널 우선순위 최상위)를 기본 선택으로 반환. */
export function defaultTrendSelection(modelNames: string[]): Set<string> {
  const best = new Map<number, string>(); // familyRank -> 대표 모델명
  for (const name of modelNames) {
    const fam = familyRank(name);
    const cur = best.get(fam);
    if (cur === undefined || channelRank(name) < channelRank(cur)) {
      best.set(fam, name);
    }
  }
  return new Set(best.values());
}

export interface TrendQueryState {
  /** undefined = URL에 models 파라미터 없음(첫 방문 → 대표 기본값 적용 신호) */
  models: Set<string> | undefined;
  /** true = 사용자가 명시적으로 전체 보기(models=all)를 선택 */
  explicitAll: boolean;
  hours: number | undefined;
  category: string | null;
}

const ALL_SENTINEL = "all";

/** 현재 선택 상태를 URL query string으로 직렬화 ("?models=..&hours=..&category=.."). */
export function buildTrendQuery(
  models: Set<string>,
  hours: number,
  category: string | null,
): string {
  const sp = new URLSearchParams();
  sp.set("models", models.size === 0 ? ALL_SENTINEL : Array.from(models).sort().join(","));
  sp.set("hours", String(hours));
  if (category) sp.set("category", category);
  return `?${sp.toString()}`;
}

/** URL query string에서 선택 상태 복원. */
export function parseTrendQuery(search: string): TrendQueryState {
  const sp = new URLSearchParams(search);
  const rawModels = sp.get("models");
  const rawHours = sp.get("hours");
  const hours = rawHours !== null && !Number.isNaN(Number(rawHours)) ? Number(rawHours) : undefined;

  let models: Set<string> | undefined;
  let explicitAll = false;
  if (rawModels === ALL_SENTINEL) {
    models = new Set();
    explicitAll = true;
  } else if (rawModels) {
    models = new Set(rawModels.split(",").filter(Boolean));
  }

  return { models, explicitAll, hours, category: sp.get("category") };
}
