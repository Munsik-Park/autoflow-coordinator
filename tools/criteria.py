#!/usr/bin/env python3
"""criteria.py <run-dir> read | seen <line|none> [--drop <line>] ... | append --grounds <file> [--drop <line>] ... <spec> ...
— read and append to the criteria block of the run's issue, with a write that reveals a lost write.

  <run-dir>   <runs>/<name>/ holding run.env (CHECKOUT, ISSUE); the workspace is the parent of CHECKOUT, and the
              repository is its repo.json > github. The account is the login of the token in use (gh api user).
  <spec>      --revise N <text> <reason> | --withdraw N <reason> | --add N <text> <reason>

The block is the lines between `<!-- criteria -->` and `<!-- /criteria -->` (each alone on its line) under the
heading `## Criteria`. A line starts with its label, `N.` or `N-k.`, in inline code or bare. The tool writes
`<label> <text> — <reason> ([grounds](<comment URL>))`, or `<label> — <reason> ([grounds](<comment URL>))` for a
withdrawal. A line without that link is the operator's, and all of it after the label is text; an empty `N-k.`
withdraws N, an empty `N.` is malformed. Within each N, in block order, a trusted line whose k is not above every
earlier trusted k of N is malformed; the effective text of N is its last valid trusted line.

Trust. A line of the accepted state (seen) is trusted while it is present. Any other line is attributed from the
issue's edit history to the version from which it has been present without a break; it is trusted when that
editor is the account and, if it is linked, its comment exists, is on this issue and is by the account. A line
first seen in the oldest retained version when edits between it and the original were removed, first seen in an
oldest version that is not the original, or first seen after a version whose content was deleted, has no
attribution. Untrusted lines are not criteria, but count for the last line, for k and for the numbers in use.

read     prints JSON: block, last_line, effective (N -> text, null for withdrawn), lines with attribution,
         malformed lines, the difference from seen (last line, new lines, accepted lines missing, criteria whose
         effective text changed), the presence of the lines this run wrote, and the history counts.
seen     records the current state as accepted: the block must hold no line the last read did not print, and
         the last line given must be the current one; an accepted line that is missing must be named by --drop (one mention, one
         copy), and a --drop must name a missing one.
append   refuses before posting anything on any difference from seen, except that a call may name with --drop
         the accepted lines it restores (the restore of those numbers: their missing lines, untrusted new lines
         of those numbers and their effective texts, and nothing else); posts one grounds comment (with "Run record: <run name>" added) and
         writes all its lines in one write: (1) compose against a read; (2) re-read, and write only when the body
         is unchanged and at most 30 s have passed since the re-read began; (3) after 60-100 s, check that every
         line is present, else start again at (1). At most five attempts. A line that does not read back as its spec
         is refused before posting. It reports every version its write overwrote: editor, time, and whether each
         block line that version held is present after the write. Each step 3 checks every line this run has
         written, in this call or an earlier one, against the body it reads, and the report and criteria.json
         give that result for each. After the last step 3 it advances seen
         when the only differences are its own lines, and drops the --drop lines from it once its lines are present.

Progress goes to standard error, one line per step; standard output ends with the JSON report. The run's state
is <run-dir>/criteria.json: the lines this run wrote, seen, the block the last read printed, and the overwritten
edits reported. The history self-check, the GraphQL/REST comparison, the overwrite report's matching of
versions and the final history check compare bodies with CRLF taken as LF; the step 2 re-read check compares
them exactly. Accepted lines are trusted from that file, so its integrity rests on the run directory's
permissions; a file of another shape stops the tool.
"""
import collections, hashlib, json, os, random, re, subprocess, sys, time
from datetime import datetime, timezone

START, END, HEADING = '<!-- criteria -->', '<!-- /criteria -->', '## Criteria'
DASH = ' — '
LABEL = re.compile(r'(`?)([1-9][0-9]*)(?:-([1-9][0-9]*))?\.\1(?: (.*))?')
LINK = re.compile(r' ?\(\[grounds\]\((https://github\.com/([^/\s()]+)/([^/\s()]+)/issues/([0-9]+)'
                  r'#issuecomment-([0-9]+))\)\)$')
NUMBER = re.compile(r'[1-9][0-9]*')
REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', re.ASCII)
PAGE = 20
MAX_PAGES = 10
ATTEMPTS = 5
REREAD_AGE = 30
WRITE_TIMEOUT = 15
READ_TIMEOUT = 60
COMMENT_MAX = 2000
HISTORY_QUERY = '''query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      body createdAt includesCreatedEdit author { login }
      userContentEdits(first: %d, after: $after) {
        totalCount pageInfo { hasNextPage endCursor }
        nodes { diff editedAt deletedAt editor { login } }
      }
    }
  }
}''' % PAGE


class Stop(Exception):
    pass


class GhError(Stop):
    def __init__(self, what, message):
        super().__init__(f'{what}: {message}')
        m = re.search(r'HTTP ([0-9]{3})', message)
        self.status = int(m.group(1)) if m else None


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def log(msg):
    print(f'{now()} {msg}', file=sys.stderr, flush=True)


def same(a, b):
    """Whether two bodies are equal with CRLF line endings taken as LF."""
    return a is not None and b is not None and a.replace('\r\n', '\n') == b.replace('\r\n', '\n')


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# --- the block -----------------------------------------------------------------------------------------------

def split_lines(body):
    return [l[:-1] if l.endswith('\r') else l for l in (body or '').split('\n')]


def block_span(lines):
    """(start, end) indexes of the markers, or None without a block; Stop on a broken pair."""
    starts = [i for i, l in enumerate(lines) if l.strip() == START]
    ends = [i for i, l in enumerate(lines) if l.strip() == END]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1:
        raise Stop(f'the body has {len(starts)} start and {len(ends)} end markers of the criteria block')
    if ends[0] < starts[0]:
        raise Stop('the end marker of the criteria block comes before its start marker')
    return starts[0], ends[0]


def block_lines(body):
    """The block's lines (blank lines left out), or None without a block."""
    lines = split_lines(body)
    span = block_span(lines)
    if span is None:
        return None
    return [l for l in lines[span[0] + 1:span[1]] if l.strip()]


def lenient_lines(body):
    """A past version's block lines; a version whose markers are broken is taken whole."""
    try:
        lines = block_lines(body)
    except Stop:
        return [l for l in split_lines(body) if l.strip()]
    return lines or []


def outside_block(body):
    lines = split_lines(body)
    try:
        span = block_span(lines)
    except Stop:
        return lines
    return lines if span is None else lines[:span[0]] + lines[span[1] + 1:]


def parse(line):
    """dict(number, k, text, reason, url, owner, repo, issue, comment, linked, withdraw, error)."""
    m = LABEL.fullmatch(line)
    if not m:
        return {'error': 'not a criterion line'}
    p = {'number': int(m.group(2)), 'k': int(m.group(3) or 0), 'linked': False, 'reason': None,
         'url': None, 'comment': None, 'error': None}
    rest = m.group(4) or ''
    link = LINK.search(rest)
    if link:
        p.update(linked=True, url=link.group(1), owner=link.group(2), repo=link.group(3),
                 issue=int(link.group(4)), comment=int(link.group(5)))
        pre = rest[:link.start()]
        if pre.startswith(DASH.lstrip()):
            text, reason = '', pre[len(DASH.lstrip()):]
        elif DASH in pre:
            i = pre.rfind(DASH)
            text, reason = pre[:i], pre[i + len(DASH):]
        else:
            p['error'] = 'a linked line without a reason'
            text, reason = pre, ''
        p['reason'] = reason
    else:
        text = rest
    p['text'] = text.strip()
    p['withdraw'] = p['text'] == ''
    if p['withdraw'] and p['k'] == 0 and not p['error']:
        p['error'] = f'an empty {p["number"]}. is neither a criterion nor a withdrawal'
    return p


def effective(entries):
    """entries: [(line, parsed, trusted)] in block order -> ({N: text | None}, [{line, why}])."""
    eff, last_k, malformed = {}, {}, []
    for line, p, trusted in entries:
        if p['error']:
            malformed.append({'line': line, 'why': p['error']})
            continue
        if not trusted:
            continue
        n, k = p['number'], p['k']
        if n in last_k and k <= last_k[n]:
            malformed.append({'line': line, 'why': f'k {k} is not above the earlier k {last_k[n]} of {n}'})
            continue
        last_k[n] = k
        eff[n] = None if p['withdraw'] else p['text']
    return eff, malformed


def present(body, line):
    lines = block_lines(body) if body is not None else None
    return line in (lines or [])


# --- history -------------------------------------------------------------------------------------------------

def read_history(fetch_page):
    """All of the issue's edit history, paged; fetch_page(after) returns the issue of one page."""
    issue = fetch_page(None)
    conn = issue['userContentEdits']
    nodes = list(conn['nodes'])
    cursor, pages = None, 1
    while conn['pageInfo']['hasNextPage']:
        nxt = conn['pageInfo']['endCursor']
        if not nxt or nxt == cursor:
            raise Stop(f'the edit history cursor does not advance ({nxt!r}) after {len(nodes)} versions')
        pages += 1
        if pages > MAX_PAGES:
            raise Stop(f'the edit history did not end within {MAX_PAGES} pages')
        cursor = nxt
        conn = fetch_page(cursor)['userContentEdits']
        nodes.extend(conn['nodes'])
    issue = dict(issue)
    issue['userContentEdits'] = dict(issue['userContentEdits'], nodes=nodes)
    return issue


def check_history(issue):
    conn = issue['userContentEdits']
    nodes = conn['nodes']
    if conn['totalCount'] > 0:
        if not nodes:
            raise Stop(f'the edit history counts {conn["totalCount"]} versions and returned none')
        if not same(nodes[0].get('diff'), issue['body']):
            raise Stop('the newest edit in the history is not the current body: its diff differs')
    if issue.get('includesCreatedEdit') and nodes and nodes[-1].get('editedAt') != issue.get('createdAt'):
        raise Stop(f'the oldest edit ({nodes[-1].get("editedAt")}) is not at the issue\'s creation '
                   f'({issue.get("createdAt")}) although the history includes the created edit')


def login_of(actor):
    return (actor or {}).get('login')


def versions(issue):
    """Versions oldest first as dicts(body, lines, editor, time), and whether the first is the original and
    whether edits are missing between the original and the oldest retained one."""
    nodes = issue['userContentEdits']['nodes']
    author = login_of(issue.get('author'))
    if not nodes:
        body = issue['body']
        return [{'body': body, 'lines': collections.Counter(lenient_lines(body)), 'editor': author,
                 'time': issue.get('createdAt')}], True, False
    out = []
    for n in reversed(nodes):
        deleted = n.get('deletedAt') is not None or n.get('diff') is None
        body = None if deleted else n['diff']
        out.append({'body': body, 'lines': None if deleted else collections.Counter(lenient_lines(body)),
                    'editor': login_of(n.get('editor')), 'time': n.get('editedAt')})
    original = bool(issue.get('includesCreatedEdit'))
    if original:
        out[0]['editor'] = author
    gap = original and len(nodes) < issue['userContentEdits']['totalCount']
    return out, original, gap


def attribute_copy(vs, original, gap, line, j):
    """(login, time, why) for the j-th copy of line, counted by introduction; login None: no attribution."""
    earliest, extra, k = len(vs) - 1, set(), len(vs) - 2
    while k >= 0:
        if vs[k]['lines'] is None:
            d = k
            while d >= 0 and vs[d]['lines'] is None:
                d -= 1
            if d < 0 or vs[d]['lines'][line] < j:
                return None, None, 'no attribution: first seen after a version whose content was deleted'
            extra |= {vs[x]['editor'] for x in range(d + 1, earliest + 1)}
            earliest, k = d, d - 1
            continue
        if vs[k]['lines'][line] >= j:
            earliest, k = k, k - 1
        else:
            break
    if earliest == 0 and not original:
        return None, None, 'no attribution: first seen in the oldest retained version, which is not the original'
    if gap and earliest <= 1:
        return None, None, 'no attribution: present across edits GitHub removed from the history'
    v = vs[earliest]
    logins = {v['editor']} | extra
    if len(logins) > 1:
        return None, None, 'no attribution: present across deleted content edited by ' + ', '.join(
            sorted(str(x) for x in logins))
    return v['editor'], v['time'], None


# --- the report ----------------------------------------------------------------------------------------------

def empty_seen():
    return {'last_line': 'none', 'lines': [], 'accepted': [], 'effective': {}, 'dropped': []}


def evaluate(issue, *, account, repo, number, get_comment, seen=None, own=()):
    """The report `read` prints, from the issue's history (all pages) and the accepted state."""
    seen = seen or empty_seen()
    body = issue['body']
    lines = block_lines(body)
    vs, original, gap = versions(issue)
    accepted = collections.defaultdict(list)
    for a in seen['accepted']:
        accepted[a['line']].append(a)
    copies = collections.Counter()
    entries, out_lines = [], []
    for line in lines or []:
        copies[line] += 1
        j = copies[line]
        p = parse(line)
        e = {'line': line, 'login': None, 'time': None, 'trusted': False, 'why': '', 'operator': False,
             'accepted': False}
        if j <= len(accepted[line]):
            a = accepted[line][j - 1]
            e.update(login=a.get('login'), time=a.get('time'), trusted=True, accepted=True, why='accepted')
        else:
            login, t, why = attribute_copy(vs, original, gap, line, j)
            e.update(login=login, time=t)
            if login is None:
                e['why'] = why
            elif login != account:
                e['why'] = f'written by login {login}'
            elif not p['error'] and p['linked']:
                e['why'] = comment_problem(p, account, repo, number, get_comment) or ''
                e['trusted'] = not e['why']
            else:
                e['trusted'] = True
            if e['trusted']:
                e['why'] = 'written by the account'
        e['operator'] = e['trusted'] and not p['error'] and not p['linked']
        entries.append((line, p, e['trusted']))
        out_lines.append(e)
    eff, malformed = effective(entries)
    last = lines[-1] if lines else 'none'
    report = {'block': lines is not None, 'last_line': last,
              'effective': {str(n): t for n, t in sorted(eff.items())},
              'lines': out_lines, 'malformed': malformed}
    report['difference'] = difference(report, seen, set(own))
    report['own'] = [{'line': l, 'present': l in (lines or [])} for l in own]
    report['history'] = {'read': len(issue['userContentEdits']['nodes']),
                         'total': issue['userContentEdits']['totalCount']}
    return report


def comment_problem(p, account, repo, number, get_comment):
    if f'{p["owner"]}/{p["repo"]}'.lower() != repo.lower() or p['issue'] != number:
        return 'grounds comment link points to another issue'
    c = get_comment(p['comment'])
    if c is None:
        return 'grounds comment missing'
    want = f'https://api.github.com/repos/{repo}/issues/{number}'.lower()
    if (c.get('issue_url') or '').lower() != want:
        return 'grounds comment on another issue'
    if login_of(c.get('user')) != account:
        return f'grounds comment by login {login_of(c.get("user"))}'
    return None


def difference(report, seen, own):
    current = collections.Counter(e['line'] for e in report['lines'])
    before = collections.Counter(seen['lines'])
    acc = collections.Counter(a['line'] for a in seen['accepted'])
    new, extra = [], current - before
    for e in report['lines']:
        if extra[e['line']] > 0 and copies_left(e, report, extra):
            new.append({'line': e['line'], 'login': e['login'], 'trusted': e['trusted'], 'own': e['line'] in own})
    missing = []
    for line, a in acc.items():
        missing += [line] * max(0, a - current[line])
    now_eff = {int(n): t for n, t in report['effective'].items()}
    then_eff = {int(n): t for n, t in seen['effective'].items()}
    changed = sorted(n for n in set(now_eff) | set(then_eff)
                     if (n in now_eff) != (n in then_eff) or now_eff.get(n) != then_eff.get(n))
    last = None if report['last_line'] == seen['last_line'] else {'seen': seen['last_line'], 'now': report['last_line']}
    return {'last_line': last, 'new': new, 'missing': missing, 'changed': changed}


def copies_left(e, report, extra):
    """Take the last copies of a line as the new ones."""
    idx = [i for i, x in enumerate(report['lines']) if x['line'] == e['line']]
    pos = next(i for i in idx if report['lines'][i] is e)
    return idx.index(pos) >= len(idx) - extra[e['line']]


def any_difference(d):
    return bool(d['last_line'] or d['new'] or d['missing'] or d['changed'])


def check_drops(drops, d):
    """Stop unless the --drop lines name exactly the missing accepted copies."""
    missing, named = collections.Counter(d['missing']), collections.Counter(drops)
    wrong = named - missing
    if wrong:
        raise Stop('--drop names lines that are not missing accepted lines: ' + json.dumps(sorted(wrong.elements()),
                                                                                        ensure_ascii=False))
    left = missing - named
    if left:
        raise Stop('accepted lines are missing and no --drop names them: '
                   + json.dumps(sorted(left.elements()), ensure_ascii=False))


def check_restore(drops, d):
    """Stop unless every difference besides the named missing lines belongs to the restore of their numbers:
    untrusted new lines of those numbers, and changes of those numbers' effective texts."""
    check_drops(drops, d)
    numbers = {parse(l).get('number') for l in drops} - {None}
    restored = {n['line'] for n in d['new'] if not n['trusted'] and parse(n['line']).get('number') in numbers}
    other = [n['line'] for n in d['new'] if n['line'] not in restored]
    if other:
        raise Stop('the block holds new lines outside the restore of ' + ', '.join(map(str, sorted(numbers)))
                   + ': ' + json.dumps(other, ensure_ascii=False) + '; assess them before restoring')
    changed = [n for n in d['changed'] if n not in numbers]
    if changed:
        raise Stop('effective texts changed outside the restore: ' + ', '.join(map(str, changed)))
    last = d['last_line']
    if last and last['now'] not in restored and any(n['line'] == last['now'] for n in d['new']):
        raise Stop(f'the last line {json.dumps(last["now"], ensure_ascii=False)} is outside the restore')


def make_seen(report, previous, drops=(), change=None):
    s = {'last_line': report['last_line'], 'lines': [e['line'] for e in report['lines']],
         'accepted': [{'line': e['line'], 'login': e['login'], 'time': e['time']}
                      for e in report['lines'] if e['trusted']],
         'effective': dict(report['effective']), 'dropped': list(previous.get('dropped', []))}
    for d in drops:
        s['dropped'].append({'line': d, 'time': now(), 'change': change})
    return s


# --- composing -----------------------------------------------------------------------------------------------

def check_text(value, what, paths):
    if '\n' in value or '\r' in value:
        raise Stop(f'{what} holds a line break')
    local_path(value, what, paths)


def local_path(value, what, paths):
    folded = value.casefold()
    for p in paths:
        if p and p.casefold() in folded:
            raise Stop(f'{what} holds a local path ({p})')
    if re.search(r'(^|[^\w/.~-])~/', value):
        raise Stop(f'{what} holds a path under the home directory in ~/ form')


def check_specs(specs, paths):
    seen_n = set()
    for kind, n, text, reason in specs:
        if n in seen_n:
            raise Stop(f'two specs for criterion {n}')
        seen_n.add(n)
        if kind != 'withdraw':
            if not text.strip():
                raise Stop(f'--{kind} {n} has an empty text')
            check_text(text, f'the text of {n}', paths)
        if not reason.strip():
            raise Stop(f'--{kind} {n} has an empty reason')
        check_text(reason, f'the reason of {n}', paths)
        if DASH in reason or reason.startswith(DASH.lstrip()):
            raise Stop(f'the reason of {n} holds " — "')


def plan_lines(specs, report, url):
    """The lines to write, against the block as reported; Stop on a spec the block refuses."""
    used = collections.defaultdict(list)
    for e in report['lines']:
        p = parse(e['line'])
        if 'number' in p:
            used[p['number']].append(p['k'])
    eff = {int(n): t for n, t in report['effective'].items()}
    out = []
    for kind, n, text, reason in specs:
        if kind == 'add':
            if used[n]:
                raise Stop(f'--add {n}: criterion {n} already has a line')
            label = f'`{n}.`'
        else:
            if not used[n]:
                raise Stop(f'--{kind} {n}: no line of criterion {n} exists')
            if kind == 'withdraw' and n in eff and eff[n] is None:
                raise Stop(f'--withdraw {n}: criterion {n} is already withdrawn')
            label = f'`{n}-{max(used[n]) + 1}.`'
        link = f'([grounds]({url}))'
        line = f'{label}{DASH}{reason} {link}' if kind == 'withdraw' else f'{label} {text}{DASH}{reason} {link}'
        check_reads_back(line, kind, n, 0 if kind == 'add' else max(used[n]) + 1, text, reason, url)
        out.append(line)
    return out


def check_reads_back(line, kind, n, k, text, reason, url):
    p = parse(line)
    got = (p.get('error'), p.get('number'), p.get('k'), p.get('withdraw'), p.get('text'), p.get('reason'), p.get('url'))
    want = (None, n, k, kind == 'withdraw', '' if kind == 'withdraw' else text, reason, url)
    if got != want:
        raise Stop(f'--{kind} {n}: the line {json.dumps(line, ensure_ascii=False)} would not read back as this spec '
                   f'(a text or reason that starts with or holds " — " can make it read otherwise)')


def compose(body, new_lines):
    body = body or ''
    raw = body.split('\n')
    span = block_span(split_lines(body))
    if span is None:
        head = body if not body or body.endswith('\n') else body + '\n'
        sep = '\n' if body else ''
        return f'{head}{sep}{HEADING}\n\n{START}\n' + ''.join(l + '\n' for l in new_lines) + f'{END}\n'
    cr = '\r' if raw[span[1]].endswith('\r') else ''
    return '\n'.join(raw[:span[1]] + [l + cr for l in new_lines] + raw[span[1]:])


# --- GitHub --------------------------------------------------------------------------------------------------

class GitHub:
    def __init__(self, repo, number):
        self.repo, self.number = repo, number
        self.issue_path = f'repos/{repo}/issues/{number}'

    def api(self, what, args, stdin=None, timeout=READ_TIMEOUT):
        try:
            p = subprocess.run(['gh', 'api', *args], input=stdin, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise TimeoutError(what)
        if p.returncode:
            raise GhError(what, p.stderr.strip() or f'gh exited {p.returncode}')
        try:
            return json.loads(p.stdout) if p.stdout.strip() else None
        except ValueError:
            raise Stop(f'{what}: gh printed no JSON')

    def account(self):
        login = login_of(self.api('reading the account', ['user']))
        if not isinstance(login, str) or not login:
            raise Stop('gh api user returned no login for the token in use')
        return login

    def issue_body(self):
        return self.api('reading the issue', [self.issue_path]).get('body') or ''

    def page(self, after):
        owner, name = self.repo.split('/', 1)
        args = ['graphql', '-f', f'query={HISTORY_QUERY}', '-f', f'owner={owner}', '-f', f'name={name}',
                '-F', f'number={self.number}']
        if after:
            args += ['-f', f'after={after}']
        out = self.api('reading the edit history', args)
        if not isinstance(out, dict) or out.get('errors'):
            raise Stop(f'reading the edit history: {json.dumps((out or {}).get("errors"))}')
        issue = ((out.get('data') or {}).get('repository') or {}).get('issue')
        if not issue:
            raise Stop('reading the edit history: no issue in the answer')
        issue['body'] = issue.get('body') or ''
        return issue

    def history(self):
        return read_history(self.page)

    def comment(self, cid):
        try:
            return self.api(f'reading comment {cid}', [f'repos/{self.repo}/issues/comments/{cid}'])
        except GhError as e:
            if e.status == 404:
                return None
            raise

    def post_comment(self, text):
        return self.api('posting the grounds comment', [f'{self.issue_path}/comments', '-X', 'POST',
                                                        '--input', '-'], stdin=json.dumps({'body': text}))

    def patch_body(self, body):
        return self.api('writing the body', [self.issue_path, '-X', 'PATCH', '--input', '-'],
                        stdin=json.dumps({'body': body}), timeout=WRITE_TIMEOUT)


def explain(e):
    if isinstance(e, GhError) and e.status == 403:
        return f'{e} (the token needs Issues: write on the repository; not retried)'
    if isinstance(e, GhError) and e.status == 429:
        return f'{e} (rate limited; not retried)'
    if isinstance(e, GhError) and e.status == 422 and e.args[0].startswith('writing the body'):
        return f'{e} (GitHub refused the body)'
    return str(e)


# --- the run -------------------------------------------------------------------------------------------------

class Run:
    def __init__(self, run_dir):
        self.dir = os.path.abspath(run_dir)
        self.name = os.path.basename(self.dir.rstrip('/'))
        try:
            env = dict(l.rstrip('\n').split('=', 1) for l in open(os.path.join(self.dir, 'run.env')) if '=' in l)
        except OSError as e:
            raise Stop(f'{self.dir}: no run.env ({e})')
        if not env.get('CHECKOUT') or not NUMBER.fullmatch(env.get('ISSUE', '')):
            raise Stop(f'{self.dir}/run.env: CHECKOUT and ISSUE are required')
        self.checkout, self.number = env['CHECKOUT'], int(env['ISSUE'])
        workspace = os.path.dirname(self.checkout.rstrip('/'))
        try:
            repo = json.load(open(os.path.join(workspace, 'repo.json')))
        except (OSError, ValueError) as e:
            raise Stop(f'{workspace}/repo.json: {e}')
        if not isinstance(repo, dict) or not isinstance(repo.get('github'), str) or not REPO.fullmatch(repo['github']):
            raise Stop(f'{workspace}/repo.json: github must be <owner>/<name> '
                       f'({repo.get("github") if isinstance(repo, dict) else repo!r})')
        self.repo = repo['github']
        root = os.path.dirname(os.path.dirname(self.dir))
        home = os.path.expanduser('~')
        self.paths = sorted({p for x in (home, root, self.checkout, env.get('RECORDS'))
                             if x and x != '/' for p in (x, os.path.realpath(x))}, key=len, reverse=True)
        self.state_path = os.path.join(self.dir, 'criteria.json')
        self.gh = GitHub(self.repo, self.number)

    def load(self):
        try:
            s = json.load(open(self.state_path))
        except FileNotFoundError:
            s = {}
        except ValueError as e:
            raise Stop(f'{self.state_path}: not JSON ({e})')
        problem = state_problem(s)
        if problem:
            raise Stop(f'{self.state_path}: {problem}; it is not changed')
        s.setdefault('written', [])
        s.setdefault('seen', None)
        s.setdefault('overwritten', [])
        return s

    def save(self, s):
        tmp = self.state_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(s, f, indent=1, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp, self.state_path)

    def report(self, issue, state, account):
        return evaluate(issue, account=account, repo=self.repo, number=self.number, get_comment=self.gh.comment,
                        seen=state['seen'], own=[w['line'] for w in state['written']])

    def fetch(self):
        issue = self.gh.history()
        check_history(issue)
        return issue


def state_problem(s):
    """What makes a criteria.json not the shape this tool writes, or None."""
    def lines_of(v):
        return isinstance(v, list) and all(isinstance(x, dict) and isinstance(x.get('line'), str) for x in v)
    if not isinstance(s, dict):
        return 'not a JSON object'
    if 'written' in s and not lines_of(s['written']):
        return 'written is not a list of lines'
    if 'overwritten' in s and not isinstance(s['overwritten'], list):
        return 'overwritten is not a list'
    shown = s.get('read')
    if shown is not None and not (isinstance(shown, dict) and (shown.get('lines') is None or (
            isinstance(shown['lines'], list) and all(isinstance(x, str) for x in shown['lines'])))):
        return 'read is not the block a read printed'
    seen = s.get('seen')
    if seen is None:
        return None
    if not isinstance(seen, dict):
        return 'seen is not an object'
    if not isinstance(seen.get('last_line'), str):
        return 'seen has no last_line'
    if not isinstance(seen.get('lines'), list) or not all(isinstance(x, str) for x in seen['lines']):
        return 'seen has no list of lines'
    if not lines_of(seen.get('accepted')):
        return 'seen has no list of accepted lines'
    if not isinstance(seen.get('effective'), dict):
        return 'seen has no effective criteria'
    if not isinstance(seen.get('dropped', []), list):
        return 'seen.dropped is not a list'
    return None


def emit(obj):
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def cmd_read(run):
    state = run.load()
    account = run.gh.account()
    issue = run.fetch()
    report = run.report(issue, state, account)
    for e in report['lines']:
        e.pop('accepted', None)
    state['read'] = {'lines': block_lines(issue['body']), 'time': now()}
    run.save(state)
    emit(report)


def cmd_seen(run, last, drops):
    state = run.load()
    account = run.gh.account()
    issue = run.fetch()
    shown = state.get('read')
    if shown is not None:
        unshown = collections.Counter(block_lines(issue['body']) or []) - collections.Counter(shown['lines'] or [])
        if unshown:
            raise Stop(f'the block holds lines the read at {shown.get("time")} did not print: '
                       + json.dumps(sorted(unshown.elements()), ensure_ascii=False) + '; run read again and assess them')
    report = run.report(issue, state, account)
    if report['last_line'] != last:
        raise Stop(f'the last line is {json.dumps(report["last_line"], ensure_ascii=False)}, not the one given')
    check_drops(drops, report['difference'])
    previous = state['seen'] or empty_seen()
    state['seen'] = make_seen(report, previous, drops, change=report['difference']['new'])
    run.save(state)
    log(f'seen recorded: last line {report["last_line"]}, {len(state["seen"]["accepted"])} accepted lines')


def overwritten(issue, reread, written, after):
    """The versions after the last version before the write whose body equals the re-read body, up to the
    write, with whether each block line a version held is present in the body read after the write."""
    vs, _, _ = versions(issue)
    wi = max((i for i, v in enumerate(vs) if same(v['body'], written)), default=None)
    if wi is None:
        return []
    ri = max((i for i, v in enumerate(vs[:wi]) if same(v['body'], reread)), default=None)
    if ri is None:
        return []
    out = []
    for i in range(ri + 1, wi):
        v, before = vs[i], vs[i - 1]
        if v['body'] is None:
            why, lines = 'content deleted, so what it held is unknown', []
        else:
            lines = [{'line': l, 'present': present(after, l)} for l in lenient_lines(v['body'])]
            if before['body'] is not None and outside_block(v['body']) != outside_block(before['body']):
                why = 'changed text outside the block'
            else:
                why = 'changed the block'
        out.append({'editor': v['editor'], 'time': v['time'], 'why': why, 'lines': lines})
    return out


def only_own(report, own_lines):
    d, own = report['difference'], set(own_lines)
    if d['missing'] or any(not n['own'] for n in d['new']):
        return False
    if d['last_line'] and d['last_line']['now'] not in own:
        return False
    numbers = {parse(l).get('number') for l in own}
    return all(n in numbers for n in d['changed'])


def cmd_append(run, grounds, drops, specs):
    if not specs:
        raise Stop('append needs at least one spec')
    check_specs(specs, run.paths)
    try:
        text = open(grounds).read().rstrip()
    except OSError as e:
        raise Stop(f'--grounds: {e}')
    if not text.strip():
        raise Stop('the grounds comment is empty')
    local_path(text, 'the grounds comment', run.paths)
    full = f'{text}\n\nRun record: {run.name}'
    if len(full) > COMMENT_MAX:
        raise Stop(f'the grounds comment is {len(full)} characters with its run record line, over {COMMENT_MAX}')
    numbers = {n for _, n, _, _ in specs}

    state = run.load()
    account = run.gh.account()
    comment, previous_lines, mine, reported = None, None, [], []
    for attempt in range(1, ATTEMPTS + 1):
        rest_body = run.gh.issue_body()
        issue = run.gh.history()
        if not same(issue['body'], rest_body):
            log(f'restart: attempt {attempt}: the GraphQL body ({sha(issue["body"])}) differs from the REST body '
                f'({sha(rest_body)})')
            continue
        check_history(issue)
        report = run.report(issue, state, account)
        current = block_lines(rest_body) or []
        if comment is None:
            d = report['difference']
            if drops:
                try:
                    check_restore(drops, d)
                except Stop:
                    print(json.dumps({'difference': d}, indent=1, ensure_ascii=False), file=sys.stderr)
                    raise
            elif any_difference(d):
                print(json.dumps({'difference': d}, indent=1, ensure_ascii=False), file=sys.stderr)
                raise Stop('the block differs from the state last accepted (seen); assess it and record it with seen')
        elif previous_lines is not None:
            added = collections.Counter(current) - collections.Counter(previous_lines) - collections.Counter(mine)
            hit = sorted(l for l in added if parse(l).get('number') in numbers)
            if hit:
                raise Stop('another writer added a line of a criterion this call writes: '
                           + json.dumps(hit, ensure_ascii=False) + f'; the comment {comment["html_url"]} stays unlinked')
        previous_lines = current
        url = comment['html_url'] if comment else 'https://github.com/{}/issues/{}#issuecomment-0'.format(
            run.repo, run.number)
        plan_lines(specs, report, url)
        if comment is None:
            comment = run.gh.post_comment(full)
            log(f'comment posted: {comment["html_url"]}')
        mine = plan_lines(specs, report, comment['html_url'])
        body = compose(rest_body, mine)
        log(f'compose: attempt {attempt}, read {sha(rest_body)}, composed {sha(body)}')

        started = time.monotonic()
        reread = run.gh.issue_body()
        equal = reread == rest_body
        log(f're-read: {sha(reread)}, {"equal" if equal else "changed"}')
        if not equal:
            log('restart: the body changed since the compose read')
            continue
        age = time.monotonic() - started
        log(f'age check: {age:.1f} s since the re-read began')
        if age > REREAD_AGE:
            log(f'restart: more than {REREAD_AGE} s since the re-read began')
            continue
        log(f'write sent: {sha(body)}')
        try:
            out = run.gh.patch_body(body)
            log(f'write returned: {sha((out or {}).get("body") or "")}')
        except TimeoutError:
            log(f'write timed out after {WRITE_TIMEOUT} s: its state is unknown; step 3 decides')
        state['written'] = [w for w in state['written'] if w['line'] not in mine] + [
            {'line': l, 'comment_id': comment['id'], 'comment_url': comment['html_url'], 'time': now(),
             'present': None} for l in mine]
        run.save(state)

        wait = random.uniform(60, 100)
        log(f'wait: {wait:.1f} s')
        time.sleep(wait)
        after = run.gh.issue_body()
        ok = True
        for w in state['written']:
            w['present'] = present(after, w['line'])
            if w['line'] in mine:
                ok = ok and w['present']
            log(f'step 3: {"present" if w["present"] else "absent"}: {w["line"]}')
        hist = run.gh.history()
        for o in overwritten(hist, reread, body, after):
            reported.append(o)
            state['overwritten'].append(dict(o, attempt=attempt, comment=comment['html_url']))
            absent = [x['line'] for x in o['lines'] if not x['present']]
            log(f'overwritten edit: {o["editor"]} at {o["time"]}: {o["why"]}; '
                + (f'absent after the write: {json.dumps(absent, ensure_ascii=False)}' if absent
                   else 'every block line it held is present'))
        run.save(state)
        if ok:
            break
        log('restart: a line of this attempt is absent')
    else:
        raise Stop(f'no write confirmed in {ATTEMPTS} attempts' + (f'; the comment {comment["html_url"]} '
                                                                    'stays unlinked' if comment else ''))

    if drops:
        seen = state['seen'] or empty_seen()
        left = collections.Counter(drops)
        kept = []
        for a in seen['accepted']:
            if left[a['line']] > 0:
                left[a['line']] -= 1
            else:
                kept.append(a)
        seen['accepted'] = kept
        seen['dropped'] = seen.get('dropped', []) + [{'line': d, 'time': now(), 'change': 'restored by '
                                                      + ', '.join(mine)} for d in drops]
        state['seen'] = seen
    if same(hist['body'], after):
        check_history(hist)
        final = run.report(hist, state, account)
        if only_own(final, mine):
            state['seen'] = make_seen(final, state['seen'] or empty_seen())
            log('seen advanced over this run\'s own lines')
        else:
            log('seen not advanced: the block holds changes this call did not write')
    run.save(state)
    emit({'lines': [{'line': w['line'], 'present': w['present']} for w in state['written']],
          'overwritten': reported})


def parse_args(argv):
    if len(argv) < 2:
        raise Stop(__doc__.split('\n')[0])
    run_dir, cmd, rest = argv[0], argv[1], argv[2:]
    if cmd == 'read' and not rest:
        return run_dir, cmd, {}
    if cmd == 'seen' and rest:
        last, drops, i = rest[0], [], 1
        while i < len(rest):
            if rest[i] != '--drop' or i + 1 >= len(rest):
                raise Stop(f'seen: unexpected {rest[i]!r}')
            drops.append(rest[i + 1])
            i += 2
        return run_dir, cmd, {'last': last, 'drops': drops}
    if cmd == 'append':
        grounds, drops, specs, i = None, [], [], 0
        arity = {'--revise': 3, '--withdraw': 2, '--add': 3}
        while i < len(rest):
            a = rest[i]
            if a in ('--grounds', '--drop') and i + 1 < len(rest):
                if a == '--grounds':
                    grounds = rest[i + 1]
                else:
                    drops.append(rest[i + 1])
                i += 2
            elif a in arity and i + arity[a] < len(rest) + 1:
                vals = rest[i + 1:i + 1 + arity[a]]
                if len(vals) < arity[a] or not NUMBER.fullmatch(vals[0]):
                    raise Stop(f'{a}: needs a criterion number and {"a reason" if a == "--withdraw" else "a text and a reason"}')
                kind = a[2:]
                text, reason = ('', vals[1]) if kind == 'withdraw' else (vals[1], vals[2])
                specs.append((kind, int(vals[0]), text, reason))
                i += 1 + arity[a]
            else:
                raise Stop(f'append: unexpected {a!r}')
        if grounds is None:
            raise Stop('append needs --grounds <comment file>')
        return run_dir, cmd, {'grounds': grounds, 'drops': drops, 'specs': specs}
    raise Stop(__doc__.split('\n')[0])


def main(argv):
    try:
        run_dir, cmd, args = parse_args(argv)
        run = Run(run_dir)
        if cmd == 'read':
            cmd_read(run)
        elif cmd == 'seen':
            cmd_seen(run, **args)
        else:
            cmd_append(run, **args)
    except TimeoutError as e:
        log(f'STOP {e}: gh did not answer within {READ_TIMEOUT} s')
        return 1
    except Stop as e:
        log(f'STOP {explain(e)}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
