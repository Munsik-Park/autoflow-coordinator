#!/usr/bin/env bash
# launch.sh <run-dir> <k> [tab] — start work session Sk (k a number) or one-off session k (e.g. X1)
# with its session id and the workspace's settings if it has them, then confirm the transcript exists
# and show the bottom of its screen. A session not yet in sessions.tsv gets a new split beside the
# coordination surface, a session id, a shell in the checkout and the tab name. The prompt is
# s<k>-prompt.txt, or <k lowercased>-prompt.txt.
set -euo pipefail
TOOLS=$(cd "$(dirname "$0")" && pwd)
RUN=$(cd "$1" && pwd); K=$2
case "$K" in [0-9]*) NAME=S$K ;; *) NAME=$K ;; esac
PROMPT=$RUN/$(printf '%s' "$NAME" | tr 'A-Z' 'a-z')-prompt.txt
source "$RUN/run.env"
: "${TERMINAL:?run.env has no TERMINAL}"
term() { python3 "$TOOLS/terminal.py" "$TERMINAL" "$TERMINAL_WORKSPACE" "$@"; }
if ! grep -q "^$NAME	" "$RUN/sessions.tsv"; then
  S=$(term split "$COORD_SURFACE")
  printf '%s\t%s\t%s\n' "$NAME" "$S" "$(uuidgen | tr 'A-Z' 'a-z')" >> "$RUN/sessions.tsv"
  term send_line "$S" "cd $CHECKOUT && clear"
  term rename "$S" "$NAME ${3:-}" >/dev/null 2>&1 || true
  sleep 2
fi
read -r _ S SID < <(grep "^$NAME	" "$RUN/sessions.tsv")
PROJ=~/.claude/projects/$(printf '%s' "$CHECKOUT" | sed 's/[^A-Za-z0-9]/-/g')
# Pin the run's AutoFlow: --plugin-dir replaces the installed copy for this session only,
# so a plugin update during the run does not reach the sessions it starts.
PLUGIN=~/.claude/plugins/cache/autoflow/autoflow/${AUTOFLOW_VER:?run.env has no AUTOFLOW_VER}
[ -f "$PLUGIN/.claude-plugin/plugin.json" ] || { echo "no AutoFlow $AUTOFLOW_VER at $PLUGIN" >&2; exit 1; }
[ -f "$PROMPT" ] || { echo "no prompt $PROMPT" >&2; exit 1; }
PERM=$(dirname "$CHECKOUT")/claude-settings.json
SETTINGS=; [ -f "$PERM" ] && SETTINGS=" --settings $PERM"
term send_line "$S" "claude --plugin-dir $PLUGIN$SETTINGS --session-id $SID \"\$(cat $PROMPT)\""
echo "$NAME $S $SID start $(date '+%Y-%m-%d %H:%M:%S')"
sleep 15
ls "$PROJ/$SID.jsonl"
term read_screen "$S" 12 | grep -v '^\s*$' | tail -8
