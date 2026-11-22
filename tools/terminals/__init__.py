"""The terminal operations coordination needs. One module per terminal in this package.

A module provides every operation below. A terminal that cannot provide them all is not supported.
A module's name is the terminal's name, and the workspaces and surfaces it takes and returns are its
own ids. A surface is the place one session runs in. An id matches UNQUOTED and stays the same while
the surface lives. A terminal without workspaces returns a fixed workspace.

Every module in this package counts as a terminal, so code shared between terminals lives in this file.

An operation that does not reach its result raises TerminalError.

To add a terminal: add its module, then pass the conformance test inside that terminal.
"""
import importlib, pkgutil, re, time

# One shell word that needs no quoting.
UNQUOTED = re.compile(r'[\w@%+=:,./-]+')
# A choice or permission prompt on a Claude Code screen.
INPUT_RE = re.compile(r'Do you want to|Enter to select|Esc to cancel|❯ \d+\.|Would you like to')
# A rule above or below Claude Code's input area.
INPUT_RULE_RE = re.compile(r'^─{3,}.*$', re.M)
# A permission prompt's question and its footer.
PERMISSION_RE = re.compile(r'Do you want to proceed\?|Esc to cancel · Tab to amend')
# The footer of a choice question page.
QUESTION_FOOTER = 'Enter to select ·'
# A row of a choice question page, its number, and the focused one.
NUMBERED_ROW_RE = re.compile(r'^[❯ ] (\d+)\. ')
FOCUSED_ROW_RE = re.compile(r'^❯ (\d+)\. ')
SUBMIT_ROW_RE = re.compile(r'^[❯ ]\s+Submit\s*$')
# All that an empty input area holds.
EMPTY_INPUT = '❯'
# Over about 1 KB, Claude Code was seen to fold the input or lose its start. Longer content goes in a file.
MAX_SUBMIT_BYTES = 700
# More lines than a screen has: read_screen stops at the screen, so this reads all of it.
WHOLE_SCREEN = 5000
# Rows of the sessions' row when it is made below a surface, a start the operator resizes from.
SESSION_ROW_HEIGHT = 15
# The keys press sends.
KEYS = ('down', 'enter')
# How long a key's effect may take to show on the screen.
KEY_WAIT = 5

OPERATIONS = {
    'inside': 'inside() -> bool: this process runs in this terminal; from the environment alone, since detect() asks every module, also where the terminal\'s command is missing',
    'caller': 'caller() -> (workspace, surface): where this process runs, not where the focus is',
    'split': 'split(workspace, surface, direction) -> surface: a new one with a shell, the focus staying; direction \'below\' takes SESSION_ROW_HEIGHT rows, or half the given one if that is less, and direction \'right\' half its width, and no other surface changes size; exists() is true for it on return; on a failure, what it made is closed or named in the error',
    'geometry': 'geometry(workspace, surface) -> (left, top, columns, rows): columns and rows in cells; left and top in a unit of the terminal\'s own that orders surfaces',
    'send_line': 'send_line(workspace, surface, text): type one line and press Enter; refuse if the terminal would not pass the keys to the surface',
    'submit': 'submit(workspace, surface, text): enter the text, its lines kept apart from blank ones at its start and end, as one ordinary message, not as pasted material, and submit it, a slash command on its first line running as one; refuse, entering nothing, if it is over MAX_SUBMIT_BYTES or a dialog or a draft holds the input; press Enter only if the input area shows the text just before, or refuse, since Enter would answer a dialog that opened meanwhile',
    'press': 'press(workspace, surface, key): send one key of KEYS to the surface, also into an open dialog; refuse any other key',
    'type_at_focus': 'type_at_focus(workspace, surface, text): enter text where the focus is, also into an open dialog, as typed text, not as pasted material; each line feed is a line break, not Enter; no Enter is pressed and nothing is checked, so the caller reads the screen before and after',
    'read_screen': 'read_screen(workspace, surface, lines) -> str: the last lines of its screen, not counting blank lines below the content',
    'rename': 'rename(workspace, surface, name): the name shown for it',
    'exists': 'exists(workspace, surface) -> bool',
    'close': 'close(workspace, surface): close it, with any other surface the terminal keeps in its place, once its session has ended',
}


class TerminalError(Exception):
    pass


def input_held(screen):
    """Why a Claude Code screen cannot take a message, or None. Only an input area recognised as empty
    passes: a draft, an input mode, a dialog and a screen this does not know all hold the input, so that
    what cannot be read stops the message visibly instead of mixing it with what is there. A prompt
    suggestion reads as a draft too."""
    area = input_area(screen)
    if area == EMPTY_INPUT:
        return None
    # A question's own text may read like a permission prompt, so a question page is named first.
    if dialog_rows(screen) is not None or review_answers(screen) is not None:
        return 'a choice question is open'
    if PERMISSION_RE.search(screen[list(INPUT_RULE_RE.finditer(screen))[-1].end():] if INPUT_RULE_RE.search(screen) else screen):
        return 'a permission prompt is open; it goes to the operator'
    if area is None:
        return 'no input area on the screen'
    return (f'the input area is not empty: {area.splitlines()[0] if area else ""!r} '
            '(if this is a prompt suggestion, the session needs promptSuggestionEnabled: false)')


def submit_refused(screen, text):
    """Why text cannot be entered on this screen, or None."""
    size = len(text.encode())
    return f'{size} bytes is over {MAX_SUBMIT_BYTES}: put it in a file' if size > MAX_SUBMIT_BYTES else input_held(screen)


def input_area(screen):
    """What Claude Code's input area shows, or None if the screen has none."""
    rules = list(INPUT_RULE_RE.finditer(screen))
    return screen[rules[-2].end():rules[-1].start()].strip() if len(rules) >= 2 else None


def input_holds(screen, text):
    """Whether the input area shows the end of text, so that Enter would submit it and nothing else. A tall
    text shows only its end, and may push the upper rule off the screen, and the screen wraps and indents
    lines, so whitespace does not count."""
    rules = list(INPUT_RULE_RE.finditer(screen))
    if not rules:
        return False
    area = screen[rules[-2].end() if len(rules) >= 2 else 0:rules[-1].start()].strip()
    shown = re.sub(r'\s+', '', area.removeprefix(EMPTY_INPUT))
    return bool(shown) and re.sub(r'\s+', '', text).endswith(shown)


def squeeze(text):
    return re.sub(r'\s+', '', text)


def bottom(screen):
    lines = screen.split('\n')
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def dialog_rows(screen):
    """The rows of a choice question page between the rule above the dialog (or the top of the screen) and
    the rule below its options, or None. The page ends in its footer, below a Chat about this row and a rule."""
    lines = bottom(screen)
    if not lines or not lines[-1].lstrip().startswith(QUESTION_FOOTER):
        return None
    chat = next((i for i in range(len(lines) - 2, -1, -1) if 'Chat about this' in lines[i]), None)
    rule = next((i for i in range(chat - 1, -1, -1) if INPUT_RULE_RE.match(lines[i])), None) if chat is not None else None
    if rule is None:
        return None
    top = next((i + 1 for i in range(rule - 1, -1, -1) if INPUT_RULE_RE.match(lines[i])), 0)
    return lines[top:rule]


def focused(rows):
    """The number of the focused row, 'submit' when the focus is on a multiSelect page's Submit row, or None."""
    for row in reversed(rows):
        m = FOCUSED_ROW_RE.match(row)
        if m:
            return int(m.group(1))
    return 'submit' if any(SUBMIT_ROW_RE.match(r) and r.startswith('❯') for r in rows) else None


def row_part(rows, number, first_line=False):
    """What row number shows after its number, squeezed: from its first line to the next row, the Submit row
    or the end of the rows. A row whose start is above the rows shown, with no numbered row shown, is all
    the rows. None if the row is not shown."""
    starts = [i for i, r in enumerate(rows) if NUMBERED_ROW_RE.match(r)]
    mine = [i for i in starts if int(NUMBERED_ROW_RE.match(rows[i]).group(1)) == number]
    if mine:
        shown = [NUMBERED_ROW_RE.sub('', rows[mine[-1]], 1)] + rows[mine[-1] + 1:]
    elif not starts:
        shown = rows
    else:
        return None
    end = 1 if first_line else next(
        (i for i, r in enumerate(shown) if i and (NUMBERED_ROW_RE.match(r) or SUBMIT_ROW_RE.match(r))), len(shown))
    return squeeze(' '.join(shown[:end]))


def unboxed(part):
    """A row's part without its multiSelect box."""
    return re.sub(r'^\[✔?\]', '', part)


def holds(part, text):
    """Whether a free-text row's part shows the end of text. A multiSelect row holds it only checked."""
    if part is None:
        return False
    shown = part.removeprefix('[✔]')
    return bool(shown) and not shown.startswith('[]') and squeeze(text).endswith(shown)


def question_page(screen, question):
    """Whether the screen shows the page of question, an entry of an AskUserQuestion call's questions: a
    question page with a focused row and its last option's row, numbered as in the call. The question's
    text and header are not needed: they may be above a short surface's top."""
    rows = dialog_rows(screen)
    if rows is None or focused(rows) is None:
        return False
    options = question['options']
    part = row_part(rows, len(options), first_line=True)
    return part is not None and unboxed(part) == squeeze(options[-1]['label'])


def free_text_holds(screen, text):
    """Whether the focused row of a question page shows the end of text, a multiSelect row with its box
    checked. A tall text shows only its end and may push the row's start off the screen, and the screen
    wraps and indents lines, so whitespace does not count."""
    rows = dialog_rows(screen)
    if rows is None:
        return False
    number = focused(rows)
    if number == 'submit' or number is None and any(NUMBERED_ROW_RE.match(r) for r in rows):
        return False
    return holds(row_part(rows, number or 0), text)


def review_answers(screen):
    """The answers a review page shows, squeezed, one per question, or None if the screen is not one."""
    lines = bottom(screen)
    if not lines or squeeze(lines[-1].replace('❯', '')) not in ('1.Submitanswers', '2.Cancel'):
        return None
    head = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == 'Review your answers'), None)
    if head is None:
        return None
    answers, current = [], None
    for line in lines[head + 1:]:
        if NUMBERED_ROW_RE.match(line.replace('❯', ' ', 1)):
            break
        if line.lstrip().startswith('●'):
            current = None
        elif line.lstrip().startswith('→'):
            current = len(answers)
            answers.append(squeeze(line.lstrip()[1:]))
        elif current is not None and line.strip():
            answers[current] += squeeze(line)
    return answers


def review_holds(screen, text):
    """Whether the screen is a review page with `1. Submit answers` focused and every answer showing text
    as far as the screen shows it. A multiSelect answer is quoted."""
    answers = review_answers(screen)
    if not answers or not any(squeeze(l) == '❯1.Submitanswers' for l in bottom(screen)):
        return False
    want = squeeze(text)

    def shows(answer):
        core = answer.strip('"').removesuffix('…')
        return want in answer or bool(core) and (want.startswith(core) or want.endswith(core))
    return all(shows(a) for a in answers)


def answer(term, workspace, surface, questions, text):
    """Enter text as the answer to every question of an open AskUserQuestion call, questions being its
    input's questions, and submit the call. The screen is read before every key, and a key goes only to the
    page it is meant for, so a run goes on from whatever page of the call is shown: a page whose free-text
    row is empty is answered, one whose row shows this text is submitted without typing it again, and the
    review page is submitted. Raises TerminalError naming the step reached, with nothing more entered."""
    if any('preview' in o for q in questions for o in q['options']):
        raise TerminalError('the question has no free-text row (options with previews); nothing was entered')
    size = len(text.encode())
    if size > MAX_SUBMIT_BYTES:
        raise TerminalError(f'{size} bytes is over {MAX_SUBMIT_BYTES}: put the details in a file the answer '
                            'names; nothing was entered')
    keys = Keys(term, workspace, surface)
    review = len(questions) > 1 or any(q.get('multiSelect') for q in questions)
    screen, expected = keys.read(), None
    for _ in range(len(questions) + 1):
        shown = review_answers(screen)
        if shown is not None:
            if expected not in (None, 'review'):
                raise TerminalError(f'the review page is shown before question {expected + 1} was answered')
            if len(shown) != len(questions) or not review_holds(screen, text):
                raise TerminalError('the review page does not show this text for every question with '
                                    '`1. Submit answers` focused; Enter not sent')
            term.press(workspace, surface, 'enter')
            return
        pages = [i for i, q in enumerate(questions) if question_page(screen, q)]
        if expected is None and not pages:
            raise TerminalError('no question page of this call on the screen; nothing was entered')
        i = expected if expected is not None else pages[0]
        before = answer_one(keys, i, questions[i], text, screen)
        if i == len(questions) - 1 and not review:
            return
        expected = i + 1 if i + 1 < len(questions) else 'review'
        target = (lambda s: review_answers(s) is not None) if expected == 'review' else \
            (lambda s, q=questions[expected]: question_page(s, q))
        screen = keys.settled(lambda s: s != before and target(s),
                              'the review page is not shown after Enter' if expected == 'review'
                              else f"question {expected + 1}'s page is not shown after Enter")
    raise TerminalError('the call did not end')


class Keys:
    """Keys to one surface, each followed by a wait for the screen to show its effect."""

    def __init__(self, term, workspace, surface):
        self.term, self.workspace, self.surface = term, workspace, surface

    def read(self):
        return self.term.read_screen(self.workspace, self.surface, WHOLE_SCREEN)

    def settled(self, ok, why):
        deadline = time.time() + KEY_WAIT
        while True:
            screen = self.read()
            if ok(screen):
                return screen
            if time.time() > deadline:
                raise TerminalError(why)
            time.sleep(0.2)

    def press(self, key, ok, why):
        self.term.press(self.workspace, self.surface, key)
        return self.settled(ok, why)

    def type(self, text, ok, why):
        self.term.type_at_focus(self.workspace, self.surface, text)
        return self.settled(ok, why)


def answer_one(keys, i, question, text, screen):
    """One question's page: Down to its free-text row, the text if the row is empty, then Enter on that row,
    or on Submit for a multiSelect question, since Enter on a filled multiSelect row unchecks it. Returns the
    screen read before Enter."""
    n, multi = len(question['options']), bool(question.get('multiSelect'))
    free = n + 1
    part = row_part(dialog_rows(screen), free)
    empty = part is not None and unboxed(part) in ('Typesomething.', 'Typesomething')
    if not empty and not holds(part, text):
        raise TerminalError(f"question {i + 1}'s free-text row does not show this text; nothing was entered; "
                            'it goes to the operator')
    focus = lambda s: focused(dialog_rows(s)) if dialog_rows(s) is not None else None
    # Before typing the page is told by its last option; after, a tall text may push that off the screen.
    page = (lambda s: question_page(s, question)) if empty else (lambda s: dialog_rows(s) is not None)
    if focus(screen) != 'submit':
        for _ in range(free):
            now = focus(screen)
            if now == free:
                break
            if not isinstance(now, int) or now > free:
                raise TerminalError(f'question {i + 1}: the focus is not above its free-text row')
            screen = keys.press('down', lambda s, k=now: page(s) and focus(s) == k + 1,
                                f"question {i + 1}: the focus did not move to row {now + 1} after Down")
        if focus(screen) != free:
            raise TerminalError(f"question {i + 1}: the focus did not reach its free-text row")
        if empty:
            screen = keys.type(text, lambda s: focus(s) == free and free_text_holds(s, text),
                               f"question {i + 1}'s free-text row does not show the text after it was typed; "
                               'Enter not sent')
    if multi and focus(screen) != 'submit':
        screen = keys.press('down', lambda s: focus(s) == 'submit',
                            f'question {i + 1}: the focus is not on Submit after Down; Enter not sent')
    if multi and not holds(row_part(dialog_rows(screen), free), text):
        raise TerminalError(f"question {i + 1}'s free-text row does not show this text; Enter not sent")
    keys.term.press(keys.workspace, keys.surface, 'enter')
    return screen


def open_session(term, workspace, coord, opened):
    """A new surface for a session: right of the last of opened that still exists, or below coord if none
    does."""
    for surface in reversed(opened):
        if surface != coord and term.exists(workspace, surface):
            return term.split(workspace, surface, 'right')
    return term.split(workspace, coord, 'below')


def names():
    return [m.name for m in pkgutil.iter_modules(__path__)]


def load(name):
    if name not in names():
        raise TerminalError(f'unsupported terminal {name!r}: one of {", ".join(names())}')
    module = importlib.import_module(f'{__name__}.{name}')
    missing = [op for op in OPERATIONS if not callable(getattr(module, op, None))]
    if missing:
        raise TerminalError(f'terminal {name} does not provide {", ".join(missing)}')
    return module


def detect():
    """The name of the one terminal this process runs in. Nested terminals cannot be told apart here:
    the outer one's environment reaches the inner one."""
    found = [n for n in names() if load(n).inside()]
    if len(found) != 1:
        raise TerminalError(f'this process must run in exactly one supported terminal ({", ".join(names())}); '
                            f'it runs in {found or "none"}. If terminals are nested, name the one to use with --terminal')
    return found[0]


def resolve(name=None):
    """The named terminal if this process runs in it, or the detected one when none is named."""
    if name is None:
        return detect()
    if not load(name).inside():
        raise TerminalError(f'this process does not run in {name}')
    return name
