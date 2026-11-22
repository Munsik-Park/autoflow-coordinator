# review-only: AutoFlow for review only

## Goal

Review a change made outside AutoFlow (a document change, a small change, an existing PR) with the `review` module of autoflow-module, so that it meets the quality goal.

## Groups and sessions

| Step | How | Goal of the step |
|---|---|---|
| Work and PR | A work session outside AutoFlow or a person (skipped if the PR already exists) | Make the requested change into a PR |
| Review | The `review` module of autoflow-module, run in a work session by the coordination session | Review the PR |

## Default quality goal

The quality goal is met when the coordination session has disposed of every finding of the review with grounds, and every finding it disposed of as fix is fixed and the fix checked on the new head (coordinator-role.md > Composition and verdict > Disposition, quality goal). A low score or a finding of a given severity is not by itself a fail: it is judged through its disposition.

## Final result

The verdict and findings condensed from the review report and posted on the PR as coordinator-role.md > Judgment at each connection (delivery, ci → review) sets.

## What to look for in the workspace's `coordination.md`

PR rules, the repository's review goal.
