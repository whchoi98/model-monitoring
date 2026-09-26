// 비용 표시 포맷 (USD). 단가는 v2.30.0부터 백엔드 단일 출처다 — 현재 단가는 GET /api/pricing의
// `models`, 호출 비용 계산은 lib/pricingTable.ts `costFromPrices`, 비용 화면 합계는 백엔드가
// 각 프로브 시각의 단가로 계산한다(ADR-030). 이 파일에 단가 표를 다시 두지 말 것.

export function formatCost(usd: number | null): string {
  if (usd === null || usd === undefined) return "—";
  if (usd < 0.001) return `$${(usd * 1000).toFixed(2)}m`; // milli-dollars
  if (usd < 1) return `$${(usd * 100).toFixed(2)}¢`;
  return `$${usd.toFixed(4)}`;
}
