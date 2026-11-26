#!/usr/bin/env python3
"""module_settings.py <instruction file> [--model <model>] [--without-autoflow] — the model and effort
flags of the session tools/launch.sh starts, as the text to put on that session's command line.

A launch is for a module's run when it is not --without-autoflow and the instruction file is
<name>.prompt.txt with <name>.invocation.json a file beside it. The module is that invocation's "module".
For such a launch the module's setting is read from the place tools/config.py module-settings prints
(<home>/config.json), anew on every call:

  {"module": {"<module name>": {"model": "<model>", "effort": "<effort>"}}}

Model: the --model argument, then the module's "model", then the module's default, then no flag.
Effort: the module's "effort", then the module's default, then no flag. DEFAULTS holds the defaults.
For any other launch nothing is read: the flags are the --model argument's, or none.

Prints one line, "--model <model> --effort <effort>" with only the flags that apply, or nothing. What it
prints is printable ASCII and one word per value for bash and zsh alike: the line is typed into a
terminal, where a raw control character acts as a key, and the shell that reads it is the surface's own.

Stops with exit status 1, printing nothing and naming the file and the error on stderr, when a module
run's invocation gives no module, when tools/config.py cannot report the place, or when the file is
present and its module settings cannot be read as configured (SETTINGS.md > Module settings).
"""
import json, os, re, subprocess, sys

from ended import INVOCATION, PROMPT

KEY = 'module'
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
DEFAULTS = {'criterion-decision': {'model': 'fable', 'effort': 'max'}}
SECTION = 'SETTINGS.md > Module settings'
# The characters a value is written with as it is. Any other value is written quoted: '=' is left out
# because zsh expands a word that begins with it.
PLAIN = re.compile(rb'[A-Za-z0-9_@%+:,./-]+')


def stop(where, error):
    sys.exit(f'{where}: {error} ({SECTION})')


def word(value):
    """The value as one shell word in printable ASCII: as it is, or in $'…' with the quote, the
    backslash and every byte outside printable ASCII as \\xHH, which bash 3.2 and zsh read alike."""
    if PLAIN.fullmatch(value):
        return value.decode('ascii')
    return "$'" + ''.join(chr(b) if 0x20 <= b <= 0x7E and b not in b"'\\" else f'\\x{b:02x}'
                          for b in value) + "'"


def module_of(invocation):
    """The module the invocation file names."""
    try:
        with open(invocation, 'rb') as f:
            d = json.loads(f.read().decode('utf-8'))
    except (OSError, ValueError) as e:
        stop(invocation, e)
    if not isinstance(d, dict):
        stop(invocation, 'not a JSON object')
    module = d.get('module')
    if not isinstance(module, str) or not module:
        stop(invocation, 'no module name in "module"')
    return module


def settings_file():
    config = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.py')
    p = subprocess.run([sys.executable, config, 'module-settings'], capture_output=True, text=True)
    if p.returncode:
        stop('tools/config.py module-settings', p.stderr.strip() or f'exit status {p.returncode}')
    return p.stdout.rstrip('\n')


def carried(model):
    """The model's bytes as a command line carries them, or None when none can."""
    try:
        b = model.encode('utf-8')
    except UnicodeEncodeError:
        return None
    return None if b'\0' in b else b


def module_settings(path):
    """Every module's entry of the settings file, each checked whichever module is launched."""
    try:
        with open(path, 'rb') as f:
            text = f.read()
    except FileNotFoundError:
        return {}
    except OSError as e:
        stop(path, e.strerror or e)
    try:
        d = json.loads(text.decode('utf-8'))
    except ValueError as e:
        stop(path, f'not JSON ({e})')
    if not isinstance(d, dict):
        stop(path, 'not a JSON object')
    if KEY not in d:
        return {}
    entries = d[KEY]
    if not isinstance(entries, dict):
        stop(path, f'.{KEY} is not an object')
    for name, entry in entries.items():
        at = f'.{KEY}.{json.dumps(name)}'
        if not isinstance(entry, dict):
            stop(path, f'{at} is not an object')
        for k in ('model', 'effort'):
            if k in entry and (not isinstance(entry[k], str) or not entry[k]):
                stop(path, f'{at}.{k} is empty or not a string')
        if 'model' in entry and carried(entry['model']) is None:
            stop(path, f'{at}.model holds a character no command line can carry')
        if 'effort' in entry and entry['effort'] not in EFFORTS:
            stop(path, f'{at}.effort is {json.dumps(entry["effort"])}, not one of {" ".join(EFFORTS)}')
    return entries


def main(argv):
    prompt, model, autoflow, args = None, None, True, list(argv)
    while args:
        a = args.pop(0)
        if a == '--without-autoflow':
            autoflow = False
        elif a == '--model':
            if not args or not args[0]:
                sys.exit('--model needs the model name')
            model = os.fsencode(args.pop(0))
        elif prompt is None:
            prompt = a
        else:
            sys.exit(__doc__.split(' — ')[0])
    if prompt is None:
        sys.exit(__doc__.split(' — ')[0])
    effort = None
    invocation = prompt[:-len(PROMPT)] + INVOCATION
    if autoflow and os.path.basename(prompt).endswith(PROMPT) and os.path.isfile(invocation):
        module = module_of(invocation)
        entry = {**DEFAULTS.get(module, {}), **module_settings(settings_file()).get(module, {})}
        if model is None and 'model' in entry:
            model = carried(entry['model'])
        effort = entry.get('effort')
    flags = []
    if model is not None:
        flags += ['--model', word(model)]
    if effort is not None:
        flags += ['--effort', word(effort.encode('ascii'))]
    if flags:
        print(' '.join(flags))


if __name__ == '__main__':
    main(sys.argv[1:])
