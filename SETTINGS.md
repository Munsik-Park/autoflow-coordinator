# 설정: 도구, 사용자 설정, workspace

이 저장소는 누구나 가져다 AutoFlow 작업을 조율하는 도구다. 도구, 사용자 설정, 레포 작업 공간(workspace)을 나누고, 도구는 설정값이 아니라 설정을 찾는 순서만 갖는다(Munsik-Park/autoflow-coordinator#6, 운영자 결정 2026-10-30).

| 구분 | 위치 | 두는 것 |
|---|---|---|
| 도구 | 이 저장소 | 룰(RUNBOOK, CLAUDE.md), 워크플로우, tools, 이 설정 문서. 사용자 값과 개별 레포 사항을 두지 않는다 |
| 사용자 설정 | 로컬·전역 설정 파일 | 조율 root 같은 사용자 값 |
| 조율 root | 설정이 가리키는 곳 | workspace 목록, 회차 자료, AutoFlow 기록 폴더 |
| workspace | 조율 root 아래, 레포 하나에 하나 | 레포 정보, 레포 작업 규칙(`CLAUDE.md`), 회차 worktree |

사용자 레포에는 이슈 해결을 위한 수정 외에 아무것도 두지 않는다.

## 설정을 찾는 순서

1. 로컬: 도구 clone root의 `coordination.local.json` (git ignore 대상)
2. 전역: `~/.autoflow/coordination.json`
3. 내장 기본값

키 단위로 가까운 쪽이 이긴다. 없는 파일은 아무 키도 정하지 않는다. 두 파일 모두 JSON object다. 견본 파일은 두지 않고 항목은 이 문서로 설명한다.

| 키 | 뜻 | 내장 기본값 |
|---|---|---|
| `root` | 조율 root. 절대경로이거나 `~`로 시작한다 | `~/.autoflow/coordination` |

적용된 값은 `tools/config.py`로 본다. 인자 없이 부르면 키마다 값과 출처를, 키를 주면 값만 출력한다. tools와 조율 세션은 경로를 이 출력에서 얻고 직접 정하지 않는다.

## 조율 root

조율 root를 clone 밖 한곳에 두면, 도구 clone이 여럿이어도 모든 조율 세션이 같은 회차 자료를 보고 `tools/check.sh`가 다른 active 회차와의 겹침을 한곳에서 본다(RUNBOOK §1.1).

```
<root>/
  workspaces/<workspace 이름>/   workspace (아래)
  runs/<회차 이름>/              회차 자료 (RUNBOOK §2.3)
  records/<회차 이름>/           AutoFlow 기록 폴더 (RUNBOOK §2.1)
```

`tools/config.py workspaces|runs|records`가 각 위치를 출력한다.

## workspace

workspace는 레포 하나의 작업 공간이다.

- **레포 정보**: GitHub 경로, 로컬 clone, base branch. 조율 세션은 회차를 시작할 때 운영자가 지정한 workspace의 레포 정보와 레포 작업 규칙을 읽는다.
- **레포 작업 규칙** (`CLAUDE.md`): 그 레포에서 작업할 때의 사실과 노하우(개발 환경 준비, CI, merge 이후 절차 등). 회차 worktree가 workspace 아래에 있으므로, Claude Code가 작업 디렉터리의 상위 `CLAUDE.md`를 읽는 동작에 따라 모든 작업 세션에 적용된다. 그래서 worktree를 도구 저장소 아래에 두지 않는다.
- **회차 worktree**: 회차마다 로컬 clone에서 만든 worktree(RUNBOOK §2.1).

workspace는 조율 세션이 사용자 요청과 질답으로 구성한다. 지정한 workspace가 없거나 회차에 필요한 사실이 빠져 있으면 운영자에게 묻고 workspace에 적는다.
