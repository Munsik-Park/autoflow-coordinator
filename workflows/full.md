# full: the whole process

## Goal

Resolve an issue with the whole process of AutoFlow modules, up to a draft PR whose review meets the quality goal.

## Groups and sessions

Each group starts in a new session. Within a group, a new session starts where a module's description requires a session other than the one that produced its input; the other modules continue in the session of the module before them, and the coordination session connects them there.

| Group | Modules | Where a new session starts | Goal of the group |
|---|---|---|---|
| Criterion review | criterion-screen, criterion-trace, criterion-in-depth, criterion-reconcile | criterion-screen (group start); criterion-trace, in a session other than the screen's, given the issue and the screen's review record only; criterion-in-depth, one session per criterion, given only that criterion's target file; criterion-reconcile, in a session of its own | Settle whether the issue's criteria hold against the code and policy |
| Criterion decision | criterion-decision | criterion-decision, in a new session each time it runs. It follows the criterion review when the review's record changes a criterion's content or leaves an item undecided | Decide each change to a criterion's content and each item the criterion review left undecided |
| Analysis | analysis, criteria-apply, hypothesis | analysis (group start), with criteria-apply continuing in its session; hypothesis, in a session other than the analysis's | Find how to resolve the problem the issue raises, starting from the settled account of whether the problem holds and what causes it, and set the criteria to apply |
| Design | design, plan | design (group start); plan, in a session other than the design's | Make a design that can be implemented and verified |
| Build | test-first, build, audit, quality | test-first (group start), with build continuing in its session; audit, in a session other than the one that made the change, with quality continuing in the audit session, which did not make the change | Implement and verify the design |
| Delivery | delivery, ci, review | delivery (group start), with ci and review continuing in its session | Put the change in a PR and take it through CI and review |

## Default quality goal

The default quality goal covers every finding of the evaluations and the review.

## Final result

The draft PR, the CI verdict, the verdict and findings condensed from the review report and posted on the PR, the merge review artifact.

## What to look for in the workspace's `coordination.md`

Repository structure, PR rules, what to judge around a merge, the repository's quality goal. The merge order and the steps after a merge that need no judgment are in the workspace's `merge-plan.json`.
