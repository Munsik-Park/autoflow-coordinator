# analysis-review: 분석과 리뷰만 AutoFlow

## 목표

원인 파악은 AutoFlow 분석으로 하고, 구현과 PR은 AutoFlow 밖에서 한다. 마지막 리뷰는 AutoFlow로 해서 품질 목표를 만족하는 PR까지 만든다.

## 묶음과 세션

단계마다 새 세션이다.

| 단계 | 방식 | 단계의 목표 |
|---|---|---|
| 분석 | AutoFlow 분석 묶음(기준이 모호하면 기준 검토 묶음을 먼저) | 문제와 원인, 적용할 기준을 정한다 |
| 구현과 PR | AutoFlow 밖의 작업 세션 | 분석 결과를 입력으로 기준을 충족하는 PR을 만든다 |
| 리뷰 | AutoFlow review | PR을 검토한다 |

## 품질 목표 기본값

hypothesis는 계약의 참고 합격선에 Medium 이상 권고 없음을 더한다. AutoFlow 밖의 구현이 분석 보고서에 기대므로 보고서의 누락이 구현으로 이어진다. 리뷰는 Medium 이상 없음.

## 최종 결과물

PR, 리뷰 보고서에서 PR에 올린 내용.

## workspace의 `coordination.md`에서 볼 것

저장소 구성, PR 규칙, 저장소의 품질 목표.
