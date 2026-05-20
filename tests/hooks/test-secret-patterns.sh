#!/usr/bin/env bash
# Test secret scanning patterns for true/false positives

echo "# Secret pattern tests"

# True positives (should be detected)
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  assert_ok "echo '$line' | grep -qE 'AKIA[0-9A-Z]{16}|sk-[a-zA-Z0-9]{20,}|BEGIN (RSA|DSA|EC|OPENSSH) PRIVATE|ghp_[a-zA-Z0-9]{36}'" \
    "True positive detected: ${line:0:30}..."
done < tests/fixtures/secret-samples.txt 2>/dev/null || true

# False positives (should NOT be detected)
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  assert_ok "! echo '$line' | grep -qE 'AKIA[0-9A-Z]{16}|sk-[a-zA-Z0-9]{20,}|BEGIN (RSA|DSA|EC|OPENSSH) PRIVATE|ghp_[a-zA-Z0-9]{36}'" \
    "False positive ignored: ${line:0:30}..."
done < tests/fixtures/false-positives.txt 2>/dev/null || true
