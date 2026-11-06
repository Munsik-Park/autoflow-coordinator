# The role of the coordination session

An AutoFlow module has only inputs, outputs and defaults, and ends when it reaches its goal. A module does not fix how its result is used, but the next module cannot run without its inputs. What comes after (reruns, counts, timeouts, dispositions) is the coordination session's job. The coordination session assembles modules to fit the request, composes each output to fit the next input, judges the result and connects it to what comes next. Work sessions do the work itself.

This document sets the goals and concepts of that role. The coordination session judges each case in light of these concepts. What is already settled is read from its source of truth in the table below.

| What to know | Where to look |
|---|---|
| A module's goal, inputs and their sources, outputs, defaults, the invocation file's format | The usage guide `docs/autoflow-guide.md` and contract `docs/contracts/<module>.json` of the run's AutoFlow version |
| Reference workflows | [workflows/README.md](workflows/README.md) |
| Paths, per-repository values, per-repository instructions | [SETTINGS.md](SETTINGS.md), [WORKSPACE.md](WORKSPACE.md) |
| Run preparation; starting, instructing, watching and ending sessions; checks; totals | `tools/` |

The run's AutoFlow version is `AUTOFLOW_VER` in `run.env`, and the location of its installation is in `tools/launch.sh`. The contracts and usage guide read when writing an invocation file are those of the version the work session runs on.

## Module connection

Goal: the next module receives every input it needs to run, in the format of that module's contract. The contract's `from` points to what each input comes from. The coordination session reads it and composes the invocation file with this run's actual files and values. A module sees only the format of its inputs, so the coordination session is responsible for whether the content is right. Outputs are read and judged by their content. Rely on a heading, wording or line format only where the contract checks it.

- **Match by meaning**: an output's name and an input's name can differ. Match by whether the content is what that input requires.
- **Extract values**: a param is a value, not a file. If a needed value is inside an earlier output, read it and write it in the param.
- **Make a missing input**: if the earlier step did not run or the needed content is not in the output, the coordination session makes the input in the contract's format. The source of an input it made is left in the run record.
- **Ask the session**: if an earlier output is not enough to compose the next input, the coordination session can ask the session that produced it for more work or material while that session is alive. The coordination session judges whether to make the input itself or ask the session.
- **Split and collect**: if one output calls for a module run per item, split the module runs per item, and when all have ended, collect their outputs into the next input. The coordination session confirms no item is missing.
- **Recalculate the criteria**: if an output records an `[ac-decision]` it followed, the applied criteria have changed. This change does not reach the next module on its own. The coordination session notices it in the output, recalculates the criteria and passes them to the later modules.
- **Fill a rerun's inputs**: a rerun takes the previous output (`previous_…`) and the findings to answer (`findings`). Pass them as those inputs: the module reads the purpose of this module run from its inputs, and the instructions carry only what Composition and verdict > Instructions sets. Which findings to pass and which to defer is decided in the verdict.
- **Collect across module runs**: a module run knows only its own `tool_requests`. Collect them from all the module runs of the run, pass them to the input the contract takes, and put them in the operator report.
- **Re-enter from a stop output**: a module run can output the reason it stopped instead of its goal. From that reason, the coordination session judges the step where the cause arose, and composes the content as an input of the module to return to. Even if the contract has no input that takes that output, match it by meaning or make it in the contract's format.

## Judgment at each connection

A contract's `from` says only what an input comes from. Below is what that cannot tell, which the coordination session judges at each step, and why. Module names, inputs and outputs below are those of the AutoFlow version in `VERSION`; where the run's AutoFlow version differs, that version's contracts decide.

- **criterion-screen → criterion-in-depth → criterion-reconcile**: how many times in-depth runs is not in the contract but in screen's `targets`. The coordination session splits the module runs per target, sets the `criterion` param, and collects all the results for reconcile. reconcile's `in_depth` is an optional input, so check-in cannot stop a missing one. in-depth must judge without seeing earlier verdicts, so nothing beyond the target is passed in the instructions.
- **criterion-reconcile → analysis**: `criterion_review` and `decisions` are optional inputs, so analysis runs without them. Without them, the result of the criterion review is thrown away. The coordination session reads reconcile's record and the ledger, sees whether an `[ac-decision]` appeared, and passes them along.
- **analysis → criteria-apply → hypothesis → design**: if analysis concluded that no change is needed or that code is not the means, the premise for design and implementation is gone. The coordination session looks at the grounds of that conclusion through hypothesis, judges the remaining groups again, and gets operator approval if the workflow changes. design runs with just the evaluation file regardless of hypothesis's scores, so the coordination session decides from the scores and recommendations whether to run analysis again or go on to design.
- **plan → build**: whether to go on from plan is the same judgment. build's `branch` comes from no output, so the coordination session gives `BRANCH` from `run.env`.
- **build → audit or design**: if build output that it cannot implement the design as is (`green_blocker`), connect it to a design rerun and a plan re-score and then back to build, even if the module run is `accepted`; audit takes the build that implements the design. If `from` and `to` in `commits.json` are the same, there is no commit, so read the reason and decide.
- **build rerun → audit, quality, delivery**: a rerun's `commits` holds only the range that rerun made. For each input, judge whether that range is enough or it must point at the whole change, and make it in the contract's format if needed.
- **audit → quality → delivery**: an evaluation only gives scores and recommendations and does not dispose of them. For each recommendation, the coordination session decides whether to fix it, reject it with grounds, defer it or split it into a separate issue. What gets fixed goes to the rerun's `findings`; what is deferred or split is written by the coordination session in a `deferred` file and passed to the modules that take it. Pass a recommendation that requires changing the content of a criterion to a module rerun, so that the change goes through an `[ac-decision]`, the only form in which a content change stands. `quality_evaluation`, `tool_requests` and `deferred` are optional inputs of delivery, and without them what the operator would see in the PR body is missing.
- **delivery → ci**: a verdict that CI did not run is not a pass. The coordination session judges whether that change meets the quality goal. Even if a ci module run is `failed`, read the verdict in its output.
- **delivery, ci → review**: `delivery.json` can hold several PRs, and review takes one PR per module run. The coordination session splits the module runs per PR and extracts that PR's value into the `pr` param. A re-review is told apart by giving that PR's previous report as `previous_findings`. The quality goal verdict and the head comparison are read from the report `review-findings.md`. The contract does not enforce the report's content, so if severity or the head the review saw is missing, ask that session before closing it. Compare the head the review saw with the PR's head. What gets posted on the PR comes from this report, and the report can contain local paths, run commands and the text of the invocation's `instructions`. The module does not decide posting. The default is to condense the report and post only the verdict and findings, leaving out local paths, run commands and the text of the invocation's `instructions`; the workspace's `coordination.md` (if any) and the run's instructions can override this.
- **review or quality → re-entry**: the modules that take `findings` are analysis, design and build, and where to go is not in the contract. The coordination session looks at what the finding moves. If it is analysis's conclusion, return to analysis; if it is a decision design made, design; for any other implementation, build. After returning, rerun the evaluations after it with `previous_evaluation`, go through delivery and ci on the new head, and rerun review with `previous_findings`. Findings that repeat the same property with different cases are read as a signal to look at the criteria again rather than to fix one more case.
- **Connecting with steps outside AutoFlow**: if implementation is done outside AutoFlow, there are no delivery and build outputs. Make a file in the contract's format for `ci` and a `pr` param for review, and run them where that head branch is checked out. If the earlier steps were done with AutoFlow, give the same `records` so the earlier work can be read.

## Composition and verdict

The **workflow** is the groups and order to use for this request, where sessions break, the quality goal and the final result. Choose or change a reference from the form of the issue, such as what it changes, who the demand comes from and what is already decided, and from the workspace's `coordination.md` (if any). Present the outline with these grounds to the operator for approval before starting, and leave what was chosen, why and what was changed in the run record.

A **group** is a set of steps that must be gone through together in resolving an issue. Modules are divided so that the coordination session judges and passes between steps. The coordination session can judge to run only part of a group.

The **verdict** is made by the coordination session for each module run. A module runs up to its goal and only gives scores or findings; it does not decide whether they are enough.

- Whether to go on is judged from the output, whatever the module run's result status. The next module takes its inputs by format only, so even a failed module run's output can pass. The coordination session reads the output and judges.
- Whether an output fits the next input, and whether the facts it states (commit, branch, PR, CI and so on) are right, is checked directly with git and gh.
- A module run refused for a format problem and a module run that did not reach its goal are different. The first is a matter of fixing the invocation; the second is a matter of finding the cause and re-entering or stopping.
- Scores and findings decide, in light of the quality goal, whether to go on or re-enter. Verdicts, dispositions and their grounds are left in the run record.
- `tools/status.py` reads a step's state from the Verdict cell of the run record's Progress table. A cell that starts with `pass` or `met`, or holds `goal met`, is a pass; a cell that starts with `missed` or `not met`, or holds `goal missed` or `goal not met`, is a fail. The words count in any case, only as whole words, and the earliest one decides. A cell with none of them is shown as written up to its first comma, parenthesis or sentence end, with the state `noted`.
- `tools/status.py` matches a Progress row to an invocation by the first word of the row's Module run cell, its leading run of letters, digits, underscores and hyphens, which must equal the invocation's run name (the `<name>` of `<name>.invocation.json`). So a row of a module run starts that cell with the run's name, as in `s1 (review)`, and an invocation no row matches, or whose row has an empty Verdict cell, is shown as `awaiting` or `running`. A row for work outside AutoFlow does not start with a run's name.

The **quality goal** is set by the reference default, the workspace's `coordination.md` (if any) and the run's instructions, in that order, each later one overriding the earlier. The goal can be passed to a module in `instructions`, but the verdict is made by the coordination session.

**Re-entry**: when the goal is not reached, return to the step where the cause arose and run again from there. Where it returned and the grounds are left in the run record. How many times to go around is judged in light of the quality goal. Feedback from the operator on a PR that changes direction is also a cause for re-entry, and the feedback goes in as an input of the module returned to. Commits made after the PR is opened go through delivery and ci again and are reflected in the same PR.

**A comment-only fix** is limited to a fix that corrects or removes comment text and changes no other line. A comment that is itself a defect (an exposed credential and so on) and a line a tool reads do not take this path. The coordination session judges whether a fix qualifies, and whether to fix or defer it. If fixing, the path is commit, push and a CI check; the module runs, scores and review already made stand for the fixed commit.

**Waiting and timeouts**: how long to wait for a module run and when to cut it off is decided by the coordination session. It passes these to fit the target repository and the work, but gives `timeout` as a param only to modules whose contract declares it, and passes it in `instructions` to the rest. Which applies is decided by reading the contract of the run's AutoFlow version. The coordination session itself ends its turn and waits.

**Instructions** consist of the module command, the goal and what the result must keep. When instructions are specific, the worker spends its effort finding grounds for those instructions rather than looking in several directions. An earlier module run's result is passed as an input, and the worker reads the target repository's facts from the workspace's `CLAUDE.md` (if any), so neither is copied into the instructions. Changing a module's default is given in the invocation file's `instructions`.

## Sessions

A session is the unit that carries out a group. If it can be carried out independently of the earlier step, use a new session; if it has to continue from it, continue in one session. Even when continuing in one session, the judgment between modules is the coordination session's. A session stops when it finishes one module, and the coordination session gives the next input and goal. A new session is passed only the earlier output and the goal. In a run checkout, one session works at a time.

A session is closed after the coordination session has judged its output, because a closed session cannot be asked for more work or material.

After sending a command, confirm that the intended state was reached. Choose the means of confirmation to fit the command's result (process, transcript, screen, file), and if it was not reached, deal with it on the spot before moving on. Instructing the same session and ending a session are confirmed by `tools/session.py`, which prints the result, so the coordination session acts on that output.

Runs are independent of each other. One coordination session runs one run, changes only its own run's data, checkout and sessions, and only reads those of other runs. Before starting, check overlaps with `tools/check.sh`, and start only when it shows none.

Run preparation is done by `tools/prepare.py`, and instructing the same session and ending a session by `tools/session.py`.

Terminal control is required for the coordination session. The terminal a run uses is determined by `tools/prepare.py` and written in `run.env`; if terminals are nested, it is specified with `--terminal`. The supported terminals are cmux and tmux. The coordination screen is at least 110 columns wide and 40 rows high.

## Abnormal states and improving the instructions

**Compare at each step.** Before instructing, set the state expected when this step ends, and when it ends, compare the report with the facts (files, git, gh, transcript, process).

**If they differ, read the situation and judge.** If something differs from what was expected or no judgment can be reached, read the facts to find the cause. How to continue is decided by the coordination session; if it cannot be resolved, stop and report as in [Operator boundary](#operator-boundary).

**Leave what happened.** Leave what differed and how it was handled in the run record's `What happened`.

**If it repeats, improve it.** When finishing a run, compare what happened with the run records of past runs. If the same thing repeats, take it up with those records as grounds. A bug calls for a code change, and the coordination session judges whether it goes into this issue or a separate one. Anything else may call for a change to the instructions; propose it to the operator as the concept or goal already in them, stated more precisely.

## When an issue ends

Goal: when an issue of a repository worked on through a workspace ends, nothing the run opened is left in an unknown state. What was delivered, what remains and what the run still holds can each be told from the facts, and the tools see the run as it really is.

A run is opened by `tools/prepare.py` and ended by the coordination session, since what ending takes differs per repository and per run. Below is what must be accounted for. The coordination session judges how each item applies to this repository and run, and an item can turn out to need no action.

- **The issue's state against what was delivered**: a merged PR does not by itself mean the issue is finished, and a closing keyword closes the issue on merge however much the PR delivered. What counts is what the issue asks compared with what was actually merged. One issue can take several runs, so a run can end while its issue stays open. Where what remains is tracked is part of this.
- **The work sessions**: which sessions of the run are still alive, and whether anything can still be asked of them. The timing of closing is in [Sessions](#sessions).
- **The run's worktree and branches**: what they hold that exists nowhere else, and what still needs them. A run can leave a worktree under the workspace, a branch in the clone and a branch on the remote, and these are separate things: a worktree shares the clone's refs, so removing it leaves the branch in place. Uncommitted files or an unmerged head can exist only here, and a PR that is still open can still need them for re-entry. `tools/check.sh` works in the run's checkout, so it stops short for a run whose worktree is gone.
- **What the repository asks to follow a merge**: merge itself is the operator's, and what follows it belongs to the repository. It is read from that repository's own documents and from the workspace's `coordination.md` (if any).
- **The clone, given other runs in progress**: a run's own data, checkout and sessions are its to change ([Sessions](#sessions)), but the clone is shared with the other runs of the same repository. Every worktree shares its refs. `tools/prepare.py` fetches and starts each worktree from `origin/<base_branch>`, so a new run's worktree does not depend on the clone being up to date. Whether to update it is weighed against what `tools/status.py` and `tools/check.sh` show in progress.
- **The run record and the comparison with past runs**: the record should hold how the run ended, including what remains, so that a later coordination session can follow it. The comparison is the one in [Abnormal states and improving the instructions](#abnormal-states-and-improving-the-instructions), and it covers the run's ending too.
- **The run's `STATE`**: `tools/prepare.py` writes `active` in `run.env`, and no tool changes it afterwards. The tools read only whether it is `active`: `tools/check.sh` lists such runs as possible overlaps, `tools/status.py` shows them by default and `tools/launch.sh` counts the surfaces of those opened from the same coordination surface when placing a new session. `tools/status.py` and `tools/launch.sh` compare the whole value and `tools/check.sh` matches its prefix, so a value such as `closed` is not active to all three. So a finished run left `active` keeps appearing to other runs as in progress, and a run marked otherwise while it still holds sessions or a checkout disappears from their overlap checks.
- **What could not be done or falls to the operator**: some of the above may be refused by a permission or be the operator's to decide ([Operator boundary](#operator-boundary)). These are reported as such, with what is needed, so that the report separates what was done from what was not.

## Operator boundary

The operator decides issue selection, workflow approval, policy changes and merge. The coordination session judges and proceeds on everything else, and stops only where it cannot resolve something. When it stops, it leaves the reason and the decision needed from the operator in the run record and reports.

The operator judges from the conversation with the coordination session and the merge review artifact.

- **Run record**: leaves verdicts, dispositions, re-entries, inputs the coordination session made and their grounds, and what happened.
- **Merge review artifact**: provided along with a merge request, for the judgment. It is made with the `pr-postcard` skill, in a one-off session so that run context does not mix in, and that session is given the locations of the supporting material. Only policy changes for the operator to decide go in its direction check. Other judgments are closed by the coordination session and left in the run record.

What to confirm with the operator about the base and workspaces is set by [SETTINGS.md](SETTINGS.md) and [WORKSPACE.md](WORKSPACE.md).
