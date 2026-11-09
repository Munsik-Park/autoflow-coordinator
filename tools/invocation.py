#!/usr/bin/env python3
"""invocation.py <run-dir> <module> <out> <inputs-json> [--instructions TEXT] — write the invocation file and
the instruction file of one module run.

  <run-dir>       <runs>/<name>/ holding run.env (RECORDS, MODULES)
  <module>        a module of the run's autoflow-module clone: a folder there holding a SKILL.md
  <out>           the name of the run's output directory under the record directory
  <inputs-json>   a JSON object of the inputs given to the module, each a string or an array of strings,
                  named as the module's input section names them
  --instructions  the coordination session's instructions for this run: criteria other than the
                  module's defaults, how to start what the module runs, and so on

Writes <records>/<out>.invocation.json and <run-dir>/<out>-prompt.txt and prints their paths. The
instruction names the path of the module's SKILL.md, the inputs, the output directory and the
instructions, and the invocation file, which tools/status.py finds the session by. The invocation
also records the clone's commit at this moment. Which inputs are given is not checked against the
module. A refused argument writes nothing, and a file that exists is not overwritten.
"""
import argparse, json, os, re, subprocess, sys

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


ap = argparse.ArgumentParser(description='Write the invocation and instruction files of one module run.')
ap.add_argument('run_dir')
ap.add_argument('module')
ap.add_argument('out')
ap.add_argument('inputs')
ap.add_argument('--instructions')
args = ap.parse_args()

for label, value in (('module', args.module), ('out', args.out)):
    if not NAME.fullmatch(value):
        sys.exit(f'{label} must be one name using only [A-Za-z0-9._-] ({value!r})')
inputs = inputs_of(args.inputs)

run_dir = os.path.abspath(args.run_dir)
env = read_env(run_dir)
records, modules = env['RECORDS'], env['MODULES']
skill = os.path.join(modules, args.module, 'SKILL.md')
if not os.path.isfile(skill):
    sys.exit(f'{skill}: no such module in {modules} (tools/modules.py lists them)')
commit = subprocess.run(['git', '-C', modules, 'rev-parse', 'HEAD'], capture_output=True, text=True)
if commit.returncode:
    sys.exit(f'{modules}: not a git clone ({commit.stderr.strip()})')

out = os.path.join(records, args.out)
invocation = {
    'module': args.module,
    'skill': skill,
    'modules_commit': commit.stdout.strip(),
    'inputs': inputs,
    'out': out,
}
if args.instructions is not None:
    invocation['instructions'] = args.instructions

invocation_file = os.path.join(records, f'{args.out}.invocation.json')
prompt_file = os.path.join(run_dir, f'{args.out}-prompt.txt')
for path in (invocation_file, prompt_file):
    if os.path.exists(path):
        sys.exit(f'{path} exists: a run gets a new output directory name')

lines = [f'Run the module defined at {skill}. Read that file first and follow it; it is the whole definition of the work.',
         '', f'Invocation: {invocation_file}', '', 'Input:']
lines += [f'- {k}: {"; ".join(v) if isinstance(v, list) else v}' for k, v in inputs.items()] or ['- none']
lines += ['', f'Output folder: {out}. Write everything the definition\'s Output names there, and nothing into the checkout.']
if args.instructions:
    lines += ['', 'Instructions:', args.instructions]
lines += ['', 'When this module ends, stop and wait for the next instruction.']

try:
    with open(invocation_file, 'w') as f:
        json.dump(invocation, f, ensure_ascii=False, indent=2)
        f.write('\n')
    with open(prompt_file, 'w') as f:
        f.write('\n'.join(lines) + '\n')
except OSError as e:
    sys.exit(str(e))

print(f'INVOCATION={invocation_file}')
print(f'PROMPT={prompt_file}')
