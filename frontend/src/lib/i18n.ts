import type { WorkloadCategoryId } from "./metricGrade";

export interface MetricInfo {
  name: string;
  unit: string;
  desc: string;
}

/** 카드 지표 등급 툴팁 입력 (lib/metricGrade.ts describeGrade 결과 + 표시용 이름). */
export interface GradeHintParams {
  grade: "normal" | "warning" | "critical";
  metric: string;
  scope: string;
  warnAt: number;
  critAt: number;
  unit: "ms" | "tok/s";
  lowerIsWorse: boolean;
}

export interface MetricGradeTexts {
  names: Record<"normal" | "warning" | "critical", string>;
  legendLabel: string;
  legendScope: string;
  showCriteria: string;
  criteriaNote: string;
  allWorkloads: string;
  defaultCategory: string;
  categories: Record<WorkloadCategoryId, string>;
  threshold: (value: number, unit: "ms" | "tok/s") => string;
  hint: (params: GradeHintParams) => string;
}

// 임계치 표기 — 지연시간은 초 단위(3.5초), TPS는 tok/s 그대로.
const koThreshold = (value: number, unit: "ms" | "tok/s") => unit === "ms" ? `${Number((value / 1000).toFixed(1))}초` : `${value} tok/s`;
const enThreshold = (value: number, unit: "ms" | "tok/s") => unit === "ms" ? `${Number((value / 1000).toFixed(1))} s` : `${value} tok/s`;

// 등급 이름 단일 출처 — 범례(names)와 툴팁(hint) 문구가 같은 객체를 읽는다.
// KO normal은 "양호": 채널 건강 배지(monitoring.health.healthy "정상")와 같은 단어면 한 카드에
// "✓ 정상" 배지와 ◆ 위험 값이 함께 보여 모순처럼 읽힌다(ADR-029). EN은 Healthy/Normal로 이미 구분된다.
const koGradeNames: MetricGradeTexts["names"] = { normal: "양호", warning: "경고", critical: "위험" };
const enGradeNames: MetricGradeTexts["names"] = { normal: "Normal", warning: "Warning", critical: "Critical" };

export interface Translations {
  common: {
    loading: string;
    retry: string;
    refresh: string;
    refreshing: string;
    autoRefresh: string;
    paused: string;
    updatedAt: string;
    notUpdated: string;
    failedToLoad: (resource: string) => string;
    lastGoodData: string;
    loadErrorHint: string;
    timeoutHint: string;
    authRequired: string;
    noData: string;
    noDataHint: string;
    resetFilters: string;
    streamInterrupted: string;
  };
  monitoring: {
    title: string;
    description: string;
    overview: string;
    monitored: string;
    observed: (count: number) => string;
    healthy: string;
    healthyHint: string;
    attention: string;
    attentionHint: string;
    successRate: string;
    successRateHint: string;
    health: Record<"healthy" | "error" | "overloaded" | "stale" | "unknown", string>;
    collection: string;
    overdue: string;
    failed: string;
    unverified: string;
    cadence: (minutes: number) => string;
    categoryCadence: (minutes: number) => string;
    latestResults: string;
    catalog: string;
    catalogRequired: string;
    unlistedChannels: (count: number) => string;
    recentFailures: string;
    recentFailuresTitle: (count: number) => string;
    noFailures: string;
    noProbes: string;
    probeCount: (count: number) => string;
    viewReliability: string;
    viewTrends: string;
    trends: string;
    search: string;
    searchPlaceholder: string;
    statusFilter: string;
    sort: string;
    sortFamily: string;
    sortAttention: string;
    sortTtft: string;
    allStatuses: string;
    failuresOnly: string;
    staleOnly: string;
    visibleCount: (visible: number, total: number) => string;
    noMatchingModels: string;
    selectHint: string;
    selection: (count: number) => string;
    clearSelection: string;
    selectModel: (name: string) => string;
    compareSelection: string;
    noTrend: string;
    noTrendHint: string;
    noMetric: string;
    noMetricHint: string;
    trendHint: string;
    singlePoint: string;
    aggregationHint: string;
    showDetails: string;
    missingHint: string;
    staleHint: string;
    unknownTime: string;
    lastResult: string;
    loginToTrigger: string;
    triggerAccepted: string;
    triggerBusy: string;
    triggerFailed: string;
    metricGuide: string;
    channelsGuide: string;
    selectionMissing: string;
    grade: MetricGradeTexts;
  };
  // Top tabs
  dashboardTab: string;
  manualProbeTab: string;

  // Header
  appTitle: string;
  appDesc: string;
  history: string;

  // Dashboard
  autoProbeStatus: string;
  lastProbe: string;
  nextProbe: string;
  interval: string;
  running: string;
  waiting: string;
  modelStatus: string;
  latencyTrend: string;
  ttftTrend: string;
  tpsTrend: string;
  noDataYet: string;
  noDataDesc: string;
  autoRefresh: string;
  refreshing: string;
  allModels: string;
  repModels: string;
  repModelsHint: string;
  seconds: string;
  minutes: string;
  triggerNow: string;
  triggering: string;
  cycleRunning: string;
  trendRange: string;
  metricDescTitle: string;
  trendRangeLabel: (hours: number) => string;
  channelDescTitle: string;
  channels: {
    bedrock: { name: string; desc: string; endpoint: string };
    anthropic: { name: string; desc: string; endpoint: string };
  };

  // Manual probe
  readyTitle: string;
  readyDesc: string;
  runProbe: string;
  stopProbe: string;

  // Tabs
  resultsTable: string;
  chartsTab: string;
  comparisonTab: string;

  // Auth
  loginTitle: string;
  loginDesc: string;
  username: string;
  password: string;
  loginButton: string;
  registerButton: string;
  logout: string;
  loginError: string;
  registerError: string;
  registerSuccess: string;
  pendingApproval: string;
  noAccount: string;
  hasAccount: string;

  // Status
  success: string;
  error: string;
  overloaded: string;
  overloadedHint: string;
  workloadLabel: string;
  workloadAll: string;

  // Time
  justNow: string;
  minutesAgo: (n: number) => string;
  hoursAgo: (n: number) => string;

  // History panel
  historyTitle: string;
  historyProbes: string;
  historyNoData: string;
  historyModelFilter: string;
  avg: string;
  range1h: string;
  range6h: string;
  range24h: string;
  range7d: string;
  range30d: string;
  regionGlobal: string;
  regionUS: string;

  // Metric descriptions
  metrics: {
    ttft: MetricInfo;
    totalLatency: MetricInfo;
    serverLatency: MetricInfo;
    tps: MetricInfo;
    inputTokens: MetricInfo;
    outputTokens: MetricInfo;
  };
}

export const ko: Translations = {
  common: {
    loading: "데이터를 불러오는 중…", retry: "다시 시도", refresh: "새로고침", refreshing: "갱신 중…",
    autoRefresh: "자동 새로고침", paused: "일시 정지", updatedAt: "마지막 확인", notUpdated: "아직 확인 전",
    failedToLoad: (resource) => `${resource} 데이터를 불러오지 못했습니다.`,
    lastGoodData: "마지막으로 조회한 결과입니다. 최신 상태와 다를 수 있습니다.",
    loadErrorHint: "연결 상태를 확인하고 다시 시도하세요.", timeoutHint: "응답이 지연되고 있습니다. 잠시 후 다시 시도하세요.",
    authRequired: "로그인이 필요합니다.", noData: "선택한 조건에 데이터가 없습니다.",
    noDataHint: "조회 기간을 늘리거나 필터를 변경해 보세요.", resetFilters: "필터 초기화",
    streamInterrupted: "완료 전에 연결이 끊겼습니다. 수집된 결과는 유지됩니다. 연결을 확인한 뒤 다시 실행하세요.",
  },
  monitoring: {
    title: "모델 모니터링", description: "채널별 최신 응답, 수집 상태와 성능 추세를 확인하세요.",
    overview: "모니터링 요약", monitored: "모니터링 채널", observed: (count) => `${count}개 채널에서 결과 수집`,
    healthy: "정상", healthyHint: "최근 수집 주기 안에 응답 성공",
    attention: "확인 필요", attentionHint: "오류·과부하·수집 지연·미수집",
    successRate: "최신 실행 성공률", successRateHint: "수집된 채널의 마지막 결과 기준",
    health: { healthy: "정상", error: "오류", overloaded: "과부하", stale: "수집 지연", unknown: "미수집" },
    collection: "자동 수집", overdue: "수집 지연", failed: "수집 실패", unverified: "상태 확인 필요",
    cadence: (minutes) => `${minutes}분 주기`, categoryCadence: (minutes) => `선택한 워크로드는 약 ${minutes}분마다 수집됩니다.`,
    latestResults: "최신 모델 상태", catalog: "모델 목록", catalogRequired: "전체 채널 목록 확인 필요",
    unlistedChannels: (count) => `${count}개 채널의 정보를 확인하지 못했습니다. 모델 목록을 다시 불러오세요.`,
    recentFailures: "최근 실패 이력",
    recentFailuresTitle: (count) => `최근 12시간 실패 ${count}건`, noFailures: "최근 12시간 실패 없음",
    noProbes: "최근 12시간 수집 기록 없음", probeCount: (count) => `자동 프로브 ${count.toLocaleString()}회 기준`,
    viewReliability: "신뢰성 상세", viewTrends: "추세 보기", trends: "성능 추세",
    search: "모델 검색", searchPlaceholder: "모델 이름 또는 ID 검색", statusFilter: "모델 상태 필터",
    sort: "모델 정렬", sortFamily: "모델 계열순", sortAttention: "문제 우선", sortTtft: "TTFT 높은 순",
    allStatuses: "전체 상태", failuresOnly: "오류·과부하", staleOnly: "지연·미수집",
    visibleCount: (visible, total) => `${total}개 중 ${visible}개 표시`, noMatchingModels: "조건에 맞는 모델이 없습니다.",
    selectHint: "카드를 선택하면 해당 모델의 추세를 비교할 수 있습니다.",
    selection: (count) => `${count}개 선택`, clearSelection: "선택 해제", selectModel: (name) => `${name} 추세 비교 선택`,
    compareSelection: "선택 모델 추세 보기", noTrend: "이 기간에 수집된 추세 데이터가 없습니다.",
    noTrendHint: "조회 기간을 늘려 보세요. 짧은 기간에는 수집 주기에 따라 결과가 없을 수 있습니다.",
    noMetric: "이 지표의 측정값이 없습니다.", noMetricHint: "측정되지 않은 값과 실패 구간은 그래프의 빈 구간으로 표시합니다.",
    trendHint: "카드 선택은 세 그래프에 함께 적용됩니다. 빈 구간은 측정값 없음 또는 호출 실패를 의미합니다.",
    singlePoint: "측정값이 한 건뿐이므로 추세선 대신 점으로 표시합니다.",
    aggregationHint: "시간별 평균과 최소–최대 범위입니다. 성공한 호출의 측정값만 포함합니다.",
    showDetails: "오류 상세", missingHint: "이 조건의 최신 실행에 결과가 없습니다.",
    staleHint: "예상 수집 주기를 지났습니다. 마지막 결과가 현재 상태를 보장하지 않습니다.",
    unknownTime: "수집 시각 확인 필요", lastResult: "마지막 결과",
    loginToTrigger: "로그인 후 프로브 실행", triggerAccepted: "프로브 실행을 요청했습니다. 결과 수집 후 화면에 반영됩니다.",
    triggerBusy: "이미 수집 중입니다. 완료 후 다시 실행할 수 있습니다.",
    triggerFailed: "프로브 실행 요청에 실패했습니다.", metricGuide: "지표 해설", channelsGuide: "호출 채널 안내",
    selectionMissing: "선택한 모델 중 이 조건에 결과가 없는 모델이 있습니다.",
    grade: {
      names: koGradeNames,
      legendLabel: "지표 등급", legendScope: "워크로드 카테고리별 기준", showCriteria: "기준값 보기",
      criteriaNote: "지연시간은 기준값 이상, TPS는 기준값 미만이면 해당 등급입니다. 성공한 호출의 값만 판정합니다.",
      allWorkloads: "전체 워크로드 공통", defaultCategory: "카테고리 미지정",
      categories: { "chat-short": "짧은 대화", structured: "JSON 추출", summarize: "요약", translate: "번역", "code-gen": "코드 생성", reasoning: "추론" },
      threshold: koThreshold,
      hint: ({ grade, metric, scope, warnAt, critAt, unit, lowerIsWorse }) => {
        const name = koGradeNames[grade];
        const [w, c] = [koThreshold(warnAt, unit), koThreshold(critAt, unit)];
        const worse = lowerIsWorse ? "미만" : "이상";
        const rule = grade === "normal" ? `${w} ${lowerIsWorse ? "이상" : "미만"}`
          : grade === "warning" ? `${w} ${worse}, ${koGradeNames.critical} ${c} ${worse}` : `${c} ${worse}`;
        return `${name} — ${scope} 기준 ${metric} ${rule}`;
      },
    },
  },
  // Top tabs
  dashboardTab: "대시보드",
  manualProbeTab: "수동 프로브",

  // Header
  appTitle: "Amazon Bedrock LLM Monitor",
  appDesc: "실시간 모델 성능 모니터링",
  history: "이력 조회",

  // Dashboard
  autoProbeStatus: "자동 프로빙 상태",
  lastProbe: "마지막 프로빙",
  nextProbe: "다음 프로빙",
  interval: "주기",
  running: "실행 중",
  waiting: "대기 중",
  modelStatus: "모델별 최신 상태",
  latencyTrend: "응답속도 추이",
  ttftTrend: "TTFT 추이",
  tpsTrend: "처리속도(TPS) 추이",
  noDataYet: "아직 자동 프로빙 데이터가 없습니다.",
  noDataDesc: "자동 프로빙이 5분 간격으로 실행됩니다. 첫 번째 결과를 기다려주세요.",
  autoRefresh: "자동 새로고침",
  refreshing: "데이터 갱신 중…",
  allModels: "전체",
  repModels: "대표 모델",
  repModelsHint: "패밀리별 대표 채널 1개만 표시",
  seconds: "초",
  minutes: "분",
  triggerNow: "지금 실행",
  triggering: "실행 요청 중...",
  cycleRunning: "프로빙 진행 중",
  trendRange: "조회 기간",
  metricDescTitle: "지표 설명",
  trendRangeLabel: (hours: number) => {
    if (hours < 1) return `${Math.round(hours * 60)}분`;
    if (hours < 24) return `${hours}시간`;
    return `${hours / 24}일`;
  },
  channelDescTitle: "호출 채널 설명",
  channels: {
    bedrock: {
      name: "Bedrock",
      desc: "AWS Bedrock의 cross-region inference profile을 통해 호출합니다. IAM 권한으로 인증되며 AWS 청구서에 통합됩니다.",
      endpoint: "bedrock-runtime.{us-east-1 | ap-northeast-2}.amazonaws.com (us.* / global.* inference profile)",
    },
    anthropic: {
      name: "Anthropic",
      desc: "Claude Platform on AWS (Path 3 External) 채널을 통해 호출합니다. AWS Marketplace 구독으로 결제 연동되며, Anthropic이 운영하는 vendor endpoint를 사용합니다.",
      endpoint: "aws-external-anthropic.us-east-2.api.aws (x-api-key + anthropic-workspace-id 헤더)",
    },
  },

  // Manual probe
  readyTitle: "프로브 실행 준비 완료",
  readyDesc: "모델을 선택하고 프롬프트를 설정한 후 '프로브 실행' 버튼을 클릭하세요.",
  runProbe: "프로브 실행",
  stopProbe: "중지",

  // Tabs
  resultsTable: "결과 테이블",
  chartsTab: "차트",
  comparisonTab: "비교 분석",

  // Auth
  loginTitle: "로그인",
  loginDesc: "수동 프로브 기능을 사용하려면 로그인이 필요합니다.",
  username: "아이디",
  password: "비밀번호",
  loginButton: "로그인",
  registerButton: "회원가입",
  logout: "로그아웃",
  loginError: "아이디 또는 비밀번호가 올바르지 않습니다",
  registerError: "회원가입에 실패했습니다",
  registerSuccess: "회원가입이 완료되었습니다. 관리자 승인 후 로그인할 수 있습니다.",
  pendingApproval: "계정 승인 대기 중입니다. 관리자 승인 후 이용 가능합니다.",
  noAccount: "계정이 없으신가요?",
  hasAccount: "이미 계정이 있으신가요?",

  // Status
  success: "성공",
  error: "오류",
  overloaded: "일시 과부하",
  overloadedHint: "공급자가 일시적인 과부하 상태입니다. 다음 수집 주기에 다시 확인합니다.",
  workloadLabel: "워크로드",
  workloadAll: "전체",

  // Time
  justNow: "방금 전",
  minutesAgo: (n: number) => `${n}분 전`,
  hoursAgo: (n: number) => `${n}시간 전`,

  // History panel
  historyTitle: "이력 통계",
  historyProbes: "회 프로빙",
  historyNoData: "선택한 기간에 이력 데이터가 없습니다.",
  historyModelFilter: "모델 필터",
  avg: "평균",
  range1h: "1시간",
  range6h: "6시간",
  range24h: "24시간",
  range7d: "7일",
  range30d: "30일",
  regionGlobal: "Global",
  regionUS: "US",

  // Metric descriptions
  metrics: {
    ttft: {
      name: "TTFT (첫 토큰 응답시간)",
      unit: "ms",
      desc: "요청 전송 후 첫 번째 토큰이 도착하기까지의 시간. 사용자가 체감하는 초기 응답 속도를 나타냅니다.",
    },
    totalLatency: {
      name: "총 응답시간",
      unit: "ms",
      desc: "요청 전송부터 마지막 토큰 수신까지의 전체 소요 시간. 클라이언트 측에서 측정한 end-to-end 지연시간입니다.",
    },
    serverLatency: {
      name: "서버 처리시간",
      unit: "ms",
      desc: "Bedrock 서버가 보고한 내부 처리 시간. 총 응답시간과의 차이가 네트워크 오버헤드입니다.",
    },
    tps: {
      name: "TPS (토큰/초)",
      unit: "tok/s",
      desc: "초당 생성 토큰 수. 첫 토큰 이후부터 마지막 토큰까지의 출력 처리량을 나타냅니다.",
    },
    inputTokens: {
      name: "입력 토큰",
      unit: "개",
      desc: "프롬프트가 소비한 토큰 수. 비용 산정의 기준이 됩니다.",
    },
    outputTokens: {
      name: "출력 토큰",
      unit: "개",
      desc: "모델이 생성한 응답 토큰 수. 비용 및 TPS 계산에 사용됩니다.",
    },
  },
};

export const en: Translations = {
  common: {
    loading: "Loading data…", retry: "Retry", refresh: "Refresh", refreshing: "Refreshing…",
    autoRefresh: "Auto refresh", paused: "Paused", updatedAt: "Last checked", notUpdated: "Not checked yet",
    failedToLoad: (resource) => `Could not load ${resource}.`,
    lastGoodData: "Showing the last successful result. It may no longer reflect the current state.",
    loadErrorHint: "Check your connection and try again.", timeoutHint: "The request is taking too long. Try again shortly.",
    authRequired: "Sign in to continue.", noData: "No data matches these filters.",
    noDataHint: "Choose a longer time range or change the filters.", resetFilters: "Reset filters",
    streamInterrupted: "The connection ended before completion. Partial results are preserved. Check your connection and run again.",
  },
  monitoring: {
    title: "Model monitoring", description: "Track the latest responses, collection health and performance across channels.",
    overview: "Monitoring overview", monitored: "Monitored channels", observed: (count) => `${count} channels with results`,
    healthy: "Healthy", healthyHint: "Successful response within the collection cadence",
    attention: "Needs attention", attentionHint: "Errors, overloads, stale or missing results",
    successRate: "Latest run success rate", successRateHint: "Last result from channels with observations",
    health: { healthy: "Healthy", error: "Error", overloaded: "Overloaded", stale: "Stale", unknown: "Unmeasured" },
    collection: "Collection", overdue: "Collection overdue", failed: "Collection failed", unverified: "Status unverified",
    cadence: (minutes) => `Every ${minutes} min`, categoryCadence: (minutes) => `This workload is collected about every ${minutes} minutes.`,
    latestResults: "latest model status", catalog: "model catalog", catalogRequired: "Full channel coverage is unknown",
    unlistedChannels: (count) => `${count} channels could not be identified. Retry loading the model catalog.`,
    recentFailures: "recent failures",
    recentFailuresTitle: (count) => `${count} failures in the last 12h`, noFailures: "No failures in the last 12h",
    noProbes: "No probes in the last 12h", probeCount: (count) => `Across ${count.toLocaleString()} automatic probes`,
    viewReliability: "Reliability details", viewTrends: "View trends", trends: "Performance trends",
    search: "Search models", searchPlaceholder: "Search by model name or ID", statusFilter: "Model status filter",
    sort: "Sort models", sortFamily: "Model family", sortAttention: "Attention first", sortTtft: "Highest TTFT",
    allStatuses: "All statuses", failuresOnly: "Errors and overloads", staleOnly: "Stale and unmeasured",
    visibleCount: (visible, total) => `${visible} of ${total} channels`, noMatchingModels: "No models match these filters.",
    selectHint: "Select cards to compare their performance trends.",
    selection: (count) => `${count} selected`, clearSelection: "Clear selection", selectModel: (name) => `Compare trends for ${name}`,
    compareSelection: "Compare selected models", noTrend: "No trend data in this time range.",
    noTrendHint: "Choose a longer range. A short window may fall between collection cycles.",
    noMetric: "No measurements for this metric.", noMetricHint: "Missing measurements and failed calls appear as gaps.",
    trendHint: "Model selection applies to all three charts. Gaps indicate missing measurements or failed calls.",
    singlePoint: "Only one measurement is available; shown as a point instead of a trend line.",
    aggregationHint: "Hourly averages with minimum–maximum ranges. Only successful calls contribute measurements.",
    showDetails: "Error details", missingHint: "No result for this channel in the latest matching run.",
    staleHint: "The expected collection cadence has elapsed. This result may not reflect the current state.",
    unknownTime: "Collection time unknown", lastResult: "Last result",
    loginToTrigger: "Sign in to run a probe", triggerAccepted: "Probe requested. Results will appear after collection completes.",
    triggerBusy: "Collection is already running. Wait for it to finish before starting another probe.",
    triggerFailed: "Could not start the probe.", metricGuide: "Metric guide", channelsGuide: "Channel guide",
    selectionMissing: "Some selected models have no results matching these filters.",
    grade: {
      names: enGradeNames,
      legendLabel: "Metric grades", legendScope: "graded per workload category", showCriteria: "View thresholds",
      criteriaNote: "Latency is graded at or above each value, TPS below it. Only successful calls are graded.",
      allWorkloads: "All workloads", defaultCategory: "Uncategorized",
      categories: { "chat-short": "Short chat", structured: "JSON extraction", summarize: "Summarization", translate: "Translation", "code-gen": "Code generation", reasoning: "Reasoning" },
      threshold: enThreshold,
      hint: ({ grade, metric, scope, warnAt, critAt, unit, lowerIsWorse }) => {
        const name = enGradeNames[grade];
        const [w, c] = [enThreshold(warnAt, unit), enThreshold(critAt, unit)];
        const worse = lowerIsWorse ? "below" : "at or above";
        const rule = grade === "normal" ? `${metric} ${lowerIsWorse ? "at or above" : "below"} ${w}`
          : grade === "warning" ? `${metric} ${worse} ${w}, ${enGradeNames.critical.toLowerCase()} ${worse} ${c}` : `${metric} ${worse} ${c}`;
        return `${name} — ${scope}: ${rule}`;
      },
    },
  },
  // Top tabs
  dashboardTab: "Dashboard",
  manualProbeTab: "Manual Probe",

  // Header
  appTitle: "Amazon Bedrock LLM Monitor",
  appDesc: "Real-time model performance monitoring",
  history: "History",

  // Dashboard
  autoProbeStatus: "Auto-Probe Status",
  lastProbe: "Last Probe",
  nextProbe: "Next Probe",
  interval: "Interval",
  running: "Running",
  waiting: "Waiting",
  modelStatus: "Latest Model Status",
  latencyTrend: "Latency Trend",
  ttftTrend: "TTFT Trend",
  tpsTrend: "TPS Trend",
  noDataYet: "No auto-probe data yet.",
  noDataDesc: "Auto-probing runs every 5 minutes. Please wait for the first result.",
  autoRefresh: "Auto Refresh",
  refreshing: "Refreshing…",
  allModels: "All",
  repModels: "Representatives",
  repModelsHint: "Show one representative channel per family",
  seconds: "s",
  minutes: "m",
  triggerNow: "Run Now",
  triggering: "Triggering...",
  cycleRunning: "Probing in progress",
  trendRange: "Time Range",
  metricDescTitle: "Metric Descriptions",
  trendRangeLabel: (hours: number) => {
    if (hours < 1) return `${Math.round(hours * 60)}m`;
    if (hours < 24) return `${hours}h`;
    return `${hours / 24}d`;
  },
  channelDescTitle: "Invocation Channels",
  channels: {
    bedrock: {
      name: "Bedrock",
      desc: "Invoked via AWS Bedrock cross-region inference profiles. Authenticated by IAM; usage rolls up to your AWS bill.",
      endpoint: "bedrock-runtime.{us-east-1 | ap-northeast-2}.amazonaws.com (us.* / global.* inference profile)",
    },
    anthropic: {
      name: "Anthropic",
      desc: "Invoked via Claude Platform on AWS (Path 3 External). Billed through AWS Marketplace subscription, using Anthropic's vendor-hosted endpoint.",
      endpoint: "aws-external-anthropic.us-east-2.api.aws (x-api-key + anthropic-workspace-id headers)",
    },
  },

  // Manual probe
  readyTitle: "Ready to Run Probe",
  readyDesc: "Select a model, configure the prompt, and click 'Run Probe'.",
  runProbe: "Run Probe",
  stopProbe: "Stop",

  // Tabs
  resultsTable: "Results Table",
  chartsTab: "Charts",
  comparisonTab: "Comparison",

  // Auth
  loginTitle: "Login",
  loginDesc: "Login is required to use manual probe features.",
  username: "Username",
  password: "Password",  // pragma: allowlist secret
  loginButton: "Login",
  registerButton: "Register",
  logout: "Logout",
  loginError: "Invalid username or password",
  registerError: "Registration failed",
  registerSuccess: "Registration complete. You can log in after admin approval.",
  pendingApproval: "Account pending approval. Please wait for admin approval.",
  noAccount: "Don't have an account?",
  hasAccount: "Already have an account?",

  // Status
  success: "OK",
  error: "Error",
  overloaded: "Overloaded",
  overloadedHint: "The provider is temporarily overloaded. The next collection cycle will check again.",
  workloadLabel: "Workload",
  workloadAll: "All",

  // Time
  justNow: "Just now",
  minutesAgo: (n: number) => `${n}m ago`,
  hoursAgo: (n: number) => `${n}h ago`,

  // History panel
  historyTitle: "Historical Stats",
  historyProbes: " probes",
  historyNoData: "No historical data available for this time range.",
  historyModelFilter: "Model filter",
  avg: "Avg",
  range1h: "1 Hour",
  range6h: "6 Hours",
  range24h: "24 Hours",
  range7d: "7 Days",
  range30d: "30 Days",
  regionGlobal: "Global",
  regionUS: "US",

  // Metric descriptions
  metrics: {
    ttft: {
      name: "TTFT (Time to First Token)",
      unit: "ms",
      desc: "Time from request to first token arrival. Represents perceived initial response speed.",
    },
    totalLatency: {
      name: "Total Latency",
      unit: "ms",
      desc: "End-to-end time from request to last token. Client-measured total latency.",
    },
    serverLatency: {
      name: "Server Latency",
      unit: "ms",
      desc: "Internal processing time reported by Bedrock. Difference from total latency = network overhead.",
    },
    tps: {
      name: "TPS (Tokens/sec)",
      unit: "tok/s",
      desc: "Tokens per second. Output throughput from first to last token.",
    },
    inputTokens: {
      name: "Input Tokens",
      unit: "tokens",
      desc: "Tokens consumed by the prompt. Basis for cost calculation.",
    },
    outputTokens: {
      name: "Output Tokens",
      unit: "tokens",
      desc: "Tokens generated by the model. Used for cost and TPS calculation.",
    },
  },
};

export type Lang = "ko" | "en";
