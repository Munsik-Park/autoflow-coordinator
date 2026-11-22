#!/usr/bin/env python3
"""session.py <run-dir> <k> send <file> | release | close — give a work session its next instruction, free its
held choice question for the operator, or end it, and confirm the result.

  <run-dir>  <runs>/<name>/ holding run.env (TERMINAL, TERMINAL_WORKSPACE, CHECKOUT) and sessions.tsv (Sk, surface, session id)
  <k>        work session number, or a one-off session name such as X1

A session started by tools/launch.sh holds each of its choice questions for its answer and records it in its
question record (tools/questions.py), with no dialog on the screen.

send gives <file>'s own text to a held question as the free-text answer of every question of the call, and
waits for the session to record it as the answer. Otherwise it enters <file> as one message, and a module
run's instruction file (<records>/<module>-<n>.prompt.txt, tools/invocation.py) that is over the size a
terminal takes as one message (MAX_SUBMIT_BYTES in tools/terminals/__init__.py) is entered as one line that
names it by the path of its invocation, for the session to read. Prints one line, exit status 0 only for the
first two:
  ARRIVED              the transcript took all that was entered, as a message or queued behind a turn
  ANSWERED             the transcript recorded the text as the answer to every question of the call; one line
                       per question follows, its header and its question
  NOT_RUNNING          the session's process is gone; nothing was entered, the shell would have run it
  NOT_ARRIVED <why>    not in the transcript after 60 s, or the terminal refused, or a choice question is open
                       that the tool does not answer, which <why> names (a question with option previews, one
                       released to the operator, one the question record does not hold); the screen follows.
                       Or the line that names a module run's instruction file is over that size too: nothing
                       was entered, and no screen follows

release frees the question the session holds: its dialog is drawn, for the operator to answer. Prints one
line, exit status 0 only for the first:
  RELEASED             the record shows it released and the screen shows its page; one line per question
                       follows, its header and its question, then the screen
  NOT_RELEASED <why>   not shown released with its page on the screen within 60 s; the screen follows
  NOT_HELD <state>     the session holds no question (taken, released, gone, closed, or none in the record);
                       nothing was written. Or the hook took an answer before the release: NOT_HELD taken,
                       and that answer is the session's

close sends /exit, confirms the process is gone, then closes the surface and confirms that. Run it again
after a failure: it does only what is left. Prints one line, exit status 0 only for the first:
  CLOSED               the process and the surface are gone
  EXIT_BLOCKED <why>   a held choice question (answer it with send or free it with release), a draft or a
                       dialog holds the input, the process is still there 30 s after /exit, or the terminal
                       refused; the screen follows and the surface is left open
  CLOSE_FAILED <why>   the process is gone, the surface is not
"""
import json, os, re, subprocess, sys, time

import questions
import terminals
from ended import INVOCATION, PROMPT

ARRIVE_WAIT = 60
# How long send waits for the hook to take the answer file: some seconds above its polling interval.
TAKE_WAIT = questions.POLL + 5
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


def answered(path, offset, call, text):
    """Whether the transcript gained, after offset, the answer to call, an AskUserQuestion tool_use block: its
    tool_result without is_error, with an answer holding text for every question of the call."""
    want = squeeze(text)
    questions = [q.get('question') for q in (call.get('input') or {}).get('questions') or []]
    if not questions or not os.path.exists(path):
        return False
    with open(path, 'rb') as f:
        f.seek(offset)
        lines = f.read().decode(errors='replace').splitlines()
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        content = (d.get('message') or {}).get('content') if d.get('type') == 'user' else None
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('tool_use_id') == call.get('id') \
                    and not b.get('is_error'):
                answers = (d.get('toolUseResult') or {}).get('answers') if isinstance(d.get('toolUseResult'), dict) else None
                if isinstance(answers, dict) and all(want in squeeze(str(answers.get(q, ''))) for q in questions):
                    return True
    return False


def fits(text):
    """Whether text is within the size a terminal takes as one message."""
    return len(text.encode()) <= terminals.MAX_SUBMIT_BYTES


def line_for(path):
    """One line that tells a session to read the module run's instruction file at path, named by the path of
    the invocation beside it."""
    return f'Read {os.path.basename(path)}, the instruction file beside {path[:-len(PROMPT)] + INVOCATION}, and follow it.'


def to_enter(path, instruction):
    """What send enters for the instruction file at path, an absolute path: its text. For a module run's
    instruction file, the one beside that run's invocation under the same name, whose text is over
    MAX_SUBMIT_BYTES: line_for(path), or None when that line is over it too."""
    if fits(instruction) or not (path.endswith(PROMPT) and os.path.isfile(path[:-len(PROMPT)] + INVOCATION)):
        return instruction
    return line_for(path) if fits(line_for(path)) else None


def report(line, term=None, workspace=None, surface=None, lines=()):
    print(line)
    for l in lines:
        print(l)
    if term:
        try:
            print(term.read_screen(workspace, surface, 12))
        except terminals.TerminalError as e:
            print(f'(no screen: {e})')
    sys.exit(0 if line in ('ARRIVED', 'ANSWERED', 'RELEASED', 'CLOSED') else 1)


def question_lines(call_input):
    return [f'{q.get("header", "")}: {q["question"]}' for q in call_input['questions']]


def question_on_screen(term, workspace, surface):
    try:
        return terminals.question_open(term.read_screen(workspace, surface, terminals.WHOLE_SCREEN))
    except terminals.TerminalError:
        return False


def send(term, workspace, surface, sid, path, file, instruction, run_dir):
    if not session_pids(sid, process_rows()):
        report('NOT_RUNNING')
    record = questions.record_path(run_dir, sid)
    call = questions.last_call(record, path)
    state = call['state'] if call else None
    if state == 'held':
        answer(term, workspace, surface, path, record, run_dir, call, instruction)
    if state == 'taken':
        if questions.well_formed(call['input']):
            receipt(term, workspace, surface, path, 0, call, instruction)
        report('NOT_ARRIVED the question record holds a call not of the form an answer needs; nothing was entered',
               term, workspace, surface)
    if state == 'released':
        if call['cause'] == questions.PREVIEWS:
            report('NOT_ARRIVED the question has no free-text row (options with previews); nothing was entered',
                   term, workspace, surface)
        released(call['cause'], term, workspace, surface)
    if state == 'gone' and question_on_screen(term, workspace, surface):
        released('the hook ended', term, workspace, surface)
    if state is None and question_on_screen(term, workspace, surface):
        report('NOT_ARRIVED a choice question is open that the question record does not hold; it goes to the '
               'operator; nothing was entered', term, workspace, surface)
    entered = to_enter(file, instruction)
    if entered is None:
        report(f'NOT_ARRIVED nothing was entered: {file} is {len(instruction.encode())} bytes and the line that names it '
               f'{len(line_for(file).encode())} bytes, both over {terminals.MAX_SUBMIT_BYTES} (MAX_SUBMIT_BYTES)')
    offset = os.path.getsize(path) if os.path.exists(path) else 0
    try:
        term.submit(workspace, surface, entered)
    except terminals.TerminalError as e:
        report(f'NOT_ARRIVED {e}', term, workspace, surface)
    deadline = time.time() + ARRIVE_WAIT
    while not arrived(path, offset, entered):
        if time.time() > deadline:
            report(f'NOT_ARRIVED no sign of it in {path} after {ARRIVE_WAIT}s', term, workspace, surface)
        time.sleep(2)
    report('ARRIVED')


def released(cause, term, workspace, surface):
    report(f"NOT_ARRIVED the question was released to the operator ({cause}); its dialog is the operator's; "
           'nothing was entered', term, workspace, surface)


def answer(term, workspace, surface, path, record, run_dir, call, text):
    """The file's own text is the answer: a line that names a file would not state the decision."""
    if not questions.well_formed(call['input']):
        report('NOT_ARRIVED the held question is not of the form an answer needs; nothing was entered',
               term, workspace, surface)
    if not fits(text):
        report(f'NOT_ARRIVED {len(text.encode())} bytes is over {terminals.MAX_SUBMIT_BYTES} (MAX_SUBMIT_BYTES): '
               'put the details in a file and answer with the decision; nothing was entered', term, workspace, surface)
    offset = os.path.getsize(path) if os.path.exists(path) else 0
    file = questions.answer_path(run_dir, call['tool_use_id'])
    questions.write_atomic(file, text)
    deadline = time.time() + TAKE_WAIT
    while True:
        now = questions.last_call(record, path) or {}
        if now.get('tool_use_id') != call['tool_use_id']:
            break
        if now['state'] in ('taken', 'closed'):
            receipt(term, workspace, surface, path, offset, call, text)
        if now['state'] == 'released':
            if os.path.exists(file):
                os.remove(file)
            released(now['cause'], term, workspace, surface)
        if now['state'] == 'gone':
            break
        if time.time() > deadline:
            report(f'NOT_ARRIVED {call["tool_use_id"]}: its hook did not take the answer within {TAKE_WAIT}s; '
                   f'the answer is left in {file} for it', term, workspace, surface)
        time.sleep(0.5)
    if os.path.exists(file):
        os.remove(file)
    report(f'NOT_ARRIVED {call["tool_use_id"]}: its hook ended before the answer; nothing was entered',
           term, workspace, surface)


def receipt(term, workspace, surface, path, offset, call, text):
    block = {'id': call['tool_use_id'], 'input': call['input']}
    deadline = time.time() + ARRIVE_WAIT
    while not answered(path, offset, block, text):
        if time.time() > deadline:
            report(f'NOT_ARRIVED no answer in {path} after {ARRIVE_WAIT}s', term, workspace, surface)
        time.sleep(2)
    report('ANSWERED', lines=question_lines(call['input']))


def release(term, workspace, surface, sid, path, run_dir):
    record = questions.record_path(run_dir, sid)
    call = questions.last_call(record, path)
    if not call or call['state'] != 'held':
        report(f'NOT_HELD {call["state"] if call else "none in the record"}')
    # An answer an earlier send left for the hook must not be taken after the release.
    left = questions.answer_path(run_dir, call['tool_use_id'])
    if os.path.exists(left):
        os.remove(left)
    questions.write_atomic(questions.release_path(run_dir, call['tool_use_id']), '')
    deadline = time.time() + ARRIVE_WAIT
    while not ((questions.last_call(record, path) or {}).get('state') == 'released'
               and question_on_screen(term, workspace, surface)):
        if (questions.last_call(record, path) or {}).get('state') == 'taken':
            report('NOT_HELD taken: the hook took an answer before the release; it is the session\'s answer',
                   term, workspace, surface)
        if time.time() > deadline:
            report(f'NOT_RELEASED no released dialog on the screen after {ARRIVE_WAIT}s', term, workspace, surface)
        time.sleep(1)
    lines = question_lines(call['input']) if questions.well_formed(call['input']) else []
    report('RELEASED', term, workspace, surface, lines=lines)


def close(term, workspace, surface, sid, path, run_dir):
    call = questions.last_call(questions.record_path(run_dir, sid), path)
    if call and call['state'] == 'held':
        # /exit would end the session with the question unanswered and no record of it in the transcript.
        shown = '; '.join(question_lines(call['input'])) if questions.well_formed(call['input']) else call['tool_use_id']
        report(f'EXIT_BLOCKED a choice question is held: {shown}; answer it with send or free it with release',
               term, workspace, surface)
    if session_pids(sid, process_rows()):
        try:
            # /exit would join a draft or answer a dialog.
            held = terminals.input_held(term.read_screen(workspace, surface, terminals.WHOLE_SCREEN))
            if held:
                report(f'EXIT_BLOCKED {held}', term, workspace, surface)
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
    if not (len(args) == 4 and args[2] == 'send' or len(args) == 3 and args[2] in ('release', 'close')):
        sys.exit(__doc__)
    run_dir, k, action = args[:3]
    env = read_env(run_dir)
    _, surface, sid = session_row(run_dir, k)
    try:
        term = terminals.load(env['TERMINAL'])
    except (KeyError, terminals.TerminalError) as e:
        sys.exit(f'{run_dir}/run.env: {e!r}')
    workspace = env['TERMINAL_WORKSPACE']
    path = os.path.join(transcript_dir(env), sid + '.jsonl')
    if action == 'release':
        release(term, workspace, surface, sid, path, run_dir)
    if action == 'close':
        close(term, workspace, surface, sid, path, run_dir)
    with open(args[3]) as f:
        instruction = f.read()
    if not instruction.strip():
        sys.exit(f'{args[3]} is empty')
    send(term, workspace, surface, sid, path, os.path.abspath(args[3]), instruction, run_dir)
