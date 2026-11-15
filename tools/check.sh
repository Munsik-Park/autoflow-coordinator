#!/usr/bin/env bash
# check.sh <run-dir> — prints other active runs under the root, each module run of the record folder that has
# an end record (<records>/<module>-<n>.ended.json) with its status and the number of files its work folder
# held at that turn end, the checkout's tree, and leftover browser, db and server processes.
set -uo pipefail
RUN=$(cd "$1" && pwd -P)
source "$RUN/run.env"
RUNS=$(python3 "$(dirname "$0")/config.py" runs) || exit 1
echo "== other active coordination runs ($RUNS)"
[ "$(dirname "$RUN")" = "$RUNS" ] || echo "NOT UNDER RUNS: $RUN is invisible to other runs' checks"
for e in "$RUNS"/*/run.env; do
  [ -f "$e" ] && [ "$e" != "$RUN/run.env" ] || continue
  grep -q '^STATE=active' "$e" || continue
  o_t=$(sed -n 's/^TERMINAL=//p' "$e"); o_ws=$(sed -n 's/^TERMINAL_WORKSPACE=//p' "$e"); o_co=$(sed -n 's/^CHECKOUT=//p' "$e")
  m=""; [ "$o_co" = "$CHECKOUT" ] && m="$m SAME CHECKOUT"; [ "$o_t" = "$TERMINAL" ] && [ "$o_ws" = "$TERMINAL_WORKSPACE" ] && m="$m SAME TERMINAL WORKSPACE"
  # A run left active whose sessions are all gone is a stale record, not an overlap.
  live=0; for id in $(cut -f3 "$(dirname "$e")/sessions.tsv" 2>/dev/null); do ps -axo command | grep -q "[s]ession-id $id" && live=$((live+1)); done
  echo "$(basename "$(dirname "$e")") terminal=$o_t terminal_workspace=$o_ws checkout=$o_co$m live_sessions=$live"
done
cd "$CHECKOUT" || exit 1
if [ -n "${RECORDS:-}" ] && [ -d "$RECORDS" ]; then
  echo "== module runs ($RECORDS)"
  for r in "$RECORDS"/*.ended.json; do
    [ -f "$r" ] || continue
    echo "$(basename "$r" .ended.json) $(jq -r '"\(.status) files=\(.outputs.files|length)"' "$r")"
  done
fi
echo "== tree"
git status --porcelain; git submodule foreach --quiet 'git status --porcelain | sed "s#^#$sm_path: #"'
echo "== leftover browser / db / server"
ps -axo pid,ppid,command | grep -E 'ms-playwright|headless_shell|Google Chrome --disable-field-trial|chrome-devtools-mcp/chrome-profile|mongod|mongo-memory|vite|playwright test' | grep -v grep | cut -c1-160
