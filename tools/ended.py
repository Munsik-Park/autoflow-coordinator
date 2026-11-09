"""ended.py — record that a module run ended, and where its output is, without judging the output.

A module run defined by a SKILL.md writes only what its definition names. When the work session that was
given an invocation ends its turn, tools/watch.py calls record() to write <out>/result.json, the place
tools/status.py and the IDE read a run's end from:

  {"status": "ended", "outputs": {"files": [every file in <out>, as a path]}}

"ended" says only that the session stopped. Whether the run reached its goal is read from the output by the
coordination session. No file in the output is checked. An invocation whose output already has a result.json
is left as it is.
"""
import glob, json, os

STATUS = 'ended'


def files_in(out):
    found = []
    for d, _, names in os.walk(out):
        found += [os.path.join(d, n) for n in names if not (d == out and n == 'result.json')]
    return sorted(found)


def record(records, transcript):
    """Writes result.json for each invocation in records that the transcript names and that has none yet.
    Returns the result.json paths written."""
    try:
        text = open(transcript, errors='replace').read()
    except OSError:
        return []
    written = []
    for path in sorted(glob.glob(os.path.join(records or '', '*.invocation.json'))):
        stem = os.path.basename(path)[:-len('.invocation.json')]
        if f'/{stem}.invocation.json' not in text:
            continue
        try:
            out = json.load(open(path)).get('out')
        except (OSError, ValueError, AttributeError):
            continue
        result = os.path.join(out, 'result.json') if isinstance(out, str) and out else None
        if not result or os.path.exists(result):
            continue
        os.makedirs(out, exist_ok=True)
        with open(result, 'w') as f:
            json.dump({'status': STATUS, 'outputs': {'files': files_in(out)}}, f, ensure_ascii=False, indent=2)
            f.write('\n')
        written.append(result)
    return written
