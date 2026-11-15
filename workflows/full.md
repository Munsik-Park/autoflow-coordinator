# full: the whole process

## Goal

Resolve an issue with the whole process of AutoFlow modules, up to a draft PR whose review meets the quality goal.

## Groups and sessions

Each group starts in a new session. Within a group, a new session starts where a module's description requires a session other than the one that produced its input; the other modules continue in the session of the module before them, and the coordination session connects them there.

| Group | Modules | Where a new session starts | Goal of the group |
|---|---|---|---|
| Criterion review | criterion-screen, criterion-trace, criterion-in-depth, criterion-reconcile | criterion-screen (group start); criterion-trace, in a session other than the screen's; criterion-in-depth, one session per criterion, given only that criterion's target file; criterion-reconcile, in a session of its own | Settle whether the issue's criteria hold against the code and policy |
| Analysis | analysis, criteria-apply, hypothesis | analysis (group start), with criteria-apply continuing in its session; hypothesis, in a session other than the analysis's | Establish the problem and cause with grounds, and set the criteria to apply |
| Design | design, plan | design (group start); plan, in a session other than the design's | Make a design that can be implemented and verified |
| Build | test-first, build, audit, quality | test-first (group start), with build continuing in its session; audit, in a session other than the one that made the change, with quality continuing in the audit session, which did not make the change | Implement and verify the design |
| Delivery | delivery, ci, review | delivery (group start), with ci and review continuing in its session | Put the change in a PR and take it through CI and review |

## Default quality goal

Each evaluation has an average of 7.5 or more and every item 7 or more, and a security score of 3 or below calls for rework. The review has no finding of Medium or above.

## Final result

The draft PR, the CI verdict, the verdict and findings condensed from the review report and posted on the PR as COORDINATOR.md > Judgment at each connection (delivery, ci → review) sets, the merge review artifact.

## What to look for in the workspace's `coordination.md`

Repository structure, PR rules, what to judge around a merge, the repository's quality goal. The merge order and the steps after a merge that need no judgment are in the workspace's `merge-plan.json` (WORKSPACE.md).
