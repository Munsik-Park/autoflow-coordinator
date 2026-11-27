# autoflow-coordinator

The coordinator of [AutoFlow](https://github.com/Munsik-Park/autoflow): a tool anyone can take to coordinate AutoFlow work.

You open Claude Code in a clone of this repository and give it a repository and an issue. That session, the coordination session, proposes a workflow for the issue, and after you approve it, runs AutoFlow modules in work sessions it opens beside itself in cmux or tmux, judges each result and connects it to the next module. You, the operator, approve the workflow and decide which pull requests to accept; a work session then merges them.

## The three repositories

| Repository | Place |
|---|---|
| [autoflow-module](https://github.com/Munsik-Park/autoflow-module) | The modules: units that each take on one piece of work, defined in the form of the module interface (`docs/module-interface.md`), each a folder holding a `SKILL.md`, which work sessions run. |
| autoflow-coordinator (this repository) | The coordination session and its `tools/`, which assemble modules, open work sessions in cmux or tmux and judge the results. |
| [autoflow-ide](https://github.com/Munsik-Park/Autoflow-ide) | The screen over the coordinator. |

[Munsik-Park/autoflow](https://github.com/Munsik-Park/autoflow) describes how the three are used together and keeps the change notes.

## Versions

`VERSION` holds the AutoFlow version this coordinator belongs to, `0.8.0`, followed by `-rcN`, where N rises by one with each merged pull request. The repositories of one AutoFlow version are used together.

- v0.7.0-rc11 is the last version that runs the AutoFlow plugin ([Munsik-Park/autoflow-plugin](https://github.com/Munsik-Park/autoflow-plugin) 0.7.0).
- From 0.8.0-rc1 the coordinator runs autoflow-module.

## Requirements

- **Claude Code**, with the `claude` command on `PATH`: the tools start work sessions by typing `claude` in a shell.
- **cmux or tmux**, with the coordination session opened inside it. The tools open work sessions, send them instructions and read their screens through the terminal, so run preparation stops in a session outside cmux or tmux. The minimum size of the terminal window is in [coordinator-role.md](coordinator-role.md) > Sessions.
  - Checked: cmux and tmux on macOS.
  - Not supported: the macOS default terminal (Terminal.app).
  - Not checked: Linux and other terminals ([#3](https://github.com/Munsik-Park/autoflow-coordinator/issues/3)).
- **Command-line tools** on `PATH`:
  - for `tools/`: `bash`, `python3` (3.9 or later, standard library only), `jq`, `uuidgen`, `git` 2.37 or later (the first with `transfer.credentialsInUrl`, which refuses URLs holding credentials) and OpenSSH's `ssh-keygen` with `-Y sign`, which signs and verifies the approval record;
  - for the coordination session: `gh`. It checks the commits, branches, pull requests and CI that work sessions report with `git` and `gh`, authenticated with the workspace's token, not with the account `gh` is signed in with.
- **For the reviewer wrappers** (`tools/review/`), on `PATH`: `codex`, signed in, and `claude`, `gh`, `jq`, `git`, `bash`, `python3`. The coordination session starts the review module's reviewers with them; their settings are in [SETTINGS.md](SETTINGS.md) > Reviewer settings.
- **A GitHub token per workspace**, kept in the workspace as `gh-token` ([Workspaces](#workspaces)); what the token must be is in [WORKSPACE.md](WORKSPACE.md) > `gh-token`.
- **A clone of [autoflow-module](https://github.com/Munsik-Park/autoflow-module)**, named by the setting `modules`: the default modules. The clone's version is not checked against this coordinator's `VERSION`. The two locations modules are taken from are in [SETTINGS.md](SETTINGS.md) > Module locations.

## Recommended: run-status

[run-status](https://github.com/Munsik-Park/autoflow-coordinator-run-status) shows a run's current step, module flow and verdicts in a Claude Code pane, from `tools/status.py`. It works in a session opened in the clone of this repository, which is where the coordination session runs. Usage is in its README.

## Install

1. Clone this repository:

   ```
   git clone https://github.com/Munsik-Park/autoflow-coordinator.git
   ```

2. Clone autoflow-module, the default modules, next to the clone of step 1, in the same parent directory. Keep it outside the base, since each directory under the base is a workspace:

   ```
   git clone https://github.com/Munsik-Park/autoflow-module.git
   ```

   and name that clone with the setting `modules` in a settings file ([Settings](#settings)):

   ```json
   {
     "modules": "<parent directory>/autoflow-module"
   }
   ```

3. Install run-status (recommended), at a Claude Code prompt:

   ```
   /plugin marketplace add Munsik-Park/autoflow-coordinator-run-status
   /plugin install run-status@autoflow-coordinator-run-status
   ```

## Settings

The keys, the two settings files, which of them wins and the built-in defaults are in [SETTINGS.md](SETTINGS.md) > Order in which settings are found. A settings file, for example:

```json
{
  "base": "~/work/coordinator",
  "root": "~/.autoflow/coordination"
}
```

`tools/config.py` prints the applied values and where each came from.

The base, the root, the home and the modules clone, as `tools/config.py` prints them (with `~` expanded and symbolic links resolved), must each be one shell word: letters, digits and `_ @ % + = : , . / -`, with no spaces. `tools/config.py` accepts other paths, but run preparation (`tools/prepare.py`), which records `<home>/modules` and the modules clone in `run.env` beside paths under the base and the root, stops on them without creating the run.

The confirmation asked for a base that comes from the built-in default is in [SETTINGS.md](SETTINGS.md) > Work space; setting `base` in a settings file avoids it.

## Workspaces

What a workspace is and the files it holds are in [WORKSPACE.md](WORKSPACE.md), and the keys of its `repo.json` in [WORKSPACE.md](WORKSPACE.md) > `repo.json`.

The workspace name is one shell word too: letters, digits and `_ @ % + = : , . -`, with no spaces. Run preparation stops otherwise.

What the workspace's token must be, that every session of the workspace uses it and how the coordination session is started with it, the origin it is used with and what it can merge are in [WORKSPACE.md](WORKSPACE.md) > `gh-token`; how the token is written into the workspace is in [WORKSPACE.md](WORKSPACE.md) > Creating.

What `claude-settings.json` holds, why the work sessions' permissions go in it, how it reaches a work session and what applies without it are in [WORKSPACE.md](WORKSPACE.md) > `claude-settings.json`.

What `coordination.md` holds is in [WORKSPACE.md](WORKSPACE.md) > `coordination.md`.

What `tools.json` holds and how its tools reach a work session are in [WORKSPACE.md](WORKSPACE.md) > `tools.json`.

You do not have to write a workspace by hand: if you name a workspace that does not exist, the coordination session builds it with you through questions and answers. [WORKSPACE.md](WORKSPACE.md) has the details.

## First run

1. Open cmux or tmux, with a window of at least the minimum size ([coordinator-role.md](coordinator-role.md) > Sessions), and go to your clone of this repository.
2. The first time you use a terminal on a machine, check it. From a shell in the same window, run:

   ```
   tools/terminal_check.py
   ```

   It opens panes below the current one, starts short Claude Code sessions there (`--model haiku`), then closes them and removes their transcripts. It prints `PASS` or `FAIL <why>` for each item and exits with status 0 only if all pass. If terminals are nested (tmux inside cmux, for example), name the one to check with `--terminal cmux` or `--terminal tmux`.

   Run the check again after the terminal is updated, and when instructions to work sessions repeatedly fail to arrive.
3. Start the coordination session in the clone with the workspace's token: `GH_TOKEN=$(cat <base>/<workspace name>/gh-token) claude`. Run preparation stops when the session's `GH_TOKEN` is not the token of the workspace it prepares a run for. For a workspace that does not exist yet, start `claude` without it, build the workspace, then start the session again with its token.
4. Tell it the workspace and the issue, for example: `Work on issue 123 in workspace my-repo.` Answer its questions: confirming the base if it comes from the built-in default, and building the workspace if it does not exist yet.
5. It presents a workflow outline for the issue. Approve it, or ask for changes. After approval it runs the workflow: work sessions open in panes below it, and it reports to you, stopping where a decision is yours (issue selection, workflow approval, policy changes and which pull requests to accept).
6. When the pull requests are ready, it gives you the merge review artifact and asks which to accept. You give your decision as the approval record, which only you make: in a terminal of your own (not through the Claude Code session), run the command it gives you. Before you run it, compare it with the form of that command in [coordinator-role.md](coordinator-role.md) > Operator boundary. What the decision in the approval record holds for is stated there as well ([coordinator-role.md](coordinator-role.md) > Operator boundary).

   Run it from the clone of this tool you know, by that path, and before you type the passphrase run `git -C <clone> fetch origin main`, check that `git -C <clone> rev-parse HEAD origin/main` prints the same commit twice and that `git -C <clone> status --porcelain --ignored -- tools/` prints nothing but `!! tools/__pycache__/` and `!! tools/terminals/__pycache__/`: a changed `approve.py` would receive your passphrase and could sign later records with it, and the key's fingerprint would not show it. For a command in that form, this proves the tool's files are origin's `main` at that commit, with no bytecode from the clone's caches; it does not prove the programs on your `PATH`, Python's own startup or what origin's `main` holds.

   `tools/approve.py` shows each pull request and its head, and asks you to type `yes` and the passphrase of your approval key. Before you type `yes`, check each printed `head` line against the merge review artifact: the heads it shows must be the heads you reviewed. When `merge-plan.json` changes after your decision, sign again: how the plan belongs to your decision is in [WORKSPACE.md](WORKSPACE.md) > `merge-plan.json`. A new run of `tools/approve.py` removes the earlier record first, so a run you do not confirm leaves none; to withdraw a decision, remove the run's `approval.json`, or run `tools/approve.py` and do not confirm. During a merge in progress, removing `approval.json` stops it before its next change on GitHub; what it already did stays. The first time, make the approval key once with `tools/approve.py --init` in your terminal, with a passphrase, and keep it out of SSH agents and keychains.

   A work session then runs `tools/merge.py`, which merges them in the order the workspace's `merge-plan.json` sets, waits for CI, closes the pull requests you did not choose and cleans up branches and the run's worktree. It stops and comes back to you through the coordination session when a head moved, on a conflict, when CI failed or did not run, and on anything else that does not match your decision. It refuses a record written by hand or by a session, but the record does not hold against a session that sets out to subvert it, since a session runs as your OS user and can put a key of its own in place of `approval-key.pub`. So compare the fingerprint the run's `merge.log` names with the one `tools/approve.py --init` printed to you: a match shows which key verified the record, not that the decision was yours.

How the coordination session builds the workflow and judges results is in [coordinator-role.md](coordinator-role.md); the reference workflows are in [workflows/README.md](workflows/README.md).

## Revising a criterion

A run records its criteria in the issue body, under the heading **Criteria**, between the lines `<!-- criteria -->` and `<!-- /criteria -->`. To revise a criterion yourself, edit the issue on GitHub while signed in as the account of the workspace's `gh-token`, and add one line at the end of that block, just above `<!-- /criteria -->`, in the form the block's lines show:

- `` `N-k.` <text> `` revises criterion N, with k a whole number above every k of N already in the block;
- `` `N-k.` `` with nothing after it withdraws criterion N;
- `` `N.` <text> `` adds criterion N, a number no line uses yet.

Leave off the `([grounds](…))` link the coordination session's lines end with: a line without it, written by that account, is your revision. A line added by another GitHub account is not taken as a criterion. The coordination session compares and assesses your line at its next comparison of the block ([coordinator-role.md](coordinator-role.md) > Module connection).

## The merge review artifact

The coordination session makes the merge review artifact, the summary you read before deciding a merge, with the `pr-postcard` skill. `pr-postcard` is the operator's own Claude Code skill: no repository distributes it, so it is not installed with this repository, AutoFlow or run-status.
