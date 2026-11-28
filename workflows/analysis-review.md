# analysis-review: AutoFlow for analysis and review only

## Goal

Find how to resolve the problem as given with AutoFlow analysis, and implement and open the PR outside AutoFlow. The final review is done with AutoFlow, up to a PR that meets the quality goal.

## Groups and sessions

Each step is a new session.

| Step | How | Goal of the step |
|---|---|---|
| Analysis | The AutoFlow analysis group (the criterion review group first if the criteria are ambiguous). criterion-decision follows the criterion review when its record changes a criterion's content or leaves an item undecided, in a new session each time it runs | Find how to resolve the problem as the criterion review or the issue's criteria set it, taking a defect's cause from the criterion review, which establishes it, and set the criteria to apply |
| Implementation and PR | A work session outside AutoFlow | Make a PR that meets the criteria, with the analysis result as input |
| Review | AutoFlow review | Review the PR |

## Default quality goal

The default quality goal covers every finding of the evaluations and the review. Implementation outside AutoFlow relies on the analysis report, and no AutoFlow evaluation runs on that implementation before the review, so a finding against the report is weighed with its carrying into the implementation.

## Final result

The PR, the verdict and findings condensed from the review report and posted on the PR.

## What to look for in the workspace's `coordination.md`

Repository structure, PR rules, the repository's quality goal.
