# review-only: AutoFlow for review only

## Goal

Review a change made outside AutoFlow (a document change, a small change, an existing PR) with an AutoFlow review, so that it meets the quality goal.

## Groups and sessions

| Step | How | Goal of the step |
|---|---|---|
| Work and PR | A work session outside AutoFlow or a person (skipped if the PR already exists) | Make the requested change into a PR |
| Review | AutoFlow review called by the coordinator | Review the PR |

## Default quality goal

The review has no finding of Medium or above.

## Final result

The verdict and findings condensed from the review report and posted on the PR (without local paths, run commands and the text of the invocation's `instructions`; `coordination.md` and the run's instructions can override this).

## What to look for in the workspace's `coordination.md`

PR rules, the repository's review goal.
