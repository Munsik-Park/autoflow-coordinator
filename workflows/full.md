# full: 전 과정

## 목표

이슈를 AutoFlow 모듈 전 과정으로 해결해, 리뷰가 품질 목표를 만족하는 draft PR까지 만든다.

## 묶음과 세션

묶음 하나가 세션 하나다. 묶음 안의 모듈은 같은 세션에서 조율자가 잇는다.

| 묶음 | 모듈 | 묶음의 목표 |
|---|---|---|
| 기준 검토 | criterion-screen, trace, in-depth, reconcile | 이슈의 기준이 코드와 정책에 비추어 성립하는지 확정한다 |
| 분석 | analysis, criteria-apply, hypothesis | 문제와 원인을 근거와 함께 밝히고 적용할 기준을 정한다 |
| 설계 | design, plan | 구현하고 검증할 수 있는 설계를 만든다 |
| 구현 | build, audit, quality | 설계를 구현하고 검증한다 |
| 전달 | delivery, ci, review | 변경을 PR로 내고 CI와 리뷰를 거친다 |

## 품질 목표 기본값

평가는 각 계약의 참고 합격선, 리뷰는 Medium 이상 없음.

## 최종 결과물

draft PR, CI 판정, PR에 올린 리뷰 집계, 머지 검토 아티팩트.

## 저장소 운영 노하우에서 볼 것

저장소 구성, PR과 merge 규칙, 저장소의 품질 목표.
