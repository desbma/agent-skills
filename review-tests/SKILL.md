---
name: review-tests
description: Review Jujutsu revision changes from jj show and propose test additions, fixes or removals.
argument-hint: "<JJ_REVISION>"
disable-model-invocation: true
---

# Review tests of Jujutsu changes

Review the Jujutsu changes for the revision supplied by the user, and propose changes to the tests covering them.

Follow the common review instructions: @../review-common.md

## Main goals

Propose to:

- test behavior that is left untested and would regress silently
- pin down a corner case whose handling looks intentional but not obvious, so that the test documents the intent
- fix a test that is incomplete, or asserts the current behavior rather than the intended one
- remove a test that is useless: it cannot fail, it duplicates another one, or it exercises the language and its libraries rather than the code
- flag a test that manufactures a state the production code cannot reach: it pins a special case that exists only to satisfy the test, and the pair should go together
- flag a test that can turn flaky: hardcoded sleep or timing values, assumptions about the host system (paths, locale, clock, available ports), or unsynchronized concurrency racing on shared state

## Guidelines

- Never propose to change the main code to make it easier to test, take it as it is
- Prefer a few meaningful tests over coverage for its own sake
- State the regression each proposed test would catch
- Anchor severity to the signal the suite gives today: `critical` when the signal is false — a test pinning wrong behavior as correct, or one that fails on states the code handles; `major` for behavior left untested that would regress silently; `minor` for a redundant or useless test, and for a case another test already covers
- Stay on tests: correctness, readability and documentation are covered by other review domains
