#!/usr/bin/env bash
# Test project structure and key files

echo "# Structure tests"

# Root files
assert_file_exists "CLAUDE.md"
assert_file_exists ".gitignore"
assert_file_exists ".editorconfig"
assert_file_exists ".mcp.json"
assert_file_exists "docker-compose.yml"

# Backend structure
assert_file_exists "backend/main.py"
assert_file_exists "backend/prober.py"
assert_file_exists "backend/auto_prober.py"
assert_file_exists "backend/auth.py"
assert_file_exists "backend/requirements.txt"
assert_file_exists "backend/CLAUDE.md"

# Frontend structure
assert_file_exists "frontend/package.json"
assert_file_exists "frontend/next.config.mjs"
assert_file_exists "frontend/CLAUDE.md"

# Module CLAUDE.md files
assert_file_exists "backend/routers/CLAUDE.md"
assert_file_exists "frontend/src/components/CLAUDE.md"

# Docs
assert_file_exists "docs/architecture.md"
assert_file_exists "docs/onboarding.md"
assert_file_exists "docs/api-reference.md"

# Skills
assert_file_exists ".claude/skills/code-review/SKILL.md"
assert_file_exists ".claude/skills/refactor/SKILL.md"
assert_file_exists ".claude/skills/release/SKILL.md"
assert_file_exists ".claude/skills/sync-docs/SKILL.md"

# Commands
assert_file_exists ".claude/commands/review.md"
assert_file_exists ".claude/commands/test-all.md"
assert_file_exists ".claude/commands/deploy.md"

# Agents
assert_file_exists ".claude/agents/code-reviewer.yml"
assert_file_exists ".claude/agents/security-auditor.yml"

# .env NOT in git
assert_ok "! git ls-files --error-unmatch backend/.env 2>/dev/null" ".env is NOT tracked by git"

# .gitignore covers sensitive files
assert_ok "grep -q '.env' .gitignore" ".gitignore covers .env"
