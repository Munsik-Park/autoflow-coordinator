#!/usr/bin/env python3
"""terminal_check.py [--terminal <name>] — check a terminal's module against the operations' contract,
in the real terminal: run it inside that terminal. Claude Code must already trust this tool clone, where
the sessions run. Prints PASS or FAIL <why> per item; exit status 0 only if all pass. A failed item ends
its group.

It opens panes beside this one and starts Claude Code sessions (--model haiku) that take a few short
turns. It closes them and removes their transcripts and temporary files. A draft in the input is checked
on screens as text: no operation can leave one.
"""
import argparse, json, os, shlex, signal, shutil, subprocess, sys, tempfile, time, uuid

import terminals
from session import arrived, entered_texts, process_rows, session_pids, squeeze, transcript_dir

TOOLS = os.path.dirname(os.path.abspath(__file__))
TRUSTED = os.path.dirname(TOOLS)
WAIT = 120
PLAIN = ('Reply with only the word PONG. Ignore the lines below.\n'
         + '\tliteral "double" \'single\' $HOME `tick`\n\n'
         + ''.join(f'line {i}\n' for i in range(80)))


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
        surface = self.term.split(self.workspace, self.coord)
        self.opened.append((surface, sid))
        self.sids.append(sid)
        return surface

    def start_claude(self, surface, cwd, sid, *flags):
        args = ' '.join(shlex.quote(a) for a in flags)
        self.term.send_line(self.workspace, surface, f'cd {shlex.quote(cwd)} && clear')
        self.term.send_line(self.workspace, surface, f'claude --model haiku --session-id {sid} {args}')

    def transcript(self, sid):
        return os.path.join(transcript_dir({'CHECKOUT': TRUSTED}), sid + '.jsonl')

    def turns(self, path):
        if not os.path.exists(path):
            return 0
        with open(path, errors='replace') as f:
            return sum('"turn_duration"' in line for line in f)

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
            self.term.submit(self.workspace, state['surface'], PLAIN)
            wait_for(lambda: arrived(path, 0, PLAIN), 'the message is not in the transcript')
            with open(path, errors='replace') as f:
                texts = [t for line in f for t in entered_texts(line)]
            require(not any('<pasted_content' in t for t in texts), 'it arrived as pasted material')
            require(any(squeeze(t) == squeeze(PLAIN) for t in texts), 'it arrived altered or split')
            wait_for(lambda: self.turns(path) >= 1, 'the turn did not end')

        def slash():
            instruction = f'/termcheck:ping {self.tmp}/x.json\n\n목표: 계약이 정한 목표.\n제약: 끝나면 멈추세요.\n'
            done = self.turns(path)
            offset = os.path.getsize(path)
            self.term.submit(self.workspace, state['surface'], instruction)
            wait_for(lambda: arrived(path, offset, instruction), 'the command is not in the transcript')
            with open(path, 'rb') as f:
                f.seek(offset)
                gained = f.read().decode(errors='replace')
            require('<command-name>/termcheck:ping</command-name>' in gained, 'it did not run as a slash command')
            wait_for(lambda: self.turns(path) > done, 'the turn did not end')

        def session(action, expected, *extra):
            run = os.path.join(self.tmp, 'run')
            os.makedirs(run, exist_ok=True)
            with open(os.path.join(run, 'run.env'), 'w') as f:
                f.write(f'TERMINAL={self.name}\nTERMINAL_WORKSPACE={self.workspace}\nCHECKOUT={TRUSTED}\n')
            with open(os.path.join(run, 'sessions.tsv'), 'w') as f:
                f.write(f'X1\t{state["surface"]}\t{sid}\n')
            p = subprocess.run([sys.executable, os.path.join(TOOLS, 'session.py'), run, 'X1', action, *extra],
                               capture_output=True, text=True)
            require(p.stdout.startswith(expected) and p.returncode == 0, f'{p.stdout.strip()} {p.stderr.strip()}')

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
        self.item('submit: plain message', plain)
        self.item('submit: slash command', slash)
        self.item('session.py send', session_send)
        self.item('session.py close, close, exists', session_close)

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

        self.item('submit: refused at a dialog', refused)

    def screens(self):
        """The screens no operation can bring about, as text."""
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

        self.item('input_held on screens', judged)

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
    try:
        for group in (check.screens, check.surfaces_and_input, check.refusal):
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
