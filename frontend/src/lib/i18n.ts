export interface MetricInfo {
  name: string;
  unit: string;
  desc: string;
}

export interface Translations {
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
  overloadedHint: "Vendor 일시 과부하 — 2초/4초/8초 backoff로 자동 재시도 완료. 다음 5분 주기에 자동 재시도합니다.",
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
  overloadedHint: "Vendor temporarily overloaded — auto-retried 2× with 2/4/8s backoff. Will auto-retry next 5-min cycle.",
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
