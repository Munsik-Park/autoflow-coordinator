# Settings: tools, user settings, work space, progress records

Coordination keeps tools, user settings, work spaces (workspaces) and progress records apart, as below.

| Part | Location | What it holds |
|---|---|---|
| Tools | this repository | the rule documents (CLAUDE.md, COORDINATOR.md, this settings document, `WORKSPACE.md`, workflows), `tools/`, the work records of earlier runs (`RUN-HISTORY.md`) and the supported version (`VERSION`) |
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

The applied values are shown by `tools/config.py`. Called without arguments, it prints each key's value and source; given a key, it prints the value alone. Paths are printed as real paths, with `~` expanded and `..` and symlinks resolved. The tools and the coordination session take paths from this output.

## Work space

- **base**: where workspaces are kept. The built-in default may not exist in the user's environment. If the base's source is the built-in default, it gets the operator's confirmation before using it. In this case `tools/prepare.py` stops without `--base-confirmed`.
- **workspace**: the work space of one repository, at `<base>/<workspace name>/`. Its structure and the role of each file are in `WORKSPACE.md`. Workspaces are found in the base (`WORKSPACE.md` > Finding).

## Progress records (coordination root)

All coordination sessions, from any tool clone, keep their run data under this one root, where `tools/check.sh` sees overlaps with other active runs.

```
<root>/
  runs/<run name>/       run data
  records/<run name>/    AutoFlow record folder
```

`tools/config.py runs|records` prints each location.

