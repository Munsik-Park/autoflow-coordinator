#!/usr/bin/env python3
"""session.py <run-dir> <k> send <file> | close — give a work session its next instruction, or end it,
and confirm the result.

  <run-dir>  <runs>/<name>/ holding run.env (TERMINAL, TERMINAL_WORKSPACE, CHECKOUT) and sessions.tsv (Sk, surface, session id)
  <k>        work session number, or a one-off session name such as X1

send enters <file> into the session as one message. Prints one line, exit status 0 only for the first:
  ARRIVED              the transcript took the whole instruction, as a message or queued behind a turn
  NOT_RUNNING          the session's process is gone; nothing was entered, the shell would have run it
  NOT_ARRIVED <why>    not in the transcript after 60 s, or the terminal refused; the screen follows

close sends /exit, confirms the process is gone, then closes the surface and confirms that. Run it again
after a failure: it does only what is left. Prints one line, exit status 0 only for the first:
  CLOSED               the process and the surface are gone
  EXIT_BLOCKED <why>   the process is still there 30 s after /exit, or the terminal refused; the screen
                       follows and the surface is left open
  CLOSE_FAILED <why>   the process is gone, the surface is not
"""
import json, os, re, subprocess, sys, time

import terminals

ARRIVE_WAIT = 60
EXIT_WAIT = 30
# How a slash command's arguments are recorded around the text that was entered.
COMMAND_TAGS = re.compile(r'</?command-(?:message|name|args)>')


def read_env(run_dir):
    return dict(l.strip().split('=', 1) for l in open(os.path.join(run_dir, 'run.env')) if '=' in l)


def session_row(run_dir, k):
    """(name, surface, session id) of Sk, or of a one-off session such as X1."""
    name = f'S{k}' if k.isdigit() else k
    for line in open(os.path.join(run_dir, 'sessions.tsv')):
        row = line.rstrip('\n').split('\t')
        if row[0] == name:
            return name, row[1], row[2]
    sys.exit(f'{name} is not in {run_dir}/sessions.tsv')


def transcript_dir(env):
    return os.path.expanduser('~/.claude/projects/' + re.sub(r'[^A-Za-z0-9]', '-', os.path.expanduser(env['CHECKOUT'])))


def process_rows():
    ps = subprocess.run(['ps', '-axo', 'pid=,ppid=,command='], capture_output=True, text=True).stdout.splitlines()
    return [(int(a), int(b), c) for a, b, c in (r.strip().split(None, 2) for r in ps if len(r.split()) >= 3)]


def session_pids(sid, rows):
    """The claude process of a session. The executable's name, not its path: a terminal may start it
    through a wrapper with a full path or from PATH. Helpers such as `cmux hooks claude …` are not it."""
    return {p for p, _, c in rows if os.path.basename(c.split()[0]) == 'claude' and sid in c}


def squeeze(text):
    return re.sub(r'\s+', '', COMMAND_TAGS.sub('', text))


def entered_texts(line):
    """The text a transcript line records as entered. The terminal may change whitespace (a tab to spaces)."""
    try:
        d = json.loads(line)
    except ValueError:
        return []
    if d.get('type') == 'queue-operation' and d.get('operation') == 'enqueue':
        return [str(d.get('content'))]
    if d.get('type') == 'user':
        c = (d.get('message') or {}).get('content')
        if isinstance(c, str):
            return [c]
        if isinstance(c, list):
            return [b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text']
    return []


def arrived(path, offset, instruction):
    """Only what the transcript gained after offset, so that a repeated instruction is not taken for this one."""
    want = squeeze(instruction)
    if not os.path.exists(path):
        return False
    with open(path, 'rb') as f:
        f.seek(offset)
        return any(want in squeeze(t) for line in f.read().decode(errors='replace').splitlines() for t in entered_texts(line))


def report(line, term=None, workspace=None, surface=None):
    print(line)
    if term:
        try:
            print(term.read_screen(workspace, surface, 12))
        except terminals.TerminalError as e:
            print(f'(no screen: {e})')
    sys.exit(0 if line in ('ARRIVED', 'CLOSED') else 1)


def send(term, workspace, surface, sid, path, instruction):
    if not session_pids(sid, process_rows()):
        report('NOT_RUNNING')
    offset = os.path.getsize(path) if os.path.exists(path) else 0
    try:
        term.submit(workspace, surface, instruction)
    except terminals.TerminalError as e:
        report(f'NOT_ARRIVED {e}', term, workspace, surface)
    deadline = time.time() + ARRIVE_WAIT
    while not arrived(path, offset, instruction):
        if time.time() > deadline:
            report(f'NOT_ARRIVED no sign of it in {path} after {ARRIVE_WAIT}s', term, workspace, surface)
        time.sleep(2)
    report('ARRIVED')


def close(term, workspace, surface, sid):
    if session_pids(sid, process_rows()):
        try:
            term.send_line(workspace, surface, '/exit')
        except terminals.TerminalError as e:
            report(f'EXIT_BLOCKED {e}', term, workspace, surface)
        deadline = time.time() + EXIT_WAIT
        while session_pids(sid, process_rows()):
            if time.time() > deadline:
                report(f'EXIT_BLOCKED process still there {EXIT_WAIT}s after /exit', term, workspace, surface)
            time.sleep(1)
    try:
        if term.exists(workspace, surface):
            term.close(workspace, surface)
        if term.exists(workspace, surface):
            report(f'CLOSE_FAILED {surface} still open')
    except terminals.TerminalError as e:
        report(f'CLOSE_FAILED {e}')
    report('CLOSED')


if __name__ == '__main__':
    args = sys.argv[1:]
    if not (len(args) == 4 and args[2] == 'send' or len(args) == 3 and args[2] == 'close'):
        sys.exit(__doc__)
    run_dir, k, action = args[:3]
    env = read_env(run_dir)
    _, surface, sid = session_row(run_dir, k)
    try:
        term = terminals.load(env['TERMINAL'])
    except (KeyError, terminals.TerminalError) as e:
        sys.exit(f'{run_dir}/run.env: {e!r}')
    workspace = env['TERMINAL_WORKSPACE']
    if action == 'close':
        close(term, workspace, surface, sid)
    with open(args[3]) as f:
        instruction = f.read()
    if not instruction.strip():
        sys.exit(f'{args[3]} is empty')
    send(term, workspace, surface, sid, os.path.join(transcript_dir(env), sid + '.jsonl'), instruction)
