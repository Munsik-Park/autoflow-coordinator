#!/usr/bin/env python3
"""modules.py — the modules a coordination session can choose from, as JSON. Changes nothing.

Reads the modules of two locations, both taken from tools/config.py: the default location, the
autoflow-module clone the setting `modules` names, then the user location `user-modules` (<home>/modules).
A module is a folder there holding a SKILL.md, from whose front matter only `name`, `metadata.goal` and
`description` are taken. Folders without a SKILL.md, and folders whose name starts with '.', are not
modules and are passed over.

Prints {"modules": <clone path>, "user_modules": <user location path>, "list": [{"name", "goal",
"description", "path", "location"}]}, path being the SKILL.md's and location "default" or "user". A SKILL.md
whose front matter cannot be parsed, or one of the default location that cannot be read, is listed as
{"path", "location", "error"}.

A module's name is its folder's name, compared exactly as the locations' listings spell it, also on a
case-insensitive volume. A user module whose folder name is a default module's replaces it: its entry gains
"replaces", the default module's SKILL.md path, and the default module is not listed. This holds for error
entries too. The list's order: the default location's entries in folder order, the entry of a replaced
default module being the user entry of that folder name, then the other user entries in folder order.

What is at <home>/modules is either nothing (no path at all, so no user modules) or a folder whose entries
and their SKILL.md can be read. Anything else there, a file or a symlink with no target included, and any
error met reading the user location other than a SKILL.md not being there (listing it, or checking or
reading an entry's SKILL.md) stops this tool.

Exits 1, with one line naming the path, when the clone does not exist, on the user location's errors above,
or when `modules` and <home>/modules resolve to the same folder. Exits 1, naming both paths, when the clone
and the base are the same folder or either lies inside the other (see overlaps).

The front matter is read as the plain YAML a module definition uses: `key: value` lines, folded (>, >-)
and literal (|, |-) block scalars, and one level of nested keys such as metadata.goal.
"""
import json, os, stat, subprocess, sys

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


def entry(path, location, strict):
    try:
        fm = front_matter(path)
    except OSError as e:
        if strict:
            raise
        return {'path': path, 'location': location, 'error': str(e)}
    except (UnicodeDecodeError, ValueError) as e:
        return {'path': path, 'location': location, 'error': str(e)}
    meta = fm.get('metadata')
    return {'name': fm.get('name'), 'goal': meta.get('goal') if isinstance(meta, dict) else None,
            'description': fm.get('description'), 'path': path, 'location': location}


def setting(key):
    p = subprocess.run([sys.executable, os.path.join(TOOLS, 'config.py'), key], capture_output=True, text=True)
    if p.returncode:
        sys.exit(p.stderr.strip() or p.stdout.strip())
    return p.stdout.strip()


def scan(root, location, strict=False):
    """The modules of one location. strict: an OSError met reading it, other than a SKILL.md not being
    there, is raised instead of passing the entry over or listing it as an error."""
    found = []
    for d in sorted(os.listdir(root)):
        if d.startswith('.'):
            continue
        skill = os.path.join(root, d, 'SKILL.md')
        if strict:
            try:
                if not stat.S_ISREG(os.stat(skill).st_mode):
                    continue
            except (FileNotFoundError, NotADirectoryError):
                continue
        elif not os.path.isfile(skill):
            continue
        found.append(entry(skill, location, strict))
    return found


def overlaps(a, b):
    """Whether a and b are the same folder or either lies inside the other, compared by file identity: each
    ancestor of one is compared with the other by os.path.samefile, so a spelling differing only in case on
    a case-insensitive volume, or through a symlink, is caught. A path that does not exist overlaps nothing."""
    if not (os.path.exists(a) and os.path.exists(b)):
        return False
    for inner, outer in ((a, b), (b, a)):
        p = os.path.realpath(inner)
        while True:
            if os.path.samefile(p, outer):
                return True
            if os.path.dirname(p) == p:
                break
            p = os.path.dirname(p)
    return False


def base_overlap(modules, base):
    """The stop message when the modules clone and the base overlap, else None."""
    if overlaps(modules, base):
        return (f'modules {os.path.realpath(modules)} and base {os.path.realpath(base)} are the same folder or one '
                'lies inside the other, and each directory under the base is a workspace: set `modules` or `base` '
                'so that the modules clone lies outside the base (SETTINGS.md)')


def folder(e):
    return os.path.basename(os.path.dirname(e['path']))


def replace(defaults, users):
    """The list: each default entry, or in its place the user entry of the same folder name with "replaces"
    set to the default's SKILL.md path; then the other user entries."""
    by_folder = {folder(e): e for e in users}
    out = []
    for e in defaults:
        u = by_folder.pop(folder(e), None)
        out.append(dict(u, replaces=e['path']) if u else e)
    return out + [e for e in users if folder(e) in by_folder]


def main():
    if len(sys.argv) > 1:
        sys.exit(__doc__.strip().split('\n')[0])
    root, user = setting('modules'), setting('user-modules')
    if not os.path.isdir(root):
        sys.exit(f'modules: {root} does not exist (set `modules` in the settings, SETTINGS.md)')
    if os.path.realpath(root) == os.path.realpath(user):
        sys.exit(f'modules and user-modules (<home>/modules) are the same folder, {os.path.realpath(root)}: '
                 'set `modules` or `home` so that they differ (SETTINGS.md)')
    stop = base_overlap(root, setting('base'))
    if stop:
        sys.exit(stop)
    found = scan(root, 'default')
    try:
        try:
            os.lstat(user)  # only no path at all is an absent user location
        except FileNotFoundError:
            pass
        else:
            found = replace(found, scan(user, 'user', strict=True))
    except OSError as e:
        sys.exit(f'user-modules: {e.filename or user} cannot be read ({e.strerror}): <home>/modules must be '
                 'absent or a folder that can be read (SETTINGS.md)')
    print(json.dumps({'modules': root, 'user_modules': user, 'list': found}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
