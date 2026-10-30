# workspace: 구성과 파일의 역할

workspace는 레포 하나의 작업 공간이다. 레포마다 다른 값과 지침을 이 도구와 사용자 레포 밖에 두고, 작업 세션과 조율 세션이 각자의 지침을 읽게 한다(Munsik-Park/autoflow-coordinator#2, 운영자 결정 2026-10-30). 이 문서는 그 구성을 정한다. 각 레포에 무엇을 쓸지는 사용자가 정한다.

```
<base>/<workspace 이름>/
  repo.json              레포 정보 (필수)
  CLAUDE.md              작업 세션 지침
  coordination.md        조율 세션 지침
  claude-settings.json   작업 세션 권한 설정 (선택)
  <회차 worktree>/
```

base는 설정으로 찾는다(`SETTINGS.md` > 작업 공간).

| 파일 | 읽는 쪽 | 역할 |
|---|---|---|
| `repo.json` | tools, 조율 세션 | 도구와 조율 운영에 필요한 값 |
| `CLAUDE.md` | 작업 세션 | 사용자 레포에 파일을 더하지 않고 그 레포의 작업 세션에 적용하는 지침 |
| `coordination.md` | 조율 세션 | workspace를 지정받으면 읽고 따르는 레포별 지침 |
| `claude-settings.json` | 작업 세션 시작 도구 | 작업 세션에 적용할 Claude Code 설정 |

## `repo.json`

```json
{
  "github": "<owner>/<name>",
  "clone": "<로컬 clone의 경로>",
  "base_branch": "<회차 worktree가 시작하는 branch>"
}
```

| 키 | 뜻 |
|---|---|
| `github` | GitHub 경로 |
| `clone` | 로컬 clone. 절대경로이거나 `~`로 시작한다. 회차 worktree를 여기서 만든다 |
| `base_branch` | base branch |

`tools/workspace.py <이름>`이 workspace의 경로, 이 값, 나머지 파일의 유무를 출력하고, `tools/workspace.py <이름> <키>`가 값 하나를 출력한다. 파일이나 키가 없으면 실패한다. tools와 조율 세션은 이 값을 이 출력에서 얻는다.

## `CLAUDE.md`

그 레포에서 작업할 때의 사실과 노하우를 쓴다. 회차 worktree가 workspace 아래에 있으므로, Claude Code가 작업 디렉터리의 상위 `CLAUDE.md`를 읽는 동작에 따라 모든 작업 세션에 적용된다. 그래서 worktree를 도구 저장소 아래에 두지 않고, 이 파일을 worktree에 복사하지 않는다.

## `coordination.md`

조율 세션이 그 레포에 대해 판단하고 수행하는 일의 지침을 쓴다. Claude Code가 자동으로 읽는 이름이 아니므로 작업 세션에는 실리지 않는다. 조율 세션은 workspace를 지정받으면 이 파일을 읽고 따른다. RUNBOOK과 조율 규칙에는 레포별 내용을 두지 않는다.

둘 수 있는 내용의 예: worktree에 갖출 git 밖 파일, 개발 환경을 만드는 명령, 리뷰 집계를 PR에 게시할지, CI 실행 여부(fork 등), merge와 그 후속 방침, 그 레포의 품질 목표.

같은 사실이 양쪽에 필요하면 그 일을 하는 세션의 지침에 쓴다.

## `claude-settings.json`

그 레포의 작업 세션에 적용할 Claude Code 설정 파일(JSON object, `permissions` 등)이다. Claude Code는 `.claude/settings.json`·`.claude/settings.local.json`을 작업 디렉터리에서만 읽고 상위 디렉터리에서는 읽지 않으므로(anthropics/claude-code#74023, #12962), workspace에 두는 것만으로는 적용되지 않는다. `tools/launch.sh`가 회차 worktree가 속한 workspace의 이 파일을 시작 옵션 `--settings`로 넘긴다. 회차 checkout에는 설정 파일을 만들지 않는다.

이 파일은 선택이다. 없으면 `launch.sh`는 `--settings` 없이 띄우고, 작업 세션은 Claude Code 기본 동작으로 돈다. 설정 없이 띄우는 것은 사용자의 선택이다(운영자 결정 2026-10-30).

## 회차 worktree

회차마다 로컬 clone에서 만든 worktree(RUNBOOK §2.1). workspace 바로 아래에 둔다. 작업 세션의 workspace는 worktree의 상위 디렉터리로 정해진다.

## 공유

여러 조율 세션이 같은 workspace를 쓰면 같은 지침을 읽는다. workspace 파일의 수정은 그 workspace를 쓰는 모든 회차에 적용되며, 의도된 동작이다.

## 만들기

1. `tools/config.py base`로 base를 확인한다.
2. `<base>/<workspace 이름>/`을 만들고 `repo.json`을 쓴다.
3. `tools/workspace.py <workspace 이름>`으로 확인한다.
4. `CLAUDE.md`, `coordination.md`, `claude-settings.json`에 그 레포에 필요한 만큼 쓴다.

workspace는 조율 세션이 사용자 요청과 질답으로 구성할 수도 있다. 지정한 workspace가 없거나 회차에 필요한 사실이 빠져 있으면 조율 세션은 운영자에게 묻고 workspace에 적는다.
