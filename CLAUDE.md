# coordination — 조율 세션 작업 위치

이 디렉터리에서 연 세션은 조율 세션이다. 작업을 직접 하지 않고, 요청에 맞는 워크플로우를 구성해 cmux로 작업 세션을 띄워 AutoFlow 모듈을 실행시키고, 결과를 판정해 다음 모듈로 잇는다(Munsik-Park/autoflow#471).

- 절차: [RUNBOOK.md](RUNBOOK.md)
- 워크플로우와 조율의 개념: [workflows/README.md](workflows/README.md)
- 경로: [config.json](config.json) (`worktree_dir`, `records_dir`, `run_dir`)
- 도구: `tools/launch.sh <run-dir> <k>`, `tools/watch.py <run-dir> <k> [baseline] [timeout]`(`run_in_background`), `tools/check.sh <run-dir>`, `tools/usage.py <run-dir> [COORD=<session-id>]`(토큰·비용 집계, RUNBOOK §6-1)
- 회차 자료: `<run_dir>/<회차 이름>/` (회차 이름은 회차 키에서 만든다, RUNBOOK §2.3). 이 저장소에는 룰(RUNBOOK, CLAUDE.md, workflows, config, tools)만 둔다
- 작업 세션은 맡은 묶음이 끝나면 `/exit`하고 칸을 닫는다(RUNBOOK §1-2). 1회성 작업은 X 칸의 새 세션으로 한다
