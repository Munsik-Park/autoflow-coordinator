#!/usr/bin/env python3
"""Tests of tools/criteria.py, the criteria block tool.

Run from the worktree root:

    python3 -m unittest discover -s tools -p 'test_*.py' -v

Standard library only; no network and no GitHub access. Every test runs the command itself,
`criteria.py <run-dir> read | seen | append`, as a subprocess, with a `gh` stand-in first in PATH. The
stand-in is this file run with --gh-standin: it emulates the `gh api` requests below over a state file
the test builds (issue body, edit history, comments) and logs every call. A test changes the issue
between calls by editing that state, as another writer would, or through a hook the stand-in applies
before or after its n-th request of a kind. Long waits are not slept: the command is started by a small
driver that replaces time.sleep for waits of 5 s or more and logs the seconds asked for.

What the tests take as the tool's interface:

- Commands: `read`; `seen <exact last line | none> [--drop <exact line>] ...`; `append --grounds <file>
  [--drop <exact line>] ... <spec> ...` with specs `--revise N <text> <reason>`, `--withdraw N <reason>`,
  `--add N <text> <reason>`. Exit status 0 on success, non-zero on a refusal or stop.
  `append --drop <line>` restores a missing accepted line: the call may proceed over a
  difference whose missing accepted lines it names, and `seen` drops a named line only after the
  restoring line is confirmed present in step 3.
- Standard output ends with one JSON object (it may be indented; it starts at a line start).
  `read`: {"block": bool, "last_line": str ("none" without a block),
           "effective": {N: text | null (withdrawn)},
           "lines": [{"line", "login" (null: no attribution), "trusted", "why", "operator"}, ...] in block order,
           "malformed": [{"line", "why"}],
           "difference": {"last_line": null | {"seen", "now"}, "new": [{"line", "login", "trusted", "own"}],
                          "missing": [line, one entry per missing copy], "changed": [N, ...]},
           "own": [{"line", "present"}], "history": {"read": int, "total": int}}
  `append`: {"lines": [{"line", "present"}],
             "overwritten": [{"editor", "time", "lines": [{"line", "present"}] (each block line the
                              overwritten version held, and whether it is present after the write)}]}.
  `seen` refuses when the block holds a line that the last `read` did not print.
- Lines are written as `<label> <text> — <reason> ([grounds](<comment URL>))`, a withdrawal as
  `<label> — <reason> ([grounds](<comment URL>))`; the block is `## Criteria`, `<!-- criteria -->`,
  the lines, `<!-- /criteria -->`.
- gh is called as `gh api ...`: `user`; `repos/<o>/<r>/issues/<n>` (GET, PATCH with the body as a field
  or --input); `repos/<o>/<r>/issues/<n>/comments` (POST); `repos/<o>/<r>/issues/comments/<id>` (GET);
  `graphql`, answered as {"data": {"repository": {"issue": {...}}}} with `userContentEdits` paged by
  `first:` and `after:`. Flags: -X/--method, -f/--raw-field, -F/--field (with @file and @-), --input,
  -H/--header, --silent. The 60-100 s wait goes through time.sleep.

The run directory is <tmp>/root/runs/<name>, run.env names CHECKOUT (a worktree in the workspace
<tmp>/base/ws, which holds repo.json) and ISSUE, and HOME is <tmp>/home, whose coordination.json sets
the root to <tmp>/root. Temporary directories come from tempfile, so TMPDIR places them.
"""
import json, os, re, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, 'criteria.py')
THIS = os.path.abspath(__file__)
ACCT, OTHER = 'acct', 'other'
REPO, NUMBER = 'o/r', 7
DASH = ' — '
CREATED = '2026-01-01T00:00:00Z'
START, END = '<!-- criteria -->', '<!-- /criteria -->'
PROSE = 'Prose of the issue.\n'
FAIL_MSG = 'stand-in failure (HTTP 502)'


# ---------------------------------------------------------------------------------------------------------
# The gh stand-in (run as: python3 -I test_criteria.py --gh-standin <gh args>)

class StandinError(Exception):
    pass


def _time(state):
    state['clock'] += 1
    c = state['clock']
    return '2026-01-02T%02d:%02d:%02dZ' % (c // 3600 % 24, c // 60 % 60, c % 60)


def _current(state):
    return state['edits'][-1]['body'] if state['edits'] else state['original']


def _set_body(state, login, body, **flags):
    if body == _current(state):
        return
    edit = {'body': body, 'editor': login, 'at': _time(state), 'deleted': False, 'hidden': False}
    edit.update(flags)
    state['edits'].append(edit)


def _insert_line(body, line):
    i = body.index('\n' + END)
    return body[:i] + '\n' + line + body[i:]


def _apply(state, hook, before_patch):
    login = hook.get('login', state['account'])
    body = _current(state)
    if hook.get('revert'):
        body = before_patch
    if 'set_body' in hook:
        body = hook['set_body']
    if 'replace' in hook:
        old, new = hook['replace']
        if old not in body:
            raise StandinError('stand-in hook: %r not in body' % old)
        body = body.replace(old, new, 1)
    if 'remove_line' in hook:
        lines = body.split('\n')
        lines.remove(hook['remove_line'])
        body = '\n'.join(lines)
    if 'append_line' in hook:
        body = _insert_line(body, hook['append_line'])
    _set_body(state, login, body)


def _typed(value):
    if value.startswith('@'):
        src = value[1:]
        return sys.stdin.read() if src == '-' else open(src).read()
    if value in ('true', 'false'):
        return value == 'true'
    if value == 'null':
        return None
    if re.fullmatch(r'-?[0-9]+', value):
        return int(value)
    return value


def _parse(argv):
    if not argv or argv[0] != 'api':
        raise StandinError('stand-in: only "gh api" is emulated, got %r' % (argv,))
    method, fields, endpoint, silent = None, {}, None, False
    i = 1
    while i < len(argv):
        a = argv[i]
        flag, eq, inline = a.partition('=') if a.startswith('--') else (a, '', '')
        val = inline if eq else (argv[i + 1] if i + 1 < len(argv) else None)
        step = 1 if eq else 2
        if flag in ('-X', '--method'):
            method = val.upper()
        elif flag in ('-f', '--raw-field', '-F', '--field'):
            k, _, v = val.partition('=')
            fields[k] = _typed(v) if flag in ('-F', '--field') else v
        elif flag in ('-H', '--header'):
            pass
        elif flag == '--input':
            data = sys.stdin.read() if val == '-' else open(val).read()
            obj = json.loads(data)
            if isinstance(obj.get('variables'), dict):
                fields.update(obj.pop('variables'))
            fields.update(obj)
        elif flag == '--silent':
            silent, step = True, 1
        elif a.startswith('-'):
            raise StandinError('stand-in: unsupported flag %s' % a)
        else:
            endpoint, step = a.lstrip('/'), 1
        i += step
    if endpoint is None:
        raise StandinError('stand-in: no endpoint')
    if method is None:
        method = 'POST' if fields else 'GET'
    return method, endpoint.split('?')[0], fields, silent


def _kind(state, method, endpoint):
    repo = re.escape(state['repo'])
    if endpoint == 'user' and method == 'GET':
        return 'user', None
    if endpoint == 'graphql':
        return 'graphql', None
    if re.fullmatch(r'repos/%s/issues/%d' % (repo, state['number']), endpoint, re.I):
        return {'GET': 'get_issue', 'PATCH': 'patch_issue'}.get(method, 'unsupported'), None
    if re.fullmatch(r'repos/%s/issues/%d/comments' % (repo, state['number']), endpoint, re.I) and method == 'POST':
        return 'post_comment', None
    m = re.fullmatch(r'repos/%s/issues/comments/([0-9]+)' % repo, endpoint, re.I)
    if m and method == 'GET':
        return 'get_comment', m.group(1)
    return 'unsupported', None


def _comment_json(state, c):
    return {'id': c['id'], 'body': c['body'], 'user': {'login': c['login']},
            'issue_url': 'https://api.github.com/repos/%s/issues/%d' % (state['repo'], c['issue']),
            'html_url': 'https://github.com/%s/issues/%d#issuecomment-%d' % (state['repo'], c['issue'], c['id']),
            'created_at': c['at']}


def _issue_json(state):
    return {'number': state['number'], 'title': 'Issue', 'body': _current(state),
            'user': {'login': state['author']}, 'created_at': state['created'],
            'url': 'https://api.github.com/repos/%s/issues/%d' % (state['repo'], state['number']),
            'html_url': 'https://github.com/%s/issues/%d' % (state['repo'], state['number'])}


def _nodes(state):
    """All history nodes newest first, as (node, hidden)."""
    opt = state['options']
    if not state['edits']:
        return []
    out = []
    for e in reversed(state['edits']):
        out.append(({'diff': None if e['deleted'] else e['body'], 'editedAt': e['at'],
                     'editor': {'login': e['editor']}, 'deletedAt': e['at'] if e['deleted'] else None},
                    e['hidden']))
    if not opt.get('no_created_edit'):
        out.append(({'diff': state['original'], 'editedAt': opt.get('created_node_at') or state['created'],
                     'editor': {'login': state['author']}, 'deletedAt': None}, False))
    if opt.get('newest_diff') is not None:
        out[0][0]['diff'] = opt['newest_diff']
    return out


def _graphql(state, fields):
    query = fields.get('query', '')
    after = None
    for k, v in fields.items():
        if k != 'query' and isinstance(v, str) and re.fullmatch(r'c[0-9]+', v):
            after = v
    m = re.search(r'after:\s*"(c[0-9]+)"', query)
    if m:
        after = m.group(1)
    first = fields.get('first') if isinstance(fields.get('first'), int) else None
    m = re.search(r'first:\s*([0-9]+)', query)
    if first is None and m:
        first = int(m.group(1))
    if first is None:
        first = 20
    allnodes = _nodes(state)
    visible = [n for n, hidden in allnodes if not hidden]
    offset = int(after[1:]) if after else 0
    page = visible[offset:offset + first]
    end = offset + len(page)
    has_next = end < len(visible)
    cursor = 'c%d' % end
    if state['options'].get('stuck_cursor') and after:
        cursor, has_next = after, True
    opt = state['options']
    issue = {'body': opt['graphql_body'] if opt.get('graphql_body') is not None else _current(state),
             'author': {'login': state['author']}, 'createdAt': state['created'],
             'includesCreatedEdit': bool(state['edits']) and not opt.get('no_created_edit'),
             'userContentEdits': {'totalCount': len(allnodes),
                                  'pageInfo': {'hasNextPage': has_next, 'endCursor': cursor},
                                  'nodes': page}}
    return {'data': {'repository': {'issue': issue}}}


def standin(argv):
    path = os.environ['GH_STANDIN_STATE']
    with open(path) as f:
        state = json.load(f)
    code, out = 0, None
    try:
        method, endpoint, fields, silent = _parse(argv)
        kind, arg = _kind(state, method, endpoint)
        state['log'].append([kind, argv])
        n = state['counts'][kind] = state['counts'].get(kind, 0) + 1
        hooks = [h for h in state['hooks'] if h['kind'] == kind and h['nth'] in (n, 'all')]
        for h in hooks:
            if h['when'] == 'before':
                if h.get('fail'):
                    raise StandinError(h['fail'])
                _apply(state, h, None)
        before_patch = _current(state)
        if kind == 'user':
            out = {} if state['account'] is None else {'login': state['account']}
        elif kind == 'get_issue':
            out = _issue_json(state)
        elif kind == 'patch_issue':
            if not isinstance(fields.get('body'), str):
                raise StandinError('stand-in: PATCH without a body field')
            _set_body(state, state['account'], fields['body'])
            out = _issue_json(state)
        elif kind == 'post_comment':
            cid = state['next_id']
            state['next_id'] += 1
            state['comments'][str(cid)] = {'id': cid, 'body': fields.get('body', ''), 'login': state['account'],
                                           'issue': state['number'], 'at': _time(state)}
            out = _comment_json(state, state['comments'][str(cid)])
        elif kind == 'get_comment':
            c = state['comments'].get(arg)
            if c is None:
                raise StandinError('Not Found (HTTP 404)')
            out = _comment_json(state, c)
        elif kind == 'graphql':
            out = _graphql(state, fields)
        else:
            raise StandinError('stand-in: unsupported request %s %s' % (method, endpoint))
        for h in hooks:
            if h['when'] == 'after':
                _apply(state, h, before_patch)
        if silent:
            out = None
    except StandinError as e:
        sys.stderr.write('gh: %s\n' % e)
        out, code = {'message': str(e)}, 1
    with open(path, 'w') as f:
        json.dump(state, f)
    if out is not None:
        sys.stdout.write(json.dumps(out) + '\n')
    sys.exit(code)


# ---------------------------------------------------------------------------------------------------------
# Test environment

DRIVER = r'''
import os, runpy, sys, time
log, tool = sys.argv[1], sys.argv[2]
real = time.sleep
def sleep(s):
    if s >= 5:
        with open(log, 'a') as f:
            f.write(repr(float(s)) + '\n')
        return
    real(s)
time.sleep = sleep
sys.argv = [tool] + sys.argv[3:]
sys.path.insert(0, os.path.dirname(tool))
runpy.run_path(tool, run_name='__main__')
'''


def last_json(text):
    s = text.rstrip()
    dec = json.JSONDecoder()
    for m in re.finditer(r'(?m)^[{]', s):
        try:
            obj, end = dec.raw_decode(s, m.start())
        except ValueError:
            continue
        if end == len(s):
            return obj
    return None


def has_string(obj, s):
    if isinstance(obj, str):
        return obj == s
    if isinstance(obj, dict):
        return any(has_string(v, s) for v in obj.values())
    if isinstance(obj, list):
        return any(has_string(v, s) for v in obj)
    return False


class Result:
    def __init__(self, p):
        self.code, self.out, self.err = p.returncode, p.stdout, p.stderr
        self.json = last_json(p.stdout)

    def __repr__(self):
        return 'exit %s\n--- stdout\n%s\n--- stderr\n%s' % (self.code, self.out[-3000:], self.err[-3000:])


class Base(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.assertTrue(os.path.isfile(TOOL), 'tools/criteria.py does not exist')
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='criteria-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        t = self.tmp
        self.home = os.path.join(t, 'home')
        self.root = os.path.join(t, 'root')
        os.makedirs(os.path.join(self.home, '.autoflow'))
        with open(os.path.join(self.home, '.autoflow', 'coordination.json'), 'w') as f:
            json.dump({'root': self.root, 'base': os.path.join(t, 'base')}, f)
        ws = os.path.join(t, 'base', 'ws')
        self.checkout = os.path.join(ws, 'r-wt-7-key')
        os.makedirs(self.checkout)
        with open(os.path.join(ws, 'repo.json'), 'w') as f:
            json.dump({'github': REPO, 'base_branch': 'main', 'clone': os.path.join(ws, 'r')}, f)
        self.run_name = 'r-7-key'
        self.run_dir = os.path.join(self.root, 'runs', self.run_name)
        os.makedirs(self.run_dir)
        os.makedirs(os.path.join(self.root, 'records', self.run_name))
        with open(os.path.join(self.run_dir, 'run.env'), 'w') as f:
            f.write(''.join('%s=%s\n' % kv for kv in [
                ('RUN_KEY', 'key'), ('CHECKOUT', self.checkout),
                ('RECORDS', os.path.join(self.root, 'records', self.run_name)),
                ('BRANCH', 'issue-7-key'), ('ISSUE', str(NUMBER)), ('STATE', 'active')]))
        bindir = os.path.join(t, 'bin')
        os.makedirs(bindir)
        gh = os.path.join(bindir, 'gh')
        with open(gh, 'w') as f:
            f.write('#!/bin/sh\nexec "%s" -I "%s" --gh-standin "$@"\n' % (sys.executable, THIS))
        os.chmod(gh, 0o755)
        self.state_path = os.path.join(t, 'gh-state.json')
        self.sleeplog = os.path.join(t, 'sleeps.log')
        self.grounds = os.path.join(t, 'grounds.md')
        self.set_grounds('The criterion did not hold. Check: criteria.py read gave block true. Details: run record.')
        self.save({'account': ACCT, 'repo': REPO, 'number': NUMBER, 'author': ACCT, 'created': CREATED,
                   'original': '', 'edits': [], 'comments': {}, 'next_id': 1000, 'clock': 0,
                   'counts': {}, 'hooks': [], 'log': [], 'options': {}})
        env = {k: v for k, v in os.environ.items() if not k.startswith(('GH_', 'GITHUB_'))}
        env.update({'PATH': bindir + os.pathsep + os.environ.get('PATH', ''), 'HOME': self.home,
                    'GH_TOKEN': 'stand-in-token', 'GH_STANDIN_STATE': self.state_path,
                    'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': t})
        env.pop('PYTHONPYCACHEPREFIX', None)
        self.env = env

    # --- state of the emulated issue

    def load(self):
        with open(self.state_path) as f:
            return json.load(f)

    def save(self, s):
        with open(self.state_path, 'w') as f:
            json.dump(s, f)

    def change(self, fn):
        s = self.load()
        fn(s)
        self.save(s)

    def issue(self, body, author=ACCT):
        self.change(lambda s: s.update(original=body, author=author))

    def edit(self, login, body, **flags):
        self.change(lambda s: _set_body(s, login, body, **flags))

    def mark(self, index, **flags):
        """Set flags (deleted, hidden) on edit number index (0 = oldest edit)."""
        self.change(lambda s: s['edits'][index].update(flags))

    def option(self, **kw):
        self.change(lambda s: s['options'].update(kw))

    def hook(self, kind, nth, when, **kw):
        h = dict(kind=kind, nth=nth, when=when, **kw)
        self.change(lambda s: s['hooks'].append(h))

    def body(self):
        return _current(self.load())

    def calls(self, kind):
        return sum(1 for k, _ in self.load()['log'] if k == kind)

    def kinds(self):
        return [k for k, _ in self.load()['log']]

    def comment(self, login=ACCT, issue=NUMBER, body='Grounds.'):
        s = self.load()
        cid = s['next_id']
        s['next_id'] += 1
        s['comments'][str(cid)] = {'id': cid, 'body': body, 'login': login, 'issue': issue, 'at': CREATED}
        self.save(s)
        return cid

    def posted(self):
        s = self.load()
        return [c['body'] for _, c in sorted(s['comments'].items(), key=lambda kv: int(kv[0]))
                if c['login'] == ACCT and c['at'] != CREATED]

    # --- lines and bodies

    @staticmethod
    def url(cid, issue=NUMBER):
        return 'https://github.com/%s/issues/%d#issuecomment-%d' % (REPO, issue, cid)

    def L(self, label, text, reason='r', cid=None):
        """A linked line, with a grounds comment by the account unless cid is given."""
        if cid is None:
            cid = self.comment()
        head = '`%s.`' % label
        tail = '%s ([grounds](%s))' % (reason, self.url(cid))
        return '%s %s%s%s' % (head, text, DASH, tail) if text else '%s%s%s' % (head, DASH, tail)

    @staticmethod
    def op(label, text=''):
        """An operator line: no link."""
        return ('`%s.` %s' % (label, text)) if text else '`%s.`' % label

    @staticmethod
    def block(lines, prose=PROSE):
        return '%s\n## Criteria\n\n%s\n%s\n%s\n' % (prose, START, '\n'.join(lines), END)

    def set_grounds(self, text):
        with open(self.grounds, 'w') as f:
            f.write(text)

    # --- running the command

    def run_tool(self, *args, timeout=120):
        p = subprocess.run([sys.executable, '-c', DRIVER, self.sleeplog, TOOL, self.run_dir, *args],
                           env=self.env, cwd=self.tmp, capture_output=True, text=True, timeout=timeout)
        return Result(p)

    def read(self):
        r = self.run_tool('read')
        self.assertEqual(r.code, 0, r)
        self.assertIsInstance(r.json, dict, r)
        return r.json

    def seen(self, last, *drops, ok=True):
        args = ['seen', last]
        for d in drops:
            args += ['--drop', d]
        r = self.run_tool(*args)
        if ok is True:
            self.assertEqual(r.code, 0, r)
        elif ok is False:
            self.assertNotEqual(r.code, 0, r)
        return r

    def append(self, *specs, drops=(), ok=True):
        args = ['append', '--grounds', self.grounds]
        for d in drops:
            args += ['--drop', d]
        r = self.run_tool(*args, *specs)
        if ok is True:
            self.assertEqual(r.code, 0, r)
            self.assertIsInstance(r.json, dict, r)
        elif ok is False:
            self.assertNotEqual(r.code, 0, r)
        return r

    def refused_before_posting(self, *specs, drops=()):
        posts, patches = self.calls('post_comment'), self.calls('patch_issue')
        r = self.append(*specs, drops=drops, ok=False)
        self.assertEqual(self.calls('post_comment'), posts, 'a comment was posted\n%r' % r)
        self.assertEqual(self.calls('patch_issue'), patches, 'the body was written\n%r' % r)
        return r

    def sleeps(self):
        if not os.path.exists(self.sleeplog):
            return []
        return [float(x) for x in open(self.sleeplog).read().split()]

    # --- reading the report

    @staticmethod
    def eff(report):
        return {int(k): v for k, v in report['effective'].items()}

    @staticmethod
    def entries(report, line):
        return [d for d in report['lines'] if d['line'] == line]

    def entry(self, report, line):
        found = self.entries(report, line)
        self.assertEqual(len(found), 1, 'line %r in %r' % (line, report['lines']))
        return found[0]

    @staticmethod
    def new(report):
        return [d['line'] for d in report['difference']['new']]

    @staticmethod
    def changed(report):
        return {int(n) for n in report['difference']['changed']}

    @staticmethod
    def malformed(report):
        return [d['line'] for d in report['malformed']]

    def assert_no_difference(self, report):
        d = report['difference']
        self.assertIsNone(d['last_line'], d)
        self.assertEqual(d['new'], [], d)
        self.assertEqual(d['missing'], [], d)
        self.assertEqual(list(d['changed']), [], d)

    def own_lines(self, report):
        return [d['line'] for d in report['own']]

    # --- the starting state of the S and E tests: lines 1., 2., 2-1. by the account, accepted

    def base_seen(self):
        self.L1, self.L2, self.L21 = self.L('1', 'a'), self.L('2', 'b'), self.L('2-1', 'c')
        self.issue(PROSE)
        self.edit(ACCT, self.block([self.L1, self.L2, self.L21]))
        r = self.read()
        self.assertEqual(self.eff(r), {1: 'a', 2: 'c'})
        self.seen(self.L21)
        self.assert_no_difference(self.read())


# ---------------------------------------------------------------------------------------------------------
# Effective-criteria parsing (all lines trusted: an issue written by the account, never edited)

class Parsing(Base):
    def test_P1_revision(self):
        self.issue(self.block([self.op('1', 'a'), self.L('1-1', 'b')]))
        r = self.read()
        self.assertTrue(r['block'])
        self.assertEqual(self.eff(r), {1: 'b'})

    def test_P2_withdrawal(self):
        l12 = self.L('1-2', '')
        self.issue(self.block([self.op('1', 'a'), l12, self.op('2', 'b'), self.op('2-1'), self.op('3')]))
        r = self.read()
        self.assertEqual(self.eff(r), {1: None, 2: None})
        self.assertEqual(self.malformed(r), ['`3.`'])

    def test_P3_addition(self):
        self.issue(self.block([self.op('4', 'd'), self.L('5-1', 'e')]))
        r = self.read()
        self.assertEqual(self.eff(r), {4: 'd', 5: 'e'})
        self.assertEqual(r['malformed'], [])

    def test_P4_gaps_in_k(self):
        self.issue(self.block([self.op('3', 'a'), self.L('3-1', 'b'), self.L('3-4', 'c')]))
        r = self.read()
        self.assertEqual(self.eff(r), {3: 'c'})
        self.assertEqual(r['malformed'], [])

    def test_P5_order(self):
        l32, l3b = self.L('3-2', 'd'), self.op('3', 'e')
        self.issue(self.block([self.op('3', 'a'), self.L('3-1', 'b'), self.L('3-4', 'c'), l32, l3b]))
        r = self.read()
        self.assertEqual(self.eff(r), {3: 'c'})
        self.assertEqual(sorted(self.malformed(r)), sorted([l32, l3b]))

    def test_P6_reading(self):
        cid = self.comment()
        linked = '`1-1.` x%sy%sr ([grounds](%s))' % (DASH, DASH, self.url(cid))
        operator = '`2-1.` p%sq' % DASH
        cid2 = self.comment()
        plain = '3-1. u%sr ([grounds](%s))' % (DASH, self.url(cid2))
        inside = 'not a criterion line'
        prose = 'Intro.\n1. outside before\n'
        lines = [self.op('1', 'a'), linked, self.op('2', 'b'), operator, '3. t', plain, inside, '`4.` last']
        body = self.block(lines, prose=prose) + '9. outside after\n'
        self.issue(body.replace('\n', '\r\n'))
        r = self.read()
        self.assertEqual(self.eff(r), {1: 'x' + DASH + 'y', 2: 'p' + DASH + 'q', 3: 'u', 4: 'last'})
        self.assertEqual(self.malformed(r), [inside])
        self.assertEqual(r['last_line'], '`4.` last')
        self.assertNotIn('1. outside before', [d['line'] for d in r['lines']])
        self.assertNotIn('9. outside after', [d['line'] for d in r['lines']])
        for d in r['lines']:
            self.assertFalse(d['line'].endswith('\r'), d)


# ---------------------------------------------------------------------------------------------------------
# Composition, refusals and stops

LINE_RE = r'`%s\.` %s' + re.escape(DASH) + r'%s \(\[grounds\]\(https://github\.com/o/r/issues/7#issuecomment-[0-9]+\)\)'


class Composition(Base):
    def test_C1_k_above_every_earlier_k(self):
        self.issue(PROSE)
        self.edit(ACCT, self.block([self.op('3', 'a'), self.L('3-1', 'b')]))
        self.edit(OTHER, _insert_line(self.body(), self.op('3-4', 'q')))
        r = self.read()
        self.seen(r['last_line'])
        a = self.append('--revise', '3', 'y', 'why')
        own = [d['line'] for d in a.json['lines']]
        self.assertEqual(len(own), 1, a)
        self.assertRegex(own[0], '^' + LINE_RE % ('3-5', 'y', 'why') + '$')
        self.assertEqual(self.eff(self.read())[3], 'y')

    def test_C2_seeding(self):
        for original in ('', 'Intro line.\n\nMore text.\n'):
            with self.subTest(original=original):
                self.setUp()
                self.issue(original)
                r = self.read()
                self.assertFalse(r['block'])
                self.assertEqual(r['last_line'], 'none')
                self.assertEqual(r['effective'], {})
                self.append('--add', '1', 'a', 'seed', '--add', '2', 'b', 'seed', '--add', '4', 'd', 'seed')
                body = self.body()
                self.assertTrue(body.startswith(original), body)
                rest = body[len(original):]
                self.assertIn('## Criteria', rest)
                lines = rest.split('\n')
                i, j = lines.index(START), lines.index(END)
                self.assertEqual(len(lines[i + 1:j]), 3, rest)
                for line, (n, t) in zip(lines[i + 1:j], [('1', 'a'), ('2', 'b'), ('4', 'd')]):
                    self.assertRegex(line, '^' + LINE_RE % (n, t, 'seed') + '$')
                self.assertEqual(self.eff(self.read()), {1: 'a', 2: 'b', 4: 'd'})
                self.refused_before_posting('--add', '2', 'again', 'r')
                self.refused_before_posting('--revise', '3', 'x', 'r')

    def test_C4_markers(self):
        good = [self.op('1', 'a')]
        bodies = {
            'two starts': self.block(good).replace(START, START + '\n' + START),
            'two ends': self.block(good).replace(END, END + '\n' + END),
            'end before start': '%s\n%s\n%s\n%s\n' % (PROSE, END, good[0], START),
        }
        for name, body in bodies.items():
            with self.subTest(name):
                self.setUp()
                self.issue(body)
                r = self.refused_before_posting('--revise', '1', 'b', 'r')
                self.assertIn('marker', r.err.lower(), r)

    def _withdrawn_base(self):
        self.issue(PROSE)
        self.edit(ACCT, self.block([self.op('1', 'a'), self.op('2', 'b'), self.L('2-1', '')]))
        self.edit(OTHER, _insert_line(self.body(), self.op('5', 'q')))
        self.seen(self.read()['last_line'])

    def test_C5_refusals(self):
        cases = {
            'line break in text': ('--revise', '1', 'x\ny', 'r'),
            'line break in reason': ('--revise', '1', 'x', 'r\ns'),
            'dash in reason': ('--revise', '1', 'x', 'r' + DASH + 's'),
            'empty reason': ('--revise', '1', 'x', ''),
            'revise of an unused number': ('--revise', '8', 'x', 'r'),
            'withdraw of an unused number': ('--withdraw', '8', 'r'),
            'withdraw of a withdrawn number': ('--withdraw', '2', 'r'),
            'add of a used number': ('--add', '1', 'x', 'r'),
            'add of a number only another login uses': ('--add', '5', 'x', 'r'),
        }
        for name, spec in cases.items():
            with self.subTest(name):
                self.setUp()
                self._withdrawn_base()
                self.refused_before_posting(*spec)

    def test_C7_restart_conflict_same_number(self):
        self.base_seen()
        other = self.op('1-1', 'theirs')
        self.hook('post_comment', 1, 'after', login=ACCT, append_line=other)
        r = self.append('--revise', '1', 'mine', 'r', ok=False)
        self.assertEqual(self.calls('patch_issue'), 0, r)
        self.assertIn(other, self.body())

    def test_C7_restart_other_number_goes_after(self):
        self.base_seen()
        other = self.op('3', 'theirs')
        self.hook('post_comment', 1, 'after', login=ACCT, append_line=other)
        a = self.append('--revise', '1', 'mine', 'r')
        mine = a.json['lines'][0]['line']
        self.assertTrue(a.json['lines'][0]['present'], a)
        lines = self.body().split('\n')
        self.assertLess(lines.index(other), lines.index(mine))
        self.assertEqual(self.calls('patch_issue'), 1)

    def test_C8_specs(self):
        self.base_seen()
        self.refused_before_posting('--revise', '1', 'x', 'r', '--revise', '1', 'y', 'r')
        self.refused_before_posting('--revise', '1', 'x', 'r', '--withdraw', '1', 'r')
        a = self.append('--revise', '2', 'x', 'r2', '--revise', '1', 'y', 'r1')
        own = [d['line'] for d in a.json['lines']]
        self.assertEqual(len(own), 2, a)
        self.assertRegex(own[0], '^' + LINE_RE % ('2-2', 'x', 'r2') + '$')
        self.assertRegex(own[1], '^' + LINE_RE % ('1-1', 'y', 'r1') + '$')
        lines = self.body().split('\n')
        self.assertEqual(lines.index(own[0]) + 1, lines.index(own[1]))
        urls = {re.search(r'\((https://[^)]+)\)\)$', l).group(1) for l in own}
        self.assertEqual(len(urls), 1, 'one call, one grounds comment')
        self.assertEqual(self.calls('patch_issue'), 1, 'one call, one write')

    def test_C9_revise_a_number_whose_lines_are_all_untrusted(self):
        self.base_seen()
        self.edit(OTHER, _insert_line(self.body(), self.op('6-3', 'x')))
        self.seen(self.read()['last_line'])
        a = self.append('--revise', '6', 'y', 'adopt')
        self.assertRegex(a.json['lines'][0]['line'], '^' + LINE_RE % ('6-4', 'y', 'adopt') + '$')
        r = self.read()
        self.assertTrue(self.entry(r, a.json['lines'][0]['line'])['trusted'])
        self.assertEqual(self.eff(r)[6], 'y')
        self.refused_before_posting('--revise', '8', 'z', 'r')
        self.refused_before_posting('--withdraw', '8', 'r')

    def test_C10_text_starting_with_the_separator(self):
        cases = {
            'revise': ('--revise', '1', DASH.lstrip() + 'keep the audit trail', 'clarification'),
            'add': ('--add', '3', DASH.lstrip() + 'new', 'r'),
        }
        for name, spec in cases.items():
            with self.subTest(name):
                self.setUp()
                self.base_seen()
                self.refused_before_posting(*spec)
                self.assert_no_difference(self.read())

    def test_C11_written_lines_read_back_as_their_spec(self):
        """Each spec form either is refused before posting or is written as a line that reads back as it:
        its number and k, the withdrawal, the text, the reason and the grounds link."""
        sep = DASH.strip()
        cases = [
            ('revise', '1', 'plain text', 'r', True),
            ('withdraw', '1', None, 'r', True),
            ('add', '3', 'plain text', 'r', True),
            ('revise', '1', 'a' + DASH + 'b', 'r', False),
            ('add', '3', 'a' + DASH + 'b', 'r', False),
            ('revise', '1', 'x' + DASH.rstrip(), 'r', False),
            ('revise', '1', sep + ' lead', 'r', False),
            ('add', '3', sep + ' lead', 'r', False),
            ('revise', '1', sep, 'r', False),
            ('add', '3', sep, 'r', False),
        ]
        labels = {'revise': '1-1', 'withdraw': '1-1', 'add': '3'}
        for kind, n, text, reason, must_write in cases:
            with self.subTest(kind=kind, text=text):
                self.setUp()
                self.base_seen()
                spec = ('--' + kind, n) + (() if text is None else (text,)) + (reason,)
                posts, patches = self.calls('post_comment'), self.calls('patch_issue')
                a = self.append(*spec, ok=None)
                if a.code != 0 and not must_write:
                    self.assertEqual(self.calls('post_comment'), posts, 'refused after posting\n%r' % a)
                    self.assertEqual(self.calls('patch_issue'), patches, 'refused after writing\n%r' % a)
                    continue
                self.assertEqual(a.code, 0, a)
                mine = a.json['lines'][0]['line']
                cid = self.load()['next_id'] - 1
                want = '`%s.`%s%s ([grounds](%s))' % (
                    labels[kind], DASH if text is None else ' ' + text + DASH, reason, self.url(cid))
                self.assertEqual(mine, want)
                r = self.read()
                self.assertEqual(r['malformed'], [], r)
                self.assertEqual(self.eff(r)[int(n)], text, r)
                self.assertTrue(self.entry(r, mine)['trusted'], r)


# ---------------------------------------------------------------------------------------------------------
# Presence

class Presence(Base):
    def _written(self):
        self.base_seen()
        a = self.append('--revise', '1', 'y', 'r')
        self.assertEqual(a.json['lines'], [{'line': a.json['lines'][0]['line'], 'present': True}])
        return a.json['lines'][0]['line']

    def test_R1_present(self):
        mine = self._written()
        self.assertEqual(self.read()['own'], [{'line': mine, 'present': True}])

    def test_R2_absent(self):
        mine = self._written()
        self.edit(OTHER, self.body().replace(mine, mine.replace(' y ', ' y  ')))
        self.assertEqual(self.read()['own'], [{'line': mine, 'present': False}])
        self.edit(OTHER, self.body().replace(mine.replace(' y ', ' y  ') + '\n', ''))
        self.assertNotIn(mine, self.body())
        self.assertEqual(self.read()['own'], [{'line': mine, 'present': False}])

    def test_R3_crlf(self):
        mine = self._written()
        self.edit(ACCT, self.body().replace('\n', '\r\n'))
        self.assertEqual(self.read()['own'], [{'line': mine, 'present': True}])


# ---------------------------------------------------------------------------------------------------------
# The accepted state and the comparison

class Accepted(Base):
    def test_S1_append_stops_on_a_new_line(self):
        self.base_seen()
        new = self.op('3', 'z')
        self.edit(ACCT, _insert_line(self.body(), new))
        r = self.refused_before_posting('--revise', '1', 'y', 'r')
        self.assertIn(new, r.out + r.err)

    def test_S2_seen_advances_over_own_lines(self):
        self.base_seen()
        a = self.append('--revise', '1', 'y', 'r')
        mine = a.json['lines'][0]['line']
        self.assertRegex(mine, '^' + LINE_RE % ('1-1', 'y', 'r') + '$')
        r = self.read()
        self.assert_no_difference(r)
        self.assertEqual(r['last_line'], mine)
        self.assertEqual(self.eff(r), {1: 'y', 2: 'c'})
        kinds = self.kinds()
        self.assertLess(kinds.index('post_comment'), kinds.index('patch_issue'), 'comment before line')
        waits = self.sleeps()
        self.assertTrue(waits, 'no step-3 wait was asked for')
        for w in waits:
            self.assertTrue(60 <= w <= 100, 'wait %s outside [60, 100]' % w)

    def test_S3_another_writers_line_is_not_marked_seen(self):
        self.base_seen()
        other = self.op('3', 'z')
        self.hook('post_comment', 1, 'after', login=ACCT, append_line=other)
        a = self.append('--revise', '1', 'y', 'r')
        mine = a.json['lines'][0]['line']
        r = self.read()
        new = {d['line']: d for d in r['difference']['new']}
        self.assertIn(other, new)
        self.assertFalse(new[other]['own'])
        if mine in new:
            self.assertTrue(new[mine]['own'])
        self.assertIsNotNone(r['difference']['last_line'])

    def test_S4_seen_takes_the_current_last_line(self):
        self.base_seen()
        new = self.op('3', 'z')
        self.edit(ACCT, _insert_line(self.body(), new))
        self.seen(self.L21, ok=False)
        self.assertIn(new, self.new(self.read()))
        self.seen(new)
        r = self.read()
        self.assert_no_difference(r)
        self.assertTrue(self.entry(r, new)['trusted'])
        self.assertEqual(self.eff(r), {1: 'a', 2: 'c', 3: 'z'})

    def test_S6_drop_must_match_a_missing_line(self):
        self.base_seen()
        self.edit(OTHER, self.body().replace(self.L1 + '\n', ''))
        self.seen(self.L21, self.L2, ok=False)
        self.seen(self.L21, self.op('9', 'never'), ok=False)
        self.assertEqual(self.read()['difference']['missing'], [self.L1])

    def test_S7_seen_refuses_a_line_added_after_read(self):
        self.base_seen()
        shown = self.op('4', 'w')
        self.edit(ACCT, _insert_line(self.body(), shown))
        self.assertEqual(self.new(self.read()), [shown])
        unshown = self.op('3', 'z')
        self.edit(ACCT, self.body().replace(shown, unshown + '\n' + shown))
        self.seen(shown, ok=False)
        r = self.read()
        self.assertIn(unshown, self.new(r))
        self.assertIn(shown, self.new(r))
        self.seen(shown)
        self.assert_no_difference(self.read())

    def test_E1_in_place_edit_by_another_login(self):
        self.base_seen()
        edited = self.L21.replace('`2-1.` c', '`2-1.` x')
        self.edit(OTHER, self.body().replace(self.L21, edited))
        r = self.read()
        d = r['difference']
        self.assertEqual(d['missing'], [self.L21])
        new = {e['line']: e for e in d['new']}
        self.assertIn(edited, new)
        self.assertFalse(new[edited]['trusted'])
        self.assertEqual(new[edited]['login'], OTHER)
        self.assertEqual(self.eff(r), {1: 'a', 2: 'b'})
        self.assertIn(2, self.changed(r))
        # seen without --drop refuses, printing the missing line, and stores nothing
        s = self.seen(edited, ok=False)
        self.assertIn(self.L21, s.out + s.err)
        self.assertEqual(self.read()['difference']['missing'], [self.L21])
        # an append over this difference is refused before posting
        self.refused_before_posting('--revise', '1', 'y', 'r')

    def test_E2_removal_with_the_last_line_unchanged(self):
        self.base_seen()
        self.edit(OTHER, self.body().replace(self.L1 + '\n', ''))
        r = self.read()
        self.assertIsNone(r['difference']['last_line'])
        self.assertEqual(r['difference']['missing'], [self.L1])
        self.assertNotIn(1, self.eff(r))
        self.assertIn(1, self.changed(r))
        s = self.seen(self.L21, ok=False)
        self.assertIn(self.L1, s.out + s.err)
        self.refused_before_posting('--revise', '2', 'y', 'r')

    def test_E3_identical_rewrite_is_no_difference(self):
        self.base_seen()
        accepted = self.body()
        self.edit(OTHER, accepted.replace(self.L1 + '\n', ''))
        self.edit(OTHER, accepted)
        r = self.read()
        self.assert_no_difference(r)
        self.assertTrue(self.entry(r, self.L1)['trusted'])
        self.assertEqual(self.eff(r), {1: 'a', 2: 'c'})

    def test_E4_deleted_revision_keeps_accepted_lines(self):
        self.base_seen()
        self.edit(ACCT, self.body().replace(PROSE, 'Prose, edited.\n'))
        self.mark(0, deleted=True)
        r = self.read()
        self.assert_no_difference(r)
        self.assertTrue(self.entry(r, self.L21)['trusted'])
        self.assertEqual(self.eff(r), {1: 'a', 2: 'c'})

    def test_E5_H3_trimmed_history(self):
        # accepted lines come in the first edit; later the oldest intermediate edits are removed by GitHub
        self.base_seen()
        new = self.op('3', 'z')
        self.edit(ACCT, _insert_line(self.body(), new))
        self.edit(ACCT, self.body().replace(PROSE, 'Prose, edited.\n'))
        self.mark(0, hidden=True)
        self.mark(1, hidden=True)
        r = self.read()
        self.assertEqual(r['history'], {'read': 2, 'total': 4})
        self.assertEqual(r['difference']['missing'], [])
        self.assertEqual(list(r['difference']['changed']), [])
        for line in (self.L1, self.L2, self.L21):
            self.assertTrue(self.entry(r, line)['trusted'], line)
        e = self.entry(r, new)
        self.assertFalse(e['trusted'])
        self.assertIsNone(e['login'])
        self.assertNotIn(3, self.eff(r))

    def test_E7_untrusted_line_does_not_block_for_good(self):
        self.base_seen()
        theirs = self.op('2-9', 'z')
        self.edit(OTHER, _insert_line(self.body(), theirs))
        r = self.read()
        self.assertIn(theirs, self.new(r))
        self.assertFalse(self.entry(r, theirs)['trusted'])
        self.assertEqual(self.eff(r), {1: 'a', 2: 'c'})
        self.refused_before_posting('--revise', '1', 'y', 'r')
        self.seen(theirs)
        r = self.read()
        self.assert_no_difference(r)
        self.assertFalse(self.entry(r, theirs)['trusted'])
        self.append('--revise', '1', 'y', 'r')
        self.assertEqual(self.eff(self.read()), {1: 'y', 2: 'c'})

    def test_E8_restore_an_edited_line(self):
        self.base_seen()
        edited = self.L21.replace('`2-1.` c', '`2-1.` x')
        self.edit(OTHER, self.body().replace(self.L21, edited))
        a = self.append('--revise', '2', 'c', 'restore', drops=[self.L21])
        mine = a.json['lines'][0]['line']
        self.assertRegex(mine, '^' + LINE_RE % ('2-2', 'c', 'restore') + '$')
        r = self.read()
        self.assertEqual(self.eff(r), {1: 'a', 2: 'c'})
        self.assertTrue(self.entry(r, mine)['trusted'])
        self.assertEqual(r['difference']['missing'], [])
        with open(os.path.join(self.run_dir, 'criteria.json')) as f:
            self.assertTrue(has_string(json.load(f), self.L21), 'criteria.json keeps the dropped line')
        self.seen(r['last_line'])
        self.assert_no_difference(self.read())

    def test_E8_restore_a_removed_number_with_add(self):
        self.base_seen()
        self.edit(OTHER, self.body().replace(self.L1 + '\n', ''))
        a = self.append('--add', '1', 'a', 'restore', drops=[self.L1])
        r = self.read()
        self.assertEqual(self.eff(r), {1: 'a', 2: 'c'})
        self.assertTrue(self.entry(r, a.json['lines'][0]['line'])['trusted'])
        self.assertEqual(r['difference']['missing'], [])

    def test_amendment_F1_restore_a_withdrawal(self):
        self.L1, self.L2, self.L21, w = self.L('1', 'a'), self.L('2', 'b'), self.L('2-1', 'c'), self.L('2-2', '')
        self.issue(PROSE)
        self.edit(ACCT, self.block([self.L1, self.L2, self.L21, w]))
        self.seen(w)
        self.assertEqual(self.eff(self.read()), {1: 'a', 2: None})
        self.edit(OTHER, self.body().replace(w + '\n', ''))
        r = self.read()
        self.assertEqual(self.eff(r)[2], 'c')
        self.assertIn(2, self.changed(r))
        a = self.append('--withdraw', '2', 'restore', drops=[w])
        self.assertRegex(a.json['lines'][0]['line'],
                         r'^`2-2\.`' + re.escape(DASH) + r'restore \(\[grounds\]\(https://github\.com/o/r/issues/7#issuecomment-[0-9]+\)\)$')
        r = self.read()
        self.assertEqual(self.eff(r), {1: 'a', 2: None})
        self.assertEqual(r['difference']['missing'], [])

    def test_amendment_F1_removal_leaving_the_effective_state_needs_no_line(self):
        self.base_seen()
        self.edit(OTHER, self.body().replace(self.L2 + '\n', ''))
        r = self.read()
        self.assertEqual(r['difference']['missing'], [self.L2])
        self.assertNotIn(2, self.changed(r))
        self.assertEqual(self.eff(r), {1: 'a', 2: 'c'})
        self.seen(self.L21, self.L2)
        self.assert_no_difference(self.read())

    def test_amendment_F2_failed_restore_keeps_the_removed_line(self):
        self.base_seen()
        self.edit(OTHER, self.body().replace(self.L1 + '\n', ''))
        self.hook('patch_issue', 'all', 'after', login=OTHER, revert=True)
        a = self.append('--add', '1', 'a', 'restore', drops=[self.L1], ok=False)
        self.assertGreaterEqual(self.calls('patch_issue'), 1, a)
        self.assertLessEqual(self.calls('patch_issue'), 5, 'at most five attempts')
        self.change(lambda s: s.update(hooks=[]))
        self.assertEqual(self.read()['difference']['missing'], [self.L1])
        self.seen(self.L21, ok=False)

    def test_amendment_F2_restore_refuses_a_newer_trusted_line_of_the_number(self):
        self.base_seen()
        edited = self.L21.replace('`2-1.` c', '`2-1.` x')
        self.edit(OTHER, self.body().replace(self.L21, edited))
        decision = self.op('2-2', 'operator decision')
        self.edit(ACCT, self.body().replace(edited, edited + '\n' + decision))
        r = self.refused_before_posting('--revise', '2', 'c', 'restore', drops=[self.L21])
        self.assertIn(decision, r.out + r.err)

    def test_amendment_F2_restore_refuses_a_new_line_of_another_number(self):
        self.base_seen()
        self.edit(OTHER, self.body().replace(self.L1 + '\n', ''))
        new = self.op('3', 'operator new criterion')
        self.edit(ACCT, _insert_line(self.body(), new))
        r = self.refused_before_posting('--add', '1', 'a', 'restore', drops=[self.L1])
        self.assertIn(new, r.out + r.err)

    def test_E9_accept_a_removal(self):
        self.base_seen()
        self.edit(OTHER, self.body().replace(self.L1 + '\n', ''))
        self.seen(self.L21, self.L1)
        r = self.read()
        self.assert_no_difference(r)
        self.assertEqual(self.eff(r), {2: 'c'})
        with open(os.path.join(self.run_dir, 'criteria.json')) as f:
            self.assertTrue(has_string(json.load(f), self.L1), 'criteria.json keeps the dropped line')
        self.append('--revise', '2', 'y', 'r')

    def test_E10_later_run_with_a_deleted_revision(self):
        l1, l2, l21 = self.L('1', 'a'), self.L('2', 'b'), self.L('2-1', 'c')
        self.issue(self.block([l1, l2]))
        self.edit(ACCT, self.block([l1, l2, l21]))
        self.edit(ACCT, self.block([l1, l2, l21], prose='Prose, edited.\n'))
        self.mark(0, deleted=True)
        r = self.read()
        self.assertEqual(sorted(self.new(r)), sorted([l1, l2, l21]))
        e = self.entry(r, l21)
        self.assertFalse(e['trusted'])
        self.assertIsNone(e['login'])
        self.assertEqual(self.eff(r), {1: 'a', 2: 'b'})
        self.seen(l21)
        a = self.append('--revise', '2', 'c', 'written again')
        r = self.read()
        self.assertTrue(self.entry(r, a.json['lines'][0]['line'])['trusted'])
        self.assertEqual(self.eff(r)[2], 'c')

    def test_M1_repeated_lines_in_the_accepted_set(self):
        l1, l2, l21 = self.L('1', 'a'), self.L('2', 'b'), self.L('2-1', 'c')
        self.issue(PROSE)
        self.edit(ACCT, self.block([l1, l2, l21, l21]))
        self.seen(l21)
        self.edit(OTHER, self.block([l1, l2, l21]))
        r = self.read()
        self.assertEqual(r['difference']['missing'], [l21])
        self.seen(l21, ok=False)
        self.seen(l21, l21, l21, ok=False)
        self.seen(l21, l21)
        self.assert_no_difference(self.read())

    def test_M2_repeated_lines_in_attribution(self):
        l1, l2 = self.L('1', 'a'), self.L('2', 'b')
        self.issue(self.block([l1, l2]))
        self.edit(OTHER, self.block([l1, l2, l2]))
        r = self.read()
        copies = self.entries(r, l2)
        self.assertEqual(sorted(d['login'] for d in copies), [ACCT, OTHER])
        self.assertEqual(sorted(d['trusted'] for d in copies), [False, True])


# ---------------------------------------------------------------------------------------------------------
# Attribution, grounds and the trust boundary: lines outside the accepted set, no seen

class Trust(Base):
    def test_A1_account_lines_trusted(self):
        l1 = self.L('1', 'a')
        self.issue(PROSE)
        self.edit(ACCT, self.block([l1]))
        e = self.entry(self.read(), l1)
        self.assertTrue(e['trusted'])
        self.assertEqual(e['login'], ACCT)
        self.setUp()
        l1 = self.L('1', 'a')
        self.issue(self.block([l1]))
        self.assertTrue(self.entry(self.read(), l1)['trusted'])

    def test_A2_other_login_untrusted(self):
        l1 = self.L('1', 'a')
        self.issue(self.block([l1]))
        theirs = self.op('4', 'q')
        self.edit(OTHER, _insert_line(self.body(), theirs))
        r = self.read()
        e = self.entry(r, theirs)
        self.assertFalse(e['trusted'])
        self.assertEqual(e['login'], OTHER)
        self.assertIn(OTHER, e['why'])
        self.assertEqual(self.eff(r), {1: 'a'})
        self.assertEqual(r['last_line'], theirs)
        self.seen(theirs)
        self.refused_before_posting('--add', '4', 'x', 'r')

    def test_A3_issue_author_other(self):
        l1 = self.op('1', 'a')
        self.issue(self.block([l1]), author=OTHER)
        r = self.read()
        self.assertFalse(self.entry(r, l1)['trusted'])
        self.assertEqual(r['effective'], {})

    def test_A4_removed_then_restored_by_other(self):
        l1, l2 = self.L('1', 'a'), self.L('2', 'b')
        self.issue(PROSE)
        self.edit(ACCT, self.block([l1, l2]))
        self.edit(OTHER, self.block([l2]))
        self.edit(OTHER, self.block([l1, l2]))
        e = self.entry(self.read(), l1)
        self.assertEqual(e['login'], OTHER)
        self.assertFalse(e['trusted'])

    def test_A5_first_seen_after_deleted_content(self):
        l1 = self.L('1', 'a')
        self.issue(PROSE)
        self.edit(ACCT, self.block([l1]))
        self.edit(ACCT, self.block([l1], prose='Prose, edited.\n'))
        self.mark(0, deleted=True)
        e = self.entry(self.read(), l1)
        self.assertFalse(e['trusted'])
        self.assertIsNone(e['login'])

    def test_A6_oldest_node_not_the_original(self):
        l1 = self.L('1', 'a')
        self.issue(PROSE)
        self.edit(ACCT, self.block([l1]))
        self.edit(ACCT, self.block([l1], prose='Prose, edited.\n'))
        self.option(no_created_edit=True)
        e = self.entry(self.read(), l1)
        self.assertFalse(e['trusted'])
        self.assertIsNone(e['login'])

    def test_A7_forged_grounds(self):
        good = self.L('1', 'a')
        missing = self.L('2', 'b', cid=99999)
        elsewhere = self.L('3', 'c', cid=self.comment(issue=8))
        by_other = self.L('4', 'd', cid=self.comment(login=OTHER))
        self.issue(self.block([good, missing, elsewhere, by_other]))
        r = self.read()
        self.assertTrue(self.entry(r, good)['trusted'])
        for line in (missing, elsewhere, by_other):
            e = self.entry(r, line)
            self.assertFalse(e['trusted'], line)
            self.assertIn('comment', e['why'].lower(), e)
        self.assertEqual(self.eff(r), {1: 'a'})

    def test_A8_operator_lines(self):
        mine = self.op('1', 'x')
        self.issue(self.block([mine]))
        theirs = self.op('2', 'y')
        self.edit(OTHER, _insert_line(self.body(), theirs))
        r = self.read()
        e = self.entry(r, mine)
        self.assertTrue(e['trusted'])
        self.assertTrue(e['operator'])
        self.assertFalse(self.entry(r, theirs)['trusted'])
        self.assertEqual(self.eff(r), {1: 'x'})

    def test_A9_untrusted_k_does_not_override(self):
        first, mine = self.op('3', 'x'), self.L('3-2', 'y')
        self.issue(self.block([first, mine]))
        theirs = self.op('3-5', 'z')
        self.edit(OTHER, self.body().replace(mine, theirs + '\n' + mine))
        r = self.read()
        self.assertEqual(self.eff(r), {3: 'y'})
        self.assertNotIn(mine, self.malformed(r))


# ---------------------------------------------------------------------------------------------------------
# History self-check and paging

class History(Base):
    def _edited(self):
        self.issue(PROSE)
        self.edit(ACCT, self.block([self.L('1', 'a')]))

    def assert_stopped(self, r, word=None):
        self.assertNotEqual(r.code, 0, r)
        self.assertNotIn('effective', r.out, r)
        if word:
            self.assertIn(word, r.err.lower(), r)

    def test_H1_newest_diff_not_the_body(self):
        self._edited()
        self.option(newest_diff='tampered body')
        self.assert_stopped(self.run_tool('read'), 'diff')

    def test_H2_oldest_node_not_at_created(self):
        self._edited()
        self.option(created_node_at='2025-12-31T00:00:00Z')
        self.assert_stopped(self.run_tool('read'), 'creation')

    def test_H4_three_pages(self):
        l1 = self.L('1', 'a')
        self.issue(PROSE)
        self.edit(ACCT, self.block([l1], prose='Prose 0.\n'))
        for i in range(1, 46):
            self.edit(OTHER, self.block([l1], prose='Prose %d.\n' % i))
        self.assertEqual(len(_nodes(self.load())), 47)
        r = self.read()
        self.assertEqual(self.calls('graphql'), 3)
        self.assertEqual(r['history'], {'read': 47, 'total': 47})
        e = self.entry(r, l1)
        self.assertEqual(e['login'], ACCT)
        self.assertTrue(e['trusted'])

    def test_H5_cursor_does_not_advance(self):
        l1 = self.L('1', 'a')
        self.issue(PROSE)
        for i in range(25):
            self.edit(ACCT, self.block([l1], prose='Prose %d.\n' % i))
        self.option(stuck_cursor=True)
        r = self.run_tool('read', timeout=60)
        self.assert_stopped(r, 'cursor')
        self.assertLessEqual(self.calls('graphql'), 3)

    def test_H6_crlf_body_with_an_lf_graphql_copy(self):
        l1 = self.L('1', 'a')
        self.issue(PROSE)
        lf = self.block([l1])
        self.edit(ACCT, lf.replace('\n', '\r\n'))
        self.option(graphql_body=lf)
        r = self.read()
        self.assertEqual(self.eff(r), {1: 'a'})
        self.assertTrue(self.entry(r, l1)['trusted'], r)


# ---------------------------------------------------------------------------------------------------------
# Fetch failures and gh failures in the protocol

class Failures(Base):
    def assert_failed(self, r):
        self.assertNotEqual(r.code, 0, r)
        self.assertIn(FAIL_MSG, r.err, r)
        self.assertNotIn('effective', r.out, r)
        self.assertNotIn('`1.`', r.out, r)

    def test_X1_graphql_fails(self):
        self.issue(self.block([self.L('1', 'a')]))
        self.hook('graphql', 1, 'before', fail=FAIL_MSG)
        self.assert_failed(self.run_tool('read'))

    def test_X1_comment_read_fails(self):
        self.issue(self.block([self.L('1', 'a')]))
        self.hook('get_comment', 1, 'before', fail=FAIL_MSG)
        self.assert_failed(self.run_tool('read'))

    def test_X1_later_page_fails(self):
        l1 = self.L('1', 'a')
        self.issue(PROSE)
        for i in range(25):
            self.edit(ACCT, self.block([l1], prose='Prose %d.\n' % i))
        self.hook('graphql', 2, 'before', fail=FAIL_MSG)
        self.assert_failed(self.run_tool('read'))

    def test_D7_403_is_not_retried(self):
        self.base_seen()
        self.hook('patch_issue', 1, 'before', fail='Resource not accessible by integration (HTTP 403)')
        r = self.append('--revise', '1', 'y', 'r', ok=False)
        self.assertEqual(self.calls('patch_issue'), 1, r)
        self.assertIn('Issues', r.err + r.out, r)

    def test_D7_422_is_not_retried(self):
        self.base_seen()
        self.hook('patch_issue', 1, 'before', fail='Validation Failed (HTTP 422)')
        r = self.append('--revise', '1', 'y', 'r', ok=False)
        self.assertEqual(self.calls('patch_issue'), 1, r)

    def test_D7_graphql_and_rest_bodies_never_equal(self):
        self.base_seen()
        self.option(graphql_body='another body', newest_diff='another body')
        before = self.calls('graphql')
        r = self.append('--revise', '1', 'y', 'r', ok=False)
        self.assertEqual(self.calls('patch_issue'), 0, r)
        self.assertGreaterEqual(self.calls('graphql') - before, 2, 'compose did not start again')


# ---------------------------------------------------------------------------------------------------------
# The three steps

class Protocol(Base):
    def test_step2_detects_a_change(self):
        self.base_seen()
        theirs = self.op('3', 'z')
        self.hook('post_comment', 1, 'after', login=ACCT, append_line=theirs)
        a = self.append('--revise', '1', 'y', 'r')
        self.assertEqual(self.calls('patch_issue'), 1)
        self.assertEqual(self.calls('post_comment'), 1, 'the comment is reused on a restart')
        self.assertIn(theirs, self.body())
        self.assertTrue(a.json['lines'][0]['present'])

    def test_step3_detects_a_lost_write_and_rewrites(self):
        self.base_seen()
        theirs = self.op('3', 'z')
        self.hook('patch_issue', 1, 'after', login=ACCT, revert=True, append_line=theirs)
        a = self.append('--revise', '1', 'y', 'r')
        mine = a.json['lines'][0]['line']
        self.assertEqual(self.calls('patch_issue'), 2, a)
        self.assertEqual(self.calls('post_comment'), 1)
        body = self.body()
        self.assertIn(theirs, body)
        self.assertIn(mine, body)
        self.assertTrue(a.json['lines'][0]['present'])
        self.assertIn('absent', (a.err + a.out).lower())
        for w in self.sleeps():
            self.assertTrue(60 <= w <= 100, 'wait %s outside [60, 100]' % w)
        self.assertGreaterEqual(len(self.sleeps()), 2)


# ---------------------------------------------------------------------------------------------------------
# Overwrite report: an edit that lands between the re-read and the write

class Overwrite(Base):
    def _run(self, **hook):
        self.base_seen()
        if hook:
            self.hook('patch_issue', 1, 'before', **hook)
        a = self.append('--revise', '1', 'y', 'r')
        self.assertTrue(a.json['lines'][0]['present'], a)
        return a.json['overwritten']

    @staticmethod
    def held(entry):
        return {d['line']: d['present'] for d in entry['lines']}

    def test_O1a_account_block_race_reported_with_its_lines_present(self):
        self.base_seen()
        theirs = self.L('3', 'z')
        self.hook('patch_issue', 1, 'before', login=ACCT, append_line=theirs)
        self.hook('patch_issue', 1, 'after', login=ACCT, append_line=theirs)
        a = self.append('--revise', '1', 'y', 'r')
        self.assertTrue(a.json['lines'][0]['present'], a)
        rep = a.json['overwritten']
        self.assertEqual(len(rep), 1, rep)
        self.assertEqual(rep[0]['editor'], ACCT)
        self.assertTrue(rep[0]['time'])
        self.assertEqual(self.held(rep[0]), {self.L1: True, self.L2: True, self.L21: True, theirs: True}, rep)

    def test_O1e_unlinked_account_line_lost_to_the_write_reported_absent(self):
        self.base_seen()
        operator = self.op('2-2', 'operator revision')
        rep = self._run_after_base(login=ACCT, append_line=operator)
        self.assertEqual(len(rep), 1, rep)
        self.assertEqual(rep[0]['editor'], ACCT)
        self.assertTrue(rep[0]['time'])
        self.assertEqual(self.held(rep[0]), {self.L1: True, self.L2: True, self.L21: True, operator: False}, rep)
        self.assertNotIn(operator, self.body())

    def _run_after_base(self, **hook):
        self.hook('patch_issue', 1, 'before', **hook)
        a = self.append('--revise', '1', 'y', 'r')
        self.assertTrue(a.json['lines'][0]['present'], a)
        return a.json['overwritten']

    def test_O1b_other_login_reported(self):
        rep = self._run(login=OTHER, replace=[PROSE, 'Prose, by other.\n'])
        self.assertEqual(len(rep), 1, rep)
        self.assertEqual(rep[0]['editor'], OTHER)
        self.assertTrue(rep[0]['time'])

    def test_O1c_account_edit_outside_block_reported(self):
        rep = self._run(login=ACCT, replace=[PROSE, 'Prose, by the operator.\n'])
        self.assertEqual(len(rep), 1, rep)
        self.assertEqual(rep[0]['editor'], ACCT)

    def test_O1d_nothing_in_between(self):
        self.assertEqual(self._run(), [])


# ---------------------------------------------------------------------------------------------------------
# What is published

class Published(Base):
    def test_G1_length_limit(self):
        self.base_seen()
        self.set_grounds('x')
        self.append('--revise', '1', 'y', 'r')
        overhead = len(self.posted()[-1]) - 1
        self.set_grounds('x' * (2000 - overhead))
        self.append('--revise', '1', 'z', 'r')
        self.assertEqual(len(self.posted()[-1]), 2000)
        self.set_grounds('x' * (2001 - overhead))
        self.refused_before_posting('--revise', '1', 'w', 'r')

    def test_G1_empty_comment(self):
        self.base_seen()
        self.set_grounds('')
        self.refused_before_posting('--revise', '1', 'y', 'r')

    def local_path(self, name):
        """A path of this setUp's tree: each subtest's setUp makes a new home, root and checkout."""
        return {'home': os.path.join(self.home, 'notes.md'), 'home ~ form': '~/notes.md',
                'root': os.path.join(self.root, 'records', self.run_name, 'x.md'),
                'checkout': os.path.join(self.checkout, 'tools', 'x.py')}[name]

    def test_G2_local_paths(self):
        for name in ('home', 'home ~ form', 'root', 'checkout'):
            for where in ('comment', 'text', 'reason'):
                with self.subTest(path=name, where=where):
                    self.setUp()
                    path = self.local_path(name)
                    self.base_seen()
                    text, reason = 'y', 'r'
                    if where == 'comment':
                        self.set_grounds('Details in %s.' % path)
                    elif where == 'text':
                        text = 'see %s' % path
                    else:
                        reason = 'see %s' % path
                    self.refused_before_posting('--revise', '1', text, reason)

    def test_G2_local_path_case_variant(self):
        for where in ('comment', 'text', 'reason'):
            with self.subTest(where=where):
                self.setUp()
                path = os.path.join(self.home, 'notes.md').upper()
                self.base_seen()
                text, reason = 'y', 'r'
                if where == 'comment':
                    self.set_grounds('Details in %s.' % path)
                elif where == 'text':
                    text = 'see %s' % path
                else:
                    reason = 'see %s' % path
                self.refused_before_posting('--revise', '1', text, reason)

    def test_G3_run_record_trailer(self):
        self.base_seen()
        self.append('--revise', '1', 'y', 'r')
        self.assertTrue(self.posted()[-1].rstrip().endswith('Run record: %s' % self.run_name), self.posted())


# ---------------------------------------------------------------------------------------------------------
# The run's inputs: criteria.json, repo.json and the account

class Inputs(Base):
    def assert_clean_stop(self, r, word):
        self.assertNotEqual(r.code, 0, r)
        self.assertNotIn('Traceback', r.err, r)
        self.assertIn(word, r.err, r)

    def test_F4_criteria_json_of_the_wrong_shape(self):
        bad = {'not an object': [], 'seen missing keys': None}
        for name in bad:
            with self.subTest(name):
                self.setUp()
                self.base_seen()
                path = os.path.join(self.run_dir, 'criteria.json')
                if name == 'not an object':
                    content = '[]\n'
                else:
                    with open(path) as f:
                        state = json.load(f)
                    state['seen'] = {'last_line': state['seen']['last_line']}
                    content = json.dumps(state)
                with open(path, 'w') as f:
                    f.write(content)
                for args in (['read'], ['seen', self.L21]):
                    self.assert_clean_stop(self.run_tool(*args), 'criteria.json')
                    with open(path) as f:
                        self.assertEqual(f.read(), content, 'criteria.json was written')
                r = self.refused_before_posting('--revise', '1', 'y', 'r')
                self.assertNotIn('Traceback', r.err, r)
                self.assertIn('criteria.json', r.err, r)
                with open(path) as f:
                    self.assertEqual(f.read(), content, 'criteria.json was written')

    def test_F5_repository_name(self):
        for github in ('o/r/issues/9', 'o/r?x'):
            with self.subTest(github=github):
                self.setUp()
                self.issue(self.block([self.op('1', 'a')]))
                ws = os.path.dirname(self.checkout)
                with open(os.path.join(ws, 'repo.json'), 'w') as f:
                    json.dump({'github': github, 'base_branch': 'main', 'clone': os.path.join(ws, 'r')}, f)
                for args in (['read'], ['seen', 'none'], ['append', '--grounds', self.grounds, '--add', '2', 'b', 'r']):
                    self.assert_clean_stop(self.run_tool(*args), 'repo.json')
                self.assertEqual(self.load()['log'], [], 'a request was made')

    def test_F6_account_without_a_login(self):
        for account in ('', None):
            with self.subTest(account=account):
                self.setUp()
                self.issue(self.block([self.op('1', 'a')]))
                self.change(lambda s: s.update(account=account))
                for args in (['read'], ['seen', '`1.` a']):
                    r = self.run_tool(*args)
                    self.assertNotEqual(r.code, 0, r)
                    self.assertNotIn('Traceback', r.err, r)
                    self.assertIn('login', r.err.lower(), r)
                    self.assertNotIn('effective', r.out, r)
                self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'criteria.json')))
                self.assertEqual(self.calls('post_comment') + self.calls('patch_issue'), 0)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--gh-standin']:
        standin(sys.argv[2:])
    unittest.main()
