#!/usr/bin/env python3
"""config.py [key] — the coordination settings, found in order (SETTINGS.md).

Each key is taken from the nearest place that sets it: the local file coordination.local.json at the
root of this tool clone (ignored by git), then the global file ~/.autoflow/coordination.json, then the
built-in default. A file that is absent sets nothing; a file that is not a JSON object is an error.

Without a key, prints every setting with where it came from, then the places under the root.
With a key, prints its value alone: a setting (root) or a place under the root (workspaces, runs,
records). Paths are printed with ~ expanded.
"""
import json, os, sys

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = os.path.join(TOOL, 'coordination.local.json')
GLOBAL = os.path.expanduser('~/.autoflow/coordination.json')
DEFAULT = {'root': '~/.autoflow/coordination'}
# Places under the root: workspace per repo, run data per run, AutoFlow record folder per run.
UNDER_ROOT = ('workspaces', 'runs', 'records')


def read(path):
    if not os.path.exists(path):
        return {}
    try:
        d = json.load(open(path))
    except ValueError as e:
        sys.exit(f'{path}: not JSON ({e})')
    if not isinstance(d, dict):
        sys.exit(f'{path}: not a JSON object')
    return d


settings = {k: (v, 'default') for k, v in DEFAULT.items()}
for path in (GLOBAL, LOCAL):  # nearer last, so it wins key by key
    for k, v in read(path).items():
        if k not in DEFAULT:
            print(f'{path}: unknown key {k}, ignored', file=sys.stderr)
            continue
        settings[k] = (v, path)

root, src = settings['root']
if not isinstance(root, str) or not os.path.isabs(os.path.expanduser(root)):
    sys.exit(f'{src}: root must be an absolute path or start with ~ ({root!r})')
root = os.path.expanduser(root)
places = {p: os.path.join(root, p) for p in UNDER_ROOT}

if len(sys.argv) > 1:
    k = sys.argv[1]
    if k == 'root':
        print(root)
    elif k in places:
        print(places[k])
    else:
        sys.exit(f'unknown key {k}: one of root, {", ".join(UNDER_ROOT)}')
else:
    print(f'root\t{root}\t({src})')
    for p, path in places.items():
        print(f'{p}\t{path}')
