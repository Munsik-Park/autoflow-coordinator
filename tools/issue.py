#!/usr/bin/env python3
"""issue.py <run-dir> --key <key> --title <title> --body <file> [--repo <owner/name>]
— registers one finding as an issue of the repository, once.

  <run-dir>   <runs>/<name>/ holding run.env (CHECKOUT, RECORDS); the workspace is the parent of CHECKOUT, and the
              repository is its repo.json > github, or --repo when the workspace's coordination.md names another.
  --key       what tells this finding apart from others, the same in every run that meets it (lowercased, runs of
              whitespace made one space).
  --title, --body
              the issue's title and the file holding its body.

The issue's body is the file's text, then "Run record: <run name>" and the line `<!-- autoflow-finding: <key> -->`.
Before creating it, the tool looks for that key in <RECORDS>/issues.jsonl and in the bodies of the repository's open
issues; when either holds it, nothing is created. The key, title or body is refused when it holds a local path (the
home folder, the runs root, the checkout, the record folder or the temporary folder). Each result, created or found, is
appended to <RECORDS>/issues.jsonl as {"key", "repo", "number", "url", "status", "time"}.

Prints one line of JSON: {"status": "created" | "exists", "key", "repo", "number", "url"}.
Exits: 0 created or found; 2 bad input or a refused text, nothing posted; 3 the repository could not be read or the
issue could not be created, with the reason on stderr.

The repository is reached with the gh CLI and the token of the session.
"""
import argparse, datetime, json, os, re, subprocess, sys, tempfile

REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
LIST_LIMIT = 1000


class Stop(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


def read_env(run_dir):
    env = {}
    try:
        for line in open(os.path.join(run_dir, 'run.env')):
            k, sep, v = line.rstrip('\n').partition('=')
            if sep:
                env[k] = v
    except OSError as e:
        raise Stop(f'{run_dir}/run.env: {e}', 2)
    for k in ('CHECKOUT', 'RECORDS'):
        if not env.get(k):
            raise Stop(f'{run_dir}/run.env: {k} is missing', 2)
    return env


def workspace_repo(env):
    path = os.path.join(os.path.dirname(env['CHECKOUT']), 'repo.json')
    try:
        repo = json.load(open(path))
    except (OSError, ValueError) as e:
        raise Stop(f'{path}: {e}', 2)
    name = repo.get('github') if isinstance(repo, dict) else None
    if not isinstance(name, str) or not REPO.fullmatch(name):
        raise Stop(f'{path}: github must be <owner>/<name> ({name!r})', 2)
    return name


def local_paths(run_dir, env):
    root = os.path.dirname(os.path.abspath(run_dir))
    home = os.path.expanduser('~')
    return sorted({p for x in (home, root, env['CHECKOUT'], env['RECORDS'], tempfile.gettempdir(), '/tmp')
                   if x and x != '/' for p in (x, os.path.realpath(x))}, key=len, reverse=True)


def refuse_paths(what, text, paths):
    for p in paths:
        if p in text:
            raise Stop(f'{what} holds a local path ({p}); nothing is posted', 2)


def gh(args, stdin=None):
    try:
        p = subprocess.run(['gh', *args], input=stdin, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Stop(f'gh {args[0]}: {e}', 3)
    if p.returncode != 0:
        raise Stop(f'gh {" ".join(args[:2])}: {p.stderr.strip() or p.returncode}', 3)
    return p.stdout


def recorded(log, key, repo):
    try:
        lines = open(log).read().splitlines()
    except FileNotFoundError:
        return None
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get('key') == key and e.get('repo') == repo and e.get('url'):
            return e
    return None


def open_issue_with(repo, marker):
    out = gh(['issue', 'list', '--repo', repo, '--state', 'open', '--limit', str(LIST_LIMIT),
              '--json', 'number,url,body'])
    try:
        issues = json.loads(out)
    except ValueError as e:
        raise Stop(f'gh issue list: not JSON ({e})', 3)
    for i in issues:
        if marker in (i.get('body') or ''):
            return i
    return None


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('run_dir')
    ap.add_argument('--key', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--body', required=True)
    ap.add_argument('--repo')
    a = ap.parse_args(argv)

    key = ' '.join(a.key.lower().split())
    if not key or '-->' in key:
        raise Stop('--key is empty or holds "-->"', 2)
    title = ' '.join(a.title.split())
    if not title:
        raise Stop('--title is empty', 2)
    try:
        body = open(a.body).read().strip()
    except OSError as e:
        raise Stop(f'--body: {e}', 2)
    if not body:
        raise Stop('--body is empty', 2)

    env = read_env(a.run_dir)
    repo = a.repo or workspace_repo(env)
    if not REPO.fullmatch(repo):
        raise Stop(f'--repo must be <owner>/<name> ({repo!r})', 2)
    paths = local_paths(a.run_dir, env)
    refuse_paths('--key', a.key, paths)
    refuse_paths('--title', title, paths)
    refuse_paths('--body', body, paths)

    run_name = os.path.basename(os.path.abspath(a.run_dir))
    marker = f'<!-- autoflow-finding: {key} -->'
    log = os.path.join(env['RECORDS'], 'issues.jsonl')

    found = recorded(log, key, repo)
    if found:
        result = {'status': 'exists', 'key': key, 'repo': repo, 'number': found.get('number'), 'url': found['url']}
    else:
        hit = open_issue_with(repo, marker)
        if hit:
            result = {'status': 'exists', 'key': key, 'repo': repo, 'number': hit.get('number'), 'url': hit.get('url')}
        else:
            text = f'{body}\n\nRun record: {run_name}\n\n{marker}\n'
            url = gh(['issue', 'create', '--repo', repo, '--title', title, '--body-file', '-'], stdin=text).strip()
            m = re.search(r'/issues/(\d+)\s*$', url)
            if not m:
                raise Stop(f'gh issue create: unexpected output ({url!r})', 3)
            result = {'status': 'created', 'key': key, 'repo': repo, 'number': int(m.group(1)), 'url': url}
    entry = dict(result, time=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    with open(log, 'a') as f:
        f.write(json.dumps(entry) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except Stop as e:
        print(f'issue.py: {e}', file=sys.stderr)
        sys.exit(e.code)
