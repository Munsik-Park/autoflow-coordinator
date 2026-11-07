"""The GitHub URLs a clone's git uses, as git resolves them, checked against the workspace's repository.

A URL passes when, after the clone's url.<base>.insteadOf and pushInsteadOf rewrites, it is
https://github.com/<owner>/<name> with an optional .git and no user or password, and <owner> is the
owner in repo.json > github (GitHub compares names without case). origin must be that repository; a
submodule may be any repository of that owner, and a relative submodule URL, resolved against origin,
passes. Each function returns the problems found, one line each, naming the URL and the accepted form.

git_args are options put before -C, such as ('-c', 'include.path=<file>') to check a clone read-only
with settings it does not hold.
"""
import re, subprocess

FORM = 'https://github.com/<owner>/<name>[.git], without user or password'
URL_RE = re.compile(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?', re.ASCII)


def _git(clone, git_args, *args):
    p = subprocess.run(['git', *git_args, '-C', clone, *args], capture_output=True, text=True)
    return p.returncode, p.stdout


def _problem(where, url, resolved, owner, name=None):
    m = URL_RE.fullmatch(resolved)
    if m and m[1].lower() == owner.lower() and (name is None or m[2].lower() == name.lower()):
        return None
    want = f'{owner}/{name}' if name else f'a repository of {owner}'
    shown = url if url == resolved else f'{url} (resolves to {resolved})'
    return f'{where} {shown}: accepted is {FORM}, for {want}'


def origin_problems(clone, github, git_args=()):
    """origin's fetch and push URLs."""
    owner, name = github.split('/')
    found = []
    for flag in ((), ('--push',)):
        rc, out = _git(clone, git_args, 'remote', 'get-url', *flag, '--all', 'origin')
        if rc:
            return [f'{clone}: no remote origin']
        found += [_problem('origin push URL' if flag else 'origin URL', u, u, owner, name) for u in out.split()]
    return [p for p in found if p]


def submodule_problems(clone, github, base_branch, git_args=()):
    """The submodule URLs in .gitmodules at origin/<base_branch> and in the clone's config."""
    owner = github.split('/')[0]
    entries = []
    blob = f'origin/{base_branch}:.gitmodules'
    if _git(clone, git_args, 'cat-file', '-e', blob)[0] == 0:
        entries += [('.gitmodules', line) for line in
                    _git(clone, git_args, 'config', '--blob', blob, '--get-regexp', r'^submodule\..*\.url$')[1].splitlines()]
    entries += [('config', line) for line in
                _git(clone, git_args, 'config', '--local', '--get-regexp', r'^submodule\..*\.url$')[1].splitlines()]
    found = []
    for source, line in entries:
        key, _, url = line.partition(' ')
        if url.startswith(('./', '../')):
            continue
        resolved = _git(clone, git_args, 'ls-remote', '--get-url', url)[1].strip()
        found.append(_problem(f'{source} {key}', url, resolved, owner))
    return [p for p in found if p]
