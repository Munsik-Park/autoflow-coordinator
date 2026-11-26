#!/usr/bin/env bash
# launch.sh <run-dir> <k> [tab] [--prompt <file>] [--tools <name>[,<name>...]] [--model <model>]
# [--without-autoflow] — start work
# session Sk (k a number) or one-off session k (e.g. X1) with its session id and the settings made for it, then
# confirm the transcript exists and show the bottom of its screen. --without-autoflow starts the merge session,
# which runs no module and gets none of the workspace's tools.
# --tools adds those tools of the workspace's tools.json to the session: <run-dir>/mcp-<session>.json, <session>
# the session's name (S<k>, or a one-off name such as X1), holds their mcp entries,
# {worktree} replaced by the checkout's absolute path in every string, and the session starts with --mcp-config
# that file. A name not in tools.json, no tools.json, or --tools with --without-autoflow stops the launch before
# a surface is opened. Without --tools, no MCP configuration is passed.
# The session's model and effort (claude --model, claude --effort) are the flags tools/module_settings.py
# prints for the launch, put on the session's command line as printed. A session started for a module's run,
# which is a --prompt <name>.prompt.txt with <name>.invocation.json beside it, gets that module's model and
# effort from the module settings (SETTINGS.md > Module settings). --model gives the session that model, for
# that session only, in place of the module's; any other session gets the --model argument's model or no flag,
# and no effort. --model with no value or an empty one, an invocation that names no module, and module
# settings that cannot be read for a module's run each stop the launch before a surface is opened.
# The session's first message is the instruction file: the one --prompt names, which for a session that starts
# with a module run is that run's <records>/<module>-<n>.prompt.txt (tools/invocation.py prints it as PROMPT);
# without --prompt, <run-dir>/s<k>-prompt.txt, or <run-dir>/<k lowercased>-prompt.txt for a one-off session,
# which the coordination session writes for a session that starts without a module run. A missing instruction
# file stops the launch before a surface is opened.
# A work session's settings get the hooks of tools/questions.py; the launch fails, exit status 1 with the reason
# and the screen, when the session's hooks did not run at the start.
# A work session runs a module from its SKILL.md path in the run's MODULES or USER_MODULES,
# so no session loads the AutoFlow plugin: each starts with --setting-sources '' and the plugin turned off.
# Claude Code's behavior the merge session's settings rely on: enabledPlugins false turns an installed plugin off
# for that session only; --setting-sources '' loads no user, project or local settings, so no plugin they enable
# and no hook they set, while --settings still applies whole, hooks included; CLAUDE_CODE_PLUGIN_DIRS in the
# environment loads plugins regardless; in dontAsk mode a tool call no allow rule admits is refused instead of
# asked; a deny wins over an allow from any source; commands Claude Code treats as read-only run without a rule.
# A session not yet in sessions.tsv gets a new surface, right of the
# coordination surface's last open session or below that surface if none is open, a session id, a shell
# in the checkout and the tab name.
# The session gets the workspace's gh-token as GH_TOKEN, the clone's gh-token.gitconfig through
# GIT_CONFIG_*, which git passes on to the submodule commands it runs, and that file's core.sshCommand as
# GIT_SSH_COMMAND, which would otherwise override it; the typed line names the files, not the token.
set -euo pipefail
TOOLS=$(cd "$(dirname "$0")" && pwd)
RUN=$(cd "$1" && pwd); K=$2; shift 2
TAB=; AUTOFLOW=1; PROMPT=; CHOSEN=; MODEL=
while [ $# -gt 0 ]; do
  case "$1" in
    --without-autoflow) AUTOFLOW= ;;
    --prompt) [ $# -ge 2 ] || { echo "--prompt needs the instruction file" >&2; exit 1; }; PROMPT=$2; shift ;;
    --tools) [ $# -ge 2 ] && [ -n "$2" ] || { echo "--tools needs the tool names, comma-separated" >&2; exit 1; }; CHOSEN=$2; shift ;;
    --model) [ $# -ge 2 ] && [ -n "$2" ] || { echo "--model needs the model name" >&2; exit 1; }; MODEL=$2; shift ;;
    *) TAB=$1 ;;
  esac
  shift
done
[ -z "$CHOSEN" ] || [ -n "$AUTOFLOW" ] || { echo "--tools with --without-autoflow: the merge session gets none of the workspace's tools (WORKSPACE.md > tools.json)" >&2; exit 1; }
case "$K" in [0-9]*) NAME=S$K ;; *) NAME=$K ;; esac
[ -n "$PROMPT" ] || PROMPT=$RUN/$(printf '%s' "$NAME" | tr 'A-Z' 'a-z')-prompt.txt
[ -f "$PROMPT" ] || { echo "no prompt $PROMPT" >&2; exit 1; }
# Absolute: the session's shell reads it from the checkout, not from where this was called.
PROMPT=$(cd "$(dirname "$PROMPT")" && pwd)/$(basename "$PROMPT")
# Before run.env is read, so a stop leaves nothing written and no surface opened.
FLAG_ARGS=("$PROMPT")
[ -z "$MODEL" ] || FLAG_ARGS+=(--model "$MODEL")
[ -n "$AUTOFLOW" ] || FLAG_ARGS+=(--without-autoflow)
FLAGS=$(python3 "$TOOLS/module_settings.py" "${FLAG_ARGS[@]}") || exit 1
source "$RUN/run.env"
: "${TERMINAL:?run.env has no TERMINAL}"
MCP_ARG=
if [ -n "$CHOSEN" ]; then
  MCP=$RUN/mcp-$NAME.json
  python3 -c '
import json, sys
src, names, worktree, out = sys.argv[1:]
try:
    tools = json.load(open(src))
except FileNotFoundError:
    sys.exit(f"no {src}: --tools names tools of the workspace'"'"'s tools.json (WORKSPACE.md > tools.json)")
except (OSError, ValueError) as e:
    sys.exit(f"{src}: {e} (WORKSPACE.md > tools.json)")
if not isinstance(tools, dict):
    sys.exit(f"{src}: not a JSON object of tools (WORKSPACE.md > tools.json)")
def fill(v):
    if isinstance(v, str):
        return v.replace("{worktree}", worktree)
    if isinstance(v, list):
        return [fill(x) for x in v]
    if isinstance(v, dict):
        return {k: fill(x) for k, x in v.items()}
    return v
servers = {}
for n in names.split(","):
    if n not in tools:
        sys.exit(f"tool {n!r} is not in {src} (WORKSPACE.md > tools.json)")
    mcp = tools[n].get("mcp") if isinstance(tools[n], dict) else None
    if not isinstance(mcp, dict):
        sys.exit(f"tool {n!r} in {src} has no mcp object (WORKSPACE.md > tools.json)")
    servers[n] = fill(mcp)
with open(out, "w") as f:
    json.dump({"mcpServers": servers}, f, indent=2)
    f.write("\n")
' "$(dirname "$CHECKOUT")/tools.json" "$CHOSEN" "$CHECKOUT" "$MCP"
  MCP_ARG=" --mcp-config $(printf %q "$MCP")"
fi
TOKEN=$(dirname "$CHECKOUT")/gh-token
if TOP=$(git -C "$(dirname "$CHECKOUT")" rev-parse --show-toplevel 2>/dev/null); then
  echo "$(dirname "$CHECKOUT") is inside the git worktree $TOP: gh-token must be outside git; keep the workspace, or the base, out of any repository (WORKSPACE.md > gh-token)" >&2; exit 1
fi
# A regular file of the caller with no group or other permission, holding a token with no whitespace and
# at most one final newline, so that $(cat) gives the token itself.
python3 -c '
import os, re, stat, sys
p = sys.argv[1]
try:
    st = os.lstat(p)
    if not stat.S_ISREG(st.st_mode):
        sys.exit(f"{p} is not a regular file: write the token in a file there, then chmod 600 {p} (WORKSPACE.md > gh-token)")
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        sys.exit(f"{p} must be yours and readable by you only: chmod 600 {p} (WORKSPACE.md > gh-token)")
    s = open(p, newline="").read()
except OSError as e:
    sys.exit(f"{p}: {e} (WORKSPACE.md > gh-token)")
t = s[:-1] if s.endswith("\n") else s
if not t or re.search(r"\s", t):
    sys.exit(f"{p}: not one token alone on one line (WORKSPACE.md > gh-token)")
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
  term rename "$S" "$NAME $TAB" >/dev/null 2>&1 || true
  sleep 2
fi
read -r _ S SID < <(grep "^$NAME	" "$RUN/sessions.tsv")
PROJ=~/.claude/projects/$(printf '%s' "$CHECKOUT" | sed 's/[^A-Za-z0-9]/-/g')
# The workspace's settings, with prompt suggestions off: the input check reads a suggestion as a draft.
PERM=$(dirname "$CHECKOUT")/claude-settings.json
ENV_ARG="env -u CLAUDE_CODE_PLUGIN_DIRS"  # Claude Code loads the plugin directories this variable lists
if [ -n "$AUTOFLOW" ]; then
  # The workspace's settings, with no user, project or local settings and so no plugin or hook they bring.
  SETTINGS=$RUN/claude-settings.json; PLUGIN_ARG="--setting-sources ''"
  { [ -f "$PERM" ] && cat "$PERM" || echo '{}'; } | jq --argjson q "$(python3 "$TOOLS/questions.py" hooks "$RUN" "$NAME")" \
    '. + {promptSuggestionEnabled: false, enabledPlugins: ((.enabledPlugins // {}) + {"autoflow@autoflow": false}),
          hooks: (reduce ($q | keys[]) as $e (.hooks // {}; .[$e] = ((.[$e] // []) + $q[$e])))}' > "$SETTINGS"
else
  # Built from nothing but these keys, not from the workspace's file: no hooks, statusLine, plugins or env of
  # its own reach the merge session. The Bash timeouts cover merge.py's default CI wait (3600 s).
  SETTINGS=$RUN/claude-settings-$NAME.json; PLUGIN_ARG="--setting-sources '' --permission-mode dontAsk"
  jq -n --arg tools "$TOOLS" '{promptSuggestionEnabled: false, enabledPlugins: {"autoflow@autoflow": false},
    env: {BASH_DEFAULT_TIMEOUT_MS: "3600000", BASH_MAX_TIMEOUT_MS: "3600000"},
    permissions: {allow: ["Bash(python3 " + $tools + "/merge.py:*)"],
                  deny: ["Bash(gh:*)", "Bash(git:*)", "Write", "Edit", "NotebookEdit"]}}' > "$SETTINGS"
fi
STARTED=$(date +%s)
term send_line "$S" "GH_TOKEN=\$(cat $TOKEN) GIT_SSH_COMMAND=\"\$(git config --file $(printf %q "$GITAUTH") core.sshCommand)\" GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=include.path GIT_CONFIG_VALUE_0=$(printf %q "$GITAUTH") $ENV_ARG claude $PLUGIN_ARG --settings $SETTINGS$MCP_ARG${FLAGS:+ $FLAGS} --session-id $SID \"\$(cat $(printf %q "$PROMPT"))\""
echo "$NAME $S $SID start $(date '+%Y-%m-%d %H:%M:%S')"
sleep 15
# The hooks run only if Claude Code applied the settings file, which it applies whole or not at all.
if [ -n "$AUTOFLOW" ] && ! REASON=$(python3 "$TOOLS/questions.py" started "$RUN" "$SID" "$SETTINGS" "$STARTED"); then
  echo "$NAME: $REASON" >&2
  term read_screen "$S" 12 | grep -v '^\s*$' | tail -8 >&2
  exit 1
fi
ls "$PROJ/$SID.jsonl"
term read_screen "$S" 12 | grep -v '^\s*$' | tail -8
