#!/usr/bin/env python3
"""terminal_check.py [--terminal <name>] — check a terminal's module against the operations' contract,
in the real terminal: run it inside that terminal. Claude Code must already trust this tool clone, where
the sessions run. Prints PASS or FAIL <why> per item; exit status 0 only if all pass. A failed item ends
its group.

It opens panes below this one and starts Claude Code sessions (--model haiku) that take a few short
turns, among them choice questions answered with session.py send. Each session starts with the question
hooks of tools/questions.py, as a work session does. Each group ends its session and closes its pane before
the next group, and the cleanup removes their transcripts and temporary files. A draft in the input and the
question and permission pages are checked on screens as text, because the operations cannot bring those
about on purpose.

It needs a caller at least twice SESSION_ROW_HEIGHT rows high, so that a pane opened below it gets the rows
a work session gets; otherwise it exits non-zero before it opens anything. Read the exit status without a
pipe, or with pipefail: a pipe gives its last command's.
"""
import argparse, json, os, shlex, signal, shutil, subprocess, sys, tempfile, time, uuid

import terminals
import questions
from session import answered, arrived, entered_texts, process_rows, session_pids, squeeze, transcript_dir

TOOLS = os.path.dirname(os.path.abspath(__file__))
TRUSTED = os.path.dirname(TOOLS)
WAIT = 120
# How long a session's question hooks may take to write the started line: launch.sh's wait after the start.
STARTED_WAIT = 15


def filled(start):
    """start and short lines, up to the largest size submit takes."""
    text, i = start, 0
    while len(text.encode()) + len(f'line {i}\n') <= terminals.MAX_SUBMIT_BYTES:
        text, i = text + f'line {i}\n', i + 1
    return text + 'x' * (terminals.MAX_SUBMIT_BYTES - len(text.encode()))


PLAIN = filled('Reply with only the word PONG. Ignore the lines below.\n'
               '\tliteral "double" \'single\' $HOME `tick`\n\n')


class Failed(Exception):
    pass


def require(ok, why):
    if not ok:
        raise Failed(why)


def wait_for(predicate, why, seconds=WAIT):
    deadline = time.time() + seconds
    while not predicate():
        require(time.time() < deadline, f'{why} after {seconds}s')
        time.sleep(1)


class Check:
    def __init__(self, name):
        self.term = terminals.load(name)
        self.name = name
        self.workspace, self.coord = self.term.caller()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='terminal-check-'))
        self.opened = []
        self.sids = []
        self.failed = False

    def item(self, label, step):
        try:
            step()
        except (Failed, terminals.TerminalError) as e:
            print(f'FAIL {label}: {e}')
            self.failed = True
            raise Failed()
        print(f'PASS {label}')

    def open(self, sid):
        surface = terminals.open_session(self.term, self.workspace, self.coord, [s for s, _ in self.opened])
        self.opened.append((surface, sid))
        self.sids.append(sid)
        return surface

    def run_dir(self, sid):
        """The session's run folder: its question record and answer files, and what session.py reads."""
        run = os.path.join(self.tmp, 'run-' + sid)
        os.makedirs(run, exist_ok=True)
        return run

    def start_claude(self, surface, cwd, sid, *flags):
        args = ' '.join(shlex.quote(a) for a in flags)
        self.term.send_line(self.workspace, surface, f'cd {shlex.quote(cwd)} && clear')
        # Suggestions off and the question hooks on, as for a work session: suggestions read as a draft. The
        # session may read this check's files, which a question too long to submit is written to.
        settings = os.path.join(self.tmp, f'settings-{sid}.json')
        with open(settings, 'w') as f:
            json.dump({'promptSuggestionEnabled': False, 'hooks': questions.hooks(self.run_dir(sid), 'X1'),
                       'permissions': {'allow': [f'Read(/{self.tmp}/**)']}}, f)
        self.term.send_line(self.workspace, surface, f'claude --model haiku --settings {shlex.quote(settings)} '
                                                     f'--session-id {sid} {args}')

    def record(self, sid):
        return questions.record_path(self.run_dir(sid), sid)

    def started(self, sid):
        """The session's question hooks ran at its start: its record's started line, waited for as launch.sh
        waits for it."""
        reason = lambda: questions.launch_reason(self.record(sid), 'the --settings file')
        try:
            wait_for(lambda: reason() is None, 'no started line', STARTED_WAIT)
        except Failed:
            raise Failed(reason())

    def end_session(self, surface, sid):
        """End the session's process and close its pane, so that the next group's pane opens below the caller
        at its width."""
        for pid in session_pids(sid, process_rows()):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        wait_for(lambda: not session_pids(sid, process_rows()), 'the session did not end', 15)
        if self.term.exists(self.workspace, surface):
            self.term.close(self.workspace, surface)
        wait_for(lambda: not self.term.exists(self.workspace, surface), f'{surface} still open', 15)
        self.opened = [(s, i) for s, i in self.opened if s != surface]

    def transcript(self, sid):
        return os.path.join(transcript_dir({'CHECKOUT': TRUSTED}), sid + '.jsonl')

    def turns(self, path):
        if not os.path.exists(path):
            return 0
        with open(path, errors='replace') as f:
            return sum('"turn_duration"' in line for line in f)

    def session_tool(self, surface, sid, action, *extra):
        """tools/session.py for the session in surface: (exit status, output)."""
        run = self.run_dir(sid)
        with open(os.path.join(run, 'run.env'), 'w') as f:
            f.write(f'TERMINAL={self.name}\nTERMINAL_WORKSPACE={self.workspace}\nCHECKOUT={TRUSTED}\n')
        with open(os.path.join(run, 'sessions.tsv'), 'w') as f:
            f.write(f'X1\t{surface}\t{sid}\n')
        p = subprocess.run([sys.executable, os.path.join(TOOLS, 'session.py'), run, 'X1', action, *extra],
                           capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr).strip()

    def fixture(self):
        """A plugin with one skill, so that a slash command can be checked without running a module."""
        root = os.path.join(self.tmp, 'plugin')
        os.makedirs(os.path.join(root, '.claude-plugin'))
        os.makedirs(os.path.join(root, 'skills', 'ping'))
        with open(os.path.join(root, '.claude-plugin', 'plugin.json'), 'w') as f:
            json.dump({'name': 'termcheck', 'version': '0.0.0'}, f)
        with open(os.path.join(root, 'skills', 'ping', 'SKILL.md'), 'w') as f:
            f.write('---\nname: ping\ndescription: terminal check\n---\nReply with only the word PONG. Do not use tools.\n')
        return root

    def placement(self):
        """Bare shells: the place of a surface does not depend on what runs in it."""
        size = lambda surface: self.term.geometry(self.workspace, surface)
        panes = []

        def open_shell():
            panes.append(self.open(str(uuid.uuid4())))
            return panes[-1]

        def first():
            coord = size(self.coord)
            row = size(open_shell())
            require(row[1] > coord[1], f'not below: {coord} and {row}')
            require(row[2] == coord[2], f'not as wide as the coordination surface: {coord} and {row}')
            wanted = min(terminals.SESSION_ROW_HEIGHT, coord[3] // 2)
            require(abs(row[3] - wanted) <= 1, f'{row[3]} rows, not {wanted}')

        def next_ones():
            coord = size(self.coord)
            for _ in range(2):
                others = {p: size(p) for p in panes[:-1]}
                last = size(panes[-1])
                made = size(open_shell())
                require(made[0] > last[0] and made[1] == last[1], f'not right of the last: {last} and {made}')
                require(made[3] == last[3], f'not as high as the last: {last} and {made}')
                require(size(self.coord) == coord, f'the coordination surface changed: {coord} and {size(self.coord)}')
                for pane, was in others.items():
                    require(size(pane) == was, f'{pane} changed: {was} and {size(pane)}')

        def one_closed():
            self.close_shell(panes.pop(0))
            last = size(panes[-1])
            made = size(open_shell())
            require(made[0] > last[0] and made[1] == last[1], f'not right of the last open one: {last} and {made}')

        def all_closed():
            while panes:
                self.close_shell(panes.pop())
            coord = size(self.coord)
            made = size(open_shell())
            require(made[1] > coord[1] and size(self.coord)[3] < coord[3], f'not below again: {coord} and {made}')
            self.close_shell(panes.pop())

        self.item('placement: the first below, at the start height', first)
        self.item('placement: the next right of the last, no other surface changing', next_ones)
        self.item('placement: right of the last one open', one_closed)
        self.item('placement: below again once all are closed', all_closed)

    def close_shell(self, surface):
        self.term.close(self.workspace, surface)
        wait_for(lambda: not self.term.exists(self.workspace, surface), f'{surface} still open', 15)
        self.opened = [(s, sid) for s, sid in self.opened if s != surface]

    def surfaces_and_input(self):
        sid = str(uuid.uuid4())
        path = self.transcript(sid)
        state = {}

        def ids():
            for value in (self.workspace, self.coord):
                require(terminals.UNQUOTED.fullmatch(value), f'{value!r} does not match UNQUOTED')

        def split():
            state['surface'] = self.open(sid)
            require(terminals.UNQUOTED.fullmatch(state['surface']), f'{state["surface"]!r} does not match UNQUOTED')
            require(self.term.exists(self.workspace, state['surface']), 'exists is false for the new surface')
            self.term.rename(self.workspace, state['surface'], 'terminal check')

        def screen():
            # Ends in ; because a terminal's command line may treat that one as its own. The clear leaves
            # the rows below the output blank, which read_screen must not count.
            self.term.send_line(self.workspace, state['surface'], 'clear; echo TERMCHECK\\;')
            wait_for(lambda: 'TERMCHECK;' in self.term.read_screen(self.workspace, state['surface'], 12),
                     'the output is not in read_screen(12)', 15)

        def plain():
            self.start_claude(state['surface'], TRUSTED, sid, '--plugin-dir', self.fixture())
            wait_for(lambda: terminals.input_held(self.term.read_screen(self.workspace, state['surface'], 12)) is None,
                     'no empty input area on the screen')
            self.started(sid)
            self.term.submit(self.workspace, state['surface'], PLAIN)
            wait_for(lambda: arrived(path, 0, PLAIN), 'the message is not in the transcript')
            with open(path, errors='replace') as f:
                texts = [t for line in f for t in entered_texts(line)]
            require(not any('<pasted_content' in t for t in texts), 'it arrived as pasted material')
            require(any(squeeze(t) == squeeze(PLAIN) for t in texts), 'it arrived altered or split')
            wait_for(lambda: self.turns(path) >= 1, 'the turn did not end')

        def slash():
            # Keep the non-ASCII text: a message can be in any language, and without it nothing here submits
            # multi-byte or wide characters.
            instruction = filled(f'/termcheck:ping {self.tmp}/x.json\n\nGoal: the goal the contract sets.\n'
                                 'Constraint: stop when it ends.\nNon-ASCII text: 계약이 정한 목표, déjà vu.\n')
            done = self.turns(path)
            offset = os.path.getsize(path)
            self.term.submit(self.workspace, state['surface'], instruction)
            wait_for(lambda: arrived(path, offset, instruction), 'the command is not in the transcript')
            with open(path, 'rb') as f:
                f.seek(offset)
                gained = f.read().decode(errors='replace')
            require('<command-name>/termcheck:ping</command-name>' in gained, 'it did not run as a slash command')
            wait_for(lambda: self.turns(path) > done, 'the turn did not end')

        def oversize():
            before = self.term.read_screen(self.workspace, state['surface'], 12)
            try:
                self.term.submit(self.workspace, state['surface'], 'x' * (terminals.MAX_SUBMIT_BYTES + 1))
            except terminals.TerminalError:
                time.sleep(1)
                require(self.term.read_screen(self.workspace, state['surface'], 12) == before, 'the refusal changed the screen')
                return
            raise Failed('submit took more than MAX_SUBMIT_BYTES')

        def session(action, expected, *extra):
            code, out = self.session_tool(state['surface'], sid, action, *extra)
            require(out.startswith(expected) and code == 0, out)

        def session_send():
            message = os.path.join(self.tmp, 'next.txt')
            with open(message, 'w') as f:
                f.write('Reply with only the word PONG.\nThis is the next instruction.\n')
            session('send', 'ARRIVED', message)

        def session_close():
            session('close', 'CLOSED')
            require(not self.term.exists(self.workspace, state['surface']), 'exists is true after close')
            self.opened.remove((state['surface'], sid))

        self.item('ids match UNQUOTED', ids)
        self.item('split, exists, rename', split)
        self.item('send_line, read_screen', screen)
        self.item('submit: plain message, the question hooks started', plain)
        self.item('submit: slash command', slash)
        self.item('submit: refused over the size limit', oversize)
        self.item('session.py send', session_send)
        self.item('session.py close, close, exists', session_close)

    def questions(self):
        """Choice questions held by the question hooks and answered with session.py send: a single-select
        call, two questions with one text, two questions with the same options, and a multiSelect call whose
        labels are longer than a row of the session, which the session reads from a file, each held, ANSWERED,
        received and its turn ended; then a call with option previews, which the hooks release and send leaves
        as it is."""
        sid = str(uuid.uuid4())
        path = self.transcript(sid)
        record = self.record(sid)
        state = {}
        option = lambda label: {'label': label, 'description': label.lower()}
        text = 'Decision: the second option, because this check needs one.'
        decision = os.path.join(self.tmp, 'decision.txt')
        with open(decision, 'w') as f:
            f.write(text)

        def ask(qs, held=('held',), in_file=False):
            spec = json.dumps({'questions': qs})
            if in_file:
                # A spec sized from the session's width can be longer than submit takes, so the session reads it.
                spec_path = os.path.join(self.tmp, 'question.json')
                with open(spec_path, 'w') as f:
                    f.write(spec)
                prompt = (f'Read the file {spec_path}. It holds one JSON object. Call the AskUserQuestion tool '
                          'exactly once with that object as its input. When the answer comes back, reply with only '
                          'the word DONE. Use no tool other than these two.')
            else:
                prompt = (f'Call the AskUserQuestion tool exactly once with this input: {spec} When the answer '
                          'comes back, reply with only the word DONE. Use no other tool.')
            state['turns'] = self.turns(path)
            last = (questions.last_call(record, path) or {}).get('tool_use_id')
            self.term.submit(self.workspace, state['surface'], prompt)
            wait_for(lambda: (questions.last_call(record, path) or {}).get('tool_use_id') not in (None, last)
                     and questions.last_call(record, path)['state'] in held, 'no question in the question record')
            return questions.last_call(record, path)

        def answer(qs, in_file=False):
            call = ask(qs, in_file=in_file)
            state['call'] = call
            code, out = self.session_tool(state['surface'], sid, 'send', decision)
            require(code == 0 and out.startswith('ANSWERED'), out)
            require(answered(path, 0, {'id': call['tool_use_id'], 'input': call['input']}, text),
                    'the transcript has no answer holding the text')
            wait_for(lambda: self.turns(path) > state['turns'], 'the turn did not end')

        def start():
            state['surface'] = self.open(sid)
            self.start_claude(state['surface'], TRUSTED, sid)
            wait_for(lambda: terminals.input_held(self.term.read_screen(self.workspace, state['surface'], 12)) is None,
                     'no empty input area on the screen')
            self.started(sid)

        def single():
            answer([{'question': 'Which one?', 'header': 'One', 'multiSelect': False,
                     'options': [option('First'), option('Second')]}])

        def two():
            answer([{'question': 'Which size?', 'header': 'Size', 'multiSelect': False,
                     'options': [option('Small'), option('Large')]},
                    {'question': 'Which form?', 'header': 'Form', 'multiSelect': False,
                     'options': [option('Text'), option('Table')]}])

        def same_options():
            answer([{'question': 'Which size for the first file?', 'header': 'First', 'multiSelect': False,
                     'options': [option('Small'), option('Large')]},
                    {'question': 'Which size for the second file?', 'header': 'Second', 'multiSelect': False,
                     'options': [option('Small'), option('Large')]}])

        def multiselect():
            width = self.term.geometry(self.workspace, state['surface'])[2]
            long = lambda word: {'label': (word + ' ') * (width // len(word) + 1), 'description': word.lower()}
            answer([{'question': 'Which checks?', 'header': 'Checks', 'multiSelect': True,
                     'options': [long('Lint'), long('Types'), long('Tests')]}], in_file=True)
            labels = [o.get('label', '') for q in state['call']['input'].get('questions', []) for o in q.get('options', [])]
            require(labels and all(len(label) > width for label in labels),
                    f'the call held labels no longer than a row of {width}: {labels}')

        def preview():
            call = ask([{'question': 'Which layout?', 'header': 'Layout', 'multiSelect': False,
                         'options': [dict(option('Stacked'), preview='A\nB'), dict(option('Side'), preview='A | B')]}],
                       held=('released',))
            require(call['cause'] == questions.PREVIEWS, f'released: {call["cause"]}')
            wait_for(lambda: terminals.question_open(
                self.term.read_screen(self.workspace, state['surface'], terminals.WHOLE_SCREEN)), 'no dialog on the screen')
            time.sleep(2)
            before = self.term.read_screen(self.workspace, state['surface'], terminals.WHOLE_SCREEN)
            size = os.path.getsize(path) if os.path.exists(path) else 0
            code, out = self.session_tool(state['surface'], sid, 'send', decision)
            require(code != 0 and out.startswith('NOT_ARRIVED the question has no free-text row'), out)
            require(self.term.read_screen(self.workspace, state['surface'], terminals.WHOLE_SCREEN) == before,
                    'send changed the screen')
            require(not answered(path, size, {'id': call['tool_use_id'], 'input': call['input']}, text),
                    'send answered the call')

        def end():
            self.end_session(state['surface'], sid)

        self.item('questions: a session, the question hooks started', start)
        self.item('questions: single-select held and answered with session.py send', single)
        self.item('questions: two questions answered with one text', two)
        self.item('questions: two questions with the same options', same_options)
        self.item('questions: multiSelect with labels longer than a row', multiselect)
        self.item('questions: a question with previews released and left as it is', preview)
        self.item('questions: the session ended and its pane closed', end)

    def refusal(self):
        sid = str(uuid.uuid4())

        def refused():
            folder = os.path.join(self.tmp, 'untrusted')
            os.makedirs(folder)
            surface = self.open(sid)
            self.start_claude(surface, folder, sid)
            wait_for(lambda: terminals.INPUT_RE.search(self.term.read_screen(self.workspace, surface, 12)),
                     'no trust dialog on the screen', 30)
            before = self.term.read_screen(self.workspace, surface, 12)
            try:
                self.term.submit(self.workspace, surface, 'this must not be entered')
            except terminals.TerminalError:
                time.sleep(1)
                require(self.term.read_screen(self.workspace, surface, 12) == before, 'the refusal changed the screen')
                return
            raise Failed('submit returned in front of a dialog')

        def end():
            for surface, opened_sid in list(self.opened):
                if opened_sid == sid:
                    self.end_session(surface, sid)

        self.item('submit: refused at a dialog', refused)
        self.item('submit: the session ended and its pane closed', end)

    def screens(self):
        """Screens as text, for the states the operations cannot bring about on purpose."""
        rule, status = '─' * 40, '  ⏵⏵ auto mode on'
        def area(*rows):
            return '\n'.join(['report', rule, *rows, rule, status])

        def judged():
            for label, screen, passes in (
                    ('empty', area('❯\xa0'), True),
                    ('words of a dialog in a report', 'Would you like to\n' + area('❯\xa0'), True),
                    ('draft', area('❯\xa0my draft'), False),
                    ('draft with a blank first row', area('❯\xa0', '  second'), False),
                    ('bash mode', area('!\xa0echo x'), False),
                    ('bash mode with no command', area('!\xa0'), False),
                    ('no input area', 'Do you want to proceed?\n❯ 1. Yes\nEsc to cancel', False),
                    ('one rule', rule + '\n❯\xa0', False),
                    ('dialog between rules', area('Do you want to proceed?', '❯ 1. Yes'), False)):
                require((terminals.input_held(screen) is None) == passes, f'{label}: {terminals.input_held(screen)!r}')
            text = 'first line\n\tsecond line\nlast line'
            for label, screen, holds in (
                    ('the text', area('❯\xa0first line', '  second line', '  last line'), True),
                    ('the end of a tall text', area('❯\xa0last line'), True),
                    ('a wrapped line', area('❯\xa0first line', 'second', 'line last', 'line'), True),
                    ('a tall text past the upper rule', '  second line\n  last line\n' + rule + '\n' + status, True),
                    ('an empty input', area('❯\xa0'), False),
                    ('other text', area('❯\xa0something else'), False),
                    ('a dialog', 'Do you want to proceed?\n❯ 1. Yes\nEsc to cancel', False),
                    ('a dialog between rules', area('Do you want to proceed?', '❯ 1. Yes'), False)):
                require(terminals.input_holds(screen, text) == holds, f'input_holds on {label}')

        def named():
            # Question and review pages as a 15-row session at 36 columns shows them: the footer wrapped, a row
            # naming the rows above the screen, the page's top cut off.
            narrow = '─' * 36
            footer = ['Enter to select · ↑/↓ to navigate ·', 'Esc to cancel']
            pages = {
                'question page': ['❯ 1. First', '     first', '  2. Second', '  3. Type something.', narrow,
                                  '  4. Chat about this', '', *footer],
                'question page with a hint row': ['  2. Second', '❯ 3. Type something.', narrow,
                                                  '  4. Chat about this', ' ↑ 4 more lines', *footer],
                'question page, footer on three lines': ['❯ 1. First', narrow, '  3. Chat about this', '',
                                                         'Enter to select · ↑/↓ to', 'navigate · ctrl+g to edit',
                                                         '· Esc to cancel'],
                'question page with previews': ['❯ 1. Stacked', narrow, '  Chat about this', '',
                                                'Enter to select · ↑/↓ to navigate · n to add notes · Esc to cancel'],
                'question worded as a permission prompt': ['Do you want to proceed?', '❯ 1. Yes', narrow,
                                                           '  3. Chat about this', '', *footer],
                'review page': ['   → Decision: the second', '   option.', ' ↑ 6 more lines', '❯ 1. Submit answers',
                                '  2. Cancel'],
            }
            for label, rows in pages.items():
                held = terminals.input_held('\n'.join(rows))
                require(held == 'a choice question is open', f'{label}: {held!r}')
            permission = '\n'.join(['report', rule, ' Bash command', ' touch x', ' Do you want to proceed?',
                                    ' ❯ 1. Yes', '   2. No', '', ' Esc to cancel · Tab to amend'])
            require('permission prompt' in (terminals.input_held(permission) or ''), 'permission prompt not named')
            held = area('❯\xa0')
            require(terminals.input_held('· Fluttering… (esc to interrupt)\n' + held) is None,
                    'a held question\'s empty input area')

        self.item('input_held on screens', judged)
        self.item('question pages named on screens', named)

    def cleanup(self):
        for surface, sid in self.opened:
            rows = process_rows()
            for pid in session_pids(sid, rows):
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            time.sleep(2)
            try:
                if self.term.exists(self.workspace, surface):
                    self.term.close(self.workspace, surface)
                require(not self.term.exists(self.workspace, surface), 'exists is true after close')
            except (Failed, terminals.TerminalError) as e:
                print(f'FAIL cleanup of {surface}: {e}')
                self.failed = True

    def sweep(self):
        for sid in self.sids:
            path = self.transcript(sid)
            if os.path.exists(path):
                os.remove(path)
        shutil.rmtree(transcript_dir({'CHECKOUT': os.path.join(self.tmp, 'untrusted')}), ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description='Check a terminal module against the operations\' contract.')
    ap.add_argument('--terminal')
    args = ap.parse_args()
    try:
        name = terminals.resolve(args.terminal)
        check = Check(name)
    except terminals.TerminalError as e:
        sys.exit(str(e))
    print(f'terminal: {name}')
    rows = check.term.geometry(check.workspace, check.coord)[3]
    if rows < 2 * terminals.SESSION_ROW_HEIGHT:
        check.sweep()
        sys.exit(f'the caller has {rows} rows; it needs {2 * terminals.SESSION_ROW_HEIGHT} (twice SESSION_ROW_HEIGHT), '
                 f'so that a pane opened below it gets {terminals.SESSION_ROW_HEIGHT}; nothing was opened')
    try:
        for group in (check.screens, check.placement, check.surfaces_and_input, check.questions, check.refusal):
            try:
                group()
            except Failed:
                pass
    finally:
        try:
            check.cleanup()
        finally:
            check.sweep()
    sys.exit(1 if check.failed else 0)


if __name__ == '__main__':
    main()
