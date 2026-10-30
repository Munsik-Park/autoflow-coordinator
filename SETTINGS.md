# 설정: 도구, 사용자 설정, 작업 공간, 진행 기록

이 저장소는 누구나 가져다 AutoFlow 작업을 조율하는 도구다. 도구, 사용자 설정, 레포 작업 공간(workspace)을 나누고, 도구는 설정값이 아니라 설정을 찾는 순서만 갖는다(Munsik-Park/autoflow-coordinator#6, 운영자 결정 2026-10-30).

| 구분 | 위치 | 두는 것 |
|---|---|---|
| 도구 | 이 저장소 | 룰(CLAUDE.md, COORDINATOR.md), 워크플로우, tools, 이 설정 문서, workspace 가이드(`WORKSPACE.md`), 이전 회차 작업 기록(`RUN-HISTORY.md`). 사용자 값과 개별 레포 사항을 두지 않는다 |
| 사용자 설정 | 로컬·전역 설정 파일 | base, 조율 root 같은 사용자 값 |
| 작업 공간 | base 아래 | 레포마다 workspace 하나(`WORKSPACE.md`) |
| 진행 기록 | 조율 root 아래 | 회차 자료, AutoFlow 기록 폴더 |

사용자 레포에는 이슈 해결을 위한 수정 외에 아무것도 두지 않는다.

## 설정을 찾는 순서

1. 로컬: 도구 clone root의 `coordination.local.json` (git ignore 대상)
2. 전역: `~/.autoflow/coordination.json`
3. 내장 기본값

키 단위로 가까운 쪽이 이긴다. 없는 파일은 아무 키도 정하지 않는다. 두 파일 모두 JSON object다. 견본 파일은 두지 않고 항목은 이 문서로 설명한다.

| 키 | 뜻 | 내장 기본값 |
|---|---|---|
| `root` | 조율 root(진행 기록). 절대경로이거나 `~`로 시작한다 | `~/.autoflow/coordination` |
| `base` | 작업 공간의 base. 절대경로이거나 `~`로 시작한다 | `~/work/coordinator` |

적용된 값은 `tools/config.py`로 본다. 인자 없이 부르면 키마다 값과 출처를, 키를 주면 값만 출력한다. 경로는 `~`를 풀고 `..`와 symlink를 정리한 실제 경로로 출력한다. tools와 조율 세션은 경로를 이 출력에서 얻고 직접 정하지 않는다.

## 작업 공간

- **base**: workspace들을 두는 곳. 내장 기본값은 사용자 환경에 없을 수 있다. 조율 세션은 사용자가 확인하지 않은 base로 작업하지 않는다. base의 출처가 내장 기본값이면 쓰기 전에 운영자에게 확인받는다.
- **workspace**: 레포 하나의 작업 공간. `<base>/<workspace 이름>/`이다. 구성과 각 파일의 역할은 `WORKSPACE.md`에 있다. 목록을 유지하지 않고 base에서 찾는다(`WORKSPACE.md` > 찾기).

## 진행 기록 (조율 root)

조율 root를 clone 밖 한곳에 두면, 도구 clone이 여럿이어도 모든 조율 세션이 같은 회차 자료를 보고 `tools/check.sh`가 다른 active 회차와의 겹침을 한곳에서 본다.

```
<root>/
  runs/<회차 이름>/      회차 자료
  records/<회차 이름>/   AutoFlow 기록 폴더
```

`tools/config.py runs|records`가 각 위치를 출력한다.

