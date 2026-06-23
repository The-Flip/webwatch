# Plans

This folder contains design documents for significant changes to the codebase.

Each document serves two purposes:

1. **Planning**: before implementation, it describes the approach, trade-offs, and alternatives considered.
2. **History**: after implementation, it records why things were built the way they were — an architectural decision record (ADR) future developers can reference.

Documents remain here whether the work is complete or not.

## The review workflow

**No significant change proceeds to implementation until its plan has been reviewed.** The working agreement for this project:

1. Write the plan as `docs/plans/<name>.md` — context, approach, the modules touched, and how it will be verified.
2. Have it reviewed by the [`agy`](https://antigravity.google/) (Google Antigravity) CLI:

   ```bash
   make review-plan PLAN=docs/plans/<name>.md
   ```

   This runs `agy` in read-only print mode against the plan and prints a critique. (`agy` reviews; it does not edit files.)

3. Address the feedback, and record what changed in a short "Review feedback incorporated" section at the end of the plan.
4. Only then implement.

Small, obvious fixes (typos, one-line corrections, dependency bumps) don't need a plan.

> The reviewer is currently `agy`. If the review tool changes, update the
> `review-plan` target in the `Makefile` and this document together.
