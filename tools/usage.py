#!/usr/bin/env python3
"""usage.py <run-dir> [LABEL=<session-id> | LABEL=<project-dir>:<session-id> ...]

Tokens and cost of a run's sessions: every row of sessions.tsv (main transcript + subagents) under the
Claude project directory of run.env CHECKOUT, plus each extra LABEL. A bare session id is looked up
under the Claude project directory of this tool clone.

A message counts once: of each message id, the last usage record with the most output tokens. Cost is $/MTok from the table
below; a model not in it is counted as `unpriced`.
"""
import collections, glob, json, os, re, sys

# $/MTok: input, 5m cache write, 1h cache write, cache read, output.
# Haiku 5.5 is the price for prompts up to 100K tokens.
PRICE = {
    'claude-opus-5-5': (4, 5, 8, 0.20, 20),
    'claude-sonnet-5-5': (2, 2.5, 4, 0.20, 10),
    'claude-fable-5-1': (10, 12.5, 20, 0.25, 50),
    'claude-haiku-5-5': (0.10, 0.125, 0.20, 0.01, 0.50),
}
PROJECTS = os.path.expanduser('~/.claude/projects')
project = lambda path: os.path.join(PROJECTS, re.sub(r'[^A-Za-z0-9]', '-', path))
COORD = project(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def messages(path):
    last = {}
    if not os.path.exists(path):
        return []
    for line in open(path, errors='replace'):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get('type') != 'assistant':
            continue
        m = d.get('message') or {}
        u, mid = m.get('usage'), m.get('id')
        if not u or not mid:
            continue
        if mid not in last or u.get('output_tokens', 0) >= last[mid][1].get('output_tokens', 0):
            last[mid] = (m.get('model'), u)
    return list(last.values())


def add(c, model, u):
    cc = u.get('cache_creation') or {}
    w5, w1 = cc.get('ephemeral_5m_input_tokens'), cc.get('ephemeral_1h_input_tokens')
    if w5 is None and w1 is None:
        w5, w1 = 0, u.get('cache_creation_input_tokens', 0)
    w5, w1 = w5 or 0, w1 or 0
    i, r, o = u.get('input_tokens', 0), u.get('cache_read_input_tokens', 0), u.get('output_tokens', 0)
    c['req'] += 1; c['in'] += i; c['cw'] += w5 + w1; c['cr'] += r; c['out'] += o
    p = PRICE.get(model)
    if p:
        c['usd'] += (i * p[0] + w5 * p[1] + w1 * p[2] + r * p[3] + o * p[4]) / 1e6
    else:
        c['unpriced'] += 1


def session(proj, sid):
    main, subs = collections.Counter(), collections.OrderedDict()
    for model, u in messages(os.path.join(proj, sid + '.jsonl')):
        add(main, model, u)
    for meta in sorted(glob.glob(os.path.join(proj, sid, 'subagents', '*.meta.json')), key=os.path.getmtime):
        role = json.load(open(meta)).get('agentType', '?').split(':')[-1].replace('autoflow-', '')
        c = subs.setdefault(role, collections.Counter())
        c['n'] += 1
        for model, u in messages(meta[:-len('.meta.json')] + '.jsonl'):
            add(c, model, u)
    return main, subs


def fmt(c):
    return (f"req {c['req']:4} cache_w {c['cw']/1e3:7.0f}k cache_r {c['cr']/1e6:7.2f}M "
            f"out {c['out']/1e3:6.1f}k ${c['usd']:7.2f}")


run = sys.argv[1]
env = dict(l.strip().split('=', 1) for l in open(os.path.join(run, 'run.env')) if '=' in l)
rows = [(s, project(env['CHECKOUT']), sid) for s, _, sid in
        (r.rstrip('\n').split('\t') for r in open(os.path.join(run, 'sessions.tsv')) if r.strip())]
for extra in sys.argv[2:]:
    label, ref = extra.split('=', 1)
    proj, sid = ref.rsplit(':', 1) if ':' in ref else (COORD, ref)
    rows.append((label, proj, sid))

total = collections.Counter()
for label, proj, sid in rows:
    if not os.path.exists(os.path.join(proj, sid + '.jsonl')):
        print(f"{label:6} no transcript {proj}/{sid}.jsonl")
        continue
    main, subs = session(proj, sid)
    t = collections.Counter(main)
    for c in subs.values():
        t.update(c)
    total.update(t)
    print(f"{label:6} TOTAL {fmt(t)}")
    print(f"{'':6}  main {fmt(main)}")
    for role, c in subs.items():
        print(f"{'':6}  {role[:22]:22} x{c['n']} {fmt(c)}")
print(f"ALL    {fmt(total)}  unpriced={total['unpriced']}")
