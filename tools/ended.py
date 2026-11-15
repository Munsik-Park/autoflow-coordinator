"""ended.py — record that a module run ended, and what its work folder held, without judging the output.

A module run writes only inside its work folder <records>/<module>-<n>/, and the coordinator's files of that
run sit beside the folder under the same name. When the work session that was given an invocation ends its
turn, tools/watch.py calls record() to write the end record <records>/<module>-<n>.ended.json beside the
invocation, the place tools/status.py and tools/check.sh read a run's end from:

  {"status": "ended", "outputs": {"files": [every file in the work folder, as a path]}}

"ended" says only that the session stopped. Whether the run reached its goal is read from the work folder by
the coordination session. No file in the work folder is checked, read or written, whatever its name. An
invocation that already has an end record is left as it is.
"""
import glob, json, os

STATUS = 'ended'
# The coordinator's files of a module run, by what follows the run's name <module>-<n>: the invocation, the
# instruction file and the end record.
INVOCATION, PROMPT, ENDED = '.invocation.json', '.prompt.txt', '.ended.json'


def end_record_of(invocation_file):
    """The path of the end record of the module run this invocation file belongs to."""
    return invocation_file[:-len(INVOCATION)] + ENDED


def files_in(folder):
    found = []
    for d, _, names in os.walk(folder):
        found += [os.path.join(d, n) for n in names]
    return sorted(found)


def record(records, transcript):
    """Writes the end record of each invocation in records that the transcript names and that has none yet.
    Returns the paths written."""
    try:
        text = open(transcript, errors='replace').read()
    except OSError:
        return []
    written = []
    for path in sorted(glob.glob(os.path.join(records or '', '*' + INVOCATION))):
        if f'/{os.path.basename(path)}' not in text:
            continue
        try:
            out = json.load(open(path)).get('out')
        except (OSError, ValueError, AttributeError):
            continue
        if not isinstance(out, str) or not out or os.path.exists(end_record_of(path)):
            continue
        ended = json.dumps({'status': STATUS, 'outputs': {'files': files_in(out)}}, ensure_ascii=False, indent=2)
        try:
            with open(end_record_of(path), 'x') as f:
                f.write(ended + '\n')
        except FileExistsError:
            continue
        written.append(end_record_of(path))
    return written
