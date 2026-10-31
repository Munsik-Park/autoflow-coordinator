#!/usr/bin/env python3
"""invocation.py <run-dir> <module> <out> <params-json> <inputs-json> [--instructions TEXT] — write the
invocation file and the instruction file of one module run.

  <run-dir>       <runs>/<name>/ holding run.env (RECORDS, AUTOFLOW_VER)
  <module>        a module the contracts of the run's AutoFlow version name
  <out>           the name of the run's output directory under the record directory
  <params-json>   a JSON object of the params
  <inputs-json>   a JSON object of each input's path or array of paths; a relative path is taken from
                  the record directory
  --instructions  the invocation's instructions

Writes <records>/<out>.invocation.json and <run-dir>/<out>-prompt.txt and prints their paths. The
invocation names the record directory only for a module whose contract reads it. Which params and
inputs are given, and whether the files exist, are not checked. A refused argument writes nothing, and
a file that exists is not overwritten.
"""
import argparse, json, os, re, sys

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')


def read_env(run_dir):
    path = os.path.join(run_dir, 'run.env')
    try:
        env = dict(l.strip().split('=', 1) for l in open(path) if '=' in l)
    except OSError as e:
        sys.exit(f'{path}: {e}')
    for k in ('RECORDS', 'AUTOFLOW_VER'):
        if not env.get(k):
            sys.exit(f'{path}: {k} is missing')
    return env


def read_contract(version, module):
    path = os.path.expanduser(f'~/.claude/plugins/cache/autoflow/autoflow/{version}/docs/contracts/{module}.json')
    try:
        contract = json.load(open(path))
        return contract['contract'], contract['reads_records']
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.exit(f'{path}: no contract for module {module} ({e!r})')


def json_object(label, text):
    try:
        value = json.loads(text)
    except ValueError as e:
        sys.exit(f'{label}: not JSON ({e})')
    if not isinstance(value, dict):
        sys.exit(f'{label}: not a JSON object')
    return value


def resolve(records, name, value):
    paths = value if isinstance(value, list) else [value]
    if not paths or not all(isinstance(p, str) and p for p in paths):
        sys.exit(f'input {name}: not a path or a non-empty array of paths ({value!r})')
    resolved = [os.path.join(records, p) for p in paths]
    return resolved if isinstance(value, list) else resolved[0]


ap = argparse.ArgumentParser(description='Write the invocation and instruction files of one module run.')
ap.add_argument('run_dir')
ap.add_argument('module')
ap.add_argument('out')
ap.add_argument('params')
ap.add_argument('inputs')
ap.add_argument('--instructions')
args = ap.parse_args()

for label, value in (('module', args.module), ('out', args.out)):
    if not NAME.fullmatch(value):
        sys.exit(f'{label} must be one name using only [A-Za-z0-9._-] ({value!r})')
params = json_object('params', args.params)
inputs = json_object('inputs', args.inputs)

run_dir = os.path.abspath(args.run_dir)
env = read_env(run_dir)
records = env['RECORDS']
version, reads_records = read_contract(env['AUTOFLOW_VER'], args.module)

invocation = {
    'contract': version,
    'module': args.module,
    'params': params,
    'inputs': {k: resolve(records, k, v) for k, v in inputs.items()},
}
if reads_records:
    invocation['records'] = records
invocation['out'] = os.path.join(records, args.out)
if args.instructions is not None:
    invocation['instructions'] = args.instructions

invocation_file = os.path.join(records, f'{args.out}.invocation.json')
prompt_file = os.path.join(run_dir, f'{args.out}-prompt.txt')
for path in (invocation_file, prompt_file):
    if os.path.exists(path):
        sys.exit(f'{path} exists: a run gets a new output directory name')

try:
    with open(invocation_file, 'w') as f:
        json.dump(invocation, f, ensure_ascii=False, indent=2)
        f.write('\n')
    with open(prompt_file, 'w') as f:
        f.write(f'/autoflow:{args.module} {invocation_file}\n\n'
                '목표: 이 모듈의 계약이 정한 목표.\n'
                '제약: 이 모듈이 끝나면 멈추고 다음 지시를 기다리세요.\n')
except OSError as e:
    sys.exit(str(e))

print(f'INVOCATION={invocation_file}')
print(f'PROMPT={prompt_file}')
