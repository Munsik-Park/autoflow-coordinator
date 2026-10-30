#!/usr/bin/env python3
"""config.py [key] — the coordination settings, found in order.

Each key is taken from the nearest place that sets it: the local file coordination.local.json at the
root of this tool clone (ignored by git), then the global file ~/.autoflow/coordination.json, then the
built-in default. A file that is absent sets nothing; a file that is not a JSON object is an error.

Without a key, prints every setting with where it came from, then the places under the root.
With a key, prints its value alone: a setting (root, base) or a place under the root (workspaces,
runs, records). Paths are printed with ~ expanded, '..' removed and symlinks resolved.
"""
import json, os, sys

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = os.path.join(TOOL, 'coordination.local.json')
GLOBAL = os.path.expanduser('~/.autoflow/coordination.json')
# root: the progress records. base: the work space, holding a workspace per repo.
DEFAULT = {'root': '~/.autoflow/coordination', 'base': '~/work/coordinator'}
# Places under the root: the workspace list, run data per run, AutoFlow record folder per run.
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

values = {}
for k, (v, src) in settings.items():
    if not isinstance(v, str) or not os.path.isabs(os.path.expanduser(v)):
        sys.exit(f'{src}: {k} must be an absolute path or start with ~ ({v!r})')
    values[k] = os.path.realpath(os.path.expanduser(v))
places = {p: os.path.join(values['root'], p) for p in UNDER_ROOT}

if len(sys.argv) > 1:
    k = sys.argv[1]
    if k in values:
        print(values[k])
    elif k in places:
        print(places[k])
    else:
        sys.exit(f'unknown key {k}: one of {", ".join(list(values) + list(UNDER_ROOT))}')
else:
    for k, (_, src) in settings.items():
        print(f'{k}\t{values[k]}\t({src})')
    for p, path in places.items():
        print(f'{p}\t{path}')
