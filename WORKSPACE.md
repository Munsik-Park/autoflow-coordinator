# workspace: structure and the role of its files

A workspace is the work space of one repository. It keeps what differs per repository outside this tool and the user repository, and the coordination session reads it and runs the run by it. This document sets that structure. What to write for each repository is up to the user.

```
<base>/<workspace name>/
  repo.json              repository information (required)
  gh-token               the workspace's GitHub token (required, mode 600, outside git)
  coordination.md        coordination session instructions (optional)
  merge-plan.json        how the accepted PRs of an issue are merged (optional)
  claude-settings.json   work session permission settings (optional)
  tools.json             extra tools set up for the repository, addable to work sessions (optional)
  <run worktree>/
```

The base is found through settings (`SETTINGS.md` > Work space).

| File | Read by | Role |
|---|---|---|
| `repo.json` | coordination session | values needed by the tools and for running coordination |
| `gh-token` | the operator's shell, `tools/prepare.py`, `tools/launch.sh` | the only GitHub credential of the workspace's sessions |
| `coordination.md` | coordination session | what holds for every run of that repository, read and followed when given the workspace |
| `merge-plan.json` | `tools/merge.py` | merge order, pointer moves, merge method and the steps after a merge that need no judgment |
| `claude-settings.json` | the tool that starts work sessions | Claude Code settings to apply to work sessions |
| `tools.json` | coordination session, `tools/launch.sh` | extra tools set up for that repository, each addable to a work session as an MCP server |

`repo.json` and `gh-token` are required; the rest are optional.

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

## `gh-token`

The GitHub token every session of the workspace uses, as `GH_TOKEN`, for gh and for git. One line holding the token, with no whitespace in it and at most one final newline, in a regular file of the operator with mode 600 (no group or other permission); `tools/prepare.py` and `tools/launch.sh` stop on anything else, and name `chmod 600 <path>` for the mode. The workspace directory is not in a git repository; the file sits at its top, beside the run worktrees, not in one. `tools/prepare.py` and `tools/launch.sh` stop when the workspace is inside a git worktree (`git -C <workspace> rev-parse --show-toplevel` succeeds), naming that worktree.

The token is a fine-grained personal access token whose resource owner is the owner in `repo.json` > `github`, with access to that repository and to its sub-repos (submodules) of the same owner, made without the Administration permission, so that it cannot delete a repository or change its settings. A sub-repo of another owner cannot be reached with it: such a workspace is not supported.

- **Coordination session**: started with `GH_TOKEN=$(cat <base>/<workspace name>/gh-token) claude` in the clone of this tool, or by the IDE with the same environment. `tools/prepare.py` stops on a `gh-token` that is not as stated above, when the calling session's `GH_TOKEN` is not exactly that token, and when the calling session has `GIT_SSH_COMMAND` set, which would override the clone's `core.sshCommand`.
- **Work sessions**: `tools/launch.sh` stops on a `gh-token` that is not as stated above. It starts the session with `GH_TOKEN=$(cat <path of gh-token>)` on the command line it types, so the line names the file, not the token. On the same line it passes `gh-token.gitconfig` through the environment (`GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=include.path GIT_CONFIG_VALUE_0=<clone>/.git/gh-token.gitconfig`), which git passes on to the submodule commands it runs, and sets `GIT_SSH_COMMAND` to the file's `core.sshCommand`.
- **What the tools set for git**: `tools/prepare.py` writes `gh-token.gitconfig` in the clone's git directory and includes it from the clone's local config (`include.path`), before it fetches; worktrees share that config. The file:
  - resets the credential helpers for `https://github.com` (an empty `credential.https://github.com.helper` drops those of the system and global config) and adds one that answers with `GH_TOKEN`. When `GH_TOKEN` is unset or empty, the helper tells git to stop (`quit=1`), so the operation fails without prompting and without another account;
  - rewrites `git@github.com:` and `ssh://git@github.com/` to `https://github.com/` (`url.https://github.com/.insteadOf`);
  - refuses SSH of any other form: `core.sshCommand` is a command that prints why and fails;
  - refuses a URL holding a user and password (`transfer.credentialsInUrl = die`);
  - resets the extra HTTP headers set for all of github.com in the system and global config (an empty `http.https://github.com/.extraHeader`), for every URL that has no extra header of a narrower scope.

  `tools/prepare.py`'s own fetch does not recurse into submodules (`--no-recurse-submodules`).
- **Where it applies**: git run in a work session, in the run worktree and its submodules at any depth, and git run in the clone and its worktrees outside their submodules. A submodule has a config of its own, which does not include the clone's. Outside a work session, git in a submodule, whether the clone's own or a worktree's (under `<clone>/.git/modules/` or `<clone>/.git/worktrees/<worktree>/modules/`), and a fetch that recurses into one use the global and system settings. Submodules are initialized and updated in work sessions.
- **Limit**: a credential written on purpose into git config is used as written. Examples are a push URL holding a password, since git refuses credentials in fetch URLs but not in push URLs, and an extra HTTP header set after the reset. An extra header scoped to a narrower URL (an owner or a repository) and read before the reset (in the system or global config) is sent for that URL together with the broader ones the reset would otherwise remove. `tools/prepare.py` stops on a push URL holding a password in origin.
- **origin**: origin's fetch and push URLs must resolve, after the rewrite, to `https://github.com/<owner>/<name>` (optional `.git`, no user or password) for the repository in `repo.json` > `github` (compared without case). Written forms that do: `https://github.com/<owner>/<name>[.git]`, `git@github.com:<owner>/<name>[.git]` and `ssh://git@github.com/<owner>/<name>[.git]`. `tools/prepare.py` checks this before it fetches and stops otherwise, naming the URL as written, the URL a rewrite rule turned it into, and the accepted form. A global or system rule that rewrites `https://github.com/` to SSH (`url.<ssh>.insteadOf` or `pushInsteadOf`) therefore makes `tools/prepare.py` stop, and is not supported.
- **A sub-repo of another owner** is not supported: the token is bound to one owner, so authentication to it fails. Nothing stops the run before that.
- **Limit (merge)**: every session of the workspace has the same token, and that token can merge the repository's PRs. The signature and head checks of `tools/merge.py` against the approval record the operator signs constrain the merges run through `tools/merge.py`; the token itself merges without it, the limit coordinator-role.md > Operator boundary states.

`tools/prepare.py` rewrites `gh-token.gitconfig` at every run and adds the `include.path` entry when the clone's local config does not list it yet; both stay in the clone after the run.

## `coordination.md`

Write what holds for every run of that repository: the facts of the repository and its work environment the coordination session runs each run by, and the facts it would otherwise find again in each run. A condition of one run stays in that run's record. It is not a name Claude Code reads automatically, so it is not loaded into work sessions. When given the workspace, the coordination session reads and follows this file. What a work session has to do, the coordination session passes on in its instructions.

This file is English by default (coordinator-role.md > Language).

This file is optional. Without it, the coordination session proceeds by the reference and asks the operator for the facts the run needs.

Examples of what it can hold: files outside git that a worktree needs, the commands that make the development environment, the reviewers a review runs and the command that starts each, which the coordination session passes to the review module in its instructions (`tools/invocation.py --instructions`), whether and how much of a review report to post on the PR, whether CI runs (a fork, for example), what the coordination session judges around a merge, that repository's quality goal. The merge order and the steps after a merge that need no judgment go in `merge-plan.json`.

## `merge-plan.json`

How the accepted PRs of an issue of that repository are merged, read by `tools/merge.py` after the operator's decision, which the operator gives as the approval record made with `tools/approve.py` (coordinator-role.md > Operator boundary). The plan is part of that decision: `tools/approve.py` shows it and signs its hash, and `tools/merge.py` stops when the file differs from the plan signed.

```json
{
  "method": "merge",
  "order": ["<owner>/<sub-repo>", "<owner>/<name>"],
  "pointers": [{"path": "<submodule path>", "repo": "<owner>/<sub-repo>"}],
  "tag": "v{VERSION}",
  "without_ci": ["<owner>/<name>"]
}
```

| Key | Meaning |
|---|---|
| `order` | Required. The repositories whose PRs can be accepted, in merge order: `repo.json` > `github`, and each sub-repo of `pointers` before it |
| `method` | `merge`, the only method and the default: a merge commit, which keeps the approved head an ancestor of the base branch, as the pointer moves and the cleanup's check need |
| `pointers` | The submodules of `repo.json` > `github` whose gitlink is moved, before its PR merges, to the merge commit of the sub-repo's accepted PR: the submodule path and the sub-repo its `.gitmodules` URL names |
| `tag` | A tag pushed at the merge commit of the `repo.json` > `github` PR; `{VERSION}` stands for the content of the `VERSION` file at that commit. With a tag, a decision accepts at most one PR of `repo.json` > `github`: `tools/approve.py` and `tools/merge.py` refuse more before any merge |
| `without_ci` | Repositories that have no CI: a head with no check passes there. Elsewhere a head with no check is CI not run, which stops the merge |

Without this file, one accepted PR of `repo.json` > `github` is merged with a merge commit, and nothing follows but closing the PRs not chosen, deleting the branches and removing the run's worktree.

This file is optional.

## `claude-settings.json`

The Claude Code settings file (a JSON object, `permissions` and so on) to apply to that repository's work sessions. `tools/launch.sh` merges `promptSuggestionEnabled: false` into this file of the workspace the run worktree belongs to, adds the coordination tools' question hooks beside the file's own hooks, writes the result to the run directory and passes it with the start option `--settings`. Without this file, the same setting is passed anyway. The merge session (`tools/launch.sh --without-autoflow`) does not use this file: its settings are built by `tools/launch.sh` from its own keys only, so a hook, a status line or a plugin set here does not reach it.

This file is optional. Without it, permissions follow Claude Code's default behavior. Starting without permission settings is the user's choice. Turning off suggested text always applies, regardless of this file or the user's settings.

## `tools.json`

Extra tools set up for that repository's work, added to a work session alongside what it already has. The coordination session chooses from them for each work session it opens (`coordinator-role.md` > Sessions), and `tools/launch.sh --tools <name>[,<name>...]` adds the chosen ones to the session.

```json
{
  "<tool name>": {
    "description": "<what the tool does and what work it serves>",
    "mcp": { "type": "stdio", "command": "...", "args": ["...", "{worktree}"] }
  }
}
```

| Key | Meaning |
|---|---|
| `<tool name>` | The name `--tools` takes, and the MCP server name the session lists |
| `description` | Required. What the tool does and what work it serves: the coordination session matches it with the work of the modules a session will run |
| `mcp` | Required. How to start the tool, as one entry of Claude Code's MCP server configuration (`mcpServers` > `<name>`) |

A value that differs per run is written as a placeholder. `{worktree}` stands for the run worktree's absolute path, and `tools/launch.sh` replaces it in every string of the `mcp` entry. It writes the chosen entries to `<run-dir>/mcp-<session>.json`, `<session>` the session's name (`S<k>`, or a one-off name such as `X1`), as `{"mcpServers": {...}}` and starts the session with `--mcp-config` that file. A name not in this file, or `--tools` without this file, stops the launch before a surface is opened, naming it. A session started without `--tools` gets none of these tools, and the merge session (`tools/launch.sh --without-autoflow`) never does.

This file is optional.

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
3. Register the token. The token must not pass through the conversation, which is kept in the transcript: the coordination session asks the operator to make the token as `gh-token` above requires and to write it from the operator's own shell, and gives the command for it:

   ```bash
   (umask 077; read -rs T; printf '%s\n' "$T" > <base>/<workspace name>/gh-token)
   ```

   Then it checks that `ls -l <base>/<workspace name>/gh-token` shows `-rw-------`, and that `GH_TOKEN=$(cat <base>/<workspace name>/gh-token) gh api repos/<github> --jq .full_name` prints the repository. The Administration permission is not checked: it is the operator's to leave out.
4. If needed, write `coordination.md`, `claude-settings.json` and `tools.json`.

The coordination session can also build a workspace from the user's request and questions and answers. If the given workspace does not exist or a fact the run needs is missing, the coordination session asks the operator; what holds for every run of that repository it writes in the workspace, and a condition of one run in that run's record.
