#!/usr/bin/env bash
# Install git hooks for the project
set -euo pipefail

HOOKS_DIR="$(git rev-parse --show-toplevel)/.git/hooks"

echo "Installing git hooks..."

# commit-msg hook: remove Co-Authored-By lines
cat > "$HOOKS_DIR/commit-msg" << 'HOOK'
#!/usr/bin/env bash
# Remove Co-Authored-By lines from commit messages
sed -i '/^Co-Authored-By:/d' "$1"
HOOK
chmod +x "$HOOKS_DIR/commit-msg"
echo "  Installed: commit-msg (removes Co-Authored-By lines)"

echo "Git hooks installed successfully."
