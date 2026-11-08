"""The approval key, the signature of an approval record, the plan's hash and the worktree-copy check, shared by the
tool that makes an approval record and the tool that acts on it.

The approval key is an ed25519 SSH key the operator makes once, kept under the
coordination root as approval-key (private, encrypted with a passphrase) and approval-key.pub. A record is signed
with `ssh-keygen -Y sign` in the namespace NAMESPACE and verified with `ssh-keygen -Y verify` against
approval-key.pub, with the signer identity IDENTITY.
"""
import fcntl, hashlib, json, os, subprocess, sys, tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
NAMESPACE = 'autoflow-approval'
IDENTITY = 'operator'
KEY_NAME = 'approval-key'
PLAN_NAME = 'merge-plan.json'
LOCK_NAME = 'merge.lock'


class Invalid(Exception):
    pass


def plan_of(workspace):
    """(sha256 hex of the workspace's merge-plan.json, its text), or (None, None) when there is none."""
    path = os.path.join(workspace, PLAN_NAME)
    if not os.path.exists(path):
        return None, None
    data = open(path, 'rb').read()
    return hashlib.sha256(data).hexdigest(), data.decode(errors='replace')


def refuse_copy_in(checkout, script):
    """Raises Invalid when script lies under the run's worktree: there it is the copy of the change under merge."""
    s, c = os.path.realpath(script), os.path.realpath(checkout)
    if s == c or s.startswith(c + os.sep):
        raise Invalid(f'{script} is inside the run\'s worktree {checkout}: run the coordination clone\'s tools, '
                      'not the copy of the change under merge')


def key_paths():
    """(private key, public key) under the coordination root."""
    p = subprocess.run([sys.executable, os.path.join(TOOLS, 'config.py'), KEY_NAME], capture_output=True, text=True)
    if p.returncode:
        raise Invalid(f'tools/config.py {KEY_NAME}: {p.stderr.strip()}')
    key = p.stdout.strip()
    return key, key + '.pub'


def encrypted(key):
    """Whether the private key needs a passphrase: ssh-keygen cannot read it with an empty one."""
    p = subprocess.run(['ssh-keygen', '-y', '-P', '', '-f', key], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, env=no_agent())
    return p.returncode != 0


def no_agent():
    """The environment for ssh-keygen: no agent and no askpass, so a passphrase comes from the terminal only."""
    env = {k: v for k, v in os.environ.items() if k not in ('SSH_AUTH_SOCK', 'SSH_ASKPASS', 'DISPLAY')}
    env['SSH_ASKPASS_REQUIRE'] = 'never'
    return env


def fingerprint(pub):
    p = subprocess.run(['ssh-keygen', '-l', '-f', pub], capture_output=True, text=True)
    if p.returncode:
        raise Invalid(f'{pub}: not a public key ({p.stderr.strip()})')
    return p.stdout.split()[1]


def verify(record, pub):
    """The bytes of record, read once, after checking that record.sig is a signature of exactly those bytes by the
    key in pub; raises Invalid otherwise. The caller parses these bytes, not the file again."""
    sig = record + '.sig'
    if not os.path.isfile(sig):
        raise Invalid(f'{record} has no signature {sig}: the operator makes the record with tools/approve.py')
    try:
        fields = open(pub).read().split()
        data = open(record, 'rb').read()
    except OSError as e:
        raise Invalid(f'{e}: the operator makes the approval key with tools/approve.py --init, and the record with tools/approve.py')
    if len(fields) < 2:
        raise Invalid(f'{pub}: not a public key')
    with tempfile.NamedTemporaryFile('w', suffix='.signers', delete=False) as f:
        f.write(f'{IDENTITY} {fields[0]} {fields[1]}\n')
    try:
        p = subprocess.run(['ssh-keygen', '-Y', 'verify', '-f', f.name, '-I', IDENTITY, '-n', NAMESPACE, '-s', sig],
                           input=data, capture_output=True)
    finally:
        os.remove(f.name)
    if p.returncode:
        raise Invalid(f'{record}: the signature does not verify against {pub} '
                      f'({(p.stderr or p.stdout).decode(errors="replace").strip()})')
    return data


def tag_conflict(plan_text, github, accepted_repos):
    """Why a decision cannot be carried out under this plan, or None: a plan with a tag tags the merge commit of
    the workspace repository's PR, so it admits at most one accepted PR of that repository."""
    if plan_text is None:
        return None
    try:
        plan = json.loads(plan_text)
    except ValueError:
        return None  # the merge refuses an unreadable plan on its own
    if not isinstance(plan, dict) or not plan.get('tag'):
        return None
    n = sum(r.lower() == github.lower() for r in accepted_repos)
    if n > 1:
        return (f'the merge plan tags the merge commit of the {github} PR, and the decision accepts {n} PRs of '
                f'{github}: accept one, or remove the tag from the plan')
    return None


def try_lock(run_dir):
    """The run's merge lock, held, or None when another process holds it. Held until the returned file closes."""
    lock = open(os.path.join(run_dir, LOCK_NAME), 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    return lock
