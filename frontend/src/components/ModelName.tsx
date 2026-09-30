// 모델 라벨의 끝 괄호 채널 표기("(ap-northeast-2)", "(Global)")를 한 덩어리로 줄바꿈한다 (v2.32.0).
// 브라우저는 하이픈 뒤에서 줄을 나누므로 390px 카드 제목이 "… Opus 5 (ap-" / "northeast-2)"로 끊겼다.
// 공백 없는 괄호 토큰만 묶어 긴 괄호 문구가 칸 밖으로 넘치지 않게 한다. 보이는 텍스트는 그대로다.

/** "Bedrock Claude Opus 5 (ap-northeast-2)" → ["Bedrock Claude Opus 5", "(ap-northeast-2)"], 서픽스가 없으면 null. */
export function splitChannelSuffix(name: string): [string, string] | null {
  const match = /^(.*\S)\s+(\([^\s()]+\))$/.exec(name);
  return match ? [match[1], match[2]] : null;
}

export default function ModelName({ name }: { name: string }) {
  const parts = splitChannelSuffix(name);
  if (!parts) return <>{name}</>;
  return <>{`${parts[0]} `}<span className="whitespace-nowrap">{parts[1]}</span></>;
}
