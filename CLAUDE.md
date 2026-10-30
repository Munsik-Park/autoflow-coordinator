# coordination — 조율 세션 작업 위치

이 디렉터리에서 연 세션은 조율 세션이다. 작업을 직접 하지 않고, 요청에 맞는 워크플로우를 구성해 cmux로 작업 세션을 띄워 AutoFlow 모듈을 실행시키고, 결과를 판정해 다음 모듈로 잇는다(Munsik-Park/autoflow#471).

- 원칙: 기계적인 동작은 JSON 설정과 tools로 AI 없이 돌게 하고, 판단은 조율 세션이 한다. 경우별 룰을 나열하거나 더하지 않는다
- 절차: [RUNBOOK.md](RUNBOOK.md). RUNBOOK은 근거가 아니라 동작 자료를 모아 하나씩 룰로 흡수해 가는 자료다. 일반 룰은 조율 도구(이 저장소의 룰, workflows, tools)로, 레포별 내용은 workspace로 옮긴다
- 워크플로우와 조율의 개념: [workflows/README.md](workflows/README.md)
- 설정과 경로: [SETTINGS.md](SETTINGS.md). 도구는 설정을 찾는 순서만 갖고, 적용된 값은 `tools/config.py`로 본다. 작업 공간은 base 아래 workspace와 회차 worktree, 진행 기록은 조율 root 아래 `workspaces`(workspace 목록), `runs`, `records`다
- workspace: 조율 세션은 workspace를 지정받으면 `repo.json`을 확인하고 `coordination.md`를 읽고 따른다. 없으면 운영자와 질답해 구성한다. 구성과 각 파일의 역할은 [WORKSPACE.md](WORKSPACE.md)에 있다. 사용자가 확인하지 않은 base로는 작업하지 않는다(SETTINGS.md > 작업 공간)
- 도구: `tools/config.py [key]`, `tools/workspace.py <이름> [key]`, `tools/launch.sh <run-dir> <k>`, `tools/watch.py <run-dir> <k> [baseline] [timeout]`(`run_in_background`), `tools/check.sh <run-dir>`, `tools/usage.py <run-dir> [COORD=<session-id>]`(토큰·비용 집계, RUNBOOK §6-1)
- 회차 자료: `<runs>/<회차 이름>/` (회차 이름은 회차 키에서 만든다, RUNBOOK §2.3). 이 저장소에는 룰(RUNBOOK, CLAUDE.md, workflows, 설정 문서, workspace 가이드, tools)만 두고, 사용자 값과 개별 레포 사항은 두지 않는다
- 작업 세션은 맡은 묶음이 끝나면 `/exit`하고 칸을 닫는다(RUNBOOK §1-2). 1회성 작업은 X 칸의 새 세션으로 한다
