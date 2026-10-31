"""cmux implementation of the terminal operations."""
import json, os, subprocess, time

from . import TerminalError, input_held, input_holds

SHELL_EXIT_WAIT = 10
SPLIT_WAIT = 5
# More than a screen has. read-screen stops at the screen, so this reads all of it.
SCREEN_LINES = 5000


def cmux(*args, stdin=None):
    try:
        p = subprocess.run(['cmux', *args], input=stdin, capture_output=True, text=True, timeout=20,
                           env={**os.environ, 'CMUX_QUIET': '1'})
    except (OSError, subprocess.TimeoutExpired) as e:
        raise TerminalError(f'cmux {args[0]}: {e}')
    if p.returncode:
        raise TerminalError(f'cmux {args[0]}: {p.stderr.strip() or p.returncode}')
    return p.stdout


def inside():
    return bool(os.environ.get('CMUX_SURFACE_ID'))


def caller():
    """identify's focused may be another window's."""
    try:
        c = json.loads(cmux('identify'))['caller']
        return c['workspace_ref'], c['surface_ref']
    except (ValueError, KeyError, TypeError, TerminalError) as e:
        raise TerminalError(f'cmux identify: no calling surface; run this from the coordination surface ({e})')


def split(workspace, surface):
    fields = cmux('new-split', 'right', '--workspace', workspace, '--surface', surface, '--focus', 'false').split()
    if len(fields) < 2:
        raise TerminalError(f'cmux new-split: no surface in {fields}')
    # new-split returns before cmux tree lists the surface.
    deadline = time.time() + SPLIT_WAIT
    why = 'not listed'
    while time.time() < deadline:
        try:
            if exists(workspace, fields[1]):
                return fields[1]
        except TerminalError as e:
            why = str(e)
        time.sleep(0.1)
    # It cannot be closed by what is not listed, so the error names it.
    raise TerminalError(f'{fields[1]} left open, {SPLIT_WAIT}s after new-split: {why}')


def send_line(workspace, surface, text):
    cmux('send', '--workspace', workspace, '--surface', surface, text + '\n')


def submit(workspace, surface, text):
    """Line by line, because paste --submit of several lines arrives as <pasted_content> and a module
    command in it does not run. A single-line paste is an ordinary input. Only the first paste keeps
    cmux's refusal of a draft or a dialog: from the second line on the draft is our own. cmux does not
    refuse at every dialog (it pastes at the trust dialog), so the screen is read first."""
    held = input_held(read_screen(workspace, surface, SCREEN_LINES))
    if held:
        raise TerminalError(f'{surface}: {held}')
    target = ('--workspace', workspace, '--surface', surface)
    lines = text.strip('\n').split('\n')
    cmux('paste', *target, '-', stdin=lines[0])
    for line in lines[1:]:
        cmux('send-key', *target, 'ctrl+j')
        if line:
            cmux('paste', '--force', *target, '-', stdin=line)
    time.sleep(0.5)
    if not input_holds(read_screen(workspace, surface, SCREEN_LINES), text):
        raise TerminalError(f'{surface}: the input area does not show the text; Enter not sent')
    cmux('send-key', *target, 'enter')


def read_screen(workspace, surface, lines):
    return cmux('read-screen', '--workspace', workspace, '--surface', surface, '--lines', str(lines))


def rename(workspace, surface, name):
    cmux('rename-tab', '--workspace', workspace, '--surface', surface, name)


def panes(workspace):
    tree = json.loads(cmux('--json', 'tree', '--all', '--workspace', workspace))
    return [p for w in tree['windows'] for ws in w['workspaces'] for p in ws['panes']]


def exists(workspace, surface):
    return any(surface in p['surface_refs'] for p in panes(workspace))


def close(workspace, surface):
    """A browser surface, which a session's Artifact opens in its pane, closes without a dialog. A
    terminal surface does not: close-surface asks about the whole tab, so its shell is told to exit."""
    for pane in panes(workspace):
        if surface in pane['surface_refs']:
            for s in pane['surfaces']:
                if s['type'] == 'browser':
                    cmux('close-surface', '--workspace', workspace, '--surface', s['ref'])
    send_line(workspace, surface, 'exit')
    deadline = time.time() + SHELL_EXIT_WAIT
    while exists(workspace, surface):
        if time.time() > deadline:
            raise TerminalError(f'{surface} still open {SHELL_EXIT_WAIT}s after exit')
        time.sleep(1)
