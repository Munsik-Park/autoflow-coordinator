# 레퍼런스 워크플로우

조율 세션이 회차 워크플로우를 짤 때 출발점으로 쓰는 기본 구성이다. 초안이다. 워크플로우, 묶음, 세션, 품질 목표의 개념과 회차에서 구성하는 법은 [COORDINATOR.md](../COORDINATOR.md)에 있다. 이 폴더의 조율자는 조율 세션이다.

## 레퍼런스

| 레퍼런스 | 목표 |
|---|---|
| [full](full.md) | 이슈를 AutoFlow 전 과정으로 해결한다 |
| [analysis-review](analysis-review.md) | 원인 파악과 리뷰는 AutoFlow로, 구현은 AutoFlow 밖에서 한다 |
| [review-only](review-only.md) | AutoFlow 밖에서 만든 변경을 AutoFlow 리뷰로 검토한다 |

레퍼런스의 정의는 이 폴더에만 둔다.

## 경로

회차 자료와 AutoFlow 기록 폴더는 진행 기록인 조율 root 아래에, worktree는 작업 공간인 base 아래 대상 레포의 workspace에 둔다. 조율 root와 base는 설정으로 찾는다([SETTINGS.md](../SETTINGS.md)).
