# full: the whole process

## Goal

Resolve an issue with the whole process of AutoFlow modules, up to a draft PR whose review meets the quality goal.

## Groups and sessions

One group is one session. The coordination session connects the modules in a group within the same session.

| Group | Modules | Goal of the group |
|---|---|---|
| Criterion review | criterion-screen, trace, in-depth, reconcile | Settle whether the issue's criteria hold against the code and policy |
| Analysis | analysis, criteria-apply, hypothesis | Establish the problem and cause with grounds, and set the criteria to apply |
| Design | design, plan | Make a design that can be implemented and verified |
| Build | build, audit, quality | Implement and verify the design |
| Delivery | delivery, ci, review | Put the change in a PR and take it through CI and review |

## Default quality goal

Evaluations use each contract's reference values, and the review has no finding of Medium or above.

## Final result

The draft PR, the CI verdict, the verdict and findings condensed from the review report and posted on the PR as COORDINATOR.md > Judgment at each connection (delivery, ci → review) sets, the merge review artifact.

## What to look for in the workspace's `coordination.md`

Repository structure, PR and merge rules, the repository's quality goal.
