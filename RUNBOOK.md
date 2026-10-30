# 조율 세션 runbook: AutoFlow 모듈 조립과 세션 운영 (cmux)

작성: 2026-10-21.

이 runbook은 근거가 아니라, 동작 자료를 모아 하나씩 룰로 흡수해 가는 자료다. 일반 룰은 조율 도구(CLAUDE.md, workflows, tools, 설정 문서)로, 레포별 내용은 workspace로 옮긴다(운영자 결정 2026-10-30).

이 runbook이 대체하는 문서: AutoFlow checkout의 `.autoflow/unit-session-coordination-guide.md`(2026-10-06, AutoFlow 0.2.x, U1~U6, 화면 기반 감시). 그 문서에서 유효한 절차는 여기로 옮겼다.

역할의 출처: Munsik-Park/autoflow#471(본문: 역할 1–4, comment 2026-10-19: 운영 요령).

## 0. 역할

조율 세션은 작업을 직접 하지 않는다. 요청에 맞는 워크플로우를 구성하고, cmux로 작업 세션을 띄워 AutoFlow 모듈을 실행시키고, 모듈의 결과를 판정해 다음 모듈의 입력과 목표로 잇는다.

- 워크플로우의 레퍼런스와 조율의 개념(연결, 판정, 재진입, 세션, 품질 목표): `workflows/README.md`
- 모듈의 입력, 출력, default: 회차 버전 설치본의 `docs/autoflow-guide.md`와 `docs/contracts/<module>.json`
- 저장소마다 다른 사실과 운영 노하우: 운영자가 지정한 workspace의 레포 정보와 레포 작업 규칙(`SETTINGS.md` > 작업 공간). 조율 세션은 시작할 때 이것을 읽는다
- 경로: 작업 공간(base 아래 workspace, 회차 worktree)과 진행 기록(조율 root 아래 위치)(`SETTINGS.md`). 값은 `tools/config.py`로 얻는다

| 주체 | 하는 일 |
|---|---|
| 운영자 | 이슈 선정, 워크플로우 승인, 정지 사유에 대한 결정 |
| 조율 세션 | 워크플로우 구성, 준비, 호출 파일과 지시 작성, 작업 세션 시작·감시·종료, 결과 판정과 연결, 기록, 보고 |
| 작업 세션 | 받은 모듈 명령을 실행하고, 모듈 하나가 끝나면 멈춤 |

## 1. 고정 규칙

1. **checkout은 하나다.** 한 회차의 모든 작업 세션은 같은 대상 checkout(회차 worktree)에서 돈다.
2. **한 번에 한 세션만 작업한다.** 세션은 맡은 묶음이 끝나면 `/exit`하고, 프로세스가 끝난 것을 확인한 뒤 칸을 닫는다. 같은 checkout에서 두 세션이 동시에 작업하면 즉시 중단하고 기록한다. 로그는 transcript와 sessions.tsv의 id(`claude --resume <id>`)로 본다(운영자 결정 2026-10-22).
3. **AutoFlow 버전을 고정한다.** 기준은 plugin 설치본(`~/.claude/plugins/cache/autoflow/autoflow/<ver>`)이다. 회차 시작 때 설치본 버전을 run.env `AUTOFLOW_VER`에 적고, `launch.sh`가 작업 세션을 `claude --plugin-dir <cache>/<AUTOFLOW_VER>`로 띄워 회차 중 설치본이 바뀌어도 같은 버전으로 돈다. 호출 파일을 쓸 때 읽는 계약과 사용법도 그 버전의 것이다(운영자 지시 2026-10-22: 실수로 들어온 update에 대한 방어는 실행 중 버전 고정까지만).
4. **결과는 직접 읽어 판정한다(§3).** 모듈 실행마다 결과와 출력을 읽고, 출력이 적은 사실은 git과 gh로 확인한다.
5. **지시는 보내기 전에 파일로 쓴다.** 시작 지시와 같은 세션에 이어 주는 모듈 지시 모두 회차 디렉터리에 남기고, 보낸 사실을 회차 runbook에 적는다.
6. **회차 자료는 조율 root의 `runs/<회차 이름>/`에 둔다(§2.3).** 이 저장소에는 룰만 두고 git으로 관리한다. 회차 자료는 git과 도구 clone 밖이라, 어느 clone, 어느 cwd에서 돈 조율 세션이든 같은 위치에 run.env를 쓰고 `check.sh`가 한곳에서 겹침을 본다(운영자 결정 2026-10-22, 2026-10-30).
7. **명령을 보낸 뒤 결과를 확인한다.** 조율 세션은 작업 세션·cmux·shell에 명령을 보낸 뒤 의도한 상태가 되었는지 직접 확인하고, 되지 않았으면(확인 창, 오류, 무반응) 그 자리에서 처리한 뒤 다음 단계로 간다. 확인 수단은 명령의 결과에 맞춰 고른다(프로세스, transcript, `cmux tree`·`read-screen`, 파일). 근거: `/exit`가 확인 창에서 멈춘 채 다음 세션을 띄워 두 세션이 약 1분 겹친 일이 있었고, 한 회차에서는 `/exit` 7개가 모두 확인 창을 띄웠다(운영자 지시 2026-10-25: "명령 -> 방치 / 명령 -> 확인으로 프로세스를 바꾸세요 … 종료도구 / 시작도구 / 중간도구 / 분할 도구를 모두 따로 만들건가요?").

## 1.1 조율 세션 병행

운영자 지시(2026-10-22): 조율 세션 둘 이상이 이 폴더에서 동시에 돌아도 서로 간섭하지 않게 한다. 아래 규칙은 서로 다른 이슈와 같은 이슈의 병행 회차에서 시험했다. 운영자 결정(2026-10-25): 조율 세션 하나가 이슈 하나를 실행하는 것을 기본으로 한다(규칙 1).

**공유되는 것과 나뉘는 것**

| 자원 | 공유 여부 | 근거 |
|---|---|---|
| coordination 저장소 working tree·작업 branch | 공유 | |
| `RUNBOOK.md`, `CLAUDE.md`, `tools/`, `.claude/settings.local.json` | 공유 | 같은 파일 |
| 조율 root(workspace 목록, 회차 자료, 기록 폴더) | 공유 | 설정으로 찾는 한 위치(`SETTINGS.md`). 도구 clone이 달라도 같다 |
| base와 workspace(레포 정보, 레포 작업 규칙) | 공유 | 설정으로 찾는 한 위치(`SETTINGS.md`). 회차 worktree는 회차마다 나뉜다 |
| AutoFlow plugin 설치본 | 공유 | `~/.claude/plugins/cache/autoflow/autoflow/<ver>` 하나 |
| `tools/check.sh`의 잔여 리소스 목록 | 기기 전체를 봄 | 마지막 단계 `ps … \| grep` 에 checkout 필터 없음 |
| `~/.claude/handoffs/` 핸드오프 파일 이름 | 나뉨 | 회차 이름을 넣는다(규칙 10). 순번 방식(`coordination-<순번>-handoff.md`)은 충돌할 수 있다 |
| `watch.py`, `launch.sh` | 나뉨 | run.env·sessions.tsv의 cmux workspace·surface·session id만 다룸 |
| AutoFlow 기록 폴더 | 나뉨 | 회차마다 조율 root의 `records/<회차 이름>` |

**규칙**

1. **회차 단위로 나눈다.** 조율 세션 하나는 회차 디렉터리 `<runs>/<회차 이름>/` 하나를 갖는다. 다른 저장소·다른 이슈를 다뤄도 회차 자료는 이 위치에 둔다. 다른 조율 세션의 회차 디렉터리는 읽기만 한다. 조율 세션 하나가 이슈 하나를 실행하는 것이 기본이고, 여러 조율 세션의 작업은 서로 독립이다(운영자 결정 2026-10-25, 같은 이슈 병행 시험 뒤: "개선하지 않는다 1 조율 세션 1이슈 실행을 베이스로 한다 같은 레포 위치에서 여러 조율 세션의 작업은 독립적이다").
2. **run.env에 소유와 상태를 적는다.** `COORD_SURFACE=<조율 surface>`, `STATE=active`를 시작 전에 쓰고, 회차가 끝나면(cleanup 완료 또는 회차 종료 기록 뒤) `STATE=closed`로 바꾼다. `STATE`가 없으면 closed로 본다.
3. **checkout과 cmux workspace는 겹치지 않는다.** 시작 전에 `tools/check.sh`가 다른 `STATE=active` 회차를 나열하고, `CHECKOUT`이나 `WORKSPACE`가 같으면 `SAME CHECKOUT`·`SAME WORKSPACE`로, 자기 회차 디렉터리가 `<runs>` 밖이라 다른 회차의 점검에 보이지 않으면 `NOT UNDER RUNS`로 표시한다. 표시가 나오면 시작하지 않고 운영자에게 알린다. 같은 이슈는 checkout이 다르면 두 회차가 동시에 다룰 수 있다.(운영자 결정 2026-10-24: 같은 이슈를 두 작업자가 실행할 수 있다).
4. **cmux는 자기 것만 만진다.** 조율 세션마다 cmux workspace를 따로 쓴다. 자기 sessions.tsv에 없는 surface에는 `send`·`paste`·`rename-tab`·`resize-pane`을 하지 않는다. `workspace.equalize_splits`는 자기 cmux workspace에만 부른다. 다른 cmux workspace는 `cmux tree --all`·`read-screen`으로 읽기만 한다.
5. **git은 자기 경로만 commit한다.**
   - `git add -- <수정한 공유 파일>`처럼 경로를 지정한다. `git add -A`, `git add .`, `commit -a`, `stash`, `reset`, `checkout -- .`, `clean`은 쓰지 않는다.
   - commit 전에 `git status --short`로 staged 목록이 자기 경로뿐인지 본다. 다른 세션의 미commit 파일은 건드리지 않는다.
   - `index.lock` 때문에 실패하면 잠시 뒤 같은 명령을 다시 한다. lock 파일을 지우지 않는다.
6. **공유 파일은 고친 즉시 따로 commit한다.** `RUNBOOK.md`·`tools/`·`CLAUDE.md`는 운영자 지시가 있을 때만 고친다. 고치기 전에 `git diff -- <파일>`로 다른 세션의 미commit 변경이 없는지 보고, 있으면 그 세션 몫으로 두고 운영자에게 알린다. 바꿀 부분만 고친다. 고친 뒤 그 파일만 담아 바로 commit하고, 자기 회차 runbook에 commit hash를 적는다. 다른 세션은 회차의 다음 세션을 시작하기 전에 `git log -1 -- RUNBOOK.md`로 바뀌었는지 보고, 바뀌었으면 다시 읽는다.
7. **잔여 리소스는 자기 것만 회수한다.** `check.sh`가 보여 주는 browser·Playwright·mongo·dev server 가운데 부모 체인이 자기 sessions.tsv의 작업 세션으로 이어지는 것만 회수한다(§4-1). 나머지는 회차 runbook에 적고 운영자에게 알린다. 패턴으로 일괄 종료(`pkill`, `killall`)하지 않는다.
8. **로컬 서비스 포트는 시작 전에 맞춘다.** 대상 작업이 dev server·mongo·Playwright 같은 로컬 서비스를 띄우면, 회차 runbook 머리에 쓰는 포트를 적고 다른 active 회차의 runbook과 대조한다. 겹치면 운영자가 순서를 정한다.
9. **보고와 알림에 회차 이름을 붙인다.** 운영자에게 보내는 보고 첫 줄과 `PushNotification` 본문은 `[<회차 이름>]`로 시작한다. 운영자가 어느 회차의 이야기인지 바로 알 수 있게 한다.
10. **핸드오프 파일 이름에 회차를 넣는다.** `~/.claude/handoffs/coordination-<회차 이름>-handoff.md`.
11. **지시는 자기 터미널에서 받은 것만 따른다.** 다른 조율 세션의 회차에 대한 결정·지시는 그 세션에 전달되어야 한다. 받았다면 수행하지 않고 운영자에게 어느 세션 몫인지 알린다.

## 2. 준비

### 2.1 이슈, workspace, worktree, 기록 폴더

- 이슈 선정(운영자가 최종 선정): 기준이 구체적이고 로컬에서 검증할 수 있는 것. 배포 호스트, 실제 외부 서비스, 선행 이슈 확정이 필요한 이슈는 제외한다.
- **base**: `tools/config.py`가 출력하는 base의 출처가 내장 기본값이면, 운영자에게 확인받기 전에는 그 base로 작업하지 않는다(`SETTINGS.md` > 작업 공간).
- **workspace**: 운영자가 지정한 workspace(`<base>/<workspace 이름>/`)의 레포 정보(JSON)와 레포 작업 규칙을 읽는다. 없거나 회차에 필요한 사실이 빠져 있으면 운영자와 질답해 workspace에 적는다(`SETTINGS.md` > 작업 공간). 레포 사실은 workspace에만 두고 사용자 레포와 이 저장소에 두지 않는다.
- **worktree**: 회차마다 workspace 아래 `<repo>-wt-<N>-<KEY>`에, 레포 정보의 로컬 clone에서 `git fetch` 뒤 `origin/<base branch>`로 detached worktree를 만든다. 경로는 회차 키(§2.3)에서 만들고, 회차 디렉터리로 키를 확보한 뒤에 만든다. 다른 회차의 worktree는 재사용하지 않는다.
  - 작업 세션은 worktree의 상위에 있는 workspace의 `CLAUDE.md`(레포 작업 규칙)를 읽으므로 레포 작업 규칙을 worktree에 복사하지 않는다.
  - git이 만들지 않는 것을 채운다: 대상 저장소의 개발 환경을 dev 도구까지 만든다. 방법은 레포 작업 규칙에 있다.
  - 작업 세션 권한 설정은 workspace에 두고 worktree에 복사하지 않는다(`SETTINGS.md` > 작업 공간).
  - 상위 폴더가 이미 신뢰되어 있으면 trust 창은 뜨지 않는다.
- **기록 폴더**: `<records>/<회차 이름>`을 조율자가 만든다. 모듈의 `records`, 실행마다의 출력 폴더, 호출 파일이 여기에 놓인다.

### 2.2 cmux 배치

조율 창 1열(전체 높이) + 작업 칸 둘(W1·W2) + 1회성 칸 X. 경계를 통과한 세션은 `/exit`하므로(§1-2) 동시에 살아 있는 작업 세션은 하나다. Sk는 홀수면 W1, 짝수면 W2에서 띄워, 직전 묶음의 화면이 옆 칸에 남는다. X는 merge 후속(§6) 같은 1회성 작업을 새 세션으로 띄우는 칸이다(운영자 제안 2026-10-22). 이전 배치(작업 창 4열×2행, S1~S7 고정)는 세션을 idle로 남기던 때의 것이다.

```bash
export CMUX_QUIET=1; W=<workspace ref>; C=<조율 surface>
sp(){ cmux new-split $1 --workspace $W --surface $2 --focus false | awk '{print $2}'; }
W1=$(sp right $C); W2=$(sp right $W1); X=$(sp down $W2)
WID=$(cmux rpc workspace.list '{}' | python3 -c "import json,sys;print([w['id'] for w in json.load(sys.stdin)['workspaces'] if w.get('ref')=='$W'][0])")
cmux rpc workspace.equalize_splits "{\"workspace_id\":\"$WID\"}"
cmux resize-pane --workspace $W --pane <조율 pane> -R --amount <px>   # 단위는 px. 나머지 열이 균등하게 줄어든다
cmux rpc pane.list "{\"workspace_id\":\"$W\"}"                       # workspace_id 없이 부르면 일부만 보인다
```

- tab 이름: 세션을 띄울 때마다 `cmux rename-tab --workspace $W --surface <W1|W2|X> "Sk <묶음>"`(X는 `"Xn <작업>"`).
- 각 칸은 `cd <checkout> && clear`로 대기시킨다. 앞 세션을 `/exit`한 칸은 그 shell에서 다음 세션을 띄운다.
- Claude Code TUI의 최소 크기 요구는 공식 기록에서 찾지 못했다. anthropics/claude-code#93475는 80×24를 standard size로 보고하고, 그 크기에서도 일부 selector가 잘린다고 한다. 작업 창은 좁아도 되고(운영자는 조율 창을 본다), 조율 창은 80 cols 이상으로 둔다.

### 2.3 회차 디렉터리

```
<runs>/<회차 이름>/
  run.env        RUN_KEY=… RUN_KEY_SOURCE=external|self WORKSPACE=<cmux workspace> CHECKOUT=… RECORDS=… ISSUE=… COORD_SURFACE=… STATE=active|closed (§1.1) AUTOFLOW_VER=… (§1-3)
  sessions.tsv   Sk<TAB>surface<TAB>session-id   (uuidgen으로 미리 정함. 1회성 세션은 Xn 행)
  sK-prompt.txt, xn-prompt.txt, 같은 세션에 이어 준 지시 파일
  runbook.md     회차 기록 (§7)
```

- `<runs>`, `<records>`, `<workspaces>`는 조율 root 아래 위치이고 `tools/config.py runs|records|workspaces`가 출력한다. workspace와 회차 worktree는 `tools/config.py base` 아래에 있다(`SETTINGS.md`).
- **회차 키.** 회차를 배정받을 때 유일한 키 하나를 정하고, 회차 이름, worktree 경로, 기록 폴더, 핸드오프 파일 이름(§1.1-10)을 모두 이 키에서 만든다(운영자 결정 2026-10-24: 같은 이슈를 두 작업자가 실행할 수 있다).
  - 외부에서 받은 키가 있으면 그것을 쓴다(`RUN_KEY_SOURCE=external`). 없으면 `$(date +%Y-%m-%d-%H%M%S)-$(openssl rand -hex 4)`로 만든다(`self`).
  - 키는 `[A-Za-z0-9._-]`만 쓴다. 경로 이름에 그대로 들어간다.
  - 회차 디렉터리를 가장 먼저 `mkdir`(`-p` 없이)로 만들어(`<runs>`가 아직 없으면 그것만 먼저 만든다) 키를 확보하고, worktree와 기록 폴더는 그 뒤에 만든다. 동시에 시도해도 `mkdir`은 하나만 성공한다(2026-10-24 시험). 실패하면 시작하지 않고 운영자에게 알린다.
- 회차 이름은 `<repo>-<N>-<KEY>`. 같은 이슈의 회차가 모이고 시간순으로 선다. 자릿수가 다른 이슈 번호는 `ls | sort -V`로 본다.
- `tools/launch.sh <run> <k>`·`tools/watch.py <run> <k>`의 k는 Sk의 숫자 또는 `X1` 같은 1회성 세션 이름이다.

### 2.4 지시

작업 세션에 주는 지시는 모듈 명령, 목표, 제약이다.

```
/autoflow:<module> <호출 파일>

목표: <이 실행이 이를 것>
제약: <결과로 지킬 것>
이 모듈이 끝나면 멈추고 다음 지시를 기다리세요.
```

- 호출 파일은 조율자가 회차 버전의 계약과 사용법을 읽고 쓴다. 입력은 앞 실행의 출력이거나, 조율자가 계약 형식에 맞춰 만든 파일이다(`workflows/README.md` > 연결).
- 지시에는 결과로 지킬 것만 쓴다. 방법, 경우 나열, 다음에 할 일은 쓰지 않는다. 작업자는 지시가 구체적이면 여러 방향을 보기보다 그 지시의 근거를 찾는 데 힘을 쓴다(운영자 확인 2026-10-26).
- 대상 저장소의 사실은 지시에 다시 쓰지 않는다. 작업자가 workspace의 레포 작업 규칙에서 읽는다.
- 같은 세션에서 묶음의 다음 모듈을 이어 줄 때도 같은 형식을 파일로 써서 보낸다(§1-5, 보내는 법은 §8.1 추가 지시).
- 모듈의 default를 바꿀 일(예: review 집계를 PR에 게시)은 호출 파일의 `instructions`로 준다. instructions는 default만 바꾸고 출력은 바꾸지 못한다.

### 2.5 재작업

제출한 PR에 운영자가 방향을 바꾸는 피드백을 주면, 같은 branch와 PR에서 원인이 생긴 단계로 재진입한다(`workflows/README.md` > 재진입). 피드백은 재진입하는 모듈의 입력으로 넘긴다. 새 회차로 처음부터 다시 할지는 운영자가 정한다.

## 3. 결과 판정

모듈 하나가 끝날 때마다 조율자가 판정한다. 기준은 `workflows/README.md` > 판정과 품질 목표다.

- 실행 결과는 출력 폴더의 `result.json`이다. `refused`는 형식 문제다: check-in 거부면 작업이 없었으니 호출 파일을 고쳐 다시 실행하고, check-out 거부면 `defects`를 보고 정한다. `failed`는 목표에 이르지 못한 것이라 `failure.md`를 읽고 재진입하거나 멈춘다.
- `accepted`여도 출력이 입력에 맞는지, 출력이 적은 사실(commit, branch, PR, CI)이 맞는지 확인한다.
- 평가 점수와 리뷰 지적은 품질 목표에 비추어 다음으로 갈지, 재진입할지 정한다. 권고마다의 처분(재실행의 입력으로 넘김, 미룸)도 조율자가 정한다.
- 출력이 따른 `[ac-decision]`을 적었으면 적용 기준이 바뀐 것이다. criteria-apply로 다시 계산해 이후 모듈에 넘긴다.
- 실행마다 남는 `tool-requests.json`은 모아서 delivery에 넘기고 최종 보고에 싣는다.
- 판정과 근거는 회차 runbook에 남긴다. `tools/check.sh`가 기록 폴더의 실행별 상태를 보여 준다.

### 3.1 GitHub CI

- ci 모듈은 timeout까지 체크가 올라오기를 기다린다. 대상 저장소에서 CI가 돌지 않으면(fork 등, 레포 작업 규칙의 사실) 짧은 timeout을 주고, CI가 도는 저장소에서는 그 저장소의 CI 소요 시간에 맞춰 준다(2026-10-30 관측: 기본 900초를 다 기다렸고, 120초로 주자 약 3분에 끝났다).
- PR을 낸 뒤 commit이 더해지면 새 head에서 ci를 다시 실행한다. 판정은 head마다 따로다.

## 4. 실행 루프 (세션 하나)

1. **시작 전 점검**: `tools/check.sh <runs>/<run>`. 다른 active 회차와의 겹침, 기록 폴더의 실행 상태, tree, 잔여 리소스를 본다.
   - 잔여 리소스: browser·Playwright·mongo·dev server. 부모 체인이 이 회차의 작업 세션으로 이어지는 것만 회수하고(세션을 `/exit`하기 전에 확인한다. 종료 뒤에는 부모 체인이 끊긴다), 출처를 추적할 수 없는 것은 기록 후 운영자에게 알린다. ChatGPT/Codex 앱, cmux, 보안 agent 같은 상주 프로세스는 대상이 아니다.
2. **시작**: `tools/launch.sh <runs>/<run> <k> [tab]`: sessions.tsv에 없는 세션이면 조율 칸 옆에 새 칸과 session id를 만들고 checkout으로 옮긴 뒤, 그 session id로 `claude --plugin-dir <cache>/<AUTOFLOW_VER> [--settings <workspace>/claude-settings.json] --session-id <id> "$(cat sK-prompt.txt)"`를 보내고(`--settings`는 workspace에 권한 설정이 있을 때만. `AUTOFLOW_VER`가 없거나 그 디렉터리가 없으면 보내지 않고 멈춤), 15초 뒤 transcript 생성과 화면을 확인한다. 시작 시각을 회차 runbook에 적는다.
3. **감시**: `tools/watch.py <runs>/<run> <k> [baseline] [timeout]`을 `run_in_background`로 돌리고 턴을 끝낸다. `TURN_END`에는 세션의 마지막 보고가 함께 나온다.
4. **판정과 연결**: 알림 처리(§4.1) → 판정(§3) → 회차 runbook에 기록 → 묶음에 다음 모듈이 있으면 같은 세션에 다음 지시(§2.4)를 보내고 3번으로, 묶음이 끝났으면 세션 `/exit`, 프로세스 소멸 확인, 칸 닫기 → 운영자 알림 → 다음 묶음의 1번.

### 4.1 감시 출력과 처리

| 출력 | 뜻 | 처리 |
|---|---|---|
| `TURN_END <n>` | 기준선 뒤 새 `system/turn_duration`이 마지막 turn 기록이고, 남은 background 작업 없음 | transcript 마지막 assistant text로 보고를 읽고(TUI scrollback은 짧다) §3 확인 |
| `WAITING_INPUT` | 화면 아래 12줄에 선택지·권한 질문 | §5.2 위임 범위대로 처리 |
| `IDLE-PENDING <ids>` | 턴 종료 + 남은 작업 + 10분간 transcript 변화 없음 + 작업 세션 아래 실행 중인 shell 없음 | 남은 작업의 정체를 transcript에서 확인. 진행 중이면 감시를 다시 건다 |
| `STALL` | 30분간 변화 없음 + 실행 중인 shell 없음 | 화면과 transcript 확인 후 운영자에게 보고 |
| `TIMEOUT` | 제한 시간 초과 | 같음 |

**감시 기준 (`watch.py`)**

- 완료 판정의 입력은 transcript다. 화면은 입력 대기 판정에만 쓴다(#471 §2: 화면 text는 작업 세션의 본문과 겹친다).
- 남은 background 작업 = `subagents/*.meta.json`의 `requestShape:"background"` `toolUseId` + tool 결과에 `running in background with ID: …`가 있는 Bash 가운데, main transcript에 `<task-notification>`(`tool-use-id` 또는 `task-id`)이 없는 것.
- 남은 작업으로 세지 않는 것: `sleep …` Bash(작업 세션 자신의 cache keep-alive).
- 진행 중으로 보는 것: main 또는 subagent transcript의 mtime 변화, 작업 세션 claude 바로 아래의 Bash tool shell(`~/.claude/shell-snapshots/`를 source하는 프로세스). MCP 서버와 `cmux hooks claude …`는 세션 내내 claude의 자식이므로 세지 않는다.
- 감시를 다시 걸 때는 이미 끝난 turn 수를 baseline으로 준다.

### 4.2 세션 유지와 종료

세션의 수명은 묶음이다(`workflows/README.md` > 세션). 묶음이 끝난 세션은 다시 입력받을 경로가 없으므로 `/exit`하고 칸을 닫는다. 묶음 안에서 다음 지시를 기다리는 동안은 유지한다. 유지하는 세션은 cache를 유지할 때마다 맥락 전체를 다시 읽어 비용이 든다(운영자 지시 2026-10-22).

- **예외**: 묶음이 끝난 뒤에도 다시 입력해야 할 일이 생긴 세션(예: 운영자가 그 세션에 질문하기로 한 경우)은 `/exit`하지 않고, 그 일이 끝날 때까지 작업 세션 자신이 background `sleep 3000`을 걸고 끝나면 다시 걸게 한다. 회차 runbook에 이유를 적는다.
- **조율 세션 자신의 타이머**: §8.1. `sleep 3000`이 수 분 만에 exit 144로 끝나는 일이 있다(여러 회차에서 관측, 원인 미확인). 끝난 이유와 관계없이 다시 건다.

## 5. 위임, 정지 사유, 맥락

### 5.1 운영자 위임

운영자가 "정지 사유가 없으면 자동으로 이어간다"고 지시한 범위(2026-10-21):

- 판정 → 기록 → 시작 전 점검 → 다음 모듈 또는 다음 세션.
- 작업 세션의 `AskUserQuestion` → "Recommended" 선택지. 권장 표시가 없으면 입력하지 않고 대기·보고.
- push와 PR 생성은 작업 세션이 모듈의 default대로 한다.
- 작업 세션이 남긴 별도·후속 이슈 후보는 정지 사유가 아니다. 기다리지 않고 진행하고, 후보는 회차 runbook에 모아 머지 검토 아티팩트(§6.1 구성 7)에 적는다. 등록 여부는 운영자가 정한다(운영자 결정 2026-10-24).
- 운영자 답을 기다려야 하는 일(외부 게시, 삭제, 되돌릴 수 없는 일)은 회차를 시작하기 전에 승인받는다.

### 5.2 정지 사유 (입력하지 않고 기록·알림)

| 상황 | 처리 |
|---|---|
| permission prompt (auto mode 차단) | 운영자 승인 대기 |
| harness-level block (도구·credential·자료) | 운영자 결정 |
| 목표에 못 미친 결과를 재진입으로 풀 수 없음 | 기록, 운영자 판단 |
| 같은 checkout 동시 작업 | 즉시 중단, 실패 사례 기록 |
| 권장 표시 없는 질문 | 대기 |

### 5.3 세션 간 맥락

- 앞 실행의 결과는 다음 모듈의 입력으로 넘긴다. 지시문에 옮겨 적지 않는다.
- 지시와 완료 판정의 주 경로는 cmux와 transcript다. `SendMessage`는 띄운 직후 첫 메시지의 보조로 쓴다(#471 §4).
- 작업 세션 안에서 `claude -p`로 중첩 세션을 띄우는 것은 auto mode classifier가 거부한다. 별도 세션이 필요하면 조율 세션이 cmux로 띄운다(#471 §5).

### 5.4 알림

- 운영자가 `/remote-control`을 켜면 `PushNotification`으로 보낸다: 묶음 완료, 정지 사유, 완주.
- 터미널이 활성 상태면 발송되지 않는다. 정상이다.

## 6. 종료 후

1. 회차 runbook에 결과 요약을 쓴다: PR, CI, 리뷰 집계, 평가 점수, 재진입과 그 근거, 감시 오판과 보정, 토큰·비용(`tools/usage.py <run-dir> COORD=<조율 session id>`, 운영자 지시 2026-10-25).
1a. 머지 검토 아티팩트를 만들어 회차 결과 보고와 함께 제시한다(§6.1).
2. merge는 외부 결정이다. merge 이후의 일(sub-repo pointer 이동, branch와 worktree 정리)은 AutoFlow가 정하지 않고 조율자가 정한다. 절차는 저장소마다 다르므로 workspace의 레포 작업 규칙에 두고, 조율 세션은 그것을 읽어 따른다. 필요한 사실이 없으면 운영자에게 묻고 레포 작업 규칙에 적는다(운영자 지시 2026-10-25: "머지 후의 절차는 레포별 상황에 맞춘 설정입니다 … 그것이 없는 경우 조율 세션이 아니라 레포에 적어야 합니다". 레포 사실의 자리는 workspace다, 운영자 결정 2026-10-30).
   - **수행**: merge 통보를 받으면 지시를 `xn-prompt.txt`로 쓰고 1회성 칸 X에서 새 세션으로 띄운다(`tools/launch.sh <run> Xn`). 끝나면 그 세션을 `/exit`하고 칸을 닫는다.

### 6.1 머지 검토 아티팩트

운영자 지시(2026-10-22): PR이 생성된 뒤 merge를 요청할 때, 결과를 개념 수준으로 정리한 HTML 아티팩트를 함께 제시한다. 작업자는 이것을 보고 이슈를 낸 의도와 결과가 맞는지 판단하고 방향을 다시 설명한다. 코드 설명이 아니라 개념 설명이 목적이다.

- **시점과 주체**: 워크플로우가 끝난 뒤, 운영자에게 하는 회차 결과 보고와 함께 만든다. 만드는 법은 `pr-postcard` 스킬을 따르고, 회차 맥락이 섞이지 않게 1회성 세션(X 칸)에서 만든다(autoflow-523 관측: 같은 입력으로 새 세션이 만든 엽서가 조율 세션의 것보다 구성이 맞았다). 이슈 작업이 아니라 운영자와 조율하는 작업이다(#471 의도 변경 2026-10-21).
- **근거**: 기록 폴더(기준 검토, ledger, 분석·설계·build 보고, 리뷰 findings), PR 본문, 회차 runbook을 직접 읽는다. 계약값·목록처럼 페이지에 적는 값은 대상 저장소에서 확인한다.
- **구성** (작업자가 묻는 순서)
  1. 왜 시작했나: 이슈가 해결하려던 문제와 그 문제가 생긴 경로
  2. 검토하면서 바뀐 것: criterion review가 바꾼 기준을 AC별로 원래 / 바뀐 뒤 / 왜(개정·추가·기각)
  3. 어떻게 풀었나: 해소 방식의 개념(무엇을 입력으로, 무엇과 비교, 실패 처리, 어디서 도는지, 사람이 계속 할 일)
  4. 다시 손본 곳: 시간순. 재진입과 그 이유
  5. 방향 점검: AutoFlow가 스스로 정했지만 원래 의도와 맞는지 사람이 봐야 하는 지점, PR 본문의 known gaps
  6. merge 순서와 merge 후속
  7. 별도·후속 이슈 후보: 작업 세션과 gate가 이 이슈 범위 밖으로 분리한 문제(criterion review의 split, gate 권고의 분리 판정, 작업 세션이 남긴 draft). 후보마다 무엇이 문제인지, 어디서 나왔는지(모듈·ledger entry), draft 위치, 중복 검색 결과를 적는다. 등록하지 않은 상태로 두고, 등록 여부는 운영자가 이슈 검토에서 정한다(§5.1)
- **설명 수준**: `plain-talk-explain` skill과 기술 문서의 중간(운영자 확인).
  - 동료에게 말하듯 쓴다. "~합니다"와 "~해요"를 섞는다.
  - 본문에서 코드 식별자·파일 경로를 빼고 하는 일로 부른다(예: flag → 배포 옵션, contract → 떠야 하는 서비스 목록, advisory → 막지 않고 경고만, fail closed → 애매하면 실패로 본다, known gaps → 남은 한계).
  - 이슈와 대조할 수 있게 AC 번호, PR 번호, gate 점수, 현장에서 그대로 쓰는 이름(서비스명 등)은 남긴다. 표·흐름·시간순 구성도 유지한다.
  - "~일 때만", "읽기만 해서 확인", "아직 확인 안 됨" 같은 조건과 근거는 남긴다.
- **그림** (`artifact-diagramming` skill, inline SVG): 말로만 하면 독자가 머릿속에서 조립해야 하는 동작이 있을 때 넣는다.
  - 해소 방식은 **이전 / 이후를 같은 칸 배치로** 그려 위아래로 비교되게 한다.
  - 기준을 추가·개정한 이유가 "원래 기준으로는 통과하는 경우"라면 그 경우를 나란히 그린다.
  - multi-repo면 저장소별 줄과 pointer 이동으로 merge 순서를 그린다.
  - 가상의 예시는 캡션에 예시라고 밝힌다. 색은 페이지 token을 따라 라이트·다크에서 모두 읽히게 하고, 좁은 화면에서는 그림만 가로 스크롤되게 한다.
- **위치와 공개**: 원본은 회차 디렉터리의 `merge-summary.html`에 두고 Artifact로 publish한다(비공개). 수정은 같은 파일 경로로 다시 publish해 링크를 유지한다.
- **PR에 남기기와 공유** (운영자 결정 2026-10-22):
  - **바뀌는 상태는 고정하지 않는다**(운영자 지시 2026-10-22: "인지 가능하고 변경되는 사항이라 고정하면 안됩니다"). PR의 CI·draft·merge 여부, 아티팩트 공개 범위처럼 나중에 바뀌는 사실은 아티팩트와 comment에 적지 않고, 확인할 곳(PR 링크)을 가리킨다. 리뷰 라운드 결과, gate 점수, 재작업 경위처럼 이미 지난 일은 적는다.
  - 조율 세션은 host PR에 아티팩트 링크 comment를 단다. 본문은 무엇을 정리했는지 한 줄과 링크로 둔다. 본문 파일을 회차 디렉터리의 `pr-<N>-artifact-comment.md`로 남기고 `gh pr comment --body-file`로 올린다. PR 본문은 delivery 모듈이 쓴 것이라 고치지 않는다.
  - 아티팩트는 비공개로 시작한다. 조율 세션은 공유 범위를 바꿀 수 없다(Share 메뉴에서만 가능).
  - 머지하는 운영자가 검토하고, 필요하면 Share로 공유 범위를 바꾸거나, 보관이 필요하면 직접 내보낸다.

## 7. 회차 runbook 형식

```
# 회차 runbook: <회차 이름> (<repo>#<N>)
- 조율 세션, 레퍼런스와 바꾼 점, 품질 목표, 운영자 지시 원문, base(commit, AutoFlow 버전), 경로(workspace, worktree, 기록 폴더)
## 진행 기록
| 세션 | 모듈 실행 | session-id | 시작 | 종료(감시 출력) | 판정 | 비고(재진입, 처분, 조율자가 만든 입력) |
## 운영자 지시 / 조율자 판단 / 결과 요약
```

## 8. 관측된 함정

| 관측 (회차) | 대응 |
|---|---|
| 화면 text로 완료를 판정하면 이전 turn의 완료 줄·보고 본문과 겹쳐 오판한다 (#471 4·5회차) | transcript 판정 (§4.1) |
| 작업 세션의 keep-alive `sleep 3000`을 남은 작업으로 셌다 | `sleep` 제외 |
| unit agent가 background로 10분 넘게 돌면 `IDLE-PENDING` | subagent transcript mtime을 진행으로 본다 |
| background Bash가 출력을 자기 로그 파일에 써서 transcript가 멈춘 것처럼 보였다 (mock e2e 26분) | 작업 세션 아래 Bash tool shell 생존을 진행으로 본다 |
| claude의 자식에 MCP 서버(`chrome-devtools-mcp` 등)가 상주해 "자식 프로세스 있음"이 항상 참이 된다 | shell-snapshot shell만 센다 |
| background Bash가 auto mode classifier에 거부되어 시작되지 않으면 알림이 오지 않는다 (#471 #465 회차) | 실제로 시작된 것(`running in background with ID`)만 센다 |
| `pgrep claude`가 `cmux hooks claude spool-forwarder`·`inbox-wait`까지 잡는다 | `.local/bin/claude`만 센다 |
| `cmux rpc pane.list '{}'`가 일부 pane만 돌려준다 | `workspace_id`를 준다 |
| `/exit` 후 `claude --resume <id>`로 다시 열면 recap이 한 번 생성된다 | 로그 확인은 transcript를 읽는 것을 먼저 한다. resume은 필요할 때만(recap 비용 감수) |
| chrome-devtools MCP가 기본 profile 하나를 공유해 idle 세션의 Chrome이 다음 세션을 막았다 (구 가이드 3회차) | `~/.claude.json`의 `--isolated`(적용됨), 잔여 browser 회수 |
| `/usage` 화면을 닫지 않으면 다음 입력이 화면에 먹힌다 (구 가이드) | 판독 후 `Escape` |
| `cmux close-surface`가 탭 닫기 확인 창을 띄운다. 확인하면 탭 안의 모든 칸이 닫힌다 (454-13, 운영자가 취소) | 쓰지 않는다. 칸 하나는 세션 `/exit` 뒤 그 칸 shell에 `exit`를 보내 닫는다 |
| 처음 쓰는 폴더에서 claude를 띄우면 workspace trust 창이 뜬다. 이 폴더처럼 `.claude/settings.local.json`이 도구를 미리 허용해도 뜬다. `Escape`는 취소이고 claude가 종료된다 (454-13) | 신뢰 여부는 운영자가 정한다. 승인 뒤 아래 화살표 + Enter로 "Yes"를 고른다 |
| `cmux tree`는 현재 window만 보여 준다. 다른 window의 조율·작업 칸이 없는 것처럼 보였다 (454-13) | 자기 칸은 `cmux identify`의 `caller.surface_ref`, 전체는 `cmux tree --all` |
| 작업 세션(주로 subagent)의 scratchpad 절대경로 삭제(`rm -rf /private/tmp/claude-501/…`)가 거부된다. 권한 설정의 deny `Bash(rm -rf /*)`가 모든 절대경로에 일치하고, allow로는 풀 수 없다(anthropics/claude-code#79756, #79759 OPEN) | 정상으로 본다. 운영자 결정: tmp는 작업 세션이 지우지 않고 운영자가 주기적으로 정리한다. 작업 세션 보고의 "삭제 거부, 남아 있음"은 정지 사유가 아니며 회차 runbook에만 적는다 |
| 작업 세션이 이미 띄운 리뷰 agent를 다시 불러 기다리는 대기를 남은 작업으로 세지 못해 완료를 일찍 냈다 (454-12·13, `~/.claude/handoffs/autoflow-454-9-handoff/analysis/scratch/watch.sh`) | 마지막 assistant text가 "기다립니다"류면 그 turn 수를 baseline으로 다시 건다 |
| 회차 중 plugin 새 버전이 cache에 들어왔고 `check.sh`가 cache 최신 디렉터리(`sort -V`)를 골라 설치본과 다른 버전으로 점검했다 (0.3.11 실수 update 후 롤백) | 버전 고정(§1-3). 실행 중 세션은 시작 때의 버전을 유지한다(anthropics/claude-code#87507). `--plugin-dir`로 띄우면 그 디렉터리만 실린다: 시험 세션(0.3.8 지정, 설치본 0.3.10)에서 gate hook은 0.3.8 경로 하나만 돌고(`autoflow@inline`), autoflow agent 9종 중복 없음, `.in_use` 표시는 0.3.8에만 |
| 작업 세션이 Artifact를 publish하면 cmux가 그 세션 칸에 browser surface를 연다. 지시로 막히지 않는다(2026-10-30 관측) | 세션 `/exit`와 칸 shell `exit` 뒤 `cmux close-surface --surface <browser surface>`로 닫는다. browser surface는 확인 창 없이 닫힌다 |

### 8.1 조율 세션 요령 (autoflow-454 회차)

- **추가 지시**: 파일로 쓰고 `cmux paste --workspace <ws> --surface <n> --submit - < <파일>`로 보낸다. 도착은 transcript에서 지시문 한 구절을 grep하거나 `queue-operation` enqueue/dequeue로 확인한다.
- **새 칸에 첫 지시**: `cmux new-split right --surface <조율 surface>`로 만든 직후 `cmux send`는 "queued (terminal starting…)"로 받아 PTY가 준비되면 보낸다. 다시 보낼 필요 없다.
- **cache 유지**: 운영자 지시(454-13)로 조율 세션은 50분 `sleep 3000` background 타이머를 건다. 울리면 작업 세션 상태를 한 번 확인하고 다시 건다.
- **리뷰어 wrapper를 실제로 돌려야 할 때**: 조율 세션 안이 아니라 cmux 칸의 shell에서 `bash <autoflow>/scripts/review/<reviewer>-review-pr.sh --pr <N> --out <파일>`을 실행한다(454-13: claude·codex 둘 다 exit 0, `review-start-check.sh` exit 0). wrapper는 PR에 게시하지 않는다. host 저장소 자신의 PR이면 `--repo`를 빼고, `--repo`는 sub-repo PR에만 준다(`scripts/review/codex-review-pr.sh:33-35`).
- **PR branch의 AutoFlow를 실제 세션으로 확인**: 이 폴더에서 `claude --plugin-dir <그 branch의 checkout> --session-id <id> '<명령>'`으로 띄운다. 실린 양은 transcript 첫 user 기록의 길이와 첫 assistant `usage`(input + cache_creation + cache_read)로 잰다. subagent 정의가 잘리지 않았는지는 그 agent에게 마지막 `## ` heading과 heading 수를 답하게 해 파일과 대조한다(454-13: evaluator 20, unit-build 35 일치).

## 9. 참조

| 자료 | 위치 |
|---|---|
| 역할과 운영 요령 | Munsik-Park/autoflow#471 |
| 구 가이드 (2026-10-06) | AutoFlow checkout의 `.autoflow/unit-session-coordination-guide.md` |
| AutoFlow 규정 | plugin 설치본 `docs/core.md`, `docs/autoflow-guide.md`, `docs/contracts/*.json`, `docs/units/*.md` |
| 레퍼런스 워크플로우 | `workflows/` |
| 설정, 작업 공간(base, workspace), 진행 기록(조율 root) | `SETTINGS.md` |
