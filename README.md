# autoflow-coordinator

The front end of [AutoFlow](https://github.com/Munsik-Park/autoflow): a tool anyone can take to coordinate AutoFlow work.

You open Claude Code in a clone of this repository and give it a repository and an issue. That session, the coordination session, proposes a workflow for the issue, and after you approve it, runs AutoFlow modules in work sessions it opens beside itself in cmux or tmux, judges each result and connects it to the next module. You, the operator, approve the workflow and decide the merge.

## The three repositories

| Repository | Place |
|---|---|
| [autoflow](https://github.com/Munsik-Park/autoflow) | The back end: the contract modules, run one at a time with `/autoflow:<module> <invocation.json>`. It can run alone, but practical use goes through the coordinator. |
| autoflow-coordinator (this repository) | The front end: the coordination session and its `tools/`, which assemble modules, open work sessions in cmux or tmux and judge the results. It does not run without AutoFlow installed at the version in its `VERSION`. |
| [autoflow-coordinator-run-status](https://github.com/Munsik-Park/autoflow-coordinator-run-status) | Optional, recommended: a mod that shows a run's flow and verdicts. |

## Requirements

- **Claude Code**, with the `claude` command on `PATH`: the tools start work sessions by typing `claude` in a shell.
- **cmux or tmux**, with the coordination session opened inside it. The tools open work sessions, send them instructions and read their screens through the terminal, so run preparation stops in a session outside cmux or tmux. The terminal window is at least 110 columns wide and 40 rows high.
  - Checked: cmux and tmux on macOS.
  - Not supported: the macOS default terminal (Terminal.app).
  - Not checked: Linux and other terminals ([#3](https://github.com/Munsik-Park/autoflow-coordinator/issues/3)).
- **Command-line tools** on `PATH`:
  - for `tools/`: `bash`, `python3` (3.9 or later, standard library only), `jq`, `uuidgen` and `git`;
  - for the coordination session: `gh`. It checks the commits, branches, pull requests and CI that work sessions report with `git` and `gh`, authenticated with the workspace's token, not with the account `gh` is signed in with.
- **A GitHub token per workspace**: a fine-grained personal access token for the workspace's repository and its sub-repos of the same owner, without the Administration permission, kept in the workspace as `gh-token` ([Workspaces](#workspaces)).
- **The AutoFlow plugin** installed as `autoflow@autoflow`, at a single version: the version in this repository's [`VERSION`](VERSION) without its `-rcN` suffix (`VERSION` `X.Y.Z-rcN` supports AutoFlow `X.Y.Z`). AutoFlow's own requirements are in its [docs/requirements.md](https://github.com/Munsik-Park/autoflow/blob/main/docs/requirements.md).

### When AutoFlow and `VERSION` differ

AutoFlow's marketplace installs the version on autoflow's `main`. AutoFlow raises its version there first, and this repository's `VERSION` follows the new AutoFlow version afterwards, so for a while the installed AutoFlow can be newer than the version this repository supports. While they differ, preparing a run stops without creating it, with:

```
installed AutoFlow <installed> is not the supported <supported>: install that version, or pass --skip-version-check for work that supports a new AutoFlow version
```

Once `VERSION` follows the new AutoFlow version, update your clone (`git pull`) and the run can be prepared. `--skip-version-check` is for the work that adds support for a new AutoFlow version to this repository, not a way around the check.

If the installed AutoFlow is older than `VERSION`, update it with the commands in AutoFlow's [Quick Start](https://github.com/Munsik-Park/autoflow#quick-start): `/plugin marketplace update` → `/plugin update autoflow@autoflow`.

## Recommended: run-status

[run-status](https://github.com/Munsik-Park/autoflow-coordinator-run-status) shows a run's current step, module flow and verdicts in a Claude Code pane, from `tools/status.py`. It works in a session opened in the clone of this repository, which is where the coordination session runs. Usage is in its README.

## Install

1. Clone this repository:

   ```
   git clone https://github.com/Munsik-Park/autoflow-coordinator.git
   ```

2. Install AutoFlow, at a Claude Code prompt:

   ```
   /plugin marketplace add Munsik-Park/autoflow
   /plugin install autoflow@autoflow
   ```

3. Install run-status (recommended), at a Claude Code prompt:

   ```
   /plugin marketplace add Munsik-Park/autoflow-coordinator-run-status
   /plugin install run-status@autoflow-coordinator-run-status
   ```

## Settings

Two paths are set:

| Key | What it is | Built-in default |
|---|---|---|
| `base` | Where workspaces are kept, one per repository you work on | `~/work/coordinator` |
| `root` | The coordination root, where the run data (`runs/`) and AutoFlow record folders (`records/`) of every run are kept | `~/.autoflow/coordination` |

Set them in either file, as a JSON object with an absolute path or one starting with `~`:

- `coordination.local.json` at the root of your clone (git ignored), for this clone;
- `~/.autoflow/coordination.json`, for every clone.

For each key, the local file wins over the global one, and the built-in default applies when neither sets it.

```json
{
  "base": "~/work/coordinator",
  "root": "~/.autoflow/coordination"
}
```

`tools/config.py` prints the applied values and where each came from.

The base and the root, as `tools/config.py` prints them (with `~` expanded and symbolic links resolved), must each be one shell word: letters, digits and `_ @ % + = : , . / -`, with no spaces. `tools/config.py` accepts other paths, but run preparation (`tools/prepare.py`) stops on them without creating the run.

If the base comes from the built-in default, the coordination session asks you to confirm it before using it: run preparation (`tools/prepare.py`) stops unless the base was confirmed. Setting `base` in a settings file avoids the question.

## Workspaces

A workspace holds what is specific to one repository you work on, outside that repository and outside this one. It is a directory under the base:

```
<base>/<workspace name>/
  repo.json              repository information (required)
  gh-token               the workspace's GitHub token (required)
  CLAUDE.md              instructions for the work sessions (optional)
  coordination.md        instructions for the coordination session (optional)
  claude-settings.json   Claude Code settings for the work sessions (optional)
```

The workspace name is one shell word too: letters, digits and `_ @ % + = : , . -`, with no spaces. Run preparation stops otherwise.

`repo.json`:

```json
{
  "github": "<owner>/<name>",
  "clone": "<path of your local clone>",
  "base_branch": "main"
}
```

- `github` is the repository's `<owner>/<name>` on GitHub.
- `clone` is a local git clone of that repository, as an absolute path or one starting with `~`. It has the remote `origin`, and `base_branch` exists there: each run fetches `origin` and makes its own worktree from `origin/<base_branch>`, directly under the workspace.

`gh-token` holds one fine-grained personal access token, mode 600: resource owner the owner in `github`, access to that repository and to its sub-repos of the same owner, and no Administration permission. Every session of the workspace uses it as `GH_TOKEN`, for gh and for git: the coordination session gets it from the command that starts it (see [First run](#first-run)), and work sessions from the coordinator. Every git network operation of the clone, its worktrees and the work sessions' submodules goes over HTTPS with that token only, or fails: run preparation rewrites `git@github.com:` and `ssh://git@github.com/` remotes to HTTPS, makes SSH of any other form fail and refuses URLs holding credentials. origin must be the workspace's repository in one of the forms `https://github.com/<owner>/<name>`, `git@github.com:<owner>/<name>` or `ssh://git@github.com/<owner>/<name>`; run preparation stops otherwise. When the coordination session builds a workspace, it asks you to write the token from your own shell, so that the token does not pass through the conversation. [WORKSPACE.md](WORKSPACE.md) > `gh-token` has the details.

Put the permissions for work sessions in `claude-settings.json`, not in a `.claude/settings.json` in the workspace. Work sessions run in a run worktree inside the workspace, and Claude Code reads `.claude/` settings only from its working directory, not from parent directories ([anthropics/claude-code#74023](https://github.com/anthropics/claude-code/issues/74023), [anthropics/claude-code#12962](https://github.com/anthropics/claude-code/issues/12962)). The coordinator passes `claude-settings.json` to each work session it starts. Without the file, permissions follow Claude Code's default behavior.

`CLAUDE.md` in the workspace applies to the work sessions, since Claude Code also reads `CLAUDE.md` from the parent directories of the working directory. `coordination.md` is read by the coordination session when you give it the workspace.

You do not have to write a workspace by hand: if you name a workspace that does not exist, the coordination session builds it with you through questions and answers. [WORKSPACE.md](WORKSPACE.md) has the details.

## First run

1. Open cmux or tmux, with a window of at least 110 columns and 40 rows, and go to your clone of this repository.
2. The first time you use a terminal on a machine, check it. From a shell in the same window, run:

   ```
   tools/terminal_check.py
   ```

   It opens panes below the current one, starts short Claude Code sessions there (`--model haiku`), then closes them and removes their transcripts. It prints `PASS` or `FAIL <why>` for each item and exits with status 0 only if all pass. If terminals are nested (tmux inside cmux, for example), name the one to check with `--terminal cmux` or `--terminal tmux`.

   Run the check again after the terminal is updated, and when instructions to work sessions repeatedly fail to arrive.
3. Start the coordination session in the clone with the workspace's token: `GH_TOKEN=$(cat <base>/<workspace name>/gh-token) claude`. Run preparation stops when the session's `GH_TOKEN` is not the token of the workspace it prepares a run for. For a workspace that does not exist yet, start `claude` without it, build the workspace, then start the session again with its token.
4. Tell it the workspace and the issue, for example: `Work on issue 123 in workspace my-repo.` Answer its questions: confirming the base if it comes from the built-in default, and building the workspace if it does not exist yet.
5. It presents a workflow outline for the issue. Approve it, or ask for changes. After approval it runs the workflow: work sessions open in panes below it, and it reports to you, stopping where a decision is yours (issue selection, workflow approval, policy changes and merge).
6. When a pull request is ready, it gives you the merge review artifact with the merge request. Merging is yours.

How the coordination session builds the workflow and judges results is in [COORDINATOR.md](COORDINATOR.md); the reference workflows are in [workflows/README.md](workflows/README.md).

## The merge review artifact

The coordination session makes the merge review artifact, the summary you read before deciding a merge, with the `pr-postcard` skill. `pr-postcard` is the operator's own Claude Code skill: no repository distributes it, so it is not installed with this repository, AutoFlow or run-status.
