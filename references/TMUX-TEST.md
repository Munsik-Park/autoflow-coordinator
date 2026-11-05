# tmux coordination test — checking the tmux equivalents of cmux operations

Written: 2026-10-22. Environment: tmux 3.8, Claude Code 2.1.308, macOS (Darwin 25.6.0), window 252×49. This is machine-local material.

Purpose: check whether the operations the coordination session and `tools/` do with cmux (splitting the screen, creating panes, creating sessions, delivering messages, reading the screen) can be done with tmux. The grounds are the tmux man page and the measurements below. The test sessions were started with `--model haiku`, and after the test all panes, sessions and claude processes were cleaned up.

## 1. Detecting the environment

| Item | Inside tmux | Inside cmux |
|---|---|---|
| `$TMUX` | set (`/private/tmp/tmux-501/default,…`) | — |
| `$TMUX_PANE` | set (`%0`) | — |
| `$TERM_PROGRAM` | `tmux` | — |
| `CMUX_*` environment variables | absent | present (`CMUX_SURFACE_ID` and others, referenced in the cmux hook settings) |

Detection uses `[ -n "$TMUX" ]` (tmux) and the presence of `CMUX_*` (cmux). In this tmux session, `cmux` was not on the PATH.

## 2. Mapping table (all measured)

| Purpose | cmux | tmux | Result |
|---|---|---|---|
| Identify own pane | `identify` (`caller.surface_ref`) | `$TMUX_PANE` | ✅ |
| Split a pane | `new-split right/down --focus false` | `split-window -d -h/-v -t <pane> -c <dir> -P -F '#{pane_id}'` | ✅ returns the new pane id |
| Even distribution | `rpc workspace.equalize_splits` | `select-layout -t <win> even-horizontal` before the row splits | ✅ |
| Set width | `resize-pane --amount <px>` | `resize-pane -t <pane> -x <cols>` (unit is cells) | ✅ coordination 83, work 40–41 cols |
| Tab name | `rename-tab` | `set -p -t <pane> @label "S1 …"`, `set -w pane-border-status top`, `set -w pane-border-format ' #{?#{@label},#{@label},#{pane_title}} '` | ✅ |
| List all panes | `tree --all`, `rpc pane.list` | `list-panes -a -F '…'` (`-s` is per session) | ✅ |
| Type a command | `send` | `send-keys -t <pane> -l "<text>"` then `send-keys -t <pane> Enter` | ✅ arrives even when sent right after the split |
| Read the screen | `read-screen --lines 12` | `capture-pane -p -t <pane>` | ✅ |
| Further instruction | `paste --submit - < file` | `load-buffer -b <buf> <file>` → `paste-buffer -r -d -b <buf> -t <pane>` → `send-keys Enter` | ✅ (§3.2) |
| Special keys | — | `send-keys -t <pane> Escape` / `Down` / `Enter` | ✅ |
| Close a pane | `close-surface` (confirmation dialog for closing the whole tab, do not use) | `kill-pane -t <pane>` | ✅ only that pane closes |
| Messages between sessions | `SendMessage` | same | ✅ shown in ListAgents as `tmux 0:@0.%18` |

## 3. What was tested

### 3.1 Layout

```bash
CO=<checkout>; C=$TMUX_PANE; T=$(tmux display -p -t $C '#{session_name}:#{window_index}')
sp(){ tmux split-window -d $1 -t $2 -c $CO -P -F '#{pane_id}'; }
S1=$(sp -h $C); S2=$(sp -h $S1); S3=$(sp -h $S2); S4=$(sp -h $S3)
tmux select-layout -t $T even-horizontal
S5=$(sp -v $S1); S6=$(sp -v $S2); S7=$(sp -v $S3)
W=$(tmux display -p -t $T '#{window_width}'); WK=$(( (W - 83 - 4) / 4 ))
tmux resize-pane -t $C -x 83; for p in $S1 $S2 $S3; do tmux resize-pane -t $p -x $WK; done
```

Result (252 cols): coordination 83×49, S1–S3 and S5–S7 41×24, S4 42×49. The layout widths summed to 252, matching the window.

### 3.2 Creating sessions and delivering messages

| Test | Method | Transcript result |
|---|---|---|
| First instruction (3 lines, containing `"…"` and `$HOME`) | `send-keys -l 'claude --model haiku --session-id <id> "$(cat prompt.txt)"'` + Enter | user message exactly as written, response `PONG-1` |
| Further instruction, bracketed paste | `paste-buffer -p` | arrived wrapped in `<pasted_content id=…>`, response `PONG-2 3` |
| Further instruction, no bracket | `paste-buffer -r` (LF kept) | arrived as one ordinary user message, response `PONG-3 2` |
| Long instruction (81 lines, 3959 bytes) | `paste-buffer -r` + Enter 1 second later | arrived as one message, response `PONG-4 79`. The only difference was tab → 4 spaces |
| `/usage` screen | `send-keys -l '/usage'` + Enter, `Escape` after reading | confirmed it opened and closed, returned to the prompt |
| workspace trust dialog | run claude in a folder used for the first time | the `capture-pane` content matched `watch.py`'s `INPUT_RE` (`Esc to cancel`, `❯ …`). `Escape` → claude exits |

### 3.3 Existing tools

- **`tools/watch.py` verdict:** running `watch.py <run> 1 0 150` with a test run dir (pane ids recorded in `run.env` and `sessions.tsv`) gave `TURN_END 1`. The transcript-based verdict does not depend on the terminal.
- **Messages between sessions:** claude started in a tmux pane was shown in ListAgents as `tmux 0:@0.%18`.

## 4. Cautions

1. **Do not use `select-layout -E`:** used on a layout that mixes columns and rows, the layout widths summed to 363, exceeding the window width of 252, and the last column was pushed off the screen. It could not be recovered afterwards even with `resize-pane`. Only the order in §3.1 (`even-horizontal`, row splits, `resize-pane -x`) worked.
2. **Do not use `paste-buffer -p`:** Claude Code wraps a bracketed paste in `<pasted_content>`, so the instruction is delivered as pasted material. Use `-r`. With neither `-p` nor `-r`, LF is changed to CR and each line can be submitted (man page `paste-buffer`).
3. **Do not use `tmux display -p` without `-t`:** it returns the active pane, not the calling pane (run from %10, it gave %9). Identify your own pane with `$TMUX_PANE`.
4. **`@label` instead of the pane title:** with `allow-set-title on`, claude changes the pane title (`✳ <session title>`). A name set with `select-pane -T` is overwritten, so attach the label with `@label` and `pane-border-format`.
5. **Send Enter separately:** after `send-keys -l` or `paste-buffer`, send `send-keys Enter` separately. For long pastes, it was sent after a 0.5–1 second pause.

## 5. Where the current tools break in tmux

| Location | Problem | Grounds |
|---|---|---|
| `tools/launch.sh:14,19` | calls `cmux send` and `cmux read-screen` directly | fails in an environment without cmux |
| `tools/watch.py` `screen_waiting()` (line 98) | when the cmux call raises an exception it returns `False`, so `WAITING_INPUT` never appears. No error is raised either | in the code, `except Exception: return False` |
| `tools/watch.py` `live_children()`, `tools/check.sh:41` | the `.local/bin/claude` pattern does not catch claude started in tmux | the process command in the tmux pane was `claude --model haiku …`. cmux starts it as `~/.local/bin/claude --settings ~/.cmuxterm/claude-settings/….json …`. Confirmed that starting it as `$HOME/.local/bin/claude` is caught by `pgrep -f '\.local/bin/claude'` |
| cmux hooks | the Notification hook (`cmux hooks claude …`) that cmux adds with `--settings` is absent in tmux | the tools do not depend on this hook, so there is no effect |

## 6. Basic tmux operations (for the operator)

| Action | Key / command |
|---|---|
| Move between panes | `Ctrl-b` then an arrow key |
| Zoom one pane and restore | `Ctrl-b` then `z` |
| Scroll past output | `Ctrl-b` then `[`, `q` to finish |
| Switch from the session list | `Ctrl-b` then `s` |
| View a session from another terminal | `tmux attach -t <session>` |
| Select panes and scroll with the mouse | `tmux set -g mouse on` |
| detach (leaves the screen, caution) | `Ctrl-b` then `d` |
