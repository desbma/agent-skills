---
name: review-docs
description: Review Jujutsu revision changes from jj show and report documentation and comments out of sync with the code.
argument-hint: "[JJ_REVISION]"
disable-model-invocation: true
---

# Review documentation of Jujutsu changes

Review the Jujutsu changes for the target revision, and report documentation that no longer matches the code.

Follow the common review instructions: @../review-common.md

## Scope

Documentation covers:

- `AGENTS.md`, `README.md`, and any other documentation file
- diagrams and schemas, which describe a structure or a flow the change may have altered
- code comments and docstrings

## Main goals

Find documentation that:

- contradicts the code: stale command, renamed item, removed option, changed default or behavior
- describes something the change deleted
- is missing for something the change introduced, and that a reader could not guess

Also report comments and docstrings that break the rules of the "Comment and docstring style" section of `AGENTS.md`.

## Guidelines

- Quote both the code and the documentation that contradict each other
- Fix documentation that is out of sync, only delete it when what it describes is gone
- Be sparing with new documentation, do not propose any for its own sake
- Anchor severity to what the documentation makes its reader do: `critical` when following it destroys state or costs work that cannot be recovered; `major` when it contradicts the code and sends the reader down a path that does not exist; `minor` for a style rule break, or for documentation missing where the code already says it
- Stay on documentation: correctness, readability and test coverage are covered by other review domains
