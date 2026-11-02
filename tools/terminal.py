#!/usr/bin/env python3
"""terminal.py <terminal> <workspace> <operation> <surface> [args...] — one terminal operation, from a
shell. <terminal> is the terminal's module name and <workspace> its workspace id. Prints the
operation's result if it has one; a failure goes to stderr with exit status 1.

  open_session <surface> [<surface>...]
                                 for the coordination surface and the surfaces of its sessions, oldest
                                 first, opens one for a new session and prints it
  send_line <surface> <text>
  read_screen <surface> <lines>
  rename <surface> <name>
"""
import sys

import terminals

SHELL_OPERATIONS = {'send_line': 2, 'read_screen': 2, 'rename': 2}

if len(sys.argv) < 4 or (len(sys.argv) < 5 if sys.argv[3] == 'open_session'
                         else SHELL_OPERATIONS.get(sys.argv[3]) != len(sys.argv) - 4):
    sys.exit(__doc__)
name, workspace, operation, *args = sys.argv[1:]
if operation == 'read_screen':
    args[1] = int(args[1])
try:
    term = terminals.load(name)
    result = (terminals.open_session(term, workspace, args[0], args[1:]) if operation == 'open_session'
              else getattr(term, operation)(workspace, *args))
except terminals.TerminalError as e:
    sys.exit(str(e))
if result is not None:
    print(result)
