# Settings: tools, user settings, work space, progress records

Coordination keeps tools, user settings, work spaces (workspaces) and progress records apart, as below.

| Part | Location | What it holds |
|---|---|---|
| Tools | this repository | the rule documents (CLAUDE.md, coordinator-role.md, this settings document, `WORKSPACE.md`, workflows), `tools/` (the reviewer wrappers in `tools/review/`), the review rule files `docs/review/`, and the supported version (`VERSION`) |
| User settings | local and global settings files | user values such as the base and the coordination root |
| Work space | under the base | one workspace per repository |
| Progress records | under the coordination root | run data, AutoFlow record folders |

A user repository receives only the changes that resolve an issue.

## Order in which settings are found

1. Local: `coordination.local.json` at the root of the tool clone (git ignored)
2. Global: `~/.autoflow/coordination.json`
3. Built-in defaults

Per key, the nearer one wins. A file that is absent sets no key. Both files are JSON objects with the keys below.

| Key | Meaning | Built-in default |
|---|---|---|
| `root` | The coordination root (progress records). An absolute path or one starting with `~` | `~/.autoflow/coordination` |
| `base` | The base of the work space. An absolute path or one starting with `~` | `~/work/coordinator` |
| `modules` | The autoflow-module clone, the default module location. An absolute path or one starting with `~` | `~/work/autoflow-module` |
| `home` | The AutoFlow home, holding the user module location. An absolute path or one starting with `~` | `~/.autoflow` |

The applied values are shown by `tools/config.py`. Called without arguments, it prints each key's value and source, then the places derived from them (`runs`, `records`, `approval-key`, `user-modules`, `reviewer-settings`, `module-settings`); given a key, it prints the value alone. Paths are printed as real paths, with `~` expanded and `..` and symlinks resolved. The tools and the coordination session take paths from this output.

## Module locations

A module is a folder holding a `SKILL.md`. Modules are taken from two locations:

- **Default location**: the autoflow-module clone the setting `modules` names. It is a git clone.
- **User location**: `<home>/modules`, which `tools/config.py user-modules` prints. It need not be a git clone. What is there is either nothing (no path at all), and then there are no user modules, or a folder whose entries and their `SKILL.md` can be read. It is a folder other than the one `modules` names.

The modules clone lies outside the base, since each directory directly under the base is a workspace: the two are not the same folder, and neither lies inside the other. The same holds between the modules clone and each workspace, as resolved.

`tools/modules.py` lists the modules of both locations, each with its location. `tools/prepare.py` records both locations in a run's `run.env`, the modules clone as `MODULES` with its commit as `MODULES_COMMIT` and the user location as `USER_MODULES`, and `tools/invocation.py` takes a module from either and records the definition it ran.

A module's name is its folder's name, matched exactly as the location's listing spells it, also on a case-insensitive volume. A user module whose folder name is a default module's replaces that default module: `tools/modules.py` lists the user module in the default module's place, with `replaces` naming the default module's `SKILL.md`, and does not list the default module; `tools/invocation.py` runs the user module and records `replaces` in the invocation.

## Reviewer settings

The reviewer wrappers `tools/review/claude-review-pr.sh` and `tools/review/codex-review-pr.sh` read each reviewer's model, effort, rule file and lenses file from `<home>/config.json`, the place `tools/config.py reviewer-settings` prints for the clone the wrapper is in. The file is read anew on every run.

```json
{"review": {"claude": {"model": "opus", "effort": "high", "rules": "<path>", "lenses": "<path>"},
            "codex": {"model": "gpt-6-sol"}}}
```

| Key under `.review.<reviewer>` | Meaning | Without it |
|---|---|---|
| `model` | The model the reviewer's CLI runs | claude `opus`, codex `gpt-6-sol` |
| `effort` | The effort passed to the CLI: claude one of `low medium high xhigh max`, codex one of `none minimal low medium high xhigh max ultra persistent` | no flag: the CLI's own configuration |
| `rules` | The rule file whose text the prompt carries. A relative path is read from the root of the clone the wrapper is in, not from the reviewed checkout. A rule file that does not exist stops the wrapper (exit 2) | `docs/review/review-<reviewer>.md` of the clone the wrapper is in |
| `lenses` | A lenses file whose text the prompt carries after the rules. A relative path is read as for `rules`. A lenses file that does not exist is reported, and the review runs without it | none |

Every key is optional, and other keys are not read. With no file, each reviewer runs with the defaults above.

Which reviewers a review runs is in the workspace's `coordination.md`.

## Module settings

`tools/launch.sh` reads a model and an effort per module from `<home>/config.json`, the place `tools/config.py module-settings` prints for the clone `tools/launch.sh` is in. The file is read anew on every launch.

```json
{"module": {"criterion-decision": {"model": "fable", "effort": "max"},
            "design": {"effort": "high"}}}
```

`<module name>` is the name the module run's invocation records as `module`, which is the module's folder name: a user module that replaces a default module is set under the same name.

| Key under `.module.<module name>` | Meaning | Without it |
|---|---|---|
| `model` | The model the session is started with (`claude --model`) | criterion-decision `fable`; any other module no flag: Claude Code's own configuration |
| `effort` | The effort the session is started with (`claude --effort`): one of `low medium high xhigh max` | criterion-decision `max`; any other module no flag: Claude Code's own configuration |

The file is a JSON object; `module` is an object holding one object per module name, and a `model` or `effort` is a non-empty string. A `model` holds no U+0000 and is valid Unicode text, so that a command line can carry it. A symlink with no target at the file's place counts as a file that is present. Every key is optional and applies by itself, and other keys are not read. A file without the key `module` sets nothing.

A module's setting applies to the session `tools/launch.sh` starts for that module's run: a launch without `--without-autoflow` whose instruction file is `<name>.prompt.txt` with `<name>.invocation.json` beside it. It does not apply to a run that continues in a running session, which keeps the model and effort that session was started with. A session started without a module run, the merge session included, gets no model or effort from the file. `tools/launch.sh --model <model>` gives the session it starts that model, for a module's run in place of the module's set or default model; the effort comes from the setting or default as without it.

Claude Code takes `CLAUDE_CODE_EFFORT_LEVEL`, set in the `env` of the workspace's `claude-settings.json` or in the environment of the terminal the session starts in, ahead of `--effort`: a workspace that uses the module settings' efforts leaves that variable unset.

`.review` and the file's other top-level keys are not read, so no value under them stops a launch. A session started without a module run reads neither an invocation nor this file, so neither stops it. `tools/module_settings.py <instruction file> [--model <model>] [--without-autoflow]` prints the flags a launch would get, or the stop, without starting a session.

## Work space

- **base**: where workspaces are kept. The built-in default may not exist in the user's environment. If the base's source is the built-in default, the coordination session confirms it with the operator before using it. In this case `tools/prepare.py` stops without `--base-confirmed`.
- **workspace**: the work space of one repository, at `<base>/<workspace name>/`. Workspaces are found in the base.

## Progress records (coordination root)

All coordination sessions, from any tool clone, keep their run data under this one root, where `tools/check.sh` sees overlaps with other active runs.

```
<root>/
  runs/<run name>/                  run data
  records/<run name>/               AutoFlow record folder
    <module>-<n>/                   a module run's work folder
    <module>-<n>.invocation.json    its invocation
    <module>-<n>.prompt.txt         its instruction file
    <module>-<n>.ended.json         its end record
  approval-key                      the operator's approval key (private, with a passphrase)
  approval-key.pub                  its public key, against which tools/merge.py verifies an approval record
```

Each place is written only by its owner.

- **A module run's work folder** is written by that module run. `tools/invocation.py` makes it, empty, under the module run's name `<module>-<n>`, n being the next unused number of that module in the run. The coordination session and its tools read it.
- **The rest of the record folder and the run data** are written by the coordination session and its tools. A module run's invocation, instruction file and end record sit beside its work folder under the same name, and a file the coordination session makes as a module's input goes in the record folder beside the work folders.

`tools/config.py runs|records|approval-key` prints each location. The approval key is made once by the operator with `tools/approve.py --init` in a terminal.

