#!/usr/bin/env python3
"""approve.py --init | <run-dir> --accept <owner>/<name>#<n>[@<sha>] ... [--close <owner>/<name>#<n> ...]
— the operator's merge decision, made by the operator in a terminal of their own, as the signed approval record
that tools/merge.py reads.

  --init           makes the approval key: `ssh-keygen -t ed25519` writes <root>/approval-key and approval-key.pub
                   and asks for a passphrase, which must not be empty. Once per machine; refused when the key exists
  <run-dir>        <runs>/<name>/ holding run.env; the workspace is the parent of CHECKOUT, holding gh-token
  --accept PR[@SHA] a PR the operator accepts. With @SHA (a full sha or a prefix of 7 or more), the PR's head must be
                   that commit: the head the operator reviewed
  --close PR       a PR of the issue the operator did not choose; merge.py closes it

Each named PR is read from GitHub with the workspace's gh-token and shown: state, draft, base, title, head sha and the
head commit's subject. The operator types `yes` on the terminal to approve what is shown, and then the key's
passphrase, which `ssh-keygen -Y sign` asks for. Then <run-dir>/approval.json and approval.json.sig are written:
  {"run": "<run name>", "made": "<UTC time>", "accept": [{"pr": "<owner>/<name>#<n>", "head": "<sha>"}, ...],
   "close": ["<owner>/<name>#<n>", ...]}
The heads recorded are those shown. A new decision replaces the record.

It refuses to run without a terminal: its stdin must be a terminal and /dev/tty must open, and ssh-keygen runs with
no SSH agent and no askpass program, so the passphrase is read from the terminal and nowhere else. A command run
by Claude Code's Bash tool has no terminal, so it is refused there. A session can still give it a pseudo-terminal
and type `yes`: what it cannot give is the passphrase, unless it knows it. What this does and does not guarantee is in
COORDINATOR.md > Operator boundary.
"""
import argparse, datetime, json, os, re, shutil, stat, subprocess, sys

import approval

PR_ARG = re.compile(r'([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]*)(?:@([0-9a-f]{7,40}))?', re.ASCII)


def fail(msg):
    sys.exit(f'approve.py: {msg}')


def terminal():
    if not os.isatty(0):
        fail('stdin is not a terminal: run it yourself, in a terminal, not from a Claude Code session')
    try:
        return open('/dev/tty'), open('/dev/tty', 'w')
    except OSError as e:
        fail(f'no terminal ({e}): run it yourself, in a terminal, not from a Claude Code session')


def init():
    key, pub = approval.key_paths()
    terminal()
    if os.path.exists(key) or os.path.exists(pub):
        fail(f'{key} exists: one approval key per machine; remove it yourself to make another')
    os.makedirs(os.path.dirname(key), exist_ok=True)
    p = subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-f', key, '-C', approval.NAMESPACE], env=approval.no_agent())
    if p.returncode:
        fail('ssh-keygen did not make the key')
    if not approval.encrypted(key):
        os.remove(key); os.remove(pub)
        fail('the passphrase was empty, so the key was removed: run --init again and give a passphrase')
    print(f'approval key {key} ({approval.fingerprint(pub)}). Do not add it to an SSH agent or a keychain: '
          'a key held there signs without the passphrase.')


def workspace_token(run_dir):
    env = dict(l.rstrip('\n').split('=', 1) for l in open(os.path.join(run_dir, 'run.env')) if '=' in l)
    path = os.path.join(os.path.dirname(env['CHECKOUT']), 'gh-token')
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
        fail(f'{path} must be a regular file readable by you only (WORKSPACE.md > gh-token)')
    return open(path).read().strip()


def gh(token, *args):
    p = subprocess.run(['gh', *args], capture_output=True, text=True, env=dict(os.environ, GH_TOKEN=token))
    if p.returncode:
        fail(f'gh {" ".join(args)}: {p.stderr.strip() or p.returncode}')
    return p.stdout


def read_pr(token, repo, n):
    d = json.loads(gh(token, 'pr', 'view', str(n), '--repo', repo, '--json',
                      'state,isDraft,baseRefName,headRefName,headRefOid,title'))
    d['subject'] = gh(token, 'api', f'repos/{repo}/commits/{d["headRefOid"]}', '--jq', '.commit.message').split('\n')[0]
    return d


def decide(args):
    run_dir = os.path.realpath(args.run_dir)
    key, pub = approval.key_paths()
    tty_in, tty = terminal()
    if not os.path.isfile(key) or not os.path.isfile(pub):
        fail(f'no approval key {key}: make it once with tools/approve.py --init')
    if not approval.encrypted(key):
        fail(f'{key} has no passphrase: remove it and make it again with --init')
    token = workspace_token(run_dir)
    accept, close, lines = [], [], []
    for arg in args.accept:
        m = PR_ARG.fullmatch(arg)
        if not m:
            fail(f'--accept {arg!r}: <owner>/<name>#<n>[@<sha>]')
        d = read_pr(token, m[1], m[2])
        if d['state'] != 'OPEN':
            fail(f'{m[1]}#{m[2]} is {d["state"].lower()}')
        if m[3] and not d['headRefOid'].startswith(m[3]):
            fail(f'{m[1]}#{m[2]}: head is {d["headRefOid"]}, not the reviewed {m[3]}')
        accept.append({'pr': f'{m[1]}#{m[2]}', 'head': d['headRefOid']})
        lines += [f'ACCEPT {m[1]}#{m[2]}  {d["title"]}',
                  f'       {d["state"].lower()}{", draft" if d["isDraft"] else ""}, {d["headRefName"]} -> {d["baseRefName"]}',
                  f'       head {d["headRefOid"]}  {d["subject"]}']
    for arg in args.close:
        m = PR_ARG.fullmatch(arg)
        if not m or m[3]:
            fail(f'--close {arg!r}: <owner>/<name>#<n>')
        d = read_pr(token, m[1], m[2])
        close.append(f'{m[1]}#{m[2]}')
        lines += [f'CLOSE  {m[1]}#{m[2]}  {d["title"]} ({d["state"].lower()})']
    tty.write(f'Run {os.path.basename(run_dir)}\n' + '\n'.join(lines) + '\nApprove these merges and closes? Type yes: ')
    tty.flush()
    if tty_in.readline().strip() != 'yes':
        fail('not approved; nothing written')
    record = {'run': os.path.basename(run_dir),
              'made': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'accept': accept, 'close': close}
    new = os.path.join(run_dir, f'approval.json.{os.getpid()}')
    with open(new, 'w') as f:
        json.dump(record, f, indent=1)
        f.write('\n')
    p = subprocess.run(['ssh-keygen', '-Y', 'sign', '-f', key, '-n', approval.NAMESPACE, new], env=approval.no_agent())
    if p.returncode or not os.path.isfile(new + '.sig'):
        os.remove(new)
        fail('ssh-keygen did not sign the record; nothing written')
    try:
        approval.verify(new, pub)
    except approval.Invalid as e:
        fail(str(e))
    os.replace(new + '.sig', os.path.join(run_dir, 'approval.json.sig'))
    os.replace(new, os.path.join(run_dir, 'approval.json'))
    print(f'approval record {run_dir}/approval.json signed by {approval.fingerprint(pub)}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Make the signed approval record of a merge decision.')
    ap.add_argument('run_dir', nargs='?')
    ap.add_argument('--init', action='store_true')
    ap.add_argument('--accept', action='append', default=[])
    ap.add_argument('--close', action='append', default=[])
    a = ap.parse_args()
    if not shutil.which('ssh-keygen'):
        fail('ssh-keygen (OpenSSH) is required')
    if a.init:
        if a.run_dir or a.accept or a.close:
            fail('--init takes no other argument')
        init()
    elif not a.run_dir or not a.accept:
        fail('a run directory and at least one --accept are required (or --init)')
    else:
        decide(a)
