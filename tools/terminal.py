#!/usr/bin/env python3
"""terminal.py <terminal> <workspace> <operation> <surface> [args...] — one terminal operation, from a
shell. <terminal> is the terminal's module name and <workspace> its workspace id. Prints the
operation's result if it has one; a failure goes to stderr with exit status 1.

  split <surface>                prints the new surface
  send_line <surface> <text>
  read_screen <surface> <lines>
  rename <surface> <name>
"""
import sys

import terminals

SHELL_OPERATIONS = {'split': 1, 'send_line': 2, 'read_screen': 2, 'rename': 2}

if len(sys.argv) < 4 or SHELL_OPERATIONS.get(sys.argv[3]) != len(sys.argv) - 4:
    sys.exit(__doc__)
name, workspace, operation, *args = sys.argv[1:]
if operation == 'read_screen':
    args[1] = int(args[1])
try:
    result = getattr(terminals.load(name), operation)(workspace, *args)
except terminals.TerminalError as e:
    sys.exit(str(e))
if result is not None:
    print(result)
