#!/usr/bin/env bash
# Install/update a weekly unprivileged devbox audit. Never changes repo settings.
set -euo pipefail

command -v git >/dev/null
command -v gh >/dev/null
command -v python3 >/dev/null
command -v systemctl >/dev/null

actor="$(gh api user --jq .login)"
if [[ "$actor" != "Ponchia" ]]; then
  printf 'Refusing to install: active GitHub user is %s, not Ponchia\n' "$actor" >&2
  exit 2
fi

workdir="$HOME/.local/share/ponchia-governance/repo"
mkdir -p "$(dirname "$workdir")" "$HOME/.config/systemd/user"

if [[ -e "$workdir" ]]; then
  if [[ ! -d "$workdir/.git" ]]; then
    echo "Refusing to overwrite non-repository path $workdir" >&2
    exit 2
  fi
  if [[ -n "$(git -C "$workdir" status --porcelain)" ]]; then
    echo 'Refusing to update a dirty governance checkout' >&2
    exit 2
  fi
  git -C "$workdir" pull --ff-only
else
  gh repo clone Ponchia/.github "$workdir" -- --quiet
fi

if [[ "$(git -C "$workdir" branch --show-current)" != "main" ]]; then
  echo 'Governance checkout must track main' >&2
  exit 2
fi

python3 "$workdir/scripts/repository_policy.py" --validate-policy
python3 -m unittest discover -s "$workdir/tests" -q

for name in ponchia-governance-watch.service ponchia-governance-watch.timer; do
  install -m 0644 "$workdir/ops/systemd/$name" "$HOME/.config/systemd/user/$name"
done

systemctl --user daemon-reload
systemctl --user enable --now ponchia-governance-watch.timer
systemctl --user list-timers --all ponchia-governance-watch.timer --no-pager
printf '\nRead-only governance timer enabled. For an immediate baseline:\n'
printf '  systemctl --user start ponchia-governance-watch.service\n'
