# analysis-review: AutoFlow for analysis and review only

## Goal

Find the cause with AutoFlow analysis, and implement and open the PR outside AutoFlow. The final review is done with AutoFlow, up to a PR that meets the quality goal.

## Groups and sessions

Each step is a new session.

| Step | How | Goal of the step |
|---|---|---|
| Analysis | The AutoFlow analysis group (the criterion review group first if the criteria are ambiguous) | Set the problem, the cause and the criteria to apply |
| Implementation and PR | A work session outside AutoFlow | Make a PR that meets the criteria, with the analysis result as input |
| Review | AutoFlow review | Review the PR |

## Default quality goal

For hypothesis, the contract's reference values plus no recommendation of Medium or above. Implementation outside AutoFlow relies on the analysis report, so an omission in the report carries into the implementation. The review has no finding of Medium or above.

## Final result

The PR, the verdict and findings condensed from the review report and posted on the PR (without local paths, run commands and the text of the invocation's `instructions`; `coordination.md` and the run's instructions can override this).

## What to look for in the workspace's `coordination.md`

Repository structure, PR rules, the repository's quality goal.
