# Reference workflows

The default compositions a coordination session starts from when it plans a run's workflow. They are drafts. The concepts of workflow, group, session and quality goal, and how to compose them in a run, are in [COORDINATOR.md](../COORDINATOR.md). The coordinator in this folder is the coordination session.

## References

| Reference | Goal |
|---|---|
| [full](full.md) | Resolve an issue with the whole AutoFlow process |
| [analysis-review](analysis-review.md) | Find the cause and review with AutoFlow, and implement outside AutoFlow |
| [review-only](review-only.md) | Review a change made outside AutoFlow with an AutoFlow review |

The definitions of the references are kept in this folder only.

## Paths

Run data and AutoFlow record folders go under the coordination root, which holds the progress records, and worktrees go in the target repository's workspace under the base, which is the work space. The coordination root and the base are found through settings ([SETTINGS.md](../SETTINGS.md)).
