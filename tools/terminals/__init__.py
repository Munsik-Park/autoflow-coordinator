"""The terminal operations coordination needs. One module per terminal in this package.

A module provides every operation below. A terminal that cannot provide them all is not supported.
A module's name is the terminal's name, and the workspaces and surfaces it takes and returns are its
own ids. A surface is the place one session runs in. An id matches UNQUOTED and stays the same while
the surface lives. A terminal without workspaces returns a fixed workspace.

Every module in this package counts as a terminal, so code shared between terminals lives in this file.

An operation that does not reach its result raises TerminalError.

To add a terminal: add its module, then pass the conformance test inside that terminal.
"""
import importlib, pkgutil, re

# One shell word that needs no quoting.
UNQUOTED = re.compile(r'[\w@%+=:,./-]+')
# A choice or permission prompt on a Claude Code screen.
INPUT_RE = re.compile(r'Do you want to|Enter to select|Esc to cancel|❯ \d+\.|Would you like to')
# A rule above or below Claude Code's input area.
INPUT_RULE_RE = re.compile(r'^─{3,}.*$', re.M)
# All that an empty input area holds.
EMPTY_INPUT = '❯'

OPERATIONS = {
    'inside': 'inside() -> bool: this process runs in this terminal; from the environment alone, since detect() asks every module, also where the terminal\'s command is missing',
    'caller': 'caller() -> (workspace, surface): where this process runs, not where the focus is',
    'split': 'split(workspace, surface) -> surface: a new one with a shell, beside the given one, the focus staying; exists() is true for it on return; on a failure, what it made is closed or named in the error',
    'send_line': 'send_line(workspace, surface, text): type one line and press Enter; refuse if the terminal would not pass the keys to the surface',
    'submit': 'submit(workspace, surface, text): enter the text, lines and all, as one ordinary message, not as pasted material, and submit it, a slash command on its first line running as one; refuse, entering nothing, if a dialog or a draft holds the input; press Enter only if the input area shows the text just before, or refuse, since Enter would answer a dialog that opened meanwhile',
    'read_screen': 'read_screen(workspace, surface, lines) -> str: the last lines of its screen, not counting blank lines below the content',
    'rename': 'rename(workspace, surface, name): the name shown for it',
    'exists': 'exists(workspace, surface) -> bool',
    'close': 'close(workspace, surface): close it and what its session opened beside it, once its session has ended',
}


class TerminalError(Exception):
    pass


def input_held(screen):
    """Why a Claude Code screen cannot take a message, or None. Only an input area recognised as empty
    passes: a draft, an input mode, a dialog and a screen this does not know all hold the input, so that
    what cannot be read stops the message visibly instead of mixing it with what is there."""
    area = input_area(screen)
    if area is None:
        return 'no input area on the screen'
    return None if area == EMPTY_INPUT else f'the input area is not empty: {area.splitlines()[0] if area else ""!r}'


def input_area(screen):
    """What Claude Code's input area shows, or None if the screen has none."""
    rules = list(INPUT_RULE_RE.finditer(screen))
    return screen[rules[-2].end():rules[-1].start()].strip() if len(rules) >= 2 else None


def input_holds(screen, text):
    """Whether the input area shows the end of text, so that Enter would submit it and nothing else. A tall
    text shows only its end, and the screen wraps and indents lines, so whitespace does not count."""
    area = input_area(screen)
    if area is None:
        return False
    shown = re.sub(r'\s+', '', area.removeprefix(EMPTY_INPUT))
    return bool(shown) and re.sub(r'\s+', '', text).endswith(shown)


def names():
    return [m.name for m in pkgutil.iter_modules(__path__)]


def load(name):
    if name not in names():
        raise TerminalError(f'unsupported terminal {name!r}: one of {", ".join(names())}')
    module = importlib.import_module(f'{__name__}.{name}')
    missing = [op for op in OPERATIONS if not callable(getattr(module, op, None))]
    if missing:
        raise TerminalError(f'terminal {name} does not provide {", ".join(missing)}')
    return module


def detect():
    """The name of the one terminal this process runs in. Nested terminals cannot be told apart here:
    the outer one's environment reaches the inner one."""
    found = [n for n in names() if load(n).inside()]
    if len(found) != 1:
        raise TerminalError(f'this process must run in exactly one supported terminal ({", ".join(names())}); '
                            f'it runs in {found or "none"}. If terminals are nested, name the one to use with --terminal')
    return found[0]


def resolve(name=None):
    """The named terminal if this process runs in it, or the detected one when none is named."""
    if name is None:
        return detect()
    if not load(name).inside():
        raise TerminalError(f'this process does not run in {name}')
    return name
