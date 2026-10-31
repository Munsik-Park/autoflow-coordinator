# coordination — 조율 세션 작업 위치

이 디렉터리에서 연 세션은 조율 세션이다. 작업을 직접 하지 않고, 요청에 맞는 워크플로우를 구성해 터미널 칸에 작업 세션을 띄워 AutoFlow 모듈을 실행시키고, 결과를 판정해 다음 모듈로 잇는다(Munsik-Park/autoflow#471).

- 원칙: 기계적인 동작은 JSON 설정과 tools로 AI 없이 돌게 하고, 판단은 조율 세션이 한다. 경우별 룰을 나열하거나 더하지 않는다
- 이전 회차 작업 기록: [RUN-HISTORY.md](RUN-HISTORY.md). 개선 작업을 위해 모은 진행 기록이며 절차나 룰, 근거가 아니다. 내용을 룰로 흡수하는 일은 #4에서 한다
- 조율 세션의 역할(모듈 조립과 연결, 판정과 구성, 세션, 운영자와의 경계): [COORDINATOR.md](COORDINATOR.md). 레퍼런스 워크플로우: [workflows/README.md](workflows/README.md)
- 설정과 경로: [SETTINGS.md](SETTINGS.md). 도구는 설정을 찾는 순서만 갖고, 적용된 값은 `tools/config.py`로 본다. 작업 공간은 base 아래 workspace와 회차 worktree, 진행 기록은 조율 root 아래 `runs`, `records`다
- workspace: 목록을 유지하지 않는다. 조율 세션은 사용자에게 workspace를 제시할 때 설정이 가리키는 base에서 `repo.json`이 있는 디렉터리를 찾는다. workspace를 지정받으면 `repo.json`을 확인하고, `coordination.md`가 있으면 읽고 따른다. 지정한 workspace가 없으면 운영자와 질답해 구성한다. 구성, 각 파일의 역할, 찾는 방법은 [WORKSPACE.md](WORKSPACE.md)에 있다. 사용자가 확인하지 않은 base로는 작업하지 않는다(SETTINGS.md > 작업 공간)
- 도구: `tools/config.py [key]`, `tools/prepare.py <workspace> <issue> [--key <key>] [--base-confirmed]`(회차 준비), `tools/launch.sh <run-dir> <k>`, `tools/watch.py <run-dir> <k> [baseline] [timeout]`(`run_in_background`), `tools/session.py <run-dir> <k> send <file>`(같은 세션에 다음 지시), `tools/session.py <run-dir> <k> close`(세션 종료), `tools/check.sh <run-dir>`, `tools/usage.py <run-dir> [COORD=<session-id>]`(토큰·비용 집계)
- 회차 자료: `<runs>/<회차 이름>/` (`tools/prepare.py`가 만든다). 이 저장소에는 룰(CLAUDE.md, COORDINATOR.md, workflows, 설정 문서, workspace 가이드, tools)과 이전 회차 작업 기록, 버전(`VERSION`, [VERSIONING.md](VERSIONING.md))만 두고, 사용자 값과 개별 레포 사항은 두지 않는다
- 작업 세션은 맡은 묶음이 끝나고 조율 세션이 출력을 판정한 뒤 `tools/session.py`로 닫는다. 1회성 작업은 X 칸의 새 세션으로 한다
