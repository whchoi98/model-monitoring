// 모델 카드/이력 정렬 공통 유틸.
// 1차: 모델 family 우선순위 (Fable 5 > Opus 4.8 > Opus 4.7 > Opus 4.6 > Sonnet 5 > Sonnet 4.6 > Haiku 4.5 > Nova ...)
// 2차: 채널 순서 (Anthropic > Bedrock Global > Bedrock US)
// FAMILY 매칭은 substring `includes` 기반이므로 "Bedrock " prefix 유무에 관계없이 동작.
// 모델명 라벨은 backend에서 "Bedrock " 또는 "Anthropic " prefix가 붙은 형태로 응답.
export const FAMILY_ORDER = [
  "Claude Fable 5",
  "Claude Opus 5",
  "Claude Opus 4.8",
  "Claude Opus 4.7",
  "Claude Opus 4.6",
  "Claude Sonnet 5",
  "Claude Sonnet 4.6",
  "Claude Haiku 4.5",
  "Nova 2.0 Lite",
  "GPT 5.6 Sol",
  "GPT 5.6 Terra",
  "GPT 5.6 Luna",
  "GPT 5.5",
  "GPT 5.4",
];

// 모니터링 catalogue에서 제외된 모델 (ADR-017). backend silent bug 대비 frontend hard-filter.
// "(1P)": OpenAI 1P direct 채널 — 2026-07-31 사용자 결정으로 비교에서 제외(비노출).
// 백엔드 등록은 env로 꺼졌고(ENABLE_OPENAI_1P), 이 필터는 과거 DB 행의 노출을 막는 이중 방어.
const EXCLUDED_FAMILIES = ["Opus 4.5", "Sonnet 4.5", "(1P)"];

export function isExcludedModel(modelName: string): boolean {
  return EXCLUDED_FAMILIES.some((p) => modelName.includes(p));
}

export function familyRank(name: string): number {
  for (let i = 0; i < FAMILY_ORDER.length; i++) {
    if (name.includes(FAMILY_ORDER[i])) return i;
  }
  return FAMILY_ORDER.length;
}

export function channelRank(name: string): number {
  if (name.startsWith("Anthropic ")) return 0;
  if (name.includes("(Global)")) return 1;
  if (name.startsWith("OpenAI ")) return 3; // OpenAI 자체 채널 티어 (us-east-1 → us-east-2)
  return 2; // Bedrock US (default)
}

export function sortResults<T extends { model_name: string }>(results: T[]): T[] {
  return [...results].sort((a, b) => {
    const fa = familyRank(a.model_name);
    const fb = familyRank(b.model_name);
    if (fa !== fb) return fa - fb;
    const ca = channelRank(a.model_name);
    const cb = channelRank(b.model_name);
    if (ca !== cb) return ca - cb;
    return a.model_name.localeCompare(b.model_name);
  });
}

/** 정렬 후 family 단위로 그룹화 — 각 family가 별도 row를 차지하도록 UI에서 사용. */
export function groupByFamily<T extends { model_name: string }>(results: T[]): T[][] {
  const sorted = sortResults(results);
  const groups: T[][] = [];
  let current: T[] = [];
  let currentRank = -1;
  for (const r of sorted) {
    const rank = familyRank(r.model_name);
    if (rank !== currentRank) {
      if (current.length) groups.push(current);
      current = [r];
      currentRank = rank;
    } else {
      current.push(r);
    }
  }
  if (current.length) groups.push(current);
  return groups;
}
