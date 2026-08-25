---
name: review-readability
description: Review Jujutsu revision changes from jj show and propose simplifications, more idiomatic code, and better consistency with surrounding patterns.
argument-hint: "[JJ_REVISION]"
disable-model-invocation: true
---

# Review readability of Jujutsu changes

Review the Jujutsu changes for the target revision, and propose ways to improve the code — above all by cutting its line count, and further by making it more idiomatic and consistent with the patterns the surrounding code already uses.

Follow the common review instructions: @../review-common.md

## Main goals

The leading goal is to reduce the code's line count: fewer lines to read and maintain. A small increase is fine when it buys a worthwhile readability, maintainability, or consistency gain; when the trade-off is roughly even, favor fewer lines.

Keeping that as the primary goal, also make the code:

- Lower in cognitive and cyclomatic complexity
- More idiomatic and least surprising for a reader used to the language and its conventions
- Consistent with the patterns the surrounding code already establishes — error handling, logging, naming, and structural conventions — preferring the established form even when a diverging one would work
- Easier to read and navigate
- Equivalent in intent and main effects; minor implementation side effects not covered by tests (logging statements, and other incidental behavioral details) may change

The work of updating tests is never an argument against a simplification: if code can be simplified but doing so requires changing tests, make the change anyway. Prefer less test coverage over high test coverage for complex code. However, when code is shaped a certain way *only* because there is no other way to test it, that is a valid reason to leave it as is.

## Opportunity examples

- Delete a special case that earns nothing: a branch, parameter or abstraction handling a state the production code cannot reach, a generalization with a single caller, or configurability nothing varies
- Factor similar code together
- Rely on existing standard library code rather than custom code
- Use idiomatic, self-documenting interfaces; for example, Python `__str__` or Rust `Display` rather than a custom `to_string` method
- Rely on types rather than unenforced conventions
- Align a diverging error-handling, logging, or naming pattern with the one prevailing in the module
- Where it helps, split a large source file into smaller modules with clear responsibilities

### Python specific

- Replace loops with list comprehensions or `itertools` functions
  - the `more_itertools` dependency can be added if it helps

### Rust specific

- Use combinators liberally
  - the `itertools` dependency can be added if it helps

## Additional instructions

Close each item with its estimated line count delta, alone on the item's last line, after any code snippet:

```markdown
**Estimated delta**: -8 lines
```

The estimate covers everything the item asks for, tests included, and carries its sign: `-8 lines`, `+3 lines`, `0 lines`. Rank the items that remove the most lines first.

Anchor severity to what the code costs whoever reads it next: `major` for a shape that actively misleads — a name or a pattern that suggests behavior the code does not have, or density enough to hide a defect from a reader looking for one; `minor` for everything else, including most line count savings. Readability has no `critical`: code that merely reads badly still runs.

When proposing to delete code as unneeded, show what makes the state impossible: an invariant, a type, or the complete set of call sites. Without it, drop the item.
