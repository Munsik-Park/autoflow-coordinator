# Settings: tools, user settings, work space, progress records

This repository is a tool anyone can take to coordinate AutoFlow work. It separates tools, user settings and repository work spaces (workspaces), and the tools hold only the order in which settings are found, not setting values (Munsik-Park/autoflow-coordinator#6, operator decision 2026-10-30).

| Part | Location | What it holds |
|---|---|---|
| Tools | this repository | rules (CLAUDE.md, COORDINATOR.md), workflows, tools, this settings document, the workspace guide (`WORKSPACE.md`), the work records of earlier runs (`RUN-HISTORY.md`), the version (`VERSION`, `VERSIONING.md`). It holds no user values or individual repository matters |
| User settings | local and global settings files | user values such as the base and the coordination root |
| Work space | under the base | one workspace per repository (`WORKSPACE.md`) |
| Progress records | under the coordination root | run data, AutoFlow record folders |

Nothing is put in a user repository other than the changes that resolve an issue.

## Order in which settings are found

1. Local: `coordination.local.json` at the root of the tool clone (git ignored)
2. Global: `~/.autoflow/coordination.json`
3. Built-in defaults

Per key, the nearer one wins. A file that is absent sets no key. Both files are JSON objects. There is no sample file, and this document explains the entries.

| Key | Meaning | Built-in default |
|---|---|---|
| `root` | The coordination root (progress records). An absolute path or one starting with `~` | `~/.autoflow/coordination` |
| `base` | The base of the work space. An absolute path or one starting with `~` | `~/work/coordinator` |

The applied values are shown by `tools/config.py`. Called without arguments, it prints each key's value and source; given a key, it prints the value alone. Paths are printed as real paths, with `~` expanded and `..` and symlinks resolved. The tools and the coordination session get paths from this output and do not decide them directly.

## Work space

- **base**: where workspaces are kept. The built-in default may not exist in the user's environment. The coordination session does not work with a base the user has not confirmed. If the base's source is the built-in default, it gets the operator's confirmation before using it. In this case `tools/prepare.py` stops without `--base-confirmed`.
- **workspace**: the work space of one repository, at `<base>/<workspace name>/`. Its structure and the role of each file are in `WORKSPACE.md`. No list is kept; workspaces are found in the base (`WORKSPACE.md` > Finding).

## Progress records (coordination root)

With the coordination root in one place outside the clones, all coordination sessions see the same run data even with several tool clones, and `tools/check.sh` sees overlaps with other active runs in one place.

```
<root>/
  runs/<run name>/       run data
  records/<run name>/    AutoFlow record folder
```

`tools/config.py runs|records` prints each location.

