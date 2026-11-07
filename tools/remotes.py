"""origin's URLs, as git resolves them, checked against the workspace's repository.

A URL passes when, after the clone's url.<base>.insteadOf and pushInsteadOf rewrites, it is
https://github.com/<owner>/<name> with an optional .git and no user or password, and <owner>/<name> is
repo.json > github (GitHub compares names without case). origin_problems returns the problems found, one
line each, naming the URL and the accepted form.
"""
import re, subprocess

FORM = 'https://github.com/<owner>/<name>[.git], without user or password'
URL_RE = re.compile(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?', re.ASCII)


def _problem(where, url, owner, name):
    m = URL_RE.fullmatch(url)
    if m and m[1].lower() == owner.lower() and m[2].lower() == name.lower():
        return None
    return f'{where} {url}: accepted is {FORM}, for {owner}/{name}'


def origin_problems(clone, github):
    """origin's fetch and push URLs."""
    owner, name = github.split('/')
    found = []
    for flag in ((), ('--push',)):
        p = subprocess.run(['git', '-C', clone, 'remote', 'get-url', *flag, '--all', 'origin'],
                           capture_output=True, text=True)
        if p.returncode:
            return [f'{clone}: no remote origin']
        found += [_problem('origin push URL' if flag else 'origin URL', u, owner, name) for u in p.stdout.split()]
    return [p for p in found if p]
