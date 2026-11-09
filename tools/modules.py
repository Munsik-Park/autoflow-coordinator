#!/usr/bin/env python3
"""modules.py — the modules a coordination session can choose from, as JSON. Changes nothing.

Reads every folder of the autoflow-module clone that the setting `modules` names (tools/config.py) and
holding a SKILL.md, and takes from the SKILL.md front matter only `name`, `metadata.goal` and `description`.
Folders without a SKILL.md, and folders whose name starts with '.', are not modules and are passed over.

Prints {"modules": <clone path>, "list": [{"name", "goal", "description", "path"}]}, sorted by folder,
path being the SKILL.md's. A SKILL.md whose front matter cannot be read is listed as {"path", "error"}.
Exits 1 when the clone does not exist.

The front matter is read as the plain YAML a module definition uses: `key: value` lines, folded (>, >-)
and literal (|, |-) block scalars, and one level of nested keys such as metadata.goal.
"""
import json, os, subprocess, sys

TOOLS = os.path.dirname(os.path.abspath(__file__))


def scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        return v[1:-1]
    return v


def block(lines, i, indent, style):
    """Lines of a block scalar indented deeper than indent, from i. Returns (text, next i)."""
    body = []
    while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
        body.append(lines[i].strip())
        i += 1
    while body and not body[-1]:
        body.pop()
    if style[0] == '|':
        text = '\n'.join(body)
    else:
        paras, cur = [], []
        for line in body:
            if line:
                cur.append(line)
            else:
                paras.append(' '.join(cur))
                cur = []
        paras.append(' '.join(cur))
        text = '\n'.join(paras)
    return text, i


def mapping(lines, i, indent):
    """Keys at exactly this indent, from i. Returns (dict, next i)."""
    out = {}
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith('#'):
            i += 1
            continue
        ind = len(line) - len(line.lstrip())
        if ind < indent:
            break
        if ind > indent or ':' not in line:
            raise ValueError(f'line {i + 1}: {line.strip()!r} is not a key')
        key, _, rest = line.strip().partition(':')
        rest = rest.strip()
        i += 1
        if rest in ('>', '>-', '|', '|-'):
            out[key], i = block(lines, i, ind, rest)
        elif rest:
            out[key] = scalar(rest)
        else:
            nxt = next((l for l in lines[i:] if l.strip()), '')
            child = len(nxt) - len(nxt.lstrip())
            if nxt and child > ind:
                out[key], i = mapping(lines, i, child)
            else:
                out[key] = ''
    return out, i


def front_matter(path):
    lines = open(path, encoding='utf-8').read().split('\n')
    if not lines or lines[0].strip() != '---':
        raise ValueError('no front matter')
    try:
        end = next(n for n in range(1, len(lines)) if lines[n].strip() == '---')
    except StopIteration:
        raise ValueError('front matter not closed')
    return mapping(lines[1:end], 0, 0)[0]


def entry(path):
    try:
        fm = front_matter(path)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return {'path': path, 'error': str(e)}
    meta = fm.get('metadata')
    return {'name': fm.get('name'), 'goal': meta.get('goal') if isinstance(meta, dict) else None,
            'description': fm.get('description'), 'path': path}


def main():
    if len(sys.argv) > 1:
        sys.exit(__doc__.strip().split('\n')[0])
    root = subprocess.run([sys.executable, os.path.join(TOOLS, 'config.py'), 'modules'],
                          capture_output=True, text=True)
    if root.returncode:
        sys.exit(root.stderr.strip() or root.stdout.strip())
    root = root.stdout.strip()
    if not os.path.isdir(root):
        sys.exit(f'modules: {root} does not exist (set `modules` in the settings, SETTINGS.md)')
    found = []
    for d in sorted(os.listdir(root)):
        skill = os.path.join(root, d, 'SKILL.md')
        if not d.startswith('.') and os.path.isfile(skill):
            found.append(entry(skill))
    print(json.dumps({'modules': root, 'list': found}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
