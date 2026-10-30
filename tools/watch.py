#!/usr/bin/env python3
"""Watch one work session until its turn completes (Munsik-Park/autoflow#471 comment 2026-10-19 §2).

usage: watch.py <run-dir> <k> [baseline-turns] [timeout-sec]

  <run-dir>  <runs>/<name>/ holding run.env (TERMINAL, TERMINAL_WORKSPACE, CHECKOUT) and sessions.tsv (Sk, surface, session id)
  <k>        work session number

Prints one line and exits:
  TURN_END <n>        a new system/turn_duration after the baseline is the last turn record
                      and no started background work is still without a task-notification;
                      the session's last assistant text (its report) follows that line
  WAITING_INPUT       the bottom 12 screen lines show a choice or permission prompt
  IDLE-PENDING <ids>  turn ended, background work pending, and for 10 min neither a transcript
                      changed nor a process ran under the worker
  STALL               transcripts unchanged for 30 min and no process under the worker
  TIMEOUT             timeout-sec elapsed

Background work that is not work: a Bash `sleep …` (the worker's own cache keep-alive).
Background agent finished: its meta.json has `finished: true`, or a task-notification names its
tool-use id or its agent id.
Background work still running: its subagent transcript changes, or a process under the worker's
claude other than a terminal's hook helpers (a background command writing to its own log).
"""
import glob, json, os, re, sys, time

import terminals
from session import process_rows, read_env, session_pids, session_row, transcript_dir

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
BG_RE = re.compile(r'running in background with ID: (\w+)')
INPUT_RE = re.compile(r'Do you want to|Enter to select|Esc to cancel|❯ \d+\.|Would you like to')


def scan():
    turns, last_kind, started, notified, keepalive = 0, None, {}, set(), set()
    with open(main, errors='replace') as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            t = d.get('type')
            if t == 'system' and d.get('subtype') == 'turn_duration':
                turns += 1
                last_kind = 'end'
            elif t in ('assistant', 'user'):
                last_kind = 'work'
                c = (d.get('message') or {}).get('content')
                if t == 'assistant' and isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == 'Bash' \
                                and str((b.get('input') or {}).get('command', '')).lstrip().startswith('sleep '):
                            keepalive.add(b.get('id'))
                if t == 'user' and isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and b.get('type') == 'tool_result':
                            m = BG_RE.search(json.dumps(b.get('content')))
                            if m:
                                started[b.get('tool_use_id')] = m.group(1)
            if '<task-notification>' in line:
                text = line.replace('\\n', '\n')
                notified.update(re.findall(r'<tool-use-id>(\w+)</tool-use-id>', text))
                notified.update(re.findall(r'<task-id>(\w+)</task-id>', text))
    for meta in glob.glob(os.path.join(subdir, '*.meta.json')):
        try:
            m = json.load(open(meta))
        except ValueError:
            continue
        # A background agent is done when its meta says so, or when a notification names its agent id
        # (agent-<id>.meta.json); some notifications carry only <task-id>, no <tool-use-id>.
        if m.get('requestShape') == 'background' and m.get('toolUseId') and not m.get('finished'):
            started[m['toolUseId']] = os.path.basename(meta)[len('agent-'):-len('.meta.json')]
    pending = [i for i, v in started.items() if i not in notified and v not in notified and i not in keepalive]
    return turns, last_kind, pending


def latest_mtime():
    files = [main] + glob.glob(os.path.join(subdir, '*.jsonl'))
    return max(os.path.getmtime(p) for p in files if os.path.exists(p))


def live_children():
    """A Bash-tool shell still running under the worker. MCP servers and a terminal's hook helpers are also
    children of claude for the whole session, so only shells that source a Claude Code shell
    snapshot count."""
    rows = process_rows()
    roots = session_pids(sid, rows)
    return any(pp in roots and '.claude/shell-snapshots/' in c for _, pp, c in rows)


def screen_waiting():
    try:
        out = term.read_screen(WS, surface, 12)
    except Exception:
        return False
    return bool(INPUT_RE.search(out))


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
    turns, last_kind, pending = scan()
    ended = turns > baseline and last_kind == 'end'
    if ended and not pending:
        time.sleep(20)  # settle: confirm nothing new arrived
        t2, k2, p2 = scan()
        if t2 == turns and k2 == 'end' and not p2:
            print(f'TURN_END {turns}'); print(last_text()); break
        continue
    if ended and pending and now - latest_mtime() > 600 and not live_children():
        print('IDLE-PENDING ' + ','.join(pending)); break
    if screen_waiting():
        time.sleep(30)
        if screen_waiting() and scan()[1] != 'end':
            print('WAITING_INPUT'); break
    if now - latest_mtime() > 1800 and not live_children():
        print('STALL'); break
    time.sleep(15)
