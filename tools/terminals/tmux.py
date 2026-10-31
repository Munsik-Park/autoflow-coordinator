"""tmux implementation of the terminal operations. A workspace is a window id and a surface a pane id.

Pane ids are unique in a tmux server, so the operations address a pane alone. The server is the one in
$TMUX: a run's tools stay inside the tmux server it was prepared in.
"""
import os, subprocess, time

from . import TerminalError, input_holds, submit_refused

PASTE_WAIT = 1


def tmux(*args, stdin=None):
    try:
        p = subprocess.run(['tmux', *args], input=stdin, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise TerminalError(f'tmux {args[0]}: {e}')
    if p.returncode:
        raise TerminalError(f'tmux {args[0]}: {p.stderr.strip() or p.returncode}')
    return p.stdout


def inside():
    return bool(os.environ.get('TMUX') and os.environ.get('TMUX_PANE'))


def caller():
    """$TMUX_PANE, because display without -t answers for the active pane. A window id, because a session
    id starts with $ and a session name may hold spaces."""
    pane = os.environ.get('TMUX_PANE')
    if not pane:
        raise TerminalError('tmux: no $TMUX_PANE; run this from the coordination pane')
    return tmux('display-message', '-p', '-t', pane, '#{window_id}').strip(), pane


def split(workspace, surface):
    pane = tmux('split-window', '-d', '-h', '-t', surface, '-P', '-F', '#{pane_id}').strip()
    if not pane:
        raise TerminalError('tmux split-window: no pane id')
    # Each split halves the pane it splits, so the panes are made even to leave every session usable.
    try:
        tmux('select-layout', '-t', pane, 'even-horizontal')
    except TerminalError as e:
        close(workspace, pane)
        raise TerminalError(f'{pane} closed: {e}')
    return pane


def keys_reach(surface):
    """In copy mode, which an operator enters to scroll, keys go to the mode and are lost."""
    if tmux('display-message', '-p', '-t', surface, '#{pane_in_mode}').strip() != '0':
        raise TerminalError(f'{surface} is in copy mode: leave it (q) and retry')


def send_line(workspace, surface, text):
    """tmux takes an argument's trailing ; as a command separator, so those go as hex."""
    keys_reach(surface)
    body = text.rstrip(';')
    if body:
        tmux('send-keys', '-t', surface, '-l', '--', body)
    if len(text) > len(body):
        tmux('send-keys', '-t', surface, '-H', *['3b'] * (len(text) - len(body)))
    tmux('send-keys', '-t', surface, 'Enter')


def submit(workspace, surface, text):
    """paste-buffer -r: with -p the message arrives as <pasted_content> and a module command in it does
    not run; with neither, each line feed becomes a carriage return and may submit its line."""
    keys_reach(surface)
    refused = submit_refused(screen(surface), text)
    if refused:
        raise TerminalError(f'{surface}: {refused}')
    buffer = 'coordination-' + surface.lstrip('%')
    tmux('load-buffer', '-b', buffer, '-', stdin=text.strip('\n'))
    tmux('paste-buffer', '-r', '-d', '-b', buffer, '-t', surface)
    time.sleep(PASTE_WAIT)
    if not input_holds(screen(surface), text):
        raise TerminalError(f'{surface}: the input area does not show the text; Enter not sent')
    tmux('send-keys', '-t', surface, 'Enter')


def screen(surface):
    """Claude Code draws from the top of a cleared pane, so the screen's bottom rows may all be blank."""
    return tmux('capture-pane', '-p', '-t', surface).rstrip()


def read_screen(workspace, surface, lines):
    return '\n'.join(screen(surface).splitlines()[-lines:])


def rename(workspace, surface, name):
    """A label, not the pane title: Claude Code overwrites the title."""
    tmux('set-option', '-p', '-t', surface, '@label', name)
    tmux('set-option', '-w', '-t', surface, 'pane-border-status', 'top')
    tmux('set-option', '-w', '-t', surface, 'pane-border-format', ' #{?#{@label},#{@label},#{pane_title}} ')


def exists(workspace, surface):
    return surface in tmux('list-panes', '-a', '-F', '#{pane_id}').split()


def close(workspace, surface):
    tmux('kill-pane', '-t', surface)
