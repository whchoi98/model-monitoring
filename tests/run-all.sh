#!/usr/bin/env bash
# Test runner with TAP-style output
set -euo pipefail

PASS=0
FAIL=0
TOTAL=0

assert_ok() {
  TOTAL=$((TOTAL + 1))
  if eval "$1" >/dev/null 2>&1; then
    echo "ok $TOTAL - $2"
    PASS=$((PASS + 1))
  else
    echo "not ok $TOTAL - $2"
    FAIL=$((FAIL + 1))
  fi
}

assert_file_exists() {
  assert_ok "[ -f '$1' ]" "File exists: $1"
}

assert_file_executable() {
  assert_ok "[ -x '$1' ]" "File executable: $1"
}

PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$PROJECT_ROOT"

echo "TAP version 13"
echo "# Bedrock LLM Monitor — Test Suite"
echo ""

# Run sub-test scripts
for test_script in tests/hooks/*.sh tests/structure/*.sh; do
  if [ -f "$test_script" ] && [ -x "$test_script" ]; then
    echo "# Running: $test_script"
    source "$test_script"
    echo ""
  fi
done

echo "1..$TOTAL"
echo ""
echo "# Results: $PASS passed, $FAIL failed, $TOTAL total"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
