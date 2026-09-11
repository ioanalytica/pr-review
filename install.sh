#!/usr/bin/env bash
#
# install.sh - link pr-review into ~/bin and ~/.config/pr-review.
#
# Both targets become symlinks into this clone, so `git pull` updates the
# script, the brief and the hooks together. Existing files that are not
# symlinks are moved aside as *.bak. Re-running is safe.
#
# Usage: ./install.sh [--bin DIR] [--config DIR]
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/bin"
CONFIG_DIR="${PR_REVIEW_CONFIG:-$HOME/.config/pr-review}"

while [ $# -gt 0 ]; do
  case "$1" in
    --bin) BIN_DIR="${2:?--bin needs a value}"; shift ;;
    --config) CONFIG_DIR="${2:?--config needs a value}"; shift ;;
    -h|--help) sed -n '3,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "install.sh: unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

# link SRC DST: symlink DST -> SRC, backing up a real file or directory at DST.
link() {
  local src="$1" dst="$2"
  if [ -L "$dst" ]; then
    rm "$dst"
  elif [ -e "$dst" ]; then
    echo "install.sh: moving existing $dst to $dst.bak"
    mv "$dst" "$dst.bak"
  fi
  ln -s "$src" "$dst"
  echo "install.sh: $dst -> $src"
}

mkdir -p "$BIN_DIR" "$(dirname "$CONFIG_DIR")"
link "$HERE/pr-review" "$BIN_DIR/pr-review"
link "$HERE/config" "$CONFIG_DIR"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "install.sh: note: $BIN_DIR is not in PATH" ;;
esac

if command -v claude >/dev/null; then
  if claude auth status 2>/dev/null | grep -q '"loggedIn": *true'; then
    echo "install.sh: claude CLI found and logged in"
  else
    echo "install.sh: claude CLI found, run 'claude login' once before the first review"
  fi
else
  echo "install.sh: claude CLI not found (needed for --provider anthropic)"
fi

if command -v codex >/dev/null; then
  if codex login status >/dev/null 2>&1; then
    echo "install.sh: codex CLI found and logged in"
  else
    echo "install.sh: codex CLI found, run 'codex login' before using --provider openai"
  fi
else
  echo "install.sh: codex CLI not found (needed for --provider openai; https://developers.openai.com/codex/cli/)"
fi
