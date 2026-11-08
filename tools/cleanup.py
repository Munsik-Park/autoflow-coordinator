#!/usr/bin/env python3
"""cleanup.py <run-dir> — remove a run's worktree and its local branch, only when nothing exists only there.

  <run-dir>  <runs>/<name>/ holding run.env (CHECKOUT, BRANCH); the workspace is the parent of CHECKOUT,
             and its repo.json names the clone

The clone is fetched from origin with --prune, and each initialized submodule of the worktree, at any depth,
from its own origin. Then nothing is removed when any of these exists:
  - in the worktree: uncommitted or untracked files (ignored files are not counted), staged changes, or
    commits of HEAD or of the run's branch BRANCH that are on no remote-tracking branch;
  - in a submodule of the worktree: uncommitted or untracked files, commits of its HEAD or of its local
    branches on no remote-tracking branch, or a stash entry. A submodule of a worktree is that worktree's
    own repository (under <clone>/.git/worktrees/<worktree>/modules/), so all of these go with it.
Otherwise the worktree is removed with `git worktree remove --force`, which git needs for a worktree holding
submodules; `git submodule deinit` is never run, since it removes the clone's submodule.<name>.* entries,
which every worktree shares. Those entries are compared before and after, and restored with
`git submodule init` when any is gone. The local branch BRANCH is then deleted, under the same check.
The clone's other branches, its checked-out branch, the remote branches and run.env's STATE are not changed.

Prints one line per step and ends with DONE, or STOP <reason> when something is left in place; exit status
0 only for DONE. Run it again after a STOP: it does only what is left.
"""
import json, os, subprocess, sys


class Refused(Exception):
    pass


def read_env(run_dir):
    path = os.path.join(run_dir, 'run.env')
    try:
        return dict(l.rstrip('\n').split('=', 1) for l in open(path) if '=' in l)
    except OSError as e:
        raise Refused(f'{path}: {e}')


def read_clone(workspace):
    path = os.path.join(workspace, 'repo.json')
    try:
        clone = json.load(open(path))['clone']
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise Refused(f'{path}: no clone ({e})')
    return os.path.realpath(os.path.expanduser(clone))


def git(where, *args, ok=(0,)):
    p = subprocess.run(['git', '-C', where, *args], capture_output=True, text=True)
    if p.returncode not in ok:
        raise Refused(f'git -C {where} {" ".join(args)}: {p.stderr.strip() or p.returncode}')
    return p.stdout


def has_branch(clone, branch):
    return subprocess.run(['git', '-C', clone, 'show-ref', '--verify', '--quiet', f'refs/heads/{branch}']).returncode == 0


def submodule_config(clone):
    return set(git(clone, 'config', '--local', '--get-regexp', r'^submodule\.', ok=(0, 1)).splitlines())


def leftovers(co, branch, clone):
    """What exists only in the worktree co, one line each."""
    found = []
    # Submodule content is checked in each submodule below; a gitlink staged in the index shows in diff --cached.
    for line in git(co, 'status', '--porcelain', '--ignore-submodules=all').splitlines():
        found.append(f'{co}: uncommitted {line}')
    for name in git(co, 'diff', '--cached', '--name-only').splitlines():
        found.append(f'{co}: staged {name}')
    tips = ['HEAD'] + ([f'refs/heads/{branch}'] if has_branch(clone, branch) else [])
    for c in git(co, 'rev-list', '--oneline', *tips, '--not', '--remotes').splitlines():
        found.append(f'{co}: commit on no remote {c}')
    subs = git(co, 'submodule', 'foreach', '--quiet', '--recursive', 'pwd').splitlines()
    for sub in subs:
        for line in git(sub, 'status', '--porcelain').splitlines():
            found.append(f'{sub}: uncommitted {line}')
        for c in git(sub, 'rev-list', '--oneline', 'HEAD', '--branches', '--not', '--remotes').splitlines():
            found.append(f'{sub}: commit on no remote {c}')
        for s in git(sub, 'stash', 'list').splitlines():
            found.append(f'{sub}: stash {s}')
    return found


def run(run_dir, say=print):
    """Removes what it can; raises Refused naming what is left and why."""
    run_dir = os.path.realpath(run_dir)
    env = read_env(run_dir)
    co, branch = env.get('CHECKOUT'), env.get('BRANCH')
    if not co or not branch:
        raise Refused(f'{run_dir}/run.env has no CHECKOUT or BRANCH')
    clone = read_clone(os.path.dirname(co))
    git(clone, 'fetch', '--no-recurse-submodules', '--prune', '--quiet', 'origin')
    say(f'OK fetched origin in {clone}')
    if os.path.isdir(co):
        git(co, 'submodule', 'foreach', '--quiet', '--recursive', 'git fetch --prune --quiet origin')
        found = leftovers(co, branch, clone)
        if found:
            raise Refused('the worktree holds what exists nowhere else, so nothing was removed:\n  ' + '\n  '.join(found))
        say(f'OK nothing exists only in {co} or its submodules')
        before = submodule_config(clone)
        os.chdir(clone)  # the caller may be inside the worktree
        git(clone, 'worktree', 'remove', '--force', co)
        say(f'DID removed worktree {co}')
        lost = before - submodule_config(clone)
        if lost:
            git(clone, 'submodule', 'init')
            still = before - submodule_config(clone)
            if still:
                raise Refused(f'{clone}: submodule entries lost and not restored by git submodule init: {sorted(still)}')
            say(f'DID restored {len(lost)} submodule entries of {clone} with git submodule init')
    else:
        say(f'OK worktree {co} already removed')
    if has_branch(clone, branch):
        only = git(clone, 'rev-list', '--oneline', f'refs/heads/{branch}', '--not', '--remotes').splitlines()
        if only:
            raise Refused(f'{clone}: branch {branch} has commits on no remote, so it was kept:\n  ' + '\n  '.join(only))
        git(clone, 'branch', '-D', branch)
        say(f'DID deleted local branch {branch} in {clone}')
    else:
        say(f'OK no local branch {branch} in {clone}')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__.split('\n\n')[0])
    try:
        run(sys.argv[1])
    except Refused as e:
        print(f'STOP {e}')
        sys.exit(1)
    print('DONE')
