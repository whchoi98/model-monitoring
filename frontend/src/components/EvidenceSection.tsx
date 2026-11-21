// 증거 대화상자(/parity, /claude-features)의 접이식 JSON 영역.
// 모듈 최상위 컴포넌트여야 한다 — 대화상자 렌더 함수 안에서 만들면 부모가 다시 그려질 때마다(자동 새로고침 카운트다운, 1초)
// 컴포넌트 타입이 바뀌어 <details>가 재마운트되고, 펼친 영역이 다시 접히며 summary의 키보드 포커스가 사라진다 (v2.44.2).
// defaultOpen은 처음 상태만 정한다. 값이 바뀌지 않는 한 React가 open 속성을 다시 쓰지 않아 사용자가 여닫은 상태가 남는다.
export default function EvidenceSection({ title, json, tone, defaultOpen }: {
  title: string; json: unknown; tone?: "error"; defaultOpen: boolean;
}) {
  return (
    <details open={defaultOpen} className="group">
      <summary className="cursor-pointer select-none text-sm text-gray-400 hover:text-gray-200 py-1">
        <span className="inline-block w-3 text-xs transition-transform group-open:rotate-90">▶</span> {title}
      </summary>
      <pre className={`mt-1 rounded-lg p-3 overflow-x-auto text-xs leading-relaxed border ${
        tone === "error" ? "bg-gray-950 border-rose-500/30 text-rose-300 whitespace-pre-wrap break-all" : "bg-gray-950 border-gray-800 text-gray-200"
      }`}>
        {typeof json === "string" ? json : JSON.stringify(json ?? {}, null, 2)}
      </pre>
    </details>
  );
}
