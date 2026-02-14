export const ko = {
  // Top tabs
  dashboardTab: "대시보드",
  manualProbeTab: "수동 프로브",

  // Header
  appTitle: "Bedrock LLM 모니터",
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
  seconds: "초",
  triggerNow: "지금 실행",
  triggering: "실행 요청 중...",
  cycleRunning: "프로빙 진행 중",

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

  // Time
  justNow: "방금 전",
  minutesAgo: (n: number) => `${n}분 전`,
  hoursAgo: (n: number) => `${n}시간 전`,

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
} as const;
