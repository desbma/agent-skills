---
name: review-correctness
description: Review Jujutsu revision changes from jj show and report correctness and completeness defects.
argument-hint: "<JJ_REVISION>"
disable-model-invocation: true
---

# Review correctness of Jujutsu changes

Review the Jujutsu changes for the revision supplied by the user, and report defects that make the code behave incorrectly or incompletely.

Follow the common review instructions: @../review-common.md

## Main goals

Take the revision description and the surrounding code as the statement of intent, and find code that:

- does not do what it is meant to do: wrong logic, inverted condition, off by one, misused API
- breaks on states it should handle: edge case, empty or missing value, overflow, concurrent access
- silently ignores an error or abnormal condition instead of surfacing it
- is incomplete: unhandled case, code path left unimplemented, change applied in one place but not in its siblings
- reaches for a fragile or suboptimal pattern when a sound alternative exists: a polling loop with a sleep call where an event, condition variable or blocking wait would do
- carries algorithmic complexity that can explode at runtime on realistic inputs when a lower complexity alternative exists: a quadratic scan inside a loop where a set lookup or precomputed index would do

## Guidelines

- Only report a defect if you can describe the concrete scenario that triggers it, and its consequence
- Do not report a bare suspicion: either exhibit the triggering input, or name what blocked you from confirming it
- Flag algorithmic complexity only when a realistic input can make its cost explode and a better alternative exists; small performance micro optimizations are out of scope
- Give a rough line count delta for each fix, so the reader can weigh its cost against the defect's impact
- Stay on correctness: readability, documentation and test coverage are covered by other review domains
