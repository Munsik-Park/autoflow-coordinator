# 버전 규칙

이 저장소의 버전은 root의 `VERSION` 파일에 둔다(Munsik-Park/autoflow-coordinator#14, 운영자 결정 2026-10-31).

- **형식**: `<지원하는 AutoFlow 버전>-rcN`. 예: `0.6.0-rc1`
- **올리기**: 조율자를 수정하는 PR마다 그 PR에서 rc를 하나 올린다.
- **새 AutoFlow 버전 지원**: `<새 버전>-rc1`에서 다시 시작한다.
- **대조**: `tools/prepare.py`는 `VERSION`에서 `-rcN`을 뺀 값과 설치된 AutoFlow 버전이 다르면 회차를 만들지 않고 멈춘다. 새 AutoFlow 버전을 지원하는 작업은 `--skip-version-check`로 이 비교를 건너뛴다(Munsik-Park/autoflow-coordinator#18).
- **태그**: merge commit에 `v<버전>` 태그를 단다. 예: `v0.6.0-rc1`
