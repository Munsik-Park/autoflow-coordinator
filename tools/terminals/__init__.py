"""The terminal operations coordination needs. One module per terminal in this package.

A module provides every operation below. A terminal that cannot provide them all is not supported.
A module's name is the terminal's name, and the workspaces and surfaces it takes and returns are its
own ids. A surface is the place one session runs in.

An operation that does not reach its result raises TerminalError.
"""
import importlib, pkgutil

OPERATIONS = {
    'inside': 'inside() -> bool: this process runs in this terminal',
    'caller': 'caller() -> (workspace, surface): where this process runs, not where the focus is',
    'split': 'split(workspace, surface) -> surface: a new one with a shell, beside the given one, the focus staying',
    'send_line': 'send_line(workspace, surface, text): type one line and press Enter',
    'submit': 'submit(workspace, surface, text): enter the text, lines and all, as one ordinary message, not as pasted material, and submit it',
    'read_screen': 'read_screen(workspace, surface, lines) -> str: the last lines of its screen',
    'rename': 'rename(workspace, surface, name): the name shown for it',
    'exists': 'exists(workspace, surface) -> bool',
    'close': 'close(workspace, surface): close it and what its session opened beside it, once its session has ended',
}


class TerminalError(Exception):
    pass


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
    """The name of the one terminal this process runs in."""
    found = [n for n in names() if load(n).inside()]
    if len(found) != 1:
        raise TerminalError(f'this process must run in exactly one supported terminal ({", ".join(names())}); it runs in {found or "none"}')
    return found[0]
