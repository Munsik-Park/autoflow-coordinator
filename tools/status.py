#!/usr/bin/env python3
"""status.py [run] | --caller [--terminal <name>] — where each run stands at this moment, as JSON. Changes nothing.

  [run]              a run's name under <runs>, or its directory, holding run.env and sessions.tsv; absent,
                     every run whose STATE is active
  --caller           only the active runs prepared in the surface this process runs in: the same terminal,
                     workspace and surface as run.env's TERMINAL, TERMINAL_WORKSPACE and COORD_SURFACE. None
                     prints an empty runs. If that surface cannot be told, prints the reason to stderr and
                     no JSON, with exit status 1
  --terminal <name>  the terminal to ask, where terminals are nested

A surface moved to another workspace no longer matches its runs. Ids can repeat once their surface is gone, or
in another tmux server, and a run records neither its surface's lifetime nor its server, so such a run also matches.

Prints {"runs": [{"name", "issue", "branch", "reference", "now", "steps", "sessions", "error"?}]}.

steps is the flow so far, in order: the rows of runbook.md's progress table, then the invocations in the
records folder that have no row yet, then what a session does that neither names. Each is
{"session", "label", "module", "state", "verdict", "entry", "cause", "session_state", "idle_sec"}, module
being null for a step with no invocation, and its state one of:
  pass, fail     the coordinator's verdict in the row, read from its words (see VERDICT)
  noted          a row whose verdict has none of those words
  awaiting       no row yet, and the invocation has a result.json, or a session with no open step ended a
                 turn its rows' end cells do not reach (see TURN_END)
  running        no row yet, and the invocation has no result.json, or a session works outside any invocation
  unknown        a session that is gone with no row and no invocation
session_state and idle_sec are the session's, on running steps only.
verdict is the words of a pass or fail in lower case, however the row has them, the
start of a noted row's cell as written, 'awaiting verdict' on an awaiting step, and null otherwise.
entry is null for a module's first run. A module's next run is "return" when an input carries what sent the
flow back to it (RETURN_INPUTS, from a run after its last one) and "rerun" otherwise; cause is the run that
input came from, or null when the invocation names none.
now is the running or awaiting step that began last, or null: an invocation begins when its file is written,
a session's work when its last turn begins in the transcript, and work with no such time counts as earliest.
Equal times go to the later step.

A session that is gone shows no step for a turn past its rows. A verdict can be written outside the table, so
comparing the turn count with the end cells cannot tell a judged turn from an unjudged one.
The session's turns stay in sessions.

Each session is {"name", "surface", "state", "turns", "pending", "idle_sec"}, its state one of:
  exited         its claude process is gone
  no-transcript  its process runs and its transcript does not exist yet
  turn-end       the last turn record is a turn end and no background work is pending
  background     the turn ended and background work is pending
  idle-pending   as background, for 10 min no transcript changed, and no Bash-tool shell runs under the worker
  waiting-input  the bottom 12 screen lines show a choice or permission prompt
  stall          transcripts unchanged for 30 min and no Bash-tool shell under the worker
  working        none of these

A turn end is a system/turn_duration, or a system/stop_hook_summary with no hookErrors while the last of the
assistant and user records is an assistant end_turn; other records may lie between them. A turn has one end,
however many of these it writes; turns counts ends.

A state is what one look shows: nothing here is confirmed over time.
"""
import datetime, glob, json, os, re, subprocess, sys, time

import terminals
from session import process_rows, read_env, session_pids, transcript_dir

IDLE_PENDING_AFTER = 600
STALL_AFTER = 1800
BG_RE = re.compile(r'running in background with ID: (\w+)')
# The words of a coordinator's verdict, read per cell: at the start of the cell or after "goal". Elsewhere the same
# words describe what the row reports (threshold met, CI pass). The earliest one decides, since a verdict goes on to
# explain itself. The words count in any case, but only whole: Goal missed is a verdict, passed and pass-through are not.
VERDICT = re.compile(r'^(?:missed|not met|met|pass)(?![\w-])|\bgoal (?:missed|not met|met)(?![\w-])', re.I)
MISSED = re.compile(r'missed|not met')
# In a progress table's header: the module run column, the verdict column and the start of the end column.
TABLE_COLUMNS = ('Module run', 'Verdict', 'End')
TABLE_ROW = re.compile(r'^\|\s*[SX]\d+\s*\|')
# In a row's end cell, the session's turn count when that turn was judged: a higher count now is a turn no row covers.
TURN_END = re.compile(r'TURN_END (\d+)')
# Inputs that carry what sent the flow back to a module, and those that carry its own previous output or judgment.
# A design takes hypothesis_evaluation on its first run too, so a return's source must be newer than its last run.
RETURN_INPUTS = ('findings', 'green_blocker', 'plan_evaluation', 'hypothesis_evaluation')
RERUN_INPUTS = ('previous_findings', 'previous_evaluation', 'previous_report', 'previous_feature_design', 'previous_verification_design')
REFERENCE = re.compile(r'^- Reference: *([\w-]+)', re.M)


def turn_records(main):
    """Yields (record, line, ended) for each JSON record of a transcript; ended is true on the one record that ends a turn."""
    # Claude Code does not write turn_duration for every turn. A Stop hook that blocks also writes a
    # stop_hook_summary, with hookErrors, and the turn goes on.
    answered, closed = False, False
    with open(main, errors='replace') as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            t, ended = d.get('type'), False
            if t in ('assistant', 'user'):
                closed = False
                answered = t == 'assistant' and (d.get('message') or {}).get('stop_reason') == 'end_turn'
            elif t == 'system' and d.get('subtype') == 'turn_duration':
                ended = not closed
            elif t == 'system' and d.get('subtype') == 'stop_hook_summary':
                ended = answered and not closed and not d.get('hookErrors')
            closed = closed or ended
            yield d, line, ended


def scan(main, subdir):
    turns, last_kind, started, notified, keepalive, bg_calls = 0, None, {}, set(), set(), set()
    for d, line, ended in turn_records(main):
        t = d.get('type')
        if ended:
            turns += 1
            last_kind = 'end'
        elif t in ('assistant', 'user'):
            last_kind = 'work'
            c = (d.get('message') or {}).get('content')
            if t == 'assistant' and isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get('type') == 'tool_use':
                        if (b.get('input') or {}).get('run_in_background') is True:
                            bg_calls.add(b.get('id'))
                        if b.get('name') == 'Bash' \
                                and str((b.get('input') or {}).get('command', '')).lstrip().startswith('sleep '):
                            keepalive.add(b.get('id'))
            if t == 'user' and isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('tool_use_id') in bg_calls:
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


def last_turn_began(main):
    """When the transcript's last turn began, in epoch seconds; 0 with no record of one."""
    began, between = None, True
    if not os.path.exists(main):
        return 0
    for d, _, ended in turn_records(main):
        if ended:
            between = True
        elif d.get('type') in ('assistant', 'user') and between:
            began, between = d.get('timestamp'), False
    return datetime.datetime.fromisoformat(began.replace('Z', '+00:00')).timestamp() if began else 0


def latest_mtime(main, subdir):
    files = [main] + glob.glob(os.path.join(subdir, '*.jsonl'))
    return max(os.path.getmtime(p) for p in files if os.path.exists(p))


def live_children(sid, rows):
    """A Bash-tool shell still running under the worker. MCP servers and a terminal's hook helpers are also
    children of claude for the whole session, so only shells that source a Claude Code shell
    snapshot count."""
    roots = session_pids(sid, rows)
    return any(pp in roots and '.claude/shell-snapshots/' in c for _, pp, c in rows)


def screen_waiting(term, workspace, surface):
    try:
        out = term.read_screen(workspace, surface, 12)
    except Exception:
        return False
    return bool(terminals.INPUT_RE.search(out))


def session_status(term, workspace, proj, name, surface, sid, rows, now):
    main = os.path.join(proj, sid + '.jsonl')
    subdir = os.path.join(proj, sid, 'subagents')
    row = {'name': name, 'surface': surface, 'state': 'exited', 'turns': 0, 'pending': 0, 'idle_sec': None}
    has_transcript = os.path.exists(main)
    if has_transcript:
        turns, last_kind, pending = scan(main, subdir)
        idle = now - latest_mtime(main, subdir)
        row.update(turns=turns, pending=len(pending), idle_sec=int(idle))
    if not session_pids(sid, rows):
        return row
    if not has_transcript:
        row['state'] = 'no-transcript'
    elif last_kind == 'end' and not pending:
        row['state'] = 'turn-end'
    elif last_kind == 'end':
        row['state'] = 'idle-pending' if idle > IDLE_PENDING_AFTER and not live_children(sid, rows) else 'background'
    elif screen_waiting(term, workspace, surface):
        row['state'] = 'waiting-input'
    elif idle > STALL_AFTER and not live_children(sid, rows):
        row['state'] = 'stall'
    else:
        row['state'] = 'working'
    return row


def runbook_rows(text):
    """(session, module run, verdict, end cell) of each row of the progress table, by its header's columns;
    the end cell is empty when the table has no such column."""
    run_column, verdict_column, end_column = TABLE_COLUMNS
    columns, end, found = None, None, []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if run_column in cells and verdict_column in cells:
            columns = cells.index(run_column), cells.index(verdict_column)
            end = next((i for i, c in enumerate(cells) if c.startswith(end_column)), None)
        elif columns and TABLE_ROW.match(line) and len(cells) > max(columns):
            ended = cells[end] if end is not None and end < len(cells) else ''
            found.append((cells[0], cells[columns[0]], cells[columns[1]], ended))
    return found


def judged(verdict):
    """The state and short words of a verdict."""
    m = VERDICT.search(verdict)
    if m:
        words = m.group().lower()
        return ('fail' if MISSED.search(words) else 'pass'), words
    return 'noted', re.split(r'[,(]|\.(?:\s|$)', verdict)[0].strip()


def invocations(records):
    """Each invocation in the records folder by its run's name, oldest first."""
    found = {}
    paths = glob.glob(os.path.join(records, '*.invocation.json')) if records else []
    for path in sorted(paths, key=os.path.getmtime):
        try:
            d = json.load(open(path))
        except ValueError:
            continue
        found[os.path.basename(path)[:-len('.invocation.json')]] = (d.get('module'), d.get('out'), d.get('inputs') or {}, os.path.getmtime(path))
    return found


def entry_of(step, last_run, invoked):
    """(entry, cause) of a module's next run. last_run is that module's run before this one."""
    order = list(invoked)
    inputs = invoked[step['label']][2]

    def sources(key):
        """The runs an input came from, oldest first. An input is a path or an array of paths."""
        value = inputs.get(key)
        paths = value if isinstance(value, list) else [value]
        runs = {os.path.basename(os.path.dirname(p)) for p in paths if isinstance(p, str)}
        return sorted(runs & set(order), key=order.index)

    for key in RETURN_INPUTS:
        if key not in inputs:
            continue
        runs = sources(key)
        if not runs:
            # Made by the coordinator, not by a run: the input is there, its source is not a step.
            return 'return', None
        if order.index(runs[-1]) > order.index(last_run):
            return 'return', runs[-1]
    for key in RERUN_INPUTS:
        runs = sources(key)
        if runs:
            return 'rerun', runs[-1]
    return 'rerun', None


def session_of(stem, transcripts):
    """The first session whose transcript names this invocation: it was given the invocation there, and
    a later session may only mention it."""
    named = [name for name, text in transcripts.items() if f'/{stem}.invocation.json' in text]
    return named[0] if named else None


def flow(run_dir, env, sessions, proj):
    path = os.path.join(run_dir, 'runbook.md')
    text = open(path).read() if os.path.exists(path) else ''
    invoked = invocations(env.get('RECORDS'))
    left = dict(invoked)
    steps, recorded, began = [], {}, []
    for session, cell, verdict, ended in runbook_rows(text):
        m = re.match(r'[\w-]+', cell)
        stem = m.group() if m else ''
        module = invoked[stem][0] if stem in invoked else None
        left.pop(stem, None)
        recorded[session] = max([recorded.get(session, 0)] + [int(n) for n in TURN_END.findall(ended)])
        state, words = judged(verdict)
        steps.append({'session': session, 'label': stem if module else cell, 'module': module, 'state': state, 'verdict': words})
    if left:
        transcripts = {}
        for s in sessions:
            main = os.path.join(proj, s['sid'] + '.jsonl')
            transcripts[s['name']] = open(main, errors='replace').read() if os.path.exists(main) else ''
        for stem, (module, out, _, written) in left.items():
            done = bool(out) and os.path.exists(os.path.join(out, 'result.json'))
            steps.append({'session': session_of(stem, transcripts), 'label': stem, 'module': module,
                          'state': 'awaiting' if done else 'running', 'verdict': 'awaiting verdict' if done else None})
            began.append((written, steps[-1]))
    # A module run again under the next number, a letter possibly following it (review-1a). Not the module's
    # name alone: a module can run once per criterion in one pass (criterion-in-depth-AC1-1, -AC2-1).
    last = {}
    for step in steps:
        step['entry'], step['cause'] = None, None
        if step['module']:
            base = re.sub(r'-?\d+[A-Za-z]*$', '', step['label'])
            if base in last:
                step['entry'], step['cause'] = entry_of(step, last[base], invoked)
            last[base] = step['label']
    by_name = {s['name']: s for s in sessions}
    for s in sessions:
        mine = [step['state'] for step in steps if step['session'] == s['name']]
        if s['state'] == 'exited':
            extra = None if mine else ('no record', 'unknown', None)
        elif s['state'] == 'turn-end':
            covered = 'running' in mine or 'awaiting' in mine or s['turns'] <= recorded.get(s['name'], 0)
            extra = None if covered else ('no row yet', 'awaiting', 'awaiting verdict')
        else:
            extra = None if 'running' in mine else ('no row yet', 'running', None)
        if extra:
            steps.append({'session': s['name'], 'label': extra[0], 'module': None, 'entry': None, 'cause': None, 'state': extra[1], 'verdict': extra[2]})
            if extra[1] != 'unknown':
                began.append((last_turn_began(os.path.join(proj, s['sid'] + '.jsonl')), steps[-1]))
    for step in steps:
        s = by_name.get(step['session'])
        running = step['state'] == 'running' and s is not None
        step['session_state'] = s['state'] if running else None
        step['idle_sec'] = s['idle_sec'] if running else None
    m = REFERENCE.search(text)
    return (m.group(1) if m else None), steps, max(reversed(began), key=lambda b: b[0])[1] if began else None


def run_status(run_dir, rows, now):
    run = {'name': os.path.basename(os.path.normpath(run_dir)), 'issue': None, 'branch': None, 'reference': None, 'now': None, 'steps': [], 'sessions': []}
    try:
        env = read_env(run_dir)
        run.update(issue=env.get('ISSUE'), branch=env.get('BRANCH'))
        # Without CHECKOUT there is no transcript to read: its sessions show only whether their process runs.
        proj = transcript_dir(env) if 'CHECKOUT' in env else ''
        path = os.path.join(run_dir, 'sessions.tsv')
        lines = [l for l in open(path).read().splitlines() if l.strip()] if os.path.exists(path) else []
        term = terminals.load(env['TERMINAL']) if 'TERMINAL' in env else None
        for line in lines:
            name, surface, sid = line.split('\t')[:3]
            row = session_status(term, env.get('TERMINAL_WORKSPACE'), proj, name, surface, sid, rows, now)
            run['sessions'].append({**row, 'sid': sid})
        run['reference'], run['steps'], run['now'] = flow(run_dir, env, run['sessions'], proj)
    except (OSError, KeyError, ValueError, terminals.TerminalError) as e:
        run['error'] = repr(e)
    for s in run['sessions']:
        del s['sid']
    return run


def runs_root():
    config = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.py')
    p = subprocess.run([sys.executable, config, 'runs'], capture_output=True, text=True)
    if p.returncode:
        sys.exit(p.stderr.strip())
    return p.stdout.strip()


def active_runs(runs):
    found = []
    for env in glob.glob(os.path.join(runs, '*', 'run.env')):
        with open(env) as f:
            if 'STATE=active' in f.read().splitlines():
                found.append(os.path.dirname(env))
    return sorted(found, key=os.path.getmtime, reverse=True)


def caller_place(named):
    """(terminal, workspace, surface) of this process; exits with the reason if that cannot be told."""
    try:
        name = terminals.resolve(named)
        return (name, *terminals.load(name).caller())
    except terminals.TerminalError as e:
        sys.exit(f'--caller: no calling surface: {e}')


def prepared_in(run_dir, place):
    env = read_env(run_dir)
    return (env.get('TERMINAL'), env.get('TERMINAL_WORKSPACE'), env.get('COORD_SURFACE')) == place


if __name__ == '__main__':
    args = sys.argv[1:]
    if args[:1] == ['--caller']:
        if args[1:] and (len(args) != 3 or args[1] != '--terminal'):
            sys.exit(__doc__)
        place = caller_place(args[2] if args[1:] else None)
        dirs = [d for d in active_runs(runs_root()) if prepared_in(d, place)]
    elif len(args) > 1:
        sys.exit(__doc__)
    elif args:
        named = args[0]
        dirs = [named if os.path.isdir(named) else os.path.join(runs_root(), named)]
        if not os.path.isdir(dirs[0]):
            sys.exit(f'no run {named}: not a directory and not under {runs_root()}')
    else:
        dirs = active_runs(runs_root())
    rows = process_rows()
    print(json.dumps({'runs': [run_status(d, rows, time.time()) for d in dirs]}, ensure_ascii=False))
