#!/usr/bin/env bash
# README 아키텍처 다이어그램과 인포그래픽을 다시 만든다 → docs/images/architecture/
#
#   AWS_ICON_BUNDLE=<aws-diagram 스킬>/assets/icons.json scripts/readme-art/build.sh
#
# 필요한 것
#   - python3 + Pillow, frontend/node_modules (playwright chromium: `cd frontend && npm ci && npx playwright install chromium`)
#   - 공식 AWS 아이콘 번들 (aws-diagram 스킬의 assets/icons.json) — AWS_ICON_BUNDLE
#   - 글꼴: Amazon Ember(다이어그램), NanumSquareOTF와 D2Coding(인포그래픽, INFOKIT_FONTS 기본 ~/.local/share/fonts)
#     글꼴이 없으면 대체 글꼴로 그려져 글자 폭이 달라지므로 PNG를 커밋하지 않는다.
#
# 채널 수, 예약 태스크, 화면 수가 바뀌면 architecture.py의 T와 glance.py의 행렬과 T를 고친 뒤 실행한다.
# 인포그래픽은 문구 규칙(lint)과 배치(QA: 넘침, 겹침)를 통과해야 끝난다.
set -euo pipefail

: "${AWS_ICON_BUNDLE:?AWS_ICON_BUNDLE에 aws-diagram 스킬의 assets/icons.json 경로를 준다}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/scripts/readme-art"
OUT="$ROOT/docs/images/architecture"
mkdir -p "$OUT"

FONTS="$(fc-list : family)"
for f in "Amazon Ember" "NanumSquareOTF" "D2Coding"; do
  grep -qi "$f" <<<"$FONTS" || echo "경고: 글꼴 '$f'가 없다. 대체 글꼴로 그려진다" >&2
done

cd "$SRC"
for lang in en ko; do
  python3 architecture.py "$lang" "$OUT/architecture-$lang.svg"
done
python3 glance.py "$OUT"

cd "$ROOT/frontend"
for lang in en ko; do
  node "$SRC/render.js" "$OUT/architecture-$lang.svg" "$OUT/architecture-$lang.png" 2
  for theme in light dark; do
    node "$SRC/render.js" "$OUT/infographic-$lang-$theme.svg" "$OUT/infographic-$lang-$theme.png" 1 --qa
  done
done
ls -la "$OUT"
