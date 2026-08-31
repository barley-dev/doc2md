#!/usr/bin/env bash
# Link the doc2md skill into ~/.claude/skills/ so Claude Code can use it.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
SRC="$REPO_DIR/skills/doc2md"
DEST="$SKILLS_DIR/doc2md"

mkdir -p "$SKILLS_DIR"

if [ -L "$DEST" ]; then
    if [ "$(readlink "$DEST")" = "$SRC" ]; then
        echo "= doc2md — already linked, nothing to do"
        exit 0
    fi
    echo "! doc2md — a different symlink exists:"
    echo "    $DEST -> $(readlink "$DEST")"
    read -r -p "  Replace it? [y/N] " reply
    case "$reply" in
        [yY]*) rm "$DEST" ;;
        *) echo "  skipped"; exit 0 ;;
    esac
elif [ -e "$DEST" ]; then
    echo "! doc2md — a real file/directory already exists at $DEST"
    echo "  Not touching it. Move or remove it first, then re-run."
    exit 0
fi

ln -s "$SRC" "$DEST"
echo "✓ doc2md -> $DEST"
echo
echo "Restart Claude Code (or run /skills) to pick it up."
