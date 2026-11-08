"""The approval key and the signature of an approval record, shared by approve.py and merge.py.

The approval key is an ed25519 SSH key the operator makes once with `tools/approve.py --init`, kept under the
coordination root as approval-key (private, encrypted with a passphrase) and approval-key.pub. A record is signed
with `ssh-keygen -Y sign` in the namespace NAMESPACE and verified with `ssh-keygen -Y verify` against
approval-key.pub, with the signer identity IDENTITY.
"""
import hashlib, os, subprocess, sys, tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
NAMESPACE = 'autoflow-approval'
IDENTITY = 'operator'
KEY_NAME = 'approval-key'
PLAN_NAME = 'merge-plan.json'


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
    """Raises Invalid unless record.sig is a signature of record by the key in pub."""
    sig = record + '.sig'
    if not os.path.isfile(sig):
        raise Invalid(f'{record} has no signature {sig}: the operator makes the record with tools/approve.py')
    try:
        fields = open(pub).read().split()
    except OSError as e:
        raise Invalid(f'{pub}: {e}: the operator makes the approval key with tools/approve.py --init')
    if len(fields) < 2:
        raise Invalid(f'{pub}: not a public key')
    with tempfile.NamedTemporaryFile('w', suffix='.signers', delete=False) as f:
        f.write(f'{IDENTITY} {fields[0]} {fields[1]}\n')
    try:
        with open(record, 'rb') as data:
            p = subprocess.run(['ssh-keygen', '-Y', 'verify', '-f', f.name, '-I', IDENTITY, '-n', NAMESPACE, '-s', sig],
                               stdin=data, capture_output=True, text=True)
    finally:
        os.remove(f.name)
    if p.returncode:
        raise Invalid(f'{record}: the signature does not verify against {pub} ({(p.stderr or p.stdout).strip()})')
