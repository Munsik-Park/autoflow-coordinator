#!/usr/bin/env python3
"""questions.py — the choice-question hook of a work session, its record, and the reader of that record.

  questions.py <run-dir> pre <hold-sec> | post | start      the hook command, its input on stdin
  questions.py hooks <run-dir> [<name>]                      the settings' hooks object for a run folder, as JSON
  questions.py started <run-dir> <session id> <settings> [<since>]
                                                             exit 0 if the session's record has a started line
                                                             (written at or after <since>, in epoch seconds);
                                                             otherwise prints why and exits 1

The hook holds each AskUserQuestion call of a work session until the call's answer file appears in the run
folder (tools/session.py send writes it) and then answers the call with that file's text as the free-text
answer of every question. A release file for the call (tools/session.py release) wins over an answer file
found at the same look. The hook lets the call's dialog be drawn, writing released with the cause, when:
  previews                          the call's options carry previews: no free-text row
  not of the form an answer needs   the call's input has no questions with options to answer
  release                           its release file appears; the hook removes that file
  answer file unreadable            its answer file appears and cannot be read
  hold ended                        QUESTION_HOLD passes
  stopped                           it gets SIGTERM, SIGHUP or SIGINT
It prints only the answer, and always exits 0.

The record, <run-dir>/questions-<session id>.jsonl, holds one JSON line per event, each written with one
append: held (with tool_use_id, tool_input, and the hook's pid and parent pid), taken, released (with its
cause), post, and started. The record and the answer and release files are readable by their owner only.
"""
import json, os, re, shlex, signal, subprocess, sys, time

TOOL = os.path.abspath(__file__)
TOOLS = os.path.dirname(TOOL)
# How long a call is held for its answer before its dialog is drawn for the operator.
QUESTION_HOLD = 8 * 3600
# What the PreToolUse entry's timeout adds to the hold, so that the hook ends its hold itself.
HOLD_MARGIN = 600
# The timeout of the other entries.
ENTRY_TIMEOUT = 30
# How often the hook looks for the answer and release files.
POLL = 0.5
TOOL_NAME = 'AskUserQuestion'
SESSION_ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
TOOL_USE_ID = re.compile(r'[A-Za-z0-9_-]+')
# Causes written in a released line.
PREVIEWS, RELEASE, HOLD_ENDED, STOPPED = 'previews', 'release', 'hold ended', 'stopped'
NOT_ANSWERABLE, UNREADABLE = 'not of the form an answer needs', 'answer file unreadable'


def record_path(run_dir, sid):
    return os.path.join(run_dir, f'questions-{sid}.jsonl')


def answer_path(run_dir, tool_use_id):
    return os.path.join(run_dir, f'answer-{tool_use_id}')


def release_path(run_dir, tool_use_id):
    return os.path.join(run_dir, f'release-{tool_use_id}')


def private(path, flags):
    """path opened for writing with mode 0600 when it is made."""
    return os.open(path, os.O_WRONLY | os.O_CREAT | flags, 0o600)


def write_atomic(path, text):
    """Written in full, then renamed into place, so that the hook never reads part of it."""
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(private(tmp, os.O_TRUNC), 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def hooks(run_dir, name=None):
    """The settings' hooks object that records and holds a session's choice questions in run_dir. name is
    the session's name in sessions.tsv, shown in the hold's status message."""
    def command(*args):
        return ' '.join(shlex.quote(a) for a in ('python3', TOOL, run_dir, *args))
    release = ' '.join(shlex.quote(a) for a in (os.path.join(TOOLS, 'session.py'), run_dir, name or '<k>', 'release'))
    return {
        'PreToolUse': [{'matcher': TOOL_NAME, 'hooks': [{
            'type': 'command', 'command': command('pre', str(QUESTION_HOLD)), 'timeout': QUESTION_HOLD + HOLD_MARGIN,
            'statusMessage': f"held for the coordination session's answer; to answer it yourself: {release}"}]}],
        'PostToolUse': [{'matcher': TOOL_NAME, 'hooks': [{
            'type': 'command', 'command': command('post'), 'timeout': ENTRY_TIMEOUT}]}],
        'SessionStart': [{'hooks': [{'type': 'command', 'command': command('start'), 'timeout': ENTRY_TIMEOUT}]}],
    }


def well_formed(call_input):
    """Whether an AskUserQuestion input has questions, each with its text and options that each have a label."""
    questions = call_input.get('questions') if isinstance(call_input, dict) else None
    return isinstance(questions, list) and bool(questions) \
        and all(isinstance(q, dict) and isinstance(q.get('question'), str) and isinstance(q.get('options'), list)
                and q['options'] and all(isinstance(o, dict) and isinstance(o.get('label'), str) for o in q['options'])
                for q in questions)


def previews(call_input):
    return any(isinstance(o, dict) and 'preview' in o
               for q in call_input['questions'] for o in q['options'])


def lines(record):
    found = []
    try:
        with open(record, errors='replace') as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    found.append(d)
    except OSError:
        pass
    return found


def alive(pid, ppid):
    """Whether the process pid runs with the parent ppid; a pid used again has another parent."""
    if not isinstance(pid, int) or not isinstance(ppid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    ps = subprocess.run(['ps', '-o', 'ppid=', '-p', str(pid)], capture_output=True, text=True)
    return ps.stdout.strip() == str(ppid)


def result_in(transcript, tool_use_id):
    """Whether the transcript holds a tool_result for the call, an answer or a rejection."""
    try:
        f = open(transcript, errors='replace')
    except OSError:
        return False
    with f:
        for line in f:
            if tool_use_id not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            content = (d.get('message') or {}).get('content') if d.get('type') == 'user' else None
            if any(isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('tool_use_id') == tool_use_id
                   for b in (content if isinstance(content, list) else [])):
                return True
    return False


def last_call(record, transcript):
    """The session's last call, {'tool_use_id', 'input', 'state', 'cause'}, or None when the record holds none.
    state is closed (a post line, or a tool_result for it in the transcript), released (cause from its line),
    taken, held (its hook process lives), or gone (its hook process does not, with no later line)."""
    found = call_state(lines(record), transcript, alive)
    if found and found['state'] == 'gone':
        # The hook writes its line before it exits: read again, for a line written after the first read.
        found = call_state(lines(record), transcript, lambda pid, ppid: False)
    return found


def call_state(recs, transcript, alive):
    held = next((d for d in reversed(recs) if d.get('event') == 'held'), None)
    if held is None:
        return None
    tool_use_id = held.get('tool_use_id')
    later = [d.get('event') for d in recs if d.get('tool_use_id') == tool_use_id]
    found = {'tool_use_id': tool_use_id, 'input': held.get('tool_input'), 'cause': None}
    if 'post' in later or result_in(transcript, tool_use_id):
        found['state'] = 'closed'
    elif 'released' in later:
        found['state'] = 'released'
        found['cause'] = next(d.get('cause') for d in reversed(recs)
                              if d.get('tool_use_id') == tool_use_id and d.get('event') == 'released')
    elif 'taken' in later:
        found['state'] = 'taken'
    else:
        found['state'] = 'held' if alive(held.get('pid'), held.get('ppid')) else 'gone'
    return found


def launch_reason(record, settings, since=0):
    """Why a launched session is not used for work, or None when its record has a started line written at or
    after since."""
    if any(d.get('event') == 'started' and isinstance(d.get('at'), (int, float)) and d['at'] >= since
           for d in lines(record)):
        return None
    return (f"no started line in {record}: the session's hooks did not run. Either its settings ({settings}) were "
            'not applied, or hooks are disabled for it, or a dialog such as folder trust holds its start. '
            'The session is not used for work: close it, and launch it again once the cause is cleared.')


def append(record, event, **fields):
    with open(private(record, os.O_APPEND), 'a') as f:
        f.write(json.dumps({'event': event, 'at': time.time(), **fields}, ensure_ascii=False) + '\n')


def hold(record, run_dir, tool_use_id, call_input, seconds):
    """Hold the call until its answer, its release, the hold's end or a signal. Returns the hook's output."""
    append(record, 'held', tool_use_id=tool_use_id, tool_input=call_input, pid=os.getpid(), ppid=os.getppid())

    def stopped(*_):
        append(record, 'released', tool_use_id=tool_use_id, cause=STOPPED)
        os._exit(0)
    for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(s, stopped)
    if not well_formed(call_input) or previews(call_input):
        append(record, 'released', tool_use_id=tool_use_id,
               cause=NOT_ANSWERABLE if not well_formed(call_input) else PREVIEWS)
        return None
    answer, release, end = answer_path(run_dir, tool_use_id), release_path(run_dir, tool_use_id), time.time() + seconds
    while time.time() < end:
        if os.path.exists(release):
            try:
                os.remove(release)
            except OSError:
                pass
            append(record, 'released', tool_use_id=tool_use_id, cause=RELEASE)
            return None
        if os.path.exists(answer):
            try:
                with open(answer) as f:
                    text = f.read()
                os.remove(answer)
            except OSError:
                append(record, 'released', tool_use_id=tool_use_id, cause=UNREADABLE)
                return None
            append(record, 'taken', tool_use_id=tool_use_id)
            return {'hookSpecificOutput': {
                'hookEventName': 'PreToolUse', 'permissionDecision': 'allow',
                'updatedInput': dict(call_input, answers={q['question']: text for q in call_input['questions']})}}
        time.sleep(POLL)
    append(record, 'released', tool_use_id=tool_use_id, cause=HOLD_ENDED)
    return None


def hook(run_dir, event, seconds):
    try:
        d = json.loads(sys.stdin.read())
    except ValueError:
        return
    sid = d.get('session_id') if isinstance(d, dict) else None
    if not isinstance(sid, str) or not SESSION_ID.fullmatch(sid) or not os.path.isdir(run_dir):
        return
    record = record_path(run_dir, sid)
    if event == 'start':
        append(record, 'started', session_id=sid, source=d.get('source'))
        return
    tool_use_id = d.get('tool_use_id')
    if d.get('tool_name') != TOOL_NAME or not isinstance(tool_use_id, str) or not TOOL_USE_ID.fullmatch(tool_use_id):
        return
    if event == 'post':
        append(record, 'post', tool_use_id=tool_use_id)
    elif event == 'pre':
        out = hold(record, run_dir, tool_use_id, d.get('tool_input'), seconds)
        if out:
            print(json.dumps(out, ensure_ascii=False))


def main(args):
    if args[:1] == ['hooks'] and len(args) in (2, 3):
        print(json.dumps(hooks(args[1], args[2] if len(args) == 3 else None)))
    elif args[:1] == ['started'] and len(args) in (4, 5):
        reason = launch_reason(record_path(args[1], args[2]), args[3], float(args[4]) if len(args) == 5 else 0)
        if reason:
            print(reason)
            sys.exit(1)
    elif len(args) >= 2 and args[1] in ('pre', 'post', 'start'):
        # A hook ends with exit status 0 whatever happens: anything else would reach the session as an error.
        try:
            hook(args[0], args[1], float(args[2]) if args[1] == 'pre' and len(args) > 2 else QUESTION_HOLD)
        except Exception:
            pass
        sys.exit(0)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
