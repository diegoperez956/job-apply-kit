#!/usr/bin/env bash
# Install the pii_scan pre-commit hook. Run once after cloning:
#   ./scripts/install_hooks.sh
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
hook_path="$repo_root/.git/hooks/pre-commit"

cat > "$hook_path" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel)"
python3 "$repo_root/scripts/pii_scan.py" --staged
EOF

chmod +x "$hook_path"
echo "Installed pre-commit hook -> $hook_path"
