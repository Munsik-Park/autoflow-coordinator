# Work records of earlier runs: AutoFlow module assembly and session operation (cmux)

Written: 2026-10-21.

This document is a progress record collected from the work of earlier runs for improvement work. It is not procedures, rules or grounds. The rules, instruction formats and handling tables in the body describe the operation at the time of recording. RUNBOOK and `RUNBOOK.md` in the body are earlier names of this file. Absorbing the content into rules is done in Munsik-Park/autoflow-coordinator#4 (operator instruction 2026-10-30).

The document this record took over: `.autoflow/unit-session-coordination-guide.md` in the AutoFlow checkout (2026-10-06, AutoFlow 0.2.x, U1~U6, screen-based watching). The content that was valid at the time of recording was moved here.

Source of the roles: Munsik-Park/autoflow#471 (body: roles 1–4, comment 2026-10-19: operating practices).

## 0. Roles

The coordination session does not do the work itself. It builds a workflow that fits the request, starts work sessions with cmux to run AutoFlow modules, and judges a module's result and connects it to the next module's input and goal.

- Workflow references and the concepts of coordination (connection, verdict, re-entry, sessions, quality goals): `workflows/README.md`
- A module's inputs, outputs, defaults: `docs/autoflow-guide.md` and `docs/contracts/<module>.json` of the installation of the run's version
- Values and instructions that differ per repository: `repo.json` and `coordination.md` (optional, `WORKSPACE.md`) of the workspace the operator specified. When given a workspace, the coordination session reads and follows them
- Paths: the work space (workspaces under the base, run worktrees) and progress records (locations under the coordination root) (`SETTINGS.md`). Values are obtained with `tools/config.py`

| Actor | What it does |
|---|---|
| Operator | issue selection, workflow approval, decisions on stop reasons |
| Coordination session | composing the workflow, preparation, writing invocation files and instructions, starting, watching and ending work sessions, judging and connecting results, recording, reporting |
| Work session | runs the module command it receives, and stops when one module ends |

## 1. Fixed rules

1. **There is one checkout.** All work sessions of a run run in the same target checkout (the run worktree).
2. **Only one session works at a time.** A session runs `/exit` when its group is finished, and its pane is closed after confirming that the process has ended. If two sessions work in the same checkout at the same time, stop immediately and record it. Logs are viewed through the transcript and the id in sessions.tsv (`claude --resume <id>`) (operator decision 2026-10-22).
3. **Pin the AutoFlow version.** The reference is the plugin installation (`~/.claude/plugins/cache/autoflow/autoflow/<ver>`). At the start of a run, the installation's version is written in run.env `AUTOFLOW_VER`, and `launch.sh` starts work sessions with `claude --plugin-dir <cache>/<AUTOFLOW_VER>`, so they run on the same version even if the installation changes during the run. The contracts and usage guide read when writing an invocation file are also those of that version (operator instruction 2026-10-22: the defense against an update that came in by mistake goes only as far as pinning the version during execution).
4. **Results are read and judged directly (§3).** For each module run, read the result and output, and check the facts the output states with git and gh.
5. **Instructions are written to a file before they are sent.** Both the start instruction and the module instructions given next to the same session are left in the run directory, and the fact that they were sent is written in the run runbook.
6. **Run data is kept in `runs/<run name>/` of the coordination root (§2.3).** This repository holds only the rules and is managed with git. Run data is outside git and the tool clone, so a coordination session run from any clone and any cwd writes run.env in the same location, and `check.sh` sees overlaps in one place (operator decision 2026-10-22, 2026-10-30).
7. **Confirm the result after sending a command.** After sending a command to a work session, cmux or the shell, the coordination session directly confirms that the intended state was reached, and if it was not (a confirmation dialog, an error, no response), deals with it on the spot before going to the next step. The means of confirmation is chosen to fit the command's result (process, transcript, `cmux tree` and `read-screen`, file). Grounds: the next session was once started while `/exit` was stuck at a confirmation dialog, and two sessions overlapped for about one minute; in one run, all 7 `/exit`s brought up a confirmation dialog (operator instruction 2026-10-25: "명령 -> 방치 / 명령 -> 확인으로 프로세스를 바꾸세요 … 종료도구 / 시작도구 / 중간도구 / 분할 도구를 모두 따로 만들건가요?").

## 1.1 Parallel coordination sessions

Operator instruction (2026-10-22): make two or more coordination sessions not interfere with each other even when they run in this folder at the same time. The rules below were tested with parallel runs of different issues and of the same issue. Operator decision (2026-10-25): the default is that one coordination session runs one issue (rule 1).

**What is shared and what is separate**

| Resource | Shared or not | Grounds |
|---|---|---|
| coordination repository working tree and work branch | shared | |
| `RUNBOOK.md`, `CLAUDE.md`, `tools/`, `.claude/settings.local.json` | shared | same files |
| coordination root (run data, record folders) | shared | the one location found through settings (`SETTINGS.md`). The same even if the tool clone differs |
| files of the base and workspaces | shared | the one location found through settings (`SETTINGS.md`). A change applies to every run that uses that workspace (`WORKSPACE.md`). Run worktrees are separate per run |
| AutoFlow plugin installation | shared | one `~/.claude/plugins/cache/autoflow/autoflow/<ver>` |
| leftover resource list of `tools/check.sh` | sees the whole machine | no checkout filter in the last step `ps … \| grep` |
| handoff file names in `~/.claude/handoffs/` | separate | include the run name (rule 10). The sequence-number scheme (`coordination-<seq>-handoff.md`) can collide |
| `watch.py`, `launch.sh` | separate | handle only the cmux workspace, surface and session ids in run.env and sessions.tsv |
| AutoFlow record folders | separate | `records/<run name>` of the coordination root per run |

**Rules**

1. **Separate by run.** One coordination session has one run directory `<runs>/<run name>/`. Even when it handles another repository or another issue, the run data is kept in this location. The run directories of other coordination sessions are only read. The default is that one coordination session runs one issue, and the work of several coordination sessions is independent of each other (operator decision 2026-10-25, after the parallel test of the same issue: "개선하지 않는다 1 조율 세션 1이슈 실행을 베이스로 한다 같은 레포 위치에서 여러 조율 세션의 작업은 독립적이다").
2. **Write ownership and state in run.env.** Write `COORD_SURFACE=<coordination surface>` and `STATE=active` before starting, and when the run ends (after cleanup is complete or the end of the run is recorded) change it to `STATE=closed`. If there is no `STATE`, it is treated as closed.
3. **Checkouts and cmux workspaces do not overlap.** Before starting, `tools/check.sh` lists the other `STATE=active` runs and marks `SAME CHECKOUT` or `SAME WORKSPACE` if `CHECKOUT` or `WORKSPACE` is the same, and `NOT UNDER RUNS` if its own run directory is outside `<runs>` and so is not visible to the checks of other runs. If a mark appears, do not start; tell the operator. The same issue can be handled by two runs at the same time if their checkouts differ.(operator decision 2026-10-24: two workers can run the same issue).
4. **cmux touches only its own.** Each coordination session uses its own cmux workspace. Do not `send`, `paste`, `rename-tab` or `resize-pane` to a surface that is not in its own sessions.tsv. Call `workspace.equalize_splits` only on its own cmux workspace. Other cmux workspaces are only read with `cmux tree --all` and `read-screen`.
5. **git commits only its own paths.**
   - Specify paths, as in `git add -- <changed shared file>`. Do not use `git add -A`, `git add .`, `commit -a`, `stash`, `reset`, `checkout -- .` or `clean`.
   - Before committing, check with `git status --short` that the staged list holds only its own paths. Do not touch the uncommitted files of other sessions.
   - If it fails because of `index.lock`, run the same command again a little later. Do not delete the lock file.
6. **Commit a shared file separately as soon as it is changed.** `RUNBOOK.md`, `tools/` and `CLAUDE.md` are changed only when the operator instructs. Before changing, check with `git diff -- <file>` that there are no uncommitted changes from another session; if there are, leave them as that session's and tell the operator. Change only the part to be changed. After changing, commit right away with only that file, and write the commit hash in its own run runbook. Other sessions check with `git log -1 -- RUNBOOK.md` whether it changed before starting the run's next session, and read it again if it changed.
7. **Reclaim only its own leftover resources.** Of the browser, Playwright, mongo and dev server processes `check.sh` shows, reclaim only those whose parent chain leads to a work session in its own sessions.tsv (§4-1). Write the rest in the run runbook and tell the operator. Do not end processes in bulk by pattern (`pkill`, `killall`).
8. **Settle local service ports before starting.** If the target work starts local services such as a dev server, mongo or Playwright, write the ports used at the head of the run runbook and compare them with the runbooks of the other active runs. If they overlap, the operator sets the order.
9. **Put the run name on reports and notifications.** The first line of a report to the operator and the body of a `PushNotification` start with `[<run name>]`. This lets the operator tell at once which run it is about.
10. **Put the run in the handoff file name.** `~/.claude/handoffs/coordination-<run name>-handoff.md`.
11. **Follow only instructions received in its own terminal.** Decisions and instructions about another coordination session's run must be delivered to that session. If received, do not carry them out; tell the operator which session they belong to.

## 2. Preparation

### 2.1 Issue, workspace, worktree, record folder

- Issue selection (the operator makes the final selection): one whose criteria are concrete and can be verified locally. Exclude issues that need a deployment host, real external services, or a prerequisite issue to be settled.
- **base**: if the source of the base that `tools/config.py` prints is the built-in default, do not work with that base before the operator confirms it (`SETTINGS.md` > Work space).
- **workspace**: when presenting workspaces to the operator, find the directories in the base that have a `repo.json` (`WORKSPACE.md` > Finding). Check `repo.json` of the workspace the operator specified, and read and follow `coordination.md` if there is one. If the workspace does not exist or facts the run needs are missing, ask the operator questions and write the answers in the workspace. The structure and the role of each file are in `WORKSPACE.md`. Repository facts are kept only in the workspace, not in the user repository or this repository.
- **worktree**: for each run, create a detached worktree at `<repo>-wt-<N>-<KEY>` under the workspace, from `origin/<base_branch>` after `git fetch` in `repo.json`'s `clone`. The path is made from the run key (§2.3), and it is created after the key is secured with the run directory. Do not reuse another run's worktree.
  - What git does not create is provided by following `coordination.md`.
  - Work session instructions and permission settings are kept in the workspace and not copied into the worktree (`WORKSPACE.md`).
  - If a parent folder is already trusted, the trust dialog does not appear.
- **record folder**: the coordinator creates `<records>/<run name>`. The module's `records`, the output folder of each module run, and the invocation files are placed here.

### 2.2 cmux layout

Coordination window as column 1 (full height) + two work panes (W1, W2) + one-off pane X. A session that has passed a boundary runs `/exit` (§1-2), so only one work session is alive at a time. Sk is started in W1 if k is odd and in W2 if even, so the screen of the previous group remains in the pane beside it. X is the pane for starting one-off work such as merge follow-up (§6) as a new session (operator suggestion 2026-10-22). The earlier layout (a work window of 4 columns × 2 rows, S1~S7 fixed) dates from when sessions were left idle.

```bash
export CMUX_QUIET=1; W=<workspace ref>; C=<coordination surface>
sp(){ cmux new-split $1 --workspace $W --surface $2 --focus false | awk '{print $2}'; }
W1=$(sp right $C); W2=$(sp right $W1); X=$(sp down $W2)
WID=$(cmux rpc workspace.list '{}' | python3 -c "import json,sys;print([w['id'] for w in json.load(sys.stdin)['workspaces'] if w.get('ref')=='$W'][0])")
cmux rpc workspace.equalize_splits "{\"workspace_id\":\"$WID\"}"
cmux resize-pane --workspace $W --pane <coordination pane> -R --amount <px>   # the unit is px. The remaining columns shrink evenly
cmux rpc pane.list "{\"workspace_id\":\"$W\"}"                       # called without workspace_id, only some are shown
```

- tab name: each time a session is started, `cmux rename-tab --workspace $W --surface <W1|W2|X> "Sk <group>"` (for X, `"Xn <work>"`).
- Each pane is kept waiting with `cd <checkout> && clear`. In a pane whose previous session ran `/exit`, the next session is started from that shell.
- No official record of a minimum size requirement for the Claude Code TUI was found. anthropics/claude-code#93475 reports 80×24 as the standard size, and says some selectors are cut off even at that size. The work windows may be narrow (the operator watches the coordination window), and the coordination window is kept at 80 cols or more.

### 2.3 Run directory

```
<runs>/<run name>/
  run.env        RUN_KEY=… RUN_KEY_SOURCE=external|self WORKSPACE=<cmux workspace> CHECKOUT=… RECORDS=… ISSUE=… COORD_SURFACE=… STATE=active|closed (§1.1) AUTOFLOW_VER=… (§1-3)
  sessions.tsv   Sk<TAB>surface<TAB>session-id   (set in advance with uuidgen. One-off sessions are Xn rows)
  sK-prompt.txt, xn-prompt.txt, instruction files given next to the same session
  runbook.md     run record (§7)
```

- `<runs>` and `<records>` are locations under the coordination root, printed by `tools/config.py runs|records`. Workspaces and run worktrees are under `tools/config.py base` (`SETTINGS.md`).
- **Run key.** When assigned a run, decide one unique key, and make the run name, worktree path, record folder and handoff file name (§1.1-10) all from this key (operator decision 2026-10-24: two workers can run the same issue).
  - If there is a key received from outside, use it (`RUN_KEY_SOURCE=external`). If not, make one with `$(date +%Y-%m-%d-%H%M%S)-$(openssl rand -hex 4)` (`self`).
  - The key uses only `[A-Za-z0-9._-]`. It goes into path names as is.
  - Create the run directory first of all with `mkdir` (without `-p`) (if `<runs>` does not exist yet, create only that first) to secure the key, and create the worktree and record folder after that. Even with simultaneous attempts, only one `mkdir` succeeds (2026-10-24 test). If it fails, do not start; tell the operator.
- The run name is `<repo>-<N>-<KEY>`. Runs of the same issue gather together and line up in time order. Issue numbers with different numbers of digits are viewed with `ls | sort -V`.
- The k of `tools/launch.sh <run> <k>` and `tools/watch.py <run> <k>` is the number of Sk or a one-off session name such as `X1`.

### 2.4 Instructions

The instructions given to a work session are the module command, the goal and the constraints.

```
/autoflow:<module> <invocation file>

Goal: <what this module run will reach>
Constraints: <what the result must keep>
Stop when this module ends and wait for the next instruction.
```

- The coordinator writes the invocation file after reading the contract and usage guide of the run's version. An input is the output of an earlier module run, or a file the coordinator made in the contract's format (`workflows/README.md` > Connection).
- Write in the instructions only what the result must keep. Do not write methods, lists of cases or what to do next. When instructions are specific, the worker spends its effort finding the grounds for those instructions rather than looking in several directions (operator confirmation 2026-10-26).
- Facts of the target repository are not written again in the instructions. The worker reads them from the workspace's `CLAUDE.md` (if any).
- When giving the next module of the group to the same session, the same format is also written to a file and sent (§1-5; how to send is in §8.1 Further instructions).
- Changing a module's default is given in the invocation file's `instructions`. What is set per repository is read from `coordination.md`. instructions change only defaults and cannot change outputs.

### 2.5 Rework

If the operator gives feedback that changes direction on a submitted PR, re-enter at the step where the cause arose, on the same branch and PR (`workflows/README.md` > Re-entry). The feedback is passed as an input of the module re-entered. Whether to start over from the beginning with a new run is decided by the operator.

## 3. Verdict on results

The coordinator makes a verdict each time a module ends. The criteria are `workflows/README.md` > Verdict and quality goals.

- The module run's result is `result.json` in the output folder. `refused` is a format problem: if refused at check-in, no work was done, so fix the invocation file and run again; if refused at check-out, decide after looking at `defects`. `failed` means the goal was not reached, so read `failure.md` and re-enter or stop.
- Even if `accepted`, check whether the output fits the input, and whether the facts the output states (commit, branch, PR, CI) are right.
- Evaluation scores and review findings decide, in light of the quality goal, whether to go on or re-enter. The disposition of each recommendation (passed as input to a rerun, deferred) is also decided by the coordinator.
- If the output records an `[ac-decision]` it followed, the applied criteria have changed. Recalculate them with criteria-apply and pass them to the later modules.
- The `tool-requests.json` left by each module run is collected, passed to delivery and put in the final report.
- Verdicts and grounds are left in the run runbook. `tools/check.sh` shows the state of each module run in the record folder.

### 3.1 GitHub CI

- The ci module waits until the timeout for checks to come up. The timeout is given to fit the target repository's CI. Whether CI runs and how long it takes are read from `coordination.md` (observed 2026-10-30: it waited the full default of 900 seconds, and given 120 seconds it ended in about 3 minutes).
- If commits are added after the PR is opened, run ci again on the new head. The verdict is separate for each head.

## 4. Execution loop (one session)

1. **Pre-start check**: `tools/check.sh <runs>/<run>`. Look at overlaps with other active runs, the state of the module runs in the record folder, the tree, and leftover resources.
   - Leftover resources: browser, Playwright, mongo, dev server. Reclaim only those whose parent chain leads to a work session of this run (check before the session runs `/exit`; after it ends, the parent chain is broken), and for those whose origin cannot be traced, record them and tell the operator. Resident processes such as the ChatGPT/Codex app, cmux and security agents are not targets.
2. **Start**: `tools/launch.sh <runs>/<run> <k> [tab]`: if the session is not in sessions.tsv, it creates a new pane beside the coordination pane and a session id, moves to the checkout, sends `claude --plugin-dir <cache>/<AUTOFLOW_VER> [--settings <workspace>/claude-settings.json] --session-id <id> "$(cat sK-prompt.txt)"` with that session id (`--settings` only when the workspace has permission settings. If `AUTOFLOW_VER` is missing or that directory does not exist, it does not send and stops), and after 15 seconds checks the transcript's creation and the screen. The start time is written in the run runbook.
3. **Watch**: run `tools/watch.py <runs>/<run> <k> [baseline] [timeout]` with `run_in_background` and end the turn. `TURN_END` comes with the session's last report.
4. **Verdict and connection**: handle the notification (§4.1) → verdict (§3) → record in the run runbook → if the group has a next module, send the next instruction (§2.4) to the same session and go to step 3; if the group is finished, `/exit` the session, confirm the process is gone, close the pane → notify the operator → step 1 of the next group.

### 4.1 Watch output and handling

| Output | Meaning | Handling |
|---|---|---|
| `TURN_END <n>` | after the baseline, a new `system/turn_duration` is the last turn record, and no background work remains | read the report from the transcript's last assistant text (the TUI scrollback is short) and check §3 |
| `WAITING_INPUT` | choices or a permission question in the bottom 12 lines of the screen | handle within the delegation scope of §5.2 |
| `IDLE-PENDING <ids>` | turn ended + remaining work + no transcript change for 10 minutes + no running shell under the work session | identify what the remaining work is from the transcript. If it is in progress, set the watch again |
| `STALL` | no change for 30 minutes + no running shell | check the screen and transcript, then report to the operator |
| `TIMEOUT` | time limit exceeded | same |

**Watch criteria (`watch.py`)**

- The input of the completion verdict is the transcript. The screen is used only for the waiting-for-input verdict (#471 §2: screen text overlaps with the work session's body text).
- Remaining background work = among the `requestShape:"background"` `toolUseId`s of `subagents/*.meta.json` and the Bash calls whose tool result has `running in background with ID: …`, those without a `<task-notification>` (`tool-use-id` or `task-id`) in the main transcript.
- Not counted as remaining work: `sleep …` Bash (the work session's own cache keep-alive).
- Treated as in progress: an mtime change of the main or subagent transcript, and a Bash tool shell directly under the work session's claude (a process that sources `~/.claude/shell-snapshots/`). MCP servers and `cmux hooks claude …` are children of claude throughout the session, so they are not counted.
- When setting the watch again, give the number of turns already ended as the baseline.

### 4.2 Keeping and ending sessions

A session's lifetime is its group (`workflows/README.md` > Sessions). A session whose group has finished has no path to receive input again, so it runs `/exit` and its pane is closed. While it waits for the next instruction within the group, it is kept. A kept session rereads its whole context each time the cache is kept alive, which incurs cost (operator instruction 2026-10-22).

- **Exception**: a session that has something to be input again even after its group finishes (for example, when the operator has decided to ask that session a question) does not `/exit`; until that is done, the work session itself sets a background `sleep 3000` and sets it again when it ends. Write the reason in the run runbook.
- **The coordination session's own timer**: §8.1. `sleep 3000` sometimes ends within minutes with exit 144 (observed in several runs, cause unconfirmed). Set it again regardless of why it ended.

## 5. Delegation, stop reasons, context

### 5.1 Operator delegation

The scope in which the operator instructed "정지 사유가 없으면 자동으로 이어간다" (2026-10-21):

- Verdict → record → pre-start check → next module or next session.
- A work session's `AskUserQuestion` → the "Recommended" option. If there is no recommended mark, do not input; wait and report.
- Push and PR creation are done by the work session according to the module's default.
- Candidates for separate or follow-up issues left by a work session are not a stop reason. Proceed without waiting, collect the candidates in the run runbook and write them in the merge review artifact (§6.1 Structure item 7). Whether to file them is decided by the operator (operator decision 2026-10-24).
- Things that would require waiting for the operator's answer (external posting, deletion, irreversible actions) are approved before the run starts.

### 5.2 Stop reasons (record and notify without inputting)

| Situation | Handling |
|---|---|
| permission prompt (blocked by auto mode) | wait for operator approval |
| harness-level block (tools, credentials, material) | operator decision |
| a result short of the goal cannot be resolved by re-entry | record, operator's judgment |
| simultaneous work in the same checkout | stop immediately, record the failure case |
| question without a recommended mark | wait |

### 5.3 Context between sessions

- The result of an earlier module run is passed as the next module's input. It is not copied into the instruction text.
- The main paths for instructions and the completion verdict are cmux and the transcript. `SendMessage` is used as an aid for the first message right after starting (#471 §4).
- Starting a nested session with `claude -p` inside a work session is refused by the auto mode classifier. If a separate session is needed, the coordination session starts it with cmux (#471 §5).

### 5.4 Notifications

- When the operator turns on `/remote-control`, send with `PushNotification`: group finished, stop reason, run completed.
- If the terminal is active, it is not sent. This is normal.

## 6. After the end

1. Write a result summary in the run runbook: PR, CI, review aggregation, evaluation scores, re-entries and their grounds, watch misjudgments and corrections, tokens and cost (`tools/usage.py <run-dir> COORD=<coordination session id>`, operator instruction 2026-10-25).
1a. Make the merge review artifact and present it along with the run result report (§6.1).
2. Merge is an external decision. What comes after merge is decided not by AutoFlow but by the coordinator. The procedure differs per repository, so it is kept in the workspace's `coordination.md`, and the coordination session reads and follows it. If a needed fact is missing, ask the operator and write it in `coordination.md` (operator instruction 2026-10-25: "머지 후의 절차는 레포별 상황에 맞춘 설정입니다 … 그것이 없는 경우 조율 세션이 아니라 레포에 적어야 합니다". The place for repository facts is the workspace, operator decision 2026-10-30).
   - **Carrying out**: on receiving the merge notice, write the instruction as `xn-prompt.txt` and start it as a new session in one-off pane X (`tools/launch.sh <run> Xn`). `coordination.md` is not loaded into work sessions, so the coordination session copies what X must do from `coordination.md` into the instruction. When it is done, `/exit` that session and close the pane.

### 6.1 Merge review artifact

Operator instruction (2026-10-22): when requesting a merge after the PR is created, present along with it an HTML artifact that summarizes the result at the conceptual level. The worker uses it to judge whether the result matches the intent behind the issue and explains the direction again. The purpose is a conceptual explanation, not a code explanation.

- **Timing and actor**: made after the workflow ends, along with the run result report to the operator. How to make it follows the `pr-postcard` skill, and it is made in a one-off session (pane X) so that run context does not mix in (autoflow-523 observation: with the same input, the postcard a new session made had a better-fitting structure than the coordination session's). It is not issue work but work of coordinating with the operator (#471 intent change 2026-10-21).
- **Grounds**: read the record folder (criterion review, ledger, analysis, design and build reports, review findings), the PR body and the run runbook directly. Values written on the page, such as contract values and lists, are checked in the target repository.
- **Structure** (in the order the worker asks)
  1. Why it started: the problem the issue meant to solve and the path by which that problem arose
  2. What changed during review: the criteria the criterion review changed, per AC, as original / after the change / why (revised, added, rejected)
  3. How it was solved: the concept of the resolution (what it takes as input, what it compares against, failure handling, where it runs, what people must keep doing)
  4. Where it was reworked: in time order. Re-entries and their reasons
  5. Direction check: points AutoFlow decided on its own but that people need to look at for whether they match the original intent, the known gaps in the PR body
  6. Merge order and merge follow-up
  7. Candidates for separate or follow-up issues: problems the work sessions and gates split out of this issue's scope (criterion review splits, split verdicts in gate recommendations, drafts left by work sessions). For each candidate, write what the problem is, where it came from (module, ledger entry), the draft location and the duplicate search result. Leave them unfiled; whether to file them is decided by the operator in the issue review (§5.1)
- **Level of explanation**: between the `plain-talk-explain` skill and technical documentation (operator confirmation).
  - Write as if talking to a colleague. Mix "~합니다" and "~해요".
  - In the body, leave out code identifiers and file paths and call things by what they do (e.g. flag → deployment option, contract → list of services that must be up, advisory → warns only, without blocking, fail closed → treats it as a failure when unclear, known gaps → remaining limits).
  - Keep AC numbers, PR numbers, gate scores and names used as is in the field (service names and so on) so it can be checked against the issue. Keep the table, flow and time-order structure too.
  - Keep conditions and grounds such as "only when …", "confirmed by reading only", "not yet confirmed".
- **Figures** (`artifact-diagramming` skill, inline SVG): add them when there is behavior that the reader would have to assemble in their head from words alone.
  - Draw the resolution as **before / after in the same box layout** so they can be compared top and bottom.
  - If the reason a criterion was added or revised is "a case that passes under the original criterion", draw that case side by side.
  - If multi-repo, draw the merge order with a line per repository and pointer movement.
  - State in the caption that a hypothetical example is an example. Colors follow the page tokens so they read in both light and dark, and on narrow screens only the figure scrolls horizontally.
- **Location and publishing**: the source is kept in `merge-summary.html` in the run directory and published as an Artifact (private). A change is published again with the same file path to keep the link.
- **Leaving it on the PR and sharing** (operator decision 2026-10-22):
  - **Do not fix state that changes** (operator instruction 2026-10-22: "인지 가능하고 변경되는 사항이라 고정하면 안됩니다"). Facts that change later, such as the PR's CI, draft and merge status and the artifact's sharing scope, are not written in the artifact or comment; point to where to check them (the PR link). What is already past, such as review round results, gate scores and the course of rework, is written.
  - The coordination session adds a comment with the artifact link on the host PR. The body is one line on what was summarized and the link. Leave the body file as `pr-<N>-artifact-comment.md` in the run directory and post it with `gh pr comment --body-file`. The PR body was written by the delivery module, so it is not changed.
  - The artifact starts private. The coordination session cannot change the sharing scope (only possible from the Share menu).
  - The operator who merges reviews it, and if needed changes the sharing scope with Share, or exports it directly if it needs to be kept.

## 7. Run runbook format

```
# Run runbook: <run name> (<repo>#<N>)
- coordination session, changes from the reference, quality goal, operator's instruction verbatim, base (commit, AutoFlow version), paths (workspace, worktree, record folder)
## Progress record
| Session | Module run | session-id | Start | End (watch output) | Verdict | Notes (re-entry, disposition, inputs the coordinator made) |
## Operator instructions / coordinator judgments / result summary
```

## 8. Observed pitfalls

| Observation (run) | Response |
|---|---|
| Judging completion from screen text misjudges because it overlaps with the completion line and report body of an earlier turn (#471 runs 4 and 5) | transcript verdict (§4.1) |
| The work session's keep-alive `sleep 3000` was counted as remaining work | exclude `sleep` |
| If a unit agent runs in the background for more than 10 minutes, `IDLE-PENDING` | treat subagent transcript mtime as progress |
| A background Bash wrote its output to its own log file, so the transcript looked stopped (mock e2e 26 minutes) | treat a live Bash tool shell under the work session as progress |
| MCP servers (`chrome-devtools-mcp` and others) stay resident as children of claude, so "has child processes" is always true | count only shell-snapshot shells |
| If a background Bash is refused by the auto mode classifier and does not start, no notification comes (#471 #465 run) | count only what actually started (`running in background with ID`) |
| `pgrep claude` also catches `cmux hooks claude spool-forwarder` and `inbox-wait` | count only `.local/bin/claude` |
| `cmux rpc pane.list '{}'` returns only some panes | give `workspace_id` |
| Reopening with `claude --resume <id>` after `/exit` generates a recap once | check logs by reading the transcript first. resume only when needed (accepting the recap cost) |
| chrome-devtools MCP shares one default profile, so an idle session's Chrome blocked the next session (old guide run 3) | `--isolated` in `~/.claude.json` (applied), reclaim leftover browsers |
| If the `/usage` screen is not closed, the next input is eaten by the screen (old guide) | `Escape` after reading |
| `cmux close-surface` brings up a tab-close confirmation dialog. Confirming closes every pane in the tab (454-13, the operator cancelled) | do not use it. To close one pane, after the session's `/exit`, send `exit` to that pane's shell |
| Starting claude in a folder used for the first time brings up the workspace trust dialog. It appears even when `.claude/settings.local.json` allows the tools in advance, as in this folder. `Escape` is cancel, and claude exits (454-13) | the operator decides whether to trust. After approval, choose "Yes" with the down arrow + Enter |
| `cmux tree` shows only the current window. The coordination and work panes of another window looked as if they did not exist (454-13) | own pane via `caller.surface_ref` of `cmux identify`, all via `cmux tree --all` |
| A work session's (mainly a subagent's) deletion of a scratchpad absolute path (`rm -rf /private/tmp/claude-501/…`) is refused. The deny `Bash(rm -rf /*)` in the permission settings matches every absolute path, and it cannot be lifted with allow (anthropics/claude-code#79756, #79759 OPEN) | treat it as normal. Operator decision: tmp is not deleted by work sessions; the operator cleans it up periodically. "Deletion refused, still present" in a work session's report is not a stop reason and is written only in the run runbook |
| The wait in which a work session called an already started review agent again and waited for it was not counted as remaining work, so completion was reported early (454-12 and 13, `~/.claude/handoffs/autoflow-454-9-handoff/analysis/scratch/watch.sh`) | if the last assistant text is of the "I'll wait" kind, set the watch again with that turn count as the baseline |
| During a run, a new plugin version came into the cache, and `check.sh` picked the latest directory in the cache (`sort -V`) and checked with a version different from the installation (rollback after the mistaken 0.3.11 update) | version pinning (§1-3). A running session keeps the version it started with (anthropics/claude-code#87507). Started with `--plugin-dir`, only that directory is loaded: in a test session (0.3.8 specified, installation 0.3.10), the gate hook ran only from the one 0.3.8 path (`autoflow@inline`), no duplicates among the 9 autoflow agents, and the `.in_use` mark only on 0.3.8 |
| When a work session publishes an Artifact, cmux opens a browser surface in that session's pane. Instructions do not prevent it (observed 2026-10-30) | after the session's `/exit` and the pane shell's `exit`, close it with `cmux close-surface --surface <browser surface>`. A browser surface closes without a confirmation dialog |

### 8.1 Coordination session practices (autoflow-454 run)

- **Further instructions**: write them to a file and send with `cmux paste --workspace <ws> --surface <n> --submit - < <file>`. Confirm arrival by grepping the transcript for a phrase of the instruction, or by the `queue-operation` enqueue/dequeue.
- **First instruction to a new pane**: right after the pane is created with `cmux new-split right --surface <coordination surface>`, `cmux send` accepts the instruction as "queued (terminal starting…)" and sends it when the PTY is ready. There is no need to send it again.
- **Keeping the cache alive**: by operator instruction (454-13), the coordination session sets a 50-minute `sleep 3000` background timer. When it goes off, check the work session's state once and set it again.
- **When the reviewer wrapper actually has to run**: run `bash <autoflow>/scripts/review/<reviewer>-review-pr.sh --pr <N> --out <file>` in the shell of a cmux pane, not inside the coordination session (454-13: claude and codex both exit 0, `review-start-check.sh` exit 0). The wrapper does not post to the PR. For a PR of the host repository itself, leave out `--repo`; give `--repo` only for sub-repo PRs (`scripts/review/codex-review-pr.sh:33-35`).

## 9. References

| Material | Location |
|---|---|
| Roles and operating practices | Munsik-Park/autoflow#471 |
| Old guide (2026-10-06) | `.autoflow/unit-session-coordination-guide.md` in the AutoFlow checkout |
| AutoFlow regulations | plugin installation `docs/core.md`, `docs/autoflow-guide.md`, `docs/contracts/*.json`, `docs/units/*.md` |
| Reference workflows | `workflows/` |
| Settings, work space (base), progress records (coordination root) | `SETTINGS.md` |
| Structure of a workspace and the role of each file | `WORKSPACE.md` |
