#!/usr/bin/env bash
# Test hook scripts exist and are properly configured

echo "# Hook tests"

# Hook files exist
assert_file_exists ".claude/hooks/check-doc-sync.sh"
assert_file_exists ".claude/hooks/secret-scan.sh"
assert_file_exists ".claude/hooks/session-context.sh"
assert_file_exists ".claude/hooks/notify.sh"

# Hook files are executable
assert_file_executable ".claude/hooks/check-doc-sync.sh"
assert_file_executable ".claude/hooks/secret-scan.sh"
assert_file_executable ".claude/hooks/session-context.sh"
assert_file_executable ".claude/hooks/notify.sh"

# Settings.json registers hooks
assert_ok "grep -q 'SessionStart' .claude/settings.json" "settings.json registers SessionStart hook"
assert_ok "grep -q 'PreCommit' .claude/settings.json" "settings.json registers PreCommit hook"
assert_ok "grep -q 'PostToolUse' .claude/settings.json" "settings.json registers PostToolUse hook"
