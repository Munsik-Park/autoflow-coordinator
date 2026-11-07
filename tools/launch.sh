#!/usr/bin/env bash
# launch.sh <run-dir> <k> [tab] — start work session Sk (k a number) or one-off session k (e.g. X1)
# with its session id and the settings made for it, then confirm the transcript exists
# and show the bottom of its screen. A session not yet in sessions.tsv gets a new surface, right of the
# coordination surface's last open session or below that surface if none is open, a session id, a shell
# in the checkout and the tab name. The prompt is s<k>-prompt.txt, or <k lowercased>-prompt.txt.
# The session gets the workspace's gh-token as GH_TOKEN, and the clone's gh-token.gitconfig through
# GIT_CONFIG_*, which git passes on to the submodule commands it runs; the typed line names the file, not
# the token.
set -euo pipefail
TOOLS=$(cd "$(dirname "$0")" && pwd)
RUN=$(cd "$1" && pwd); K=$2
case "$K" in [0-9]*) NAME=S$K ;; *) NAME=$K ;; esac
PROMPT=$RUN/$(printf '%s' "$NAME" | tr 'A-Z' 'a-z')-prompt.txt
source "$RUN/run.env"
: "${TERMINAL:?run.env has no TERMINAL}"
TOKEN=$(dirname "$CHECKOUT")/gh-token
# A token with no whitespace and at most one final newline, so that $(cat) gives the token itself.
python3 -c '
import re, sys
try:
    s = open(sys.argv[1], newline="").read()
except OSError as e:
    sys.exit(f"{sys.argv[1]}: {e} (WORKSPACE.md > gh-token)")
t = s[:-1] if s.endswith("\n") else s
if not t or re.search(r"\s", t):
    sys.exit(f"{sys.argv[1]}: not one token alone on one line (WORKSPACE.md > gh-token)")
' "$TOKEN"
GITAUTH=$(git -C "$CHECKOUT" rev-parse --path-format=absolute --git-common-dir)/gh-token.gitconfig
[ -f "$GITAUTH" ] || { echo "no $GITAUTH: write it with tools/prepare.py $(basename "$(dirname "$CHECKOUT")") $ISSUE --key $RUN_KEY, which sets the clone's git and then stops on the taken key without making a run; then launch again" >&2; exit 1; }
term() { python3 "$TOOLS/terminal.py" "$TERMINAL" "$TERMINAL_WORKSPACE" "$@"; }
# The surfaces of the sessions opened from this coordination surface, in its other active runs and then
# this one: a second run's first session must not take room from the coordination surface again.
opened() {
  local runs env
  runs=$(python3 "$TOOLS/config.py" runs)
  for env in "$runs"/*/run.env; do
    [ -f "$env" ] && [ "$(dirname "$env")" != "$RUN" ] || continue
    ( source "$env"; [ "$STATE $TERMINAL $TERMINAL_WORKSPACE $COORD_SURFACE" = "active $1" ] ) || continue
    cut -f2 "$(dirname "$env")/sessions.tsv" 2>/dev/null || true
  done
  cut -f2 "$RUN/sessions.tsv"
}
if ! grep -q "^$NAME	" "$RUN/sessions.tsv"; then
  S=$(term open_session "$COORD_SURFACE" $(opened "$TERMINAL $TERMINAL_WORKSPACE $COORD_SURFACE"))
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
# The workspace's settings, with prompt suggestions off: the input check reads a suggestion as a draft.
PERM=$(dirname "$CHECKOUT")/claude-settings.json
SETTINGS=$RUN/claude-settings.json
{ [ -f "$PERM" ] && cat "$PERM" || echo '{}'; } | jq '. + {promptSuggestionEnabled: false}' > "$SETTINGS"
term send_line "$S" "GH_TOKEN=\$(cat $TOKEN) GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=include.path GIT_CONFIG_VALUE_0=$(printf %q "$GITAUTH") claude --plugin-dir $PLUGIN --settings $SETTINGS --session-id $SID \"\$(cat $PROMPT)\""
echo "$NAME $S $SID start $(date '+%Y-%m-%d %H:%M:%S')"
sleep 15
ls "$PROJ/$SID.jsonl"
term read_screen "$S" 12 | grep -v '^\s*$' | tail -8
