import type { TrendPoint } from "./types";

export type TrendMetric = "ttft_ms" | "total_latency_ms" | "tps";

export interface PivotedTrend {
  modelNames: string[];
  chartData: Array<Record<string, string | number | number[] | null>>;
}

export interface PivotOptions {
  /** true면 집계 행의 [min,max]를 `<모델명>__range` 컬럼으로 추가 (Recharts range Area용). */
  withRange?: boolean;
}

/**
 * TrendPoint 배열을 Recharts LineChart용 wide 포맷으로 피벗한다.
 * { timestamp, time, [modelName]: metricValue, ... } 행 하나가 한 시점.
 *
 * 단일 패스 Map 집계 O(N) — TrendChart가 매 렌더마다 호출하므로
 * timestamp×model 중첩 탐색(O(T×M×N)) 구현으로 되돌리면 안 된다 (pivotTrend.test.ts).
 */
export function pivotTrend(
  data: TrendPoint[],
  metric: TrendMetric,
  selectedModels?: Set<string>,
  options?: PivotOptions,
): PivotedTrend {
  const hasSelection = !!selectedModels && selectedModels.size > 0;

  const modelSet = new Set<string>();
  const rows = new Map<string, Record<string, string | number | number[] | null>>();

  for (const d of data) {
    if (hasSelection && !selectedModels!.has(d.model_name)) continue;
    modelSet.add(d.model_name);
    let row = rows.get(d.timestamp);
    if (!row) {
      row = {
        timestamp: d.timestamp,
        time: new Date(d.timestamp).toLocaleTimeString("ko-KR", {
          hour: "2-digit",
          minute: "2-digit",
        }),
      };
      rows.set(d.timestamp, row);
    }
    row[d.model_name] = d[metric];
    if (options?.withRange) {
      const lo = d[`${metric}_min` as keyof TrendPoint] as number | null | undefined;
      const hi = d[`${metric}_max` as keyof TrendPoint] as number | null | undefined;
      if (lo != null && hi != null) {
        row[`${d.model_name}__range`] = [lo, hi];
      }
    }
  }

  const modelNames = Array.from(modelSet);
  const chartData = Array.from(rows.values()).sort((a, b) =>
    (a.timestamp as string) < (b.timestamp as string) ? -1 : 1,
  );
  // 결측 모델 컬럼을 null로 채움 (Line dataKey가 undefined면 tooltip/connectNulls 동작 차이 방지).
  for (const row of chartData) {
    for (const name of modelNames) {
      if (!(name in row)) row[name] = null;
    }
  }

  return { modelNames, chartData };
}
