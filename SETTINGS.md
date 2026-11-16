# Settings: tools, user settings, work space, progress records

Coordination keeps tools, user settings, work spaces (workspaces) and progress records apart, as below.

| Part | Location | What it holds |
|---|---|---|
| Tools | this repository | the rule documents (CLAUDE.md, coordinator-role.md, this settings document, `WORKSPACE.md`, workflows), `tools/` and the supported version (`VERSION`) |
| User settings | local and global settings files | user values such as the base and the coordination root |
| Work space | under the base | one workspace per repository (`WORKSPACE.md`) |
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
| `modules` | The autoflow-module clone, the default module location. An absolute path or one starting with `~` | `~/work/coordinator/autoflow-module` |
| `home` | The AutoFlow home, holding the user module location. An absolute path or one starting with `~` | `~/.autoflow` |

The applied values are shown by `tools/config.py`. Called without arguments, it prints each key's value and source, then the places derived from them; given a key, it prints the value alone. Paths are printed as real paths, with `~` expanded and `..` and symlinks resolved. The tools and the coordination session take paths from this output.

## Module locations

A module is a folder holding a `SKILL.md`. Modules are taken from two locations:

- **Default location**: the autoflow-module clone the setting `modules` names. It is a git clone.
- **User location**: `<home>/modules`, which `tools/config.py user-modules` prints. It need not be a git clone. When it does not exist, there are no user modules.

`tools/modules.py` lists the modules of both locations, each with its location. `tools/prepare.py` records both locations in a run's `run.env`, and `tools/invocation.py` takes a module from either and records the definition it ran.

## Work space

- **base**: where workspaces are kept. The built-in default may not exist in the user's environment. If the base's source is the built-in default, the coordination session confirms it with the operator before using it. In this case `tools/prepare.py` stops without `--base-confirmed`.
- **workspace**: the work space of one repository, at `<base>/<workspace name>/`. Its structure and the role of each file are in `WORKSPACE.md`. Workspaces are found in the base (`WORKSPACE.md` > Finding).

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

`tools/config.py runs|records|approval-key` prints each location. The approval key is made once by the operator with `tools/approve.py --init` in a terminal (coordinator-role.md > Operator boundary).

