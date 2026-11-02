#!/usr/bin/env python3
"""Watch one work session until its turn completes.

usage: watch.py <run-dir> <k> [baseline-turns] [timeout-sec]

  <run-dir>  <runs>/<name>/ holding run.env (TERMINAL, TERMINAL_WORKSPACE, CHECKOUT) and sessions.tsv (Sk, surface, session id)
  <k>        work session number, or a one-off session name such as X1

Prints one line and exits:
  TURN_END <n>        a new turn end after the baseline is the last turn record
                      and no started background work is still without a task-notification;
                      the session's last assistant text (its report) follows that line
  WAITING_INPUT       the bottom 12 screen lines show a choice or permission prompt, still 30 s
                      later, and the last turn record is not a turn end
  IDLE-PENDING <ids>  turn ended, background work pending, for 10 min no transcript changed, and
                      no Bash-tool shell runs under the worker
  STALL               transcripts unchanged for 30 min and no Bash-tool shell under the worker
  STALL no-transcript the session's transcript did not appear within 5 min
  TIMEOUT             timeout-sec elapsed

Turn end: a system/turn_duration, or a system/stop_hook_summary with no hookErrors straight after an
assistant end_turn. A turn has one end, however many of these it writes; <n> and the baseline count ends.

Background command started: a tool result carrying the start phrase, for a call whose input has
`run_in_background: true`.
Background work that is not work: a Bash `sleep …` (the worker's own cache keep-alive).
Background agent finished: its meta.json has `finished: true`, or a task-notification names its
tool-use id or its agent id.
Background work still running: its subagent transcript changes, or a Bash-tool shell runs under the
worker's claude (a background command writing to its own log).
"""
import json, os, sys, time

import terminals
from session import process_rows, read_env, session_row, transcript_dir
from status import IDLE_PENDING_AFTER, STALL_AFTER, latest_mtime, live_children, scan, screen_waiting

run_dir, k = sys.argv[1], sys.argv[2]
baseline = int(sys.argv[3]) if len(sys.argv) > 3 else 0
timeout = int(sys.argv[4]) if len(sys.argv) > 4 else 6 * 3600

env = read_env(run_dir)
WS = env['TERMINAL_WORKSPACE']
term = terminals.load(env['TERMINAL'])
_, surface, sid = session_row(run_dir, k)
PROJ = transcript_dir(env)
main = os.path.join(PROJ, sid + '.jsonl')
subdir = os.path.join(PROJ, sid, 'subagents')


def last_text():
    text = ''
    with open(main, errors='replace') as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get('type') == 'assistant':
                for b in (d.get('message') or {}).get('content') or []:
                    if isinstance(b, dict) and b.get('type') == 'text':
                        text = b['text']
    return text


start = time.time()
while not os.path.exists(main):
    if time.time() - start > 300:
        print('STALL no-transcript'); sys.exit(0)
    time.sleep(5)
while True:
    now = time.time()
    if now - start > timeout:
        print('TIMEOUT'); break
    turns, last_kind, pending = scan(main, subdir)
    ended = turns > baseline and last_kind == 'end'
    if ended and not pending:
        time.sleep(20)
        t2, k2, p2 = scan(main, subdir)
        if t2 == turns and k2 == 'end' and not p2:
            print(f'TURN_END {turns}'); print(last_text()); break
        continue
    if ended and pending and now - latest_mtime(main, subdir) > IDLE_PENDING_AFTER and not live_children(sid, process_rows()):
        print('IDLE-PENDING ' + ','.join(pending)); break
    if screen_waiting(term, WS, surface):
        time.sleep(30)
        if screen_waiting(term, WS, surface) and scan(main, subdir)[1] != 'end':
            print('WAITING_INPUT'); break
    if now - latest_mtime(main, subdir) > STALL_AFTER and not live_children(sid, process_rows()):
        print('STALL'); break
    time.sleep(15)
