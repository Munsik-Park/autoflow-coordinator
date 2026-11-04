# workspace: structure and the role of its files

A workspace is the work space of one repository. It keeps the values and instructions that differ per repository outside this tool and the user repository, and lets work sessions and coordination sessions each read their own instructions. This document sets that structure. What to write for each repository is up to the user.

```
<base>/<workspace name>/
  repo.json              repository information (required)
  CLAUDE.md              work session instructions (optional)
  coordination.md        coordination session instructions (optional)
  claude-settings.json   work session permission settings (optional)
  <run worktree>/
```

The base is found through settings (`SETTINGS.md` > Work space).

| File | Read by | Role |
|---|---|---|
| `repo.json` | coordination session | values needed by the tools and for running coordination |
| `CLAUDE.md` | work session | instructions applied to that repository's work sessions without adding a file to the user repository |
| `coordination.md` | coordination session | repository-specific instructions it reads and follows when given the workspace |
| `claude-settings.json` | the tool that starts work sessions | Claude Code settings to apply to work sessions |

Only `repo.json` is required; the rest are optional.

## `repo.json`

```json
{
  "github": "<owner>/<name>",
  "clone": "<path of the local clone>",
  "base_branch": "<branch the run worktree starts from>"
}
```

| Key | Meaning |
|---|---|
| `github` | GitHub path |
| `clone` | The local clone. An absolute path or one starting with `~`. Run worktrees are made from here |
| `base_branch` | The base branch |

When given a workspace, the coordination session reads values from this file. The run preparation tool `tools/prepare.py` reads this file too.

## `CLAUDE.md`

Write the facts and know-how for working in that repository. Run worktrees are under the workspace, so it applies to every work session through Claude Code's behavior of reading `CLAUDE.md` in the parent directories of the working directory.

This file is English by default (this repository's root `CLAUDE.md` > Language).

This file is optional. Without it, no workspace instructions apply to work sessions.

## `coordination.md`

Write the instructions for what the coordination session judges and does for that repository. It is not a name Claude Code reads automatically, so it is not loaded into work sessions. When given the workspace, the coordination session reads and follows this file. What a work session has to do, the coordination session passes on in its instructions.

This file is English by default (this repository's root `CLAUDE.md` > Language).

This file is optional. Without it, the coordination session proceeds by the reference and asks the operator for the facts the run needs.

Examples of what it can hold: files outside git that a worktree needs, the commands that make the development environment, whether and how much of a review report to post on the PR, whether CI runs (a fork, for example), the policy for merge and what follows it, that repository's quality goal.

If both sides need the same fact, write it in the instructions of the session that does the work.

## `claude-settings.json`

The Claude Code settings file (a JSON object, `permissions` and so on) to apply to that repository's work sessions. `tools/launch.sh` merges `promptSuggestionEnabled: false` into this file of the workspace the run worktree belongs to, writes the result to the run directory and passes it with the start option `--settings`. Without this file, the same setting is passed anyway.

This file is optional. Without it, permissions follow Claude Code's default behavior. Starting without permission settings is the user's choice. Turning off suggested text always applies, regardless of this file or the user's settings.

## Run worktree

A worktree made from the local clone for each run. `tools/prepare.py` makes it directly under the workspace. A work session's workspace is determined as the parent directory of the worktree.

## Sharing

Several coordination sessions using the same workspace read the same instructions. A change to a workspace file applies to every run using that workspace.

## Finding

When presenting workspaces to the user, the coordination session finds the directories that have a `repo.json` in the base the settings point to. If the base's source is the built-in default, it first gets the operator's confirmation (`SETTINGS.md` > Work space).

```bash
find "$(tools/config.py base)" -mindepth 2 -maxdepth 2 -type f -name repo.json
```

The directory of each printed path is a workspace. If none is found, make one through questions and answers with the operator.

## Creating

1. Check the base with `tools/config.py base`.
2. Make `<base>/<workspace name>/` and write `repo.json`.
3. If needed, write `CLAUDE.md`, `coordination.md` and `claude-settings.json`.

The coordination session can also build a workspace from the user's request and questions and answers. If the given workspace does not exist or a fact the run needs is missing, the coordination session asks the operator and writes it in the workspace.
