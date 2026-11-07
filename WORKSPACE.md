# workspace: structure and the role of its files

A workspace is the work space of one repository. It keeps the values and instructions that differ per repository outside this tool and the user repository, and lets work sessions and coordination sessions each read their own instructions. This document sets that structure. What to write for each repository is up to the user.

```
<base>/<workspace name>/
  repo.json              repository information (required)
  gh-token               the workspace's GitHub token (required, mode 600, outside git)
  CLAUDE.md              work session instructions (optional)
  coordination.md        coordination session instructions (optional)
  claude-settings.json   work session permission settings (optional)
  <run worktree>/
```

The base is found through settings (`SETTINGS.md` > Work space).

| File | Read by | Role |
|---|---|---|
| `repo.json` | coordination session | values needed by the tools and for running coordination |
| `gh-token` | the operator's shell, `tools/prepare.py`, `tools/launch.sh` | the only GitHub credential of the workspace's sessions |
| `CLAUDE.md` | work session | instructions applied to that repository's work sessions without adding a file to the user repository |
| `coordination.md` | coordination session | repository-specific instructions it reads and follows when given the workspace |
| `claude-settings.json` | the tool that starts work sessions | Claude Code settings to apply to work sessions |

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

The GitHub token every session of the workspace uses, as `GH_TOKEN`, for gh and for git. One line holding the token, with no whitespace in it and at most one final newline, in a regular file of the operator with mode 600 (no group or other permission); `tools/prepare.py` and `tools/launch.sh` stop on anything else, and name `chmod 600 <path>` for the mode. The workspace directory is not in a git repository; the file sits at its top, beside the run worktrees, not in one.

The token is a fine-grained personal access token whose resource owner is the owner in `repo.json` > `github`, with access to that repository and to its sub-repos (submodules) of the same owner, made without the Administration permission, so that it cannot delete a repository or change its settings. A sub-repo of another owner cannot be reached with it: such a workspace is not supported.

- **Coordination session**: started with `GH_TOKEN=$(cat <base>/<workspace name>/gh-token) claude` in the clone of this tool, or by the IDE with the same environment. `tools/prepare.py` stops when the workspace has no `gh-token`, when it is empty, or when the calling session's `GH_TOKEN` is not that token.
- **Work sessions**: `tools/launch.sh` stops when the workspace has no `gh-token` or it is empty, and starts the session with `GH_TOKEN=$(cat <path of gh-token>)` on the command line it types, so the line names the file, not the token.
- **What is guaranteed for git**: git run in a work session (in the run worktree and its submodules at any depth), and git run anywhere else in the clone and its worktrees outside their submodules, goes over HTTPS, where github.com is answered by the `GH_TOKEN` helper only, or fails, whatever the URL's form, fetch or push URL and remote. Outside a work session, git in a worktree's submodule, or a fetch in a worktree that recurses into one, uses the global and system settings, since a submodule's config does not include the clone's. A plaintext credential written into a push URL (a `pushurl`, or a `pushInsteadOf` into one) is used as written: git refuses credentials in fetch URLs, not in push URLs. `tools/prepare.py` stops on one in origin's push URL.
- **How**: `tools/prepare.py` writes `gh-token.gitconfig` in the clone's git directory and includes it from the clone's local config (`include.path`), before it fetches. Worktrees share that config. The file:
  - resets the credential helpers for `https://github.com` (an empty `credential.https://github.com.helper`, which drops the helpers set in the system and global config) and adds one that answers with `GH_TOKEN`. When `GH_TOKEN` is unset or empty, the helper tells git to stop (`quit=1`): the operation fails with `credential helper '…' told us to quit`, without prompting and without another account;
  - rewrites the two usual SSH forms `git@github.com:` and `ssh://git@github.com/` to `https://github.com/` (`url.https://github.com/.insteadOf`), so they keep working over HTTPS;
  - sets `core.sshCommand` to a command that prints why and fails, so SSH of any other form fails: a host alias from `~/.ssh/config`, a port, `ssh://github.com/`, `git+ssh://`, or a `pushInsteadOf` that turns a URL into SSH;
  - sets `transfer.credentialsInUrl = die`, so a URL holding a user and password is refused.
- **Work sessions and submodules**: a submodule has a repository and a config of its own (in a worktree, under `<clone>/.git/worktrees/<worktree>/modules/<name>`), which the clone's local config does not reach. `tools/launch.sh` therefore also passes `gh-token.gitconfig` to work sessions through the environment (`GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=include.path GIT_CONFIG_VALUE_0=<clone>/.git/gh-token.gitconfig`), which git passes on to the submodule commands it runs, and sets `GIT_SSH_COMMAND` to the file's `core.sshCommand`, since `GIT_SSH_COMMAND` overrides `core.sshCommand`. Submodules are initialized and updated in work sessions; the coordination session and the operator's shell do not get this environment. `tools/prepare.py` stops when the calling session has `GIT_SSH_COMMAND` set.
- **origin**: origin's fetch and push URLs must resolve, after the rewrite, to `https://github.com/<owner>/<name>` (optional `.git`, no user or password) for the repository in `repo.json` > `github` (compared without case). Written forms that do: `https://github.com/<owner>/<name>[.git]`, `git@github.com:<owner>/<name>[.git]` and `ssh://git@github.com/<owner>/<name>[.git]`. `tools/prepare.py` checks this before it fetches and stops otherwise, naming the URL and the accepted form.
- **A sub-repo of another owner** is not supported: the token is bound to one owner, so authentication to it fails. Nothing stops the run before that.

`tools/prepare.py` rewrites `gh-token.gitconfig` at every run and adds the `include.path` entry when the clone's local config does not list it yet; both stay in the clone after the run.

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
3. Register the token. The token must not pass through the conversation, which is kept in the transcript: the coordination session asks the operator to make the token as `gh-token` above requires and to write it from the operator's own shell, and gives the command for it:

   ```bash
   (umask 077; read -rs T; printf '%s\n' "$T" > <base>/<workspace name>/gh-token)
   ```

   Then it checks that `ls -l <base>/<workspace name>/gh-token` shows `-rw-------`, and that `GH_TOKEN=$(cat <base>/<workspace name>/gh-token) gh api repos/<github> --jq .full_name` prints the repository. The Administration permission is not checked: it is the operator's to leave out.
4. If needed, write `CLAUDE.md`, `coordination.md` and `claude-settings.json`.

The coordination session can also build a workspace from the user's request and questions and answers. If the given workspace does not exist or a fact the run needs is missing, the coordination session asks the operator and writes it in the workspace.
