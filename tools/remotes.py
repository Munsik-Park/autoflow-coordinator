"""origin's URLs, as git resolves them, checked against the workspace's repository.

A URL passes when, after the clone's url.<base>.insteadOf and pushInsteadOf rewrites, it is
https://github.com/<owner>/<name> with an optional .git and no user or password, and <owner>/<name> is
the github argument (GitHub compares names without case). origin_problems returns the problems found, one
line each, naming the URL as written and, when a url.<base>.insteadOf or pushInsteadOf rule changed it,
the URL it resolves to, and the accepted form. When the URLs as written and the resolved ones do not pair
one to one (a pushInsteadOf matching only some of several URLs), it names the resolved URL only.
"""
import re, subprocess

FORM = 'https://github.com/<owner>/<name>[.git], without user or password'
URL_RE = re.compile(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?', re.ASCII)


def _problem(where, written, url, owner, name):
    m = URL_RE.fullmatch(url)
    if m and m[1].lower() == owner.lower() and m[2].lower() == name.lower():
        return None
    shown = url if written in (None, url) else (
        f"{written} (resolves to {url} by a url.*.insteadOf or pushInsteadOf rule; "
        f"git config --show-origin --get-regexp '^url\\.' shows where)")
    return f'{where} {shown}: accepted is {FORM}, for {owner}/{name}'


def _git(clone, *args):
    return subprocess.run(['git', '-C', clone, *args], capture_output=True, text=True)


def origin_problems(clone, github):
    """origin's fetch and push URLs."""
    owner, name = github.split('/')
    urls = _git(clone, 'config', '--get-all', 'remote.origin.url').stdout.split()
    found = []
    for flag in ((), ('--push',)):
        p = _git(clone, 'remote', 'get-url', *flag, '--all', 'origin')
        if p.returncode:
            return [f'{clone}: no remote origin']
        resolved = p.stdout.split()
        written = (_git(clone, 'config', '--get-all', 'remote.origin.pushurl').stdout.split() or urls) if flag else urls
        if len(written) != len(resolved):
            written = [None] * len(resolved)
        found += [_problem('origin push URL' if flag else 'origin URL', w, u, owner, name)
                  for w, u in zip(written, resolved)]
    return [p for p in found if p]
