#!/usr/bin/env python3
"""workspace.py <name> [key] — a workspace's repo information and which of its files it has.

The workspace is <base>/<name>, with base from config.py. Its repo.json is required: a workspace
without it, or without one of its keys, is an error. The other files may be absent.

Without a key, prints the workspace path, the repo information, then each other file with its path
or absent. With a key, prints its value alone: path, or a key of repo.json. Paths are printed with
~ expanded, '..' removed and symlinks resolved.
"""
import json, os, subprocess, sys

REPO_FILE = 'repo.json'
# github: owner/name. clone: the local clone the run worktrees are made from. base_branch: what they start from.
REPO_KEYS = ('github', 'clone', 'base_branch')
OTHER_FILES = ('CLAUDE.md', 'coordination.md', 'claude-settings.json')


if not 2 <= len(sys.argv) <= 3:
    sys.exit('usage: workspace.py <name> [key]')
name = sys.argv[1]
if name in ('', '.', '..') or os.path.basename(name) != name:
    sys.exit(f'workspace name must be one directory name ({name!r})')

config = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.py')
base = subprocess.run([sys.executable, config, 'base'], stdout=subprocess.PIPE, text=True)
if base.returncode:
    sys.exit(base.returncode)
path = os.path.join(base.stdout.strip(), name)
repo_file = os.path.join(path, REPO_FILE)
if not os.path.isfile(repo_file):
    sys.exit(f'{path}: no {REPO_FILE}')

try:
    d = json.load(open(repo_file))
except ValueError as e:
    sys.exit(f'{repo_file}: not JSON ({e})')
if not isinstance(d, dict):
    sys.exit(f'{repo_file}: not a JSON object')
for k in d:
    if k not in REPO_KEYS:
        print(f'{repo_file}: unknown key {k}, ignored', file=sys.stderr)
for k in REPO_KEYS:
    if not isinstance(d.get(k), str) or not d[k]:
        sys.exit(f'{repo_file}: {k} must be a non-empty string ({d.get(k)!r})')
if not os.path.isabs(os.path.expanduser(d['clone'])):
    sys.exit(f"{repo_file}: clone must be an absolute path or start with ~ ({d['clone']!r})")
clone = os.path.realpath(os.path.expanduser(d['clone']))
if not os.path.isdir(clone):
    sys.exit(f'{repo_file}: clone is not a directory ({clone})')
values = {'path': path, **{k: d[k] for k in REPO_KEYS}, 'clone': clone}

if len(sys.argv) > 2:
    k = sys.argv[2]
    if k not in values:
        sys.exit(f'unknown key {k}: one of {", ".join(values)}')
    print(values[k])
else:
    for k, v in values.items():
        print(f'{k}\t{v}')
    for f in OTHER_FILES:
        p = os.path.join(path, f)
        print(f'{f}\t{p if os.path.isfile(p) else "absent"}')
