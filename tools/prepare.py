#!/usr/bin/env python3
"""prepare.py <workspace> <issue> [--key KEY] [--base-confirmed] — prepare one coordination run.

Everything the run needs is checked first, then in this order: the run directory is claimed by mkdir
(one claim wins per key), the clone is fetched, a detached worktree is added at origin/<base_branch>,
the record folder is made, and sessions.tsv, runbook.md and last run.env are written. run.env comes
last so that no half-prepared run is seen by check.sh. On a failure, what this call made is removed.

  <workspace>       a workspace name under the base, holding repo.json
  <issue>           the issue number
  --key KEY         a run key received from outside; without it one is generated
  --base-confirmed  the operator confirmed the base; required when the base is the built-in default

Paths come from config.py. Prints the run directory and run.env. The branch is a name for the run:
the worktree stays detached and the ref is not created. Preparation that differs by repo is not here
(the workspace's coordination.md).
"""
import argparse, json, os, re, secrets, shutil, subprocess, sys, time

TOOLS = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.expanduser('~/.claude/plugins')
# run.env is sourced by bash and split on '=' by python, and launch.sh sends these values unquoted.
UNQUOTED = re.compile(r'[\w@%+=:,./-]+')


def run(*cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        sys.exit(f'{" ".join(cmd)}: {p.stderr.strip() or p.returncode}')
    return p.stdout


def git(clone, *args):
    return run('git', '-C', clone, *args).strip()


def has_ref(clone, ref):
    return subprocess.run(['git', '-C', clone, 'show-ref', '--verify', '--quiet', ref]).returncode == 0


def settings():
    """config.py's values, and whether the base is the built-in default."""
    rows = [l.split('\t') for l in run(sys.executable, os.path.join(TOOLS, 'config.py')).splitlines()]
    values = {r[0]: r[1] for r in rows}
    return values, next(r[2] for r in rows if r[0] == 'base') == '(default)'


def read_repo(workspace):
    path = os.path.join(workspace, 'repo.json')
    try:
        repo = json.load(open(path))
    except (OSError, ValueError) as e:
        sys.exit(f'{path}: {e}')
    if not isinstance(repo, dict):
        sys.exit(f'{path}: not a JSON object')
    for k in ('github', 'clone', 'base_branch'):
        if not isinstance(repo.get(k), str) or not repo[k]:
            sys.exit(f'{path}: {k} is missing')
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo['github'], re.ASCII):
        sys.exit(f'{path}: github must be <owner>/<name> ({repo["github"]!r})')
    if not os.path.isabs(os.path.expanduser(repo['clone'])):
        sys.exit(f'{path}: clone must be an absolute path or start with ~ ({repo["clone"]!r})')
    repo['clone'] = os.path.realpath(os.path.expanduser(repo['clone']))
    git(repo['clone'], 'rev-parse', '--git-dir')
    return repo


def cmux_caller():
    """The cmux workspace and surface of this session. focused may be another window's."""
    p = subprocess.run(['cmux', 'identify'], capture_output=True, text=True, env={**os.environ, 'CMUX_QUIET': '1'})
    try:
        caller = json.loads(p.stdout)['caller']
        return caller['workspace_ref'], caller['surface_ref']
    except (ValueError, KeyError, TypeError):
        sys.exit(f'cmux identify: no calling surface; run this from the coordination surface ({p.stderr.strip()})')


def autoflow_version():
    """The installed AutoFlow, not the newest directory in the cache, which can differ."""
    path = os.path.join(PLUGINS, 'installed_plugins.json')
    try:
        entries = json.load(open(path))['plugins']['autoflow@autoflow']
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.exit(f'{path}: no installed AutoFlow ({e})')
    versions = {e.get('version') for e in entries}
    if len(versions) != 1:
        sys.exit(f'{path}: no single installed AutoFlow version ({sorted(map(str, versions))})')
    ver = versions.pop()
    # The directory launch.sh starts work sessions from.
    if not os.path.isfile(os.path.join(PLUGINS, 'cache/autoflow/autoflow', str(ver), '.claude-plugin/plugin.json')):
        sys.exit(f'no AutoFlow {ver} in {PLUGINS}/cache')
    return ver


def runbook(name, github, n, env, commit, base_branch, workspace):
    return f"""# 회차 기록: {name} ({github}#{n})

- 조율 세션: <session-id> ({env['CMUX_WORKSPACE']}, {env['COORD_SURFACE']})
- 레퍼런스: <레퍼런스>. 바꾼 점: <바꾼 점>
- 품질 목표: <품질 목표>
- 운영자 지시 원문: <지시>
- base: origin/{base_branch} {commit[:7]}, AutoFlow {env['AUTOFLOW_VER']}
- 경로: workspace {workspace}, worktree {env['CHECKOUT']}, 기록 폴더 {env['RECORDS']}
- 작업 branch: {env['BRANCH']}

## 진행 기록
| 세션 | 모듈 실행 | session-id | 시작 | 종료(감시 출력) | 판정 | 비고(재진입, 처분, 조율자가 만든 입력) |
|---|---|---|---|---|---|---|

## 운영자 지시 / 조율자 판단 / 결과 요약
"""


ap = argparse.ArgumentParser(description='Prepare one coordination run.')
ap.add_argument('workspace')
ap.add_argument('issue')
ap.add_argument('--key')
ap.add_argument('--base-confirmed', action='store_true')
args = ap.parse_args()

if not re.fullmatch(r'[1-9][0-9]*', args.issue):
    sys.exit(f'issue must be a number ({args.issue!r})')
if args.workspace in ('.', '..') or '/' in args.workspace:
    sys.exit(f'workspace must be a name under the base ({args.workspace!r})')
if args.key is not None and not re.fullmatch(r'[A-Za-z0-9._-]+', args.key):
    sys.exit(f'key must use only [A-Za-z0-9._-] ({args.key!r})')

config, base_is_default = settings()
if base_is_default and not args.base_confirmed:
    sys.exit(f'base {config["base"]} is the built-in default: confirm it with the operator, then pass --base-confirmed')
workspace = os.path.realpath(os.path.join(config['base'], args.workspace))
repo = read_repo(workspace)
cmux_workspace, coord_surface = cmux_caller()
autoflow_ver = autoflow_version()

key = args.key or f'{time.strftime("%Y-%m-%d-%H%M%S")}-{secrets.token_hex(4)}'
n, repo_name = args.issue, repo['github'].split('/')[1]
name = f'{repo_name}-{n}-{key}'
run_dir = os.path.join(config['runs'], name)
branch = f'issue-{n}-{key}'
env = {
    'RUN_KEY': key,
    'RUN_KEY_SOURCE': 'external' if args.key else 'self',
    'CMUX_WORKSPACE': cmux_workspace,
    'CHECKOUT': os.path.join(workspace, f'{repo_name}-wt-{n}-{key}'),
    'RECORDS': os.path.join(config['records'], name),
    'BRANCH': branch,
    'ISSUE': n,
    'COORD_SURFACE': coord_surface,
    'STATE': 'active',
    'AUTOFLOW_VER': autoflow_ver,
}
for k, v in env.items():
    if not UNQUOTED.fullmatch(v):
        sys.exit(f'{k} would not survive run.env unquoted ({v!r})')
if subprocess.run(['git', 'check-ref-format', f'refs/heads/{branch}']).returncode:
    sys.exit(f'{branch} is not a valid branch name; choose another key')

undo = []
try:
    os.makedirs(config['runs'], exist_ok=True)
    try:
        os.mkdir(run_dir)
    except FileExistsError:
        sys.exit(f'{run_dir} exists: the key is taken')
    undo.append(lambda: shutil.rmtree(run_dir))

    clone = repo['clone']
    git(clone, 'fetch', 'origin')
    commit = git(clone, 'rev-parse', '--verify', f'origin/{repo["base_branch"]}^{{commit}}')
    # Worktrees of one clone share refs, so a branch name in use would collide on checkout or push.
    for ref in (f'refs/heads/{branch}', f'refs/remotes/origin/{branch}'):
        if has_ref(clone, ref):
            sys.exit(f'{ref} exists in {clone}: choose another key')
    if os.path.exists(env['CHECKOUT']):
        sys.exit(f'{env["CHECKOUT"]} exists: a run does not reuse a worktree')
    git(clone, 'worktree', 'add', '--detach', env['CHECKOUT'], commit)
    undo.append(lambda: git(clone, 'worktree', 'remove', '--force', env['CHECKOUT']))

    os.makedirs(config['records'], exist_ok=True)
    os.mkdir(env['RECORDS'])
    undo.append(lambda: os.rmdir(env['RECORDS']))

    open(os.path.join(run_dir, 'sessions.tsv'), 'w').close()
    with open(os.path.join(run_dir, 'runbook.md'), 'w') as f:
        f.write(runbook(name, repo['github'], n, env, commit, repo['base_branch'], workspace))
    with open(os.path.join(run_dir, 'run.env'), 'w') as f:
        f.write(''.join(f'{k}={v}\n' for k, v in env.items()))
except BaseException:
    for u in reversed(undo):
        u()
    raise

print(f'RUN_DIR={run_dir}')
print(''.join(f'{k}={v}\n' for k, v in env.items()), end='')
