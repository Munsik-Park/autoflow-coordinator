#!/usr/bin/env python3
"""merge.py <run-dir> [--ci-timeout S] [--ci-start S] [--poll S] — carry out the operator's merge decision
recorded in <run-dir>/approval.json, in the order of the workspace's merge-plan.json, and stop on anything
that does not match them.

  <run-dir>        <runs>/<name>/ holding run.env (CHECKOUT, BRANCH, ISSUE) and approval.json; the workspace
                   is the parent of CHECKOUT, holding repo.json and, optionally, merge-plan.json
  --ci-timeout S   how long to wait for CI on a head before stopping (default 3600)
  --ci-start S     how long a head may have no check at all before CI counts as not run (default 300)
  --poll S         seconds between GitHub reads while waiting (default 30)

approval.json is the approval record, made and signed by the operator (approval.json.sig):
  {"run": "<run name>", "made": "<UTC time>", "plan": "<sha256 of merge-plan.json>" | null,
   "accept": [{"pr": "<owner>/<name>#<n>", "head": "<40-hex sha>", "base": "<branch>"}, ...],
   "close": ["<owner>/<name>#<n>", ...]}
  accept: the PRs the operator accepted, each with the head and the base it had when the operator decided. close:
  the PRs of the issue the operator did not choose. plan: the workspace's merge plan the operator was shown, null
  for none. The tool acts on no other PR. It refuses the record unless the signature verifies against the approval
  key <root>/approval-key.pub, the private key beside it, when present, has a passphrase, run is this run
  directory's name, and plan is the hash of the workspace's merge-plan.json as read now; the plan executed is
  parsed from those same bytes, as the record is parsed from the bytes verified. A plan with a tag admits one accepted
  PR of the workspace repository. It refuses to run from a copy inside the run's worktree, and while another
  process holds <run-dir>/merge.lock.

merge-plan.json: without it, one accepted PR, of repo.json's repository, merged with a merge commit; nothing else
follows. The only merge method is a merge commit.

The rule at every step is that a fact the approval binds is checked where it is used. Immediately before every
change on GitHub or a remote (marking ready, the merge, the pointer push, the tag push, a close, a branch deletion),
the approval record and its signature must still be the bytes verified at load, and for an accepted PR GitHub must
still report the head the change is made for, the approved base, and, while it is open, that head on its branch
ref. Removing or changing approval.json during a run therefore stops it before its next such change; what it did
before stays. Every ref this tool changes
on a remote is changed conditionally on the state it checked: the pointer push is leased on the fetched head, a
branch deletion on the head handled, a tag push on the tag's absence, and the merge on --match-head-commit.

Order of work. Nothing is changed until every check below passes for every PR as it is now:
  1. each PR to close is open or already closed; each accepted PR is open, or merged from its approved head
     (a rerun after a stop), comes from a branch of its own repository, is based on its approved base, and the
     workspace repository's PR is based on repo.json's base_branch;
  2. each accepted PR's head is its approved head, both as GitHub's PR view reports it and as its branch ref is
     read directly (the PR view can lag a push). The one exception is the workspace repository's PR when the
     plan has pointers: commits after the approved head that each change only the gitlinks of planned pointer
     paths, each to the merge commit of the sub-repo's accepted PR, merged from its approved head. This is
     read from each commit's tree (git diff-tree), not from its message;
  3. for each planned pointer: when the sub-repo has an accepted PR, the workspace PR's .gitmodules names that
     sub-repo at the path and the gitlink at the approved head is the sub-repo PR's approved head (or its
     merge commit); when it has none, the PR does not change that gitlink;
  4. each open accepted PR is mergeable (GitHub's mergeable is MERGEABLE), and no check on its head failed.
Then, for each accepted PR in the plan's order: one found merged must have been merged from its approved head
(else STOP, with no tag and no branch deletion); the workspace PR's planned pointers are moved to the merge
commits of the sub-repo PRs merged before it (one commit on its branch, pushed only after the fetched head passes
steps 1-2); the checks of steps 1, 2 and 4 are made again; CI on the head is waited for; the branch ref is read
again; a draft is marked ready; the ref is read once more, and the PR is merged with --match-head-commit <head>:
GitHub merges only when the PR's head is <head>, so in the window where its PR view still shows <head> after a
push it merges <head> itself or refuses; the merge commit must have the head as a parent; the plan's tag is
pushed for the workspace repository's merge commit; the PR's branch is deleted with
`git push --force-with-lease=refs/heads/<ref>:<head>`, which deletes it only while it points at the head merged,
in one operation, and keeps it (KEPT) when it moved. Then the PRs to close are closed, with a comment naming the
accepted PRs, and their branches deleted under the same lease, against the head each PR had; a PR to close found
merged is a STOP. Last, the run's worktree and local branch are removed, only when nothing exists only there.

CI passes on a head when its check runs and commit statuses have all completed, none failed, and at least
one succeeded. A head with no check after --ci-start seconds, or whose checks were all skipped or neutral,
has CI not run, which is not a pass; a repository in the plan's without_ci passes with no check at all.

Prints one line per step (OK a check passed, DID a change was made, KEPT a branch that moved, WAIT) and ends with
DONE, or with STOP <reason> and nothing further done; the same lines are appended to <run-dir>/merge.log. Exit
status 0 only for DONE. Each merge it makes is recorded in <run-dir>/merged.json (PR: head merged, merge commit).
After a STOP, run it again once the cause is resolved: a PR merged from its approved head or from the head
recorded there, moved pointers, closed PRs and deleted branches are recognized and not redone. The GitHub API
calls all go through the class GitHub; branch deletion and the pointer push are git.
"""
import argparse, json, os, re, subprocess, sys, tempfile, time

import approval, cleanup

SHA = re.compile(r'[0-9a-f]{40}')
PR_RE = re.compile(r'([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]*)', re.ASCII)
REPO_RE = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', re.ASCII)
GITHUB_URL = re.compile(r'(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)'
                        r'([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?', re.ASCII)
METHODS = ('merge',)  # squash and rebase leave the approved head off the base branch: pointers and cleanup need it there
PLAN_KEYS = {'method', 'order', 'pointers', 'tag', 'without_ci'}
MERGEABLE_WAIT = 120
HEAD_WAIT = 120


class Stop(Exception):
    pass


class GitHub:
    """Every GitHub call of the merge, made with gh and the session's GH_TOKEN."""

    def _gh(self, *args):
        p = subprocess.run(['gh', *args], capture_output=True, text=True)
        if p.returncode:
            raise Stop(f'gh {" ".join(args)}: {p.stderr.strip() or p.returncode}')
        return p.stdout

    def pr(self, repo, n):
        """{state OPEN|CLOSED|MERGED, head, head_ref, base_ref, draft, mergeable MERGEABLE|CONFLICTING|UNKNOWN,
        cross_repo, merge_commit (or None)}"""
        d = json.loads(self._gh('pr', 'view', str(n), '--repo', repo, '--json',
                                'state,headRefOid,headRefName,baseRefName,isDraft,mergeable,isCrossRepository,mergeCommit'))
        return {'state': d['state'], 'head': d['headRefOid'], 'head_ref': d['headRefName'],
                'base_ref': d['baseRefName'], 'draft': d['isDraft'], 'mergeable': d['mergeable'],
                'cross_repo': d['isCrossRepository'], 'merge_commit': (d.get('mergeCommit') or {}).get('oid')}

    def checks(self, repo, sha):
        """[(name, pending|success|failure|skipped|neutral)] of the check runs and commit statuses on sha."""
        out = []
        runs = self._gh('api', '--paginate', f'repos/{repo}/commits/{sha}/check-runs',
                        '--jq', '.check_runs[] | [.name, .status, (.conclusion // "")] | @tsv')
        for line in runs.splitlines():
            name, status, conclusion = (line.split('\t') + ['', ''])[:3]
            if status != 'completed':
                out.append((name, 'pending'))
            elif conclusion in ('success', 'skipped', 'neutral'):
                out.append((name, conclusion))
            else:
                out.append((name, 'failure'))
        statuses = self._gh('api', '--paginate', f'repos/{repo}/commits/{sha}/statuses',
                            '--jq', '.[] | [.context, .state] | @tsv')
        seen = set()
        for line in statuses.splitlines():  # newest first; the newest per context counts
            context, state = (line.split('\t') + [''])[:2]
            if context in seen:
                continue
            seen.add(context)
            out.append((context, {'success': 'success', 'pending': 'pending'}.get(state, 'failure')))
        return out

    def parents(self, repo, sha):
        return json.loads(self._gh('api', f'repos/{repo}/commits/{sha}', '--jq', '[.parents[].sha]'))

    def ready(self, repo, n):
        self._gh('pr', 'ready', str(n), '--repo', repo)

    def merge(self, repo, n, method, head):
        self._gh('pr', 'merge', str(n), '--repo', repo, f'--{method}', '--match-head-commit', head)

    def close(self, repo, n, comment):
        self._gh('pr', 'close', str(n), '--repo', repo, '--comment', comment)

    def branch_head(self, repo, ref):
        """The commit refs/heads/<ref> points at, read from the ref itself; None when it does not exist."""
        p = subprocess.run(['gh', 'api', f'repos/{repo}/git/ref/heads/{ref}', '--jq', '.object.sha'],
                           capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout.strip()
        if 'HTTP 404' in p.stderr or 'Not Found' in p.stderr:
            return None
        raise Stop(f'reading branch {ref} of {repo}: {p.stderr.strip() or p.returncode}')


def read_json(path, what):
    try:
        d = json.load(open(path))
    except (OSError, ValueError) as e:
        raise Stop(f'{path}: {e}')
    if not isinstance(d, dict):
        raise Stop(f'{path}: {what} must be a JSON object')
    return d


def parse_pr(s, path):
    m = PR_RE.fullmatch(s) if isinstance(s, str) else None
    if not m:
        raise Stop(f'{path}: {s!r} is not <owner>/<name>#<number>')
    return m[1].lower(), int(m[2])


def read_approval(path, run_name, key, pub, plan_hash):
    """The accepted and closed PRs of a record the approval key signed for this run, and the key's fingerprint."""
    if not os.path.isfile(path):
        raise Stop(f'no approval record {path}: the operator makes it with tools/approve.py')
    if not os.path.isfile(pub):
        raise Stop(f'no approval key {pub}: the operator makes it once with tools/approve.py --init')
    if os.path.exists(key) and not approval.encrypted(key):
        raise Stop(f'the approval key {key} has no passphrase, so its signature does not show the operator\'s action')
    try:
        data = approval.verify(path, pub)  # read once: the record parsed is the record verified
        signer = approval.fingerprint(pub)
    except approval.Invalid as e:
        raise Stop(str(e))
    try:
        d = json.loads(data)
    except ValueError as e:
        raise Stop(f'{path}: {e}')
    if not isinstance(d, dict):
        raise Stop(f'{path}: the approval record must be a JSON object')
    if set(d) != {'run', 'made', 'plan', 'accept', 'close'} or not isinstance(d['accept'], list) \
            or not isinstance(d['close'], list):
        raise Stop(f'{path}: holds exactly "run", "made", "plan", "accept" (a list) and "close" (a list)')
    if d['run'] != run_name:
        raise Stop(f'{path}: made for the run {d["run"]!r}, not {run_name}')
    if d['plan'] != plan_hash:
        raise Stop(f'{path}: signed for the merge plan {d["plan"] or "none"}, and the workspace\'s merge-plan.json is now '
                   f'{plan_hash or "absent"}: the plan changed after the decision')
    if not d['accept']:
        raise Stop(f'{path}: accept is empty')
    accept, close, seen = [], [], set()
    for e in d['accept']:
        if not isinstance(e, dict) or set(e) != {'pr', 'head', 'base'} or not isinstance(e['base'], str) or not e['base']:
            raise Stop(f'{path}: each accept entry is {{"pr", "head", "base"}} ({e!r})')
        repo, n = parse_pr(e['pr'], path)
        if not isinstance(e['head'], str) or not SHA.fullmatch(e['head']):
            raise Stop(f'{path}: {e["pr"]} head must be a full 40-hex sha ({e["head"]!r})')
        accept.append({'repo': repo, 'n': n, 'head': e['head'], 'base': e['base'], 'name': f'{repo}#{n}'})
    for s in d['close']:
        repo, n = parse_pr(s, path)
        close.append({'repo': repo, 'n': n, 'name': f'{repo}#{n}'})
    for e in accept + close:
        if e['name'] in seen:
            raise Stop(f'{path}: {e["name"]} is named twice')
        seen.add(e['name'])
    return accept, close, signer, d['made'], data


def read_plan(text, path, github):
    """The plan parsed from text, the bytes read from path once (None: no plan), with defaults; github is
    repo.json's repository, in lower case."""
    if text is None:
        return {'method': 'merge', 'order': [github], 'pointers': [], 'tag': None, 'without_ci': [], 'file': None}
    try:
        d = json.loads(text)
    except ValueError as e:
        raise Stop(f'{path}: {e}')
    if not isinstance(d, dict):
        raise Stop(f'{path}: the merge plan must be a JSON object')
    if set(d) - PLAN_KEYS:
        raise Stop(f'{path}: unknown keys {sorted(set(d) - PLAN_KEYS)}')
    order = d.get('order')
    if not isinstance(order, list) or not all(isinstance(r, str) and REPO_RE.fullmatch(r) for r in order):
        raise Stop(f'{path}: order must be a list of <owner>/<name>')
    order = [r.lower() for r in order]
    if len(set(order)) != len(order) or github not in order:
        raise Stop(f'{path}: order must name each repository once, {github} included')
    method = d.get('method', 'merge')
    if method not in METHODS:
        raise Stop(f'{path}: method must be merge (a merge commit)')
    pointers = d.get('pointers', [])
    if not isinstance(pointers, list):
        raise Stop(f'{path}: pointers must be a list')
    paths = set()
    for p in pointers:
        if not isinstance(p, dict) or set(p) != {'path', 'repo'} or not isinstance(p['path'], str) \
                or not p['path'] or not isinstance(p['repo'], str):
            raise Stop(f'{path}: each pointer is {{"path", "repo"}} ({p!r})')
        p['repo'] = p['repo'].lower()
        if p['repo'] not in order or order.index(p['repo']) > order.index(github):
            raise Stop(f'{path}: pointer {p["path"]}: {p["repo"]} must be in order, before {github}')
        if p['path'] in paths:
            raise Stop(f'{path}: pointer path {p["path"]} is named twice')
        paths.add(p['path'])
    tag = d.get('tag')
    if tag is not None and (not isinstance(tag, str) or not tag):
        raise Stop(f'{path}: tag must be a non-empty string')
    without_ci = d.get('without_ci', [])
    if not isinstance(without_ci, list) or not all(isinstance(r, str) and r.lower() in order for r in without_ci):
        raise Stop(f'{path}: without_ci must list repositories of order')
    return {'method': method, 'order': order, 'pointers': pointers, 'tag': tag,
            'without_ci': [r.lower() for r in without_ci], 'file': path}


class Merge:
    def __init__(self, run_dir, gh, ci_timeout=3600, ci_start=300, poll=30, sleep=time.sleep, now=time.monotonic):
        self.run_dir = os.path.realpath(run_dir)
        self.gh, self.ci_timeout, self.ci_start, self.poll, self.sleep, self.now = gh, ci_timeout, ci_start, poll, sleep, now
        self.log = os.path.join(self.run_dir, 'merge.log')
        self.merged = {}  # repo -> (pr name, merge commit) of the accepted PRs merged
        self.done_path = os.path.join(self.run_dir, 'merged.json')  # PR name -> {head, merge_commit} this tool merged
        self.done = {}

    def say(self, line):
        print(line, flush=True)
        with open(self.log, 'a') as f:
            f.write(line + '\n')

    # ---- git in the run's worktree, for the workspace repository

    def git(self, *args, env=None):
        p = subprocess.run(['git', '-C', self.co, *args], capture_output=True, text=True, env=env)
        if p.returncode:
            raise Stop(f'git -C {self.co} {" ".join(args)}: {p.stderr.strip() or p.returncode}')
        return p.stdout.strip()

    def fetch(self, ref):
        """The commit origin's ref points at, fetched into the worktree's object store."""
        if not os.path.isdir(self.co):
            raise Stop(f'the run\'s worktree {self.co} is gone: the workspace PR\'s commits cannot be read')
        self.git('fetch', '--no-recurse-submodules', '--quiet', 'origin', ref)
        return self.git('rev-parse', 'FETCH_HEAD')

    def gitlink(self, commit, path):
        out = self.git('ls-tree', commit, '--', path)
        parts = out.split()
        return parts[2] if len(parts) >= 3 and parts[0] == '160000' else None

    def submodule_repo(self, commit, path):
        """The GitHub repository .gitmodules at commit names for path, in lower case, or None."""
        p = subprocess.run(['git', '-C', self.co, 'config', '--blob', f'{commit}:.gitmodules', '--get-regexp', r'^submodule\..*\.path$'],
                           capture_output=True, text=True)
        for line in p.stdout.splitlines():
            key, value = line.split(' ', 1)
            if value == path:
                url = subprocess.run(['git', '-C', self.co, 'config', '--blob', f'{commit}:.gitmodules',
                                      key[:-len('.path')] + '.url'], capture_output=True, text=True).stdout.strip()
                m = GITHUB_URL.fullmatch(url)
                return m[1].lower() if m else url
        return None

    # ---- checks

    def is_merged_from(self, e, info):
        """An accepted PR GitHub reports merged: from its approved head, or from the head this tool checked and
        merged (merged.json), with the merge commit known."""
        if info['base_ref'] != e['base']:
            raise Stop(f'{e["name"]} is merged into {info["base_ref"]}, not the approved base {e["base"]}')
        done = self.done.get(e['name'], {})
        ok = info['head'] == e['head'] or (info['head'] == done.get('head') and info['merge_commit'] == done.get('merge_commit'))
        if not ok or not info['merge_commit']:
            raise Stop(f'{e["name"]} is merged from {info["head"][:7]}, neither the approved head {e["head"][:7]} '
                       'nor a head this tool merged')
        if info['head'] not in self.gh.parents(e['repo'], info['merge_commit']):
            raise Stop(f'{e["name"]}: merge commit {info["merge_commit"][:7]} does not have the head '
                       f'{info["head"][:7]} as a parent')
        self.merged[e['repo']] = (e['name'], info['merge_commit'])

    def accepted_sub(self, sub):
        return next((a for a in self.accept if a['repo'] == sub), None)

    def check_pointers(self, e, info, head):
        """Step 3, at the approved head; head is the PR's current head, fetched."""
        base = self.fetch(f'refs/heads/{self.base_branch}')
        fork = self.git('merge-base', head, base)
        for p in self.plan['pointers']:
            sub = self.accepted_sub(p['repo'])
            at = self.gitlink(e['head'], p['path'])
            if sub is None:
                if self.gitlink(head, p['path']) != self.gitlink(fork, p['path']):
                    raise Stop(f'{e["name"]} changes the gitlink {p["path"]} ({p["repo"]}), but no PR of {p["repo"]} '
                               'is in the approval record')
                continue
            named = self.submodule_repo(e['head'], p['path'])
            if named != p['repo']:
                raise Stop(f'{e["name"]}: .gitmodules names {named} at {p["path"]}, the plan {p["repo"]}')
            merge_commit = self.merged.get(p['repo'], (None, None))[1]
            if at not in (sub['head'], merge_commit):
                raise Stop(f'{e["name"]}: gitlink {p["path"]} at the approved head is {at and at[:7]}, not the approved '
                           f'head {sub["head"][:7]} of {sub["name"]}' + (f' or its merge commit {merge_commit[:7]}' if merge_commit else ''))

    def check_ref(self, e, info):
        """The PR's branch ref, read directly, is the head the PR view reports."""
        ref = self.gh.branch_head(e['repo'], info['head_ref'])
        if ref != info['head']:
            raise Stop(f'{e["name"]}: branch {info["head_ref"]} is at {ref[:7] if ref else "nothing (deleted)"}, '
                       f'while GitHub\'s PR view reports {info["head"][:7]}: a push it has not registered yet, or a moved branch')

    def check_head(self, e, info):
        """Steps 1 (the base) and 2 (and 3 for the workspace repository's PR)."""
        head = info['head']
        if info['base_ref'] != e['base']:
            raise Stop(f'{e["name"]} is based on {info["base_ref"]}, not the approved base {e["base"]}')
        self.check_ref(e, info)
        if e['repo'] == self.github and self.plan['pointers']:
            fetched = self.fetch(f'refs/heads/{info["head_ref"]}')
            if fetched != head:
                raise Stop(f'{e["name"]}: GitHub reports head {head[:7]}, origin\'s {info["head_ref"]} is {fetched[:7]}')
            if subprocess.run(['git', '-C', self.co, 'cat-file', '-e', f'{e["head"]}^{{commit}}'],
                              stderr=subprocess.DEVNULL).returncode:
                raise Stop(f'{e["name"]}: the approved head {e["head"][:7]} is not in the history of its branch '
                           f'{info["head_ref"]} (head {head[:7]})')
            self.check_pointers(e, info, head)
        if head == e['head']:
            self.say(f'OK {e["name"]} head is the approved head {head[:7]}')
            return
        if e['repo'] != self.github or not self.plan['pointers']:
            raise Stop(f'{e["name"]}: head is {head[:7]}, not the approved head {e["head"][:7]}')
        if subprocess.run(['git', '-C', self.co, 'merge-base', '--is-ancestor', e['head'], head],
                          stderr=subprocess.DEVNULL).returncode:
            raise Stop(f'{e["name"]}: head {head[:7]} does not contain the approved head {e["head"][:7]}')
        paths = {p['path']: p['repo'] for p in self.plan['pointers']}
        for line in self.git('rev-list', '--reverse', '--parents', f'{e["head"]}..{head}').splitlines():
            commit, *parents = line.split()
            if len(parents) != 1:
                raise Stop(f'{e["name"]}: {commit[:7]} after the approved head is a merge commit')
            changes = self.git('diff-tree', '--no-commit-id', '-r', '--raw', '--no-renames', parents[0], commit).splitlines()
            if not changes:
                raise Stop(f'{e["name"]}: {commit[:7]} after the approved head changes nothing')
            for c in changes:
                meta, path = c.split('\t', 1)
                old_mode, new_mode, _, new, _ = meta.lstrip(':').split()
                if path not in paths or old_mode != '160000' or new_mode != '160000':
                    raise Stop(f'{e["name"]}: {commit[:7]} after the approved head changes {path}, '
                               'which is not a planned gitlink')
                sub, merge_commit = paths[path], self.merged.get(paths[path], (None, None))[1]
                if new != merge_commit:
                    want = (f'the merge commit {merge_commit[:7]} of {self.merged[sub][0]}' if merge_commit
                            else f'a merge commit of an accepted {sub} PR merged in this procedure (none is)')
                    raise Stop(f'{e["name"]}: {commit[:7]} after the approved head moves {path} to {new[:7]}, not {want}')
        self.say(f'OK {e["name"]} head {head[:7]}: the approved head {e["head"][:7]} and pointer-only commits after it')

    def guard(self, action, e=None, head=None):
        """Called immediately before every change this tool makes on GitHub or a remote. The approval record and its
        signature are still the bytes verified at load (a removed or changed record withdraws the decision from here
        on), and for an accepted PR, GitHub still reports the head the change is made for and the approved base, and
        an open PR's branch ref is that head."""
        for path, data in ((self.record_path, self.record_bytes), (self.record_path + '.sig', self.sig_bytes)):
            try:
                now = open(path, 'rb').read()
            except OSError:
                now = None
            if now != data:
                raise Stop(f'before {action}: {path} was {"removed" if now is None else "changed"} after this run '
                           'verified it, so the decision is withdrawn from here on; what was done before stays')
        if e is None:
            return
        info = self.gh.pr(e['repo'], e['n'])
        if info['base_ref'] != e['base']:
            raise Stop(f'before {action}: {e["name"]} is based on {info["base_ref"]}, not the approved base {e["base"]}')
        if info['head'] != head:
            raise Stop(f'before {action}: {e["name"]}\'s head is {info["head"][:7]}, not {head[:7]}')
        if info['state'] == 'OPEN':
            self.check_ref(e, info)

    def wait_mergeable(self, e):
        start = self.now()
        while True:
            info = self.gh.pr(e['repo'], e['n'])
            if info['mergeable'] == 'MERGEABLE':
                self.say(f'OK {e["name"]} is mergeable')
                return info
            if info['mergeable'] == 'CONFLICTING':
                raise Stop(f'{e["name"]} has a conflict with {info["base_ref"]}')
            if self.now() - start >= MERGEABLE_WAIT:
                raise Stop(f'{e["name"]} is not mergeable: GitHub reports {info["mergeable"]} after {MERGEABLE_WAIT} s')
            self.sleep(min(self.poll, 10))

    def ci(self, e, sha, wait):
        """CI on sha. Without wait, stops only on a failed check."""
        start = self.now()
        while True:
            checks = self.gh.checks(e['repo'], sha)
            failed = [n for n, s in checks if s == 'failure']
            if failed:
                raise Stop(f'CI failed on {e["name"]} {sha[:7]}: {", ".join(failed)}')
            pending = [n for n, s in checks if s == 'pending']
            if not wait:
                return
            if checks and not pending:
                if any(s == 'success' for _, s in checks) or e['repo'] in self.plan['without_ci']:
                    self.say(f'OK CI passed on {e["name"]} {sha[:7]} ({len(checks)} checks)')
                    return
                raise Stop(f'CI did not run on {e["name"]} {sha[:7]}: every check was skipped or neutral')
            if not checks:
                if e['repo'] in self.plan['without_ci']:
                    self.say(f'OK no CI on {e["name"]} {sha[:7]}: {e["repo"]} is in the plan\'s without_ci')
                    return
                if self.now() - start >= self.ci_start:
                    raise Stop(f'CI did not run on {e["name"]} {sha[:7]}: no check after {self.ci_start} s')
            if self.now() - start >= self.ci_timeout:
                raise Stop(f'CI did not finish on {e["name"]} {sha[:7]} in {self.ci_timeout} s: {", ".join(pending)}')
            self.sleep(self.poll)

    # ---- changes

    def move_pointers(self, e, info):
        """Moves the planned gitlinks of the workspace PR to the sub-repo merge commits; returns the PR's head."""
        head = self.fetch(f'refs/heads/{info["head_ref"]}')
        moves = []
        for p in self.plan['pointers']:
            if self.accepted_sub(p['repo']) is None:
                continue
            if p['repo'] not in self.merged:
                raise Stop(f'{e["name"]}: {p["repo"]} has an accepted PR that is not merged before it')
            name, merge_commit = self.merged[p['repo']]
            if self.gitlink(head, p['path']) != merge_commit:
                moves.append((p['path'], merge_commit, name))
        if not moves:
            return info
        self.check_head(e, dict(info, head=head))  # before anything is pushed on top of it
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, GIT_INDEX_FILE=os.path.join(d, 'index'))
            self.git('read-tree', head, env=env)
            for path, sha, _ in moves:
                self.git('update-index', '--cacheinfo', f'160000,{sha},{path}', env=env)
            tree = self.git('write-tree', env=env)
        subject = '; '.join(f'Move {path} to the merge commit of {name}' for path, _, name in moves)
        body = '\n'.join(f'{path}: {sha}' for path, sha, _ in moves)
        commit = self.git('commit-tree', tree, '-p', head, '-m', subject, '-m', body)
        # Leased on the fetched head, the one just checked: any change of the branch since, a rewind included,
        # refuses the push.
        self.guard('the pointer push', e, head)
        p = subprocess.run(['git', '-C', self.co, 'push', '--quiet', '--recurse-submodules=no',
                            f'--force-with-lease=refs/heads/{info["head_ref"]}:{head}', 'origin',
                            f'{commit}:refs/heads/{info["head_ref"]}'], capture_output=True, text=True)
        if p.returncode:
            raise Stop(f'{e["name"]}: the pointer commit was not pushed: branch {info["head_ref"]} changed since its head '
                       f'{head[:7]} was fetched and checked ({p.stderr.strip() or p.returncode})')
        self.say(f'DID pushed {commit[:7]} on {e["name"]}\'s branch {info["head_ref"]}: ' +
                 ', '.join(f'{path} -> {sha[:7]}' for path, sha, _ in moves))
        start = self.now()
        while True:
            info = self.gh.pr(e['repo'], e['n'])
            if info['head'] == commit:
                return info
            if self.now() - start >= HEAD_WAIT:
                raise Stop(f'{e["name"]}: GitHub reports head {info["head"][:7]}, not the pushed {commit[:7]}, after {HEAD_WAIT} s')
            self.sleep(min(self.poll, 5))

    def tag(self, e, info):
        merge_commit = info['merge_commit']
        name = self.plan['tag']
        if '{VERSION}' in name:
            self.fetch(f'refs/heads/{self.base_branch}')
            version = self.git('show', f'{merge_commit}:VERSION')
            name = name.replace('{VERSION}', version)
        if subprocess.run(['git', 'check-ref-format', f'refs/tags/{name}']).returncode:
            raise Stop(f'{name!r} is not a valid tag name')
        remote = self.git('ls-remote', 'origin', f'refs/tags/{name}').split()
        if remote:
            if remote[0] != merge_commit:
                raise Stop(f'tag {name} exists on origin at {remote[0][:7]}, not at the merge commit {merge_commit[:7]}')
            self.say(f'OK tag {name} is on origin at {merge_commit[:7]}')
            return
        # Leased on the tag's absence, which was just read: a tag made since refuses the push.
        self.guard(f'pushing tag {name}', e, info['head'])
        p = subprocess.run(['git', '-C', self.co, 'push', '--quiet', f'--force-with-lease=refs/tags/{name}:', 'origin',
                            f'{merge_commit}:refs/tags/{name}'], capture_output=True, text=True)
        if p.returncode:
            raise Stop(f'tag {name} was not pushed: it was made on origin since it was read ({p.stderr.strip() or p.returncode})')
        self.say(f'DID pushed tag {name} at {merge_commit[:7]}')

    def delete_branch(self, e, info):
        """Deletes the PR's branch only while it points at info's head (the head merged, or the head at closing),
        in one operation: a push whose lease is that head."""
        if info['cross_repo']:
            return
        ref, head = info['head_ref'], info['head']
        accepted = 'base' in e  # an accepted PR binds its head and base; a PR to close binds only its name
        self.guard(f'deleting branch {ref} of {e["repo"]}', e if accepted else None, head if accepted else None)
        p = subprocess.run(['git', '-C', self.clone, 'push', '--quiet', f'--force-with-lease=refs/heads/{ref}:{head}',
                            f'https://github.com/{e["repo"]}.git', f':refs/heads/{ref}'], capture_output=True, text=True)
        if p.returncode == 0:
            self.say(f'DID deleted branch {ref} of {e["repo"]} at {head[:7]}')
            return
        now = self.gh.branch_head(e['repo'], ref)  # what the refused lease met, for the report only
        if now is None:
            self.say(f'OK branch {ref} of {e["repo"]} is already gone')
        elif now != head:
            self.say(f'KEPT branch {ref} of {e["repo"]}: it is at {now[:7]}, not at {e["name"]}\'s head {head[:7]}, '
                     'so it holds commits this procedure did not handle')
        else:
            raise Stop(f'deleting branch {ref} of {e["repo"]}: {p.stderr.strip() or p.returncode}')

    # ---- the procedure

    def load(self):
        env = cleanup.read_env(self.run_dir) if os.path.isdir(self.run_dir) else None
        if not env or not env.get('CHECKOUT'):
            raise Stop(f'{self.run_dir}: no run.env with CHECKOUT')
        self.co, self.issue = env['CHECKOUT'], env.get('ISSUE', '?')
        workspace = os.path.dirname(self.co)
        repo = read_json(os.path.join(workspace, 'repo.json'), 'repo.json')
        if not isinstance(repo.get('github'), str) or not isinstance(repo.get('base_branch'), str):
            raise Stop(f'{workspace}/repo.json: github and base_branch are required')
        self.github, self.base_branch = repo['github'].lower(), repo['base_branch']
        if not isinstance(repo.get('clone'), str):
            raise Stop(f'{workspace}/repo.json: clone is required')
        self.clone = os.path.realpath(os.path.expanduser(repo['clone']))
        try:
            approval.refuse_copy_in(self.co, __file__)
            key, pub = approval.key_paths()
        except approval.Invalid as e:
            raise Stop(str(e))
        plan_hash, plan_text = approval.plan_of(workspace)  # read once: the plan executed is the plan hashed
        self.record_path = os.path.join(self.run_dir, 'approval.json')
        self.accept, self.close, signer, made, self.record_bytes = read_approval(
            self.record_path, os.path.basename(self.run_dir), key, pub, plan_hash)
        self.sig_bytes = open(self.record_path + '.sig', 'rb').read()
        self.say(f'OK approval record made {made}, signed by the approval key {signer} ({pub})')
        self.plan = read_plan(plan_text, os.path.join(workspace, approval.PLAN_NAME), self.github)
        self.say(f'OK approval: accept {", ".join(a["name"] for a in self.accept)}; close {", ".join(c["name"] for c in self.close) or "none"}; '
                 f'plan {self.plan["file"] or "none (one PR, merge commit)"}')
        order = self.plan['order']
        for e in self.accept + self.close:
            if e['repo'] not in order:
                raise Stop(f'{e["name"]} is in {e["repo"]}, which the merge plan does not name' if self.plan['file'] else
                           f'{e["name"]} is not in {self.github}, and without a merge plan only {self.github} is merged')
        if not self.plan['file'] and len(self.accept) != 1:
            raise Stop(f'without a merge plan one PR is merged, and the approval accepts {len(self.accept)}')
        conflict = approval.tag_conflict(plan_text, self.github, [a['repo'] for a in self.accept])
        if conflict:
            raise Stop(conflict)
        for p in self.plan['pointers']:
            if sum(a['repo'] == p['repo'] for a in self.accept) > 1:
                raise Stop(f'the approval accepts more than one PR of {p["repo"]}, whose merge the pointer {p["path"]} moves to')
        self.accept.sort(key=lambda a: order.index(a['repo']))  # stable: the approval's order within a repository

    def preflight(self):
        for c in self.close:
            info = self.gh.pr(c['repo'], c['n'])
            if info['state'] == 'MERGED':
                raise Stop(f'{c["name"]}, to be closed, is merged')
        infos = {}
        for e in self.accept:
            info = infos[e['name']] = self.gh.pr(e['repo'], e['n'])
            if info['state'] == 'MERGED':
                self.is_merged_from(e, info)
                self.say(f'OK {e["name"]} is already merged from its approved head: {info["merge_commit"][:7]}')
                continue
            if info['state'] != 'OPEN':
                raise Stop(f'{e["name"]} is {info["state"].lower()}')
            if info['cross_repo']:
                raise Stop(f'{e["name"]} comes from another repository\'s branch, which this tool does not merge')
            if e['repo'] == self.github and info['base_ref'] != self.base_branch:
                raise Stop(f'{e["name"]} is based on {info["base_ref"]}, not {self.base_branch}')
        for e in self.accept:
            info = infos[e['name']]
            if info['state'] == 'MERGED':
                continue
            self.check_head(e, info)
            self.wait_mergeable(e)
            self.ci(e, info['head'], wait=False)
        self.say('OK every check passed before any change')

    def merge_one(self, e):
        info = self.gh.pr(e['repo'], e['n'])
        if info['state'] == 'MERGED':
            self.is_merged_from(e, info)
            self.say(f'OK {e["name"]} is merged from its approved head: {info["merge_commit"][:7]}')
            return
        if info['state'] != 'OPEN':
            raise Stop(f'{e["name"]} is {info["state"].lower()}')
        if e['repo'] == self.github and self.plan['pointers']:
            info = self.move_pointers(e, info)
        self.check_head(e, info)
        self.wait_mergeable(e)
        self.say(f'WAIT CI on {e["name"]} {info["head"][:7]}')
        self.ci(e, info['head'], wait=True)
        if info['draft']:
            self.guard(f'marking {e["name"]} ready', e, info['head'])
            self.gh.ready(e['repo'], e['n'])
            self.say(f'DID marked {e["name"]} ready for review')
        self.guard(f'merging {e["name"]}', e, info['head'])
        self.gh.merge(e['repo'], e['n'], self.plan['method'], info['head'])
        done = self.gh.pr(e['repo'], e['n'])
        if done['state'] != 'MERGED' or not done['merge_commit']:
            raise Stop(f'{e["name"]}: GitHub reports {done["state"]} after the merge call')
        if done['base_ref'] != e['base']:  # a retarget between the last guard and the merge: detected, not undone
            raise Stop(f'{e["name"]} was merged into {done["base_ref"]}, not the approved base {e["base"]} '
                       f'(merge commit {done["merge_commit"][:7]}); nothing further is done')
        if info['head'] not in self.gh.parents(e['repo'], done['merge_commit']):
            raise Stop(f'{e["name"]}: merge commit {done["merge_commit"][:7]} does not have the head {info["head"][:7]} as a parent')
        self.merged[e['repo']] = (e['name'], done['merge_commit'])
        self.done[e['name']] = {'head': info['head'], 'merge_commit': done['merge_commit']}
        with open(self.done_path + '.new', 'w') as f:
            json.dump(self.done, f, indent=1)
        os.replace(self.done_path + '.new', self.done_path)
        self.say(f'DID merged {e["name"]} ({self.plan["method"]}) from {info["head"][:7]}: {done["merge_commit"][:7]}')

    def after(self, e):
        info = self.gh.pr(e['repo'], e['n'])
        if e['repo'] == self.github and self.plan['tag']:
            self.tag(e, info)
        self.delete_branch(e, info)

    def run(self):
        self.done = json.load(open(self.done_path)) if os.path.exists(self.done_path) else {}
        self.load()
        self.preflight()
        for e in self.accept:
            self.merge_one(e)
            self.after(e)
        accepted = ', '.join(a['name'] for a in self.accept)
        for c in self.close:
            info = self.gh.pr(c['repo'], c['n'])
            if info['state'] == 'MERGED':
                raise Stop(f'{c["name"]}, to be closed, is merged')
            if info['state'] == 'OPEN':
                self.guard(f'closing {c["name"]}')
                self.gh.close(c['repo'], c['n'], f'Not chosen for issue #{self.issue}: the operator accepted {accepted}.')
                self.say(f'DID closed {c["name"]}')
            else:
                self.say(f'OK {c["name"]} is already closed')
            self.delete_branch(c, info)
        try:
            cleanup.run(self.run_dir, self.say)
        except cleanup.Refused as e:
            raise Stop(f'merges done; cleanup: {e}')


def main(argv, gh=None, **timing):
    ap = argparse.ArgumentParser(description='Carry out the operator\'s merge decision of a run.')
    ap.add_argument('run_dir')
    ap.add_argument('--ci-timeout', type=int, default=3600)
    ap.add_argument('--ci-start', type=int, default=300)
    ap.add_argument('--poll', type=int, default=30)
    a = ap.parse_args(argv)
    m = Merge(a.run_dir, gh or GitHub(), ci_timeout=a.ci_timeout, ci_start=a.ci_start, poll=a.poll, **timing)
    if not os.path.isdir(m.run_dir):
        print(f'STOP {m.run_dir} is not a run directory')
        return 1
    lock = approval.try_lock(m.run_dir)  # held for the whole run
    if lock is None:  # merge.log is the other process's; nothing is written to it
        print(f'STOP another process holds {os.path.join(m.run_dir, approval.LOCK_NAME)} (a merge.py run, or a decision '
              'being signed): wait for it to end, then run again')
        return 1
    try:
        m.say(f'== merge.py {time.strftime("%Y-%m-%d %H:%M:%S")}')
        m.run()
        m.say('DONE')
        return 0
    except Stop as e:
        m.say(f'STOP {e}')
        return 1
    finally:
        lock.close()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
