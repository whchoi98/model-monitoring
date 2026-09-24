import type { TrendPoint } from "./types";
import { parseTimestamp } from "./format";

export type TrendMetric = "ttft_ms" | "total_latency_ms" | "tps";

export interface PivotedTrend {
  modelNames: string[];
  chartData: TrendRow[];
  /** Only a model's own samples belong to its line; explicit failures stay null. */
  seriesData: Record<string, TrendRow[]>;
}

export interface TrendRow {
  timestamp: string;
  time: number;
  [key: string]: string | number | number[] | null;
}

export interface PivotOptions {
  /** true면 집계 행의 [min,max]를 `<모델명>__range` 컬럼으로 추가 (Recharts range Area용). */
  withRange?: boolean;
  /** Expected spacing of one series; a longer silence breaks its line. A function gets the series' model_id
   *  (v2.29.0: Claude Platform on AWS is sampled every 10 minutes, other channels every 5). */
  cadenceSeconds?: number | ((modelId: string) => number);
}

/** Isolated successes need dots even when dense charts omit ordinary markers. */
export function isolatedSampleTimes(
  points: ReadonlyArray<Record<string, unknown>>,
  valueKey: string,
  timeKey = "time",
): Set<number> {
  const measured = (point: Record<string, unknown> | undefined) => typeof point?.[valueKey] === "number" && Number.isFinite(point[valueKey]);
  return new Set(points.filter((point, index) =>
    measured(point) && !measured(points[index - 1]) && !measured(points[index + 1]) && typeof point[timeKey] === "number",
  ).map((point) => point[timeKey] as number));
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
  const rows = new Map<number, TrendRow>();
  const series = new Map<string, Map<number, TrendRow>>();
  const seriesModelId = new Map<string, string>();

  for (const d of data) {
    if (hasSelection && !selectedModels!.has(d.model_name)) continue;
    const time = parseTimestamp(d.timestamp);
    if (time === null) continue;
    modelSet.add(d.model_name);
    let row = rows.get(time);
    if (!row) {
      row = { timestamp: d.timestamp, time };
      rows.set(time, row);
    }
    row[d.model_name] = d.status === "success" && d[metric] != null && Number.isFinite(d[metric]) ? d[metric] : null;
    if (!series.has(d.model_name)) {
      series.set(d.model_name, new Map());
      seriesModelId.set(d.model_name, d.model_id);
    }
    series.get(d.model_name)!.set(time, row);
    if (options?.withRange && d.status === "success") {
      const lo = d[`${metric}_min` as keyof TrendPoint] as number | null | undefined;
      const hi = d[`${metric}_max` as keyof TrendPoint] as number | null | undefined;
      if (lo != null && hi != null && Number.isFinite(lo) && Number.isFinite(hi) && lo <= hi) {
        row[`${d.model_name}__range`] = [lo, hi];
      }
    }
  }

  const modelNames = Array.from(modelSet);
  const chartData = Array.from(rows.values()).sort((a, b) => a.time - b.time);
  // 결측 모델 컬럼을 null로 채움 (Line dataKey가 undefined면 tooltip/connectNulls 동작 차이 방지).
  for (const row of chartData) {
    for (const name of modelNames) {
      if (!(name in row)) row[name] = null;
    }
  }

  const seriesData: Record<string, TrendRow[]> = Object.create(null);
  for (const name of modelNames) {
    const points = Array.from(series.get(name)!.values()).sort((a, b) => a.time - b.time);
    const option = options?.cadenceSeconds;
    const cadence = typeof option === "function" ? option(seriesModelId.get(name) ?? name) : option;
    const withGaps: TrendRow[] = [];
    for (const point of points) {
      const previous = withGaps[withGaps.length - 1];
      if (cadence && previous && point.time - previous.time > (cadence + Math.min(cadence, 300)) * 1000) {
        const time = previous.time + cadence * 1000;
        withGaps.push({ time, timestamp: new Date(time).toISOString(), [name]: null });
      }
      withGaps.push(point);
    }
    seriesData[name] = withGaps;
  }
  return { modelNames, chartData, seriesData };
}
