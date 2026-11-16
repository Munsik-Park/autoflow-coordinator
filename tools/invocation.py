#!/usr/bin/env python3
"""invocation.py <run-dir> <module> <inputs-json> [--instructions TEXT] — make the work folder of one module
run and write its invocation file and its instruction file.

  <run-dir>       <runs>/<name>/ holding run.env (RECORDS, MODULES, and USER_MODULES when recorded)
  <module>        a module of the run: a folder holding a SKILL.md in the run's default location MODULES
                  (the autoflow-module clone) or in its user location USER_MODULES
  <inputs-json>   a JSON object of the inputs given to the module, each a string or an array of strings,
                  named as the module's input section names them
  --instructions  the coordination session's instructions for this run: criteria other than the
                  module's defaults, how to start what the module runs, and so on

The module run's name is <module>-<n>, n being one more than the highest number that module has in the record
folder, from 1. This tool makes the name; the caller gives none. Under that name it makes

  <records>/<module>-<n>/                  the work folder, empty: only the module run writes inside it
  <records>/<module>-<n>.invocation.json   the invocation
  <records>/<module>-<n>.prompt.txt        the instruction file, which starts a session (tools/launch.sh
                                           --prompt) or is given to a running one (tools/session.py send)

and prints NAME, WORK_FOLDER, INVOCATION and PROMPT, one NAME=value line each. The end record
<records>/<module>-<n>.ended.json is written beside them by tools/watch.py.

The instruction names the path of the module's SKILL.md, the inputs, the work folder and the instructions, and
the invocation file, which tools/status.py finds the session by. The invocation records the definition it runs:
the module's location (default or user), the SKILL.md path as skill, the SHA-256 of the SKILL.md bytes read at
this moment as skill_sha256, and, when the location is a git clone, its commit at this moment as
modules_commit. The default location must be a git clone; a user location is one when it is the top of a git
worktree. Which inputs are given is not checked against the module. A refused argument makes nothing. Of two
calls at once for one module, each gets its own number.

Stops, making nothing, when the run's USER_MODULES exists but cannot be listed, when the module is in neither
location, or when it is in both, naming both paths. A USER_MODULES that does not exist holds no modules.

Stops, making nothing, when the line tools/session.py send enters for the run's instruction file would be over
the size a terminal takes as one message: the record folder's path is too long, and a shorter root (SETTINGS.md)
is what to change.
"""
import argparse, hashlib, json, os, re, subprocess, sys

import terminals
from ended import ENDED, INVOCATION, PROMPT
from session import fits, line_for

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')


def read_env(run_dir):
    path = os.path.join(run_dir, 'run.env')
    try:
        env = dict(l.strip().split('=', 1) for l in open(path) if '=' in l)
    except OSError as e:
        sys.exit(f'{path}: {e}')
    for k in ('RECORDS', 'MODULES'):
        if not env.get(k):
            sys.exit(f'{path}: {k} is missing')
    return env


def inputs_of(text):
    try:
        value = json.loads(text)
    except ValueError as e:
        sys.exit(f'inputs: not JSON ({e})')
    if not isinstance(value, dict):
        sys.exit('inputs: not a JSON object')
    for k, v in value.items():
        items = v if isinstance(v, list) else [v]
        if not items or not all(isinstance(i, str) and i for i in items):
            sys.exit(f'input {k}: not a string or a non-empty array of strings ({v!r})')
    return value


def claim(records, module):
    """Makes the work folder of the module's next run and returns the run's name. A number counts as used
    when the work folder or any of the coordinator's files has it. Exits, making nothing, when the line that
    names the run's instruction file does not fit a terminal's message."""
    used = re.compile(re.escape(module) + r'-([0-9]+)(?:' + '|'.join(map(re.escape, (INVOCATION, PROMPT, ENDED))) + r')?')
    try:
        numbers = [int(m.group(1)) for m in map(used.fullmatch, os.listdir(records)) if m]
    except OSError as e:
        sys.exit(f'{records}: {e}')
    n = max(numbers, default=0) + 1
    while True:
        name = f'{module}-{n}'
        line = line_for(os.path.join(records, name + PROMPT))
        if not fits(line):
            size = len(line.encode())
            over = size - terminals.MAX_SUBMIT_BYTES
            sys.exit(f'{records}: the path of this record folder is {over} byte{"s" if over > 1 else ""} too long: the line '
                     f'tools/session.py send enters for {name}{PROMPT} would be {size} bytes, over the '
                     f'{terminals.MAX_SUBMIT_BYTES} a terminal takes as one message. Set a shorter root (SETTINGS.md)')
        try:
            os.mkdir(os.path.join(records, name))
            return name
        except FileExistsError:
            n += 1  # a call at the same moment took it
        except OSError as e:
            sys.exit(f'{records}: {e}')


ap = argparse.ArgumentParser(description='Make the work folder of one module run and write its invocation and instruction files.')
ap.add_argument('run_dir')
ap.add_argument('module')
ap.add_argument('inputs')
ap.add_argument('--instructions')
args = ap.parse_args()

if not NAME.fullmatch(args.module):
    sys.exit(f'module must be one name using only [A-Za-z0-9._-] ({args.module!r})')
inputs = inputs_of(args.inputs)

run_dir = os.path.abspath(args.run_dir)
env = read_env(run_dir)
records = env['RECORDS']
locations = [('default', env['MODULES'])]
if env.get('USER_MODULES'):
    locations.append(('user', env['USER_MODULES']))
    if os.path.lexists(env['USER_MODULES']):
        try:
            os.listdir(env['USER_MODULES'])
        except OSError as e:
            sys.exit(f'USER_MODULES: {env["USER_MODULES"]} cannot be read ({e.strerror}); nothing was made')
found = [(location, root, os.path.join(root, args.module, 'SKILL.md')) for location, root in locations
         if os.path.isdir(root) and os.path.isfile(os.path.join(root, args.module, 'SKILL.md'))]
if not found:
    sys.exit(f'{args.module}: no such module in {" or ".join(root for _, root in locations)} '
             '(tools/modules.py lists them)')
if len(found) > 1:
    sys.exit(f'{args.module}: a module of this name is in both locations, {found[0][2]} and {found[1][2]}; '
             'nothing was made')
location, root, skill = found[0]
try:
    with open(skill, 'rb') as f:
        skill_sha256 = hashlib.sha256(f.read()).hexdigest()
except OSError as e:
    sys.exit(f'{skill}: {e}')
commit = subprocess.run(['git', '-C', root, 'rev-parse', '--show-toplevel', 'HEAD'], capture_output=True, text=True)
top, _, head = commit.stdout.strip().partition('\n')
if location == 'default' and commit.returncode:
    sys.exit(f'{root}: not a git clone ({commit.stderr.strip()})')
# A user location is a clone only at a worktree's top, not as a folder inside some other repository.
is_clone = not commit.returncode and (location == 'default' or os.path.realpath(top) == os.path.realpath(root))

name = claim(records, args.module)
out = os.path.join(records, name)
invocation = {
    'module': args.module,
    'location': location,
    'skill': skill,
    'skill_sha256': skill_sha256,
}
if is_clone:
    invocation['modules_commit'] = head
invocation.update({'inputs': inputs, 'out': out})
if args.instructions is not None:
    invocation['instructions'] = args.instructions

invocation_file, prompt_file = out + INVOCATION, out + PROMPT

lines = [f'Run the module defined at {skill}. Read that file first and follow it; it is the whole definition of the work.',
         "For each behavior the work needs, first find what sets it; the definition's Default applies only where nothing does.",
         '', f'Invocation: {invocation_file}', '', 'Input:']
lines += [f'- {k}: {"; ".join(v) if isinstance(v, list) else v}' for k, v in inputs.items()] or ['- none']
lines += ['', f'Work folder: {out}. Write the records the definition\'s Output names there.']
if args.instructions:
    lines += ['', 'Instructions:', args.instructions]
lines += ['', 'When this module ends, stop and wait for the next instruction.']

made = []
try:
    for path, text in ((invocation_file, json.dumps(invocation, ensure_ascii=False, indent=2)), (prompt_file, '\n'.join(lines))):
        with open(path, 'x') as f:
            made.append(path)
            f.write(text + '\n')
except OSError as e:
    for path in made:
        os.remove(path)
    os.rmdir(out)
    sys.exit(str(e))

print(f'NAME={name}')
print(f'WORK_FOLDER={out}')
print(f'INVOCATION={invocation_file}')
print(f'PROMPT={prompt_file}')
