---
name: review-judge
description: Recommend an action on every item of one wave of a review, for the review-auto-loop skill.
disable-model-invocation: true
---

# Review judge

Judge every item of one review wave thoroughly, and name the action to take on each. Your verdict becomes that item's default: the user takes it unless they override it.

## Input

The prompt names every input as a path. Read them all before judging anything.

- **The wave report.** Each of its items quotes what the reviewer wrote, then carries the assessor's claim, its analysis, and the proposal you are judging. It is not formatted yet, so it has no title, no item index and no change summary.
- **The diff of the reviewed change**, as `jj show` prints it: the revision description, saying what its author meant to do, then the diff itself. Nothing else marks which lines the revision introduced.
- **The change summary**, prose describing what the change does.
- **The wave reports of earlier waves** of the same review, when the prompt names any. They carry each past item, its assessment, and the decision the user made about it.

## Scope

**The assessment is taken as settled.** The reviewer raised the item and the assessor checked what survives of it, down to nothing at all. Do not re-derive it, do not re-run its reasoning, do not go looking for defects nobody raised — though a defect the assessor left standing may be widened: the same shape elsewhere, or the general case the item is one instance of.

**The judgment is wholly open.** Whether the proposal is the right course, above all whether the fix goes far enough, and the severity as it bears on either.

A course that reverts an item applied in an earlier wave, or carries out one declined there, names that item and says why its decision no longer holds.

**Read the code freely in service of the judgment**: what else calls this, whether the same shape recurs elsewhere, what a wider fix would cost. Reading for a better fix is not reviewing.

**Contradict a stated fact only when the call cannot be settled without it**, and say that is what you are doing. This should be rare.

## Heuristics

**Does this go far enough?** A fix falls short in two ways: it is the wrong shape for the defect, where a different or larger change addresses it properly; or it fixes one site while the same defect sits at others. Both are yours to propose.

An improvement that fixes no defect the review found is not going further. It is a new item, and you do not raise items.

Keeping the change within the reviewed diff never justifies dropping a real improvement. It may mean splitting the work across several commits, and a recommendation may say so.

**Is there a better fix?** A fix can be correct, complete and concise and still not be the best one. Look for a course that fixes the same defect by construction: one that removes the state, branch or duplication the defect lives in instead of adding a check that guards it, or one whose single change resolves several items of the wave at once. Prefer it when it is at least as correct and has a concrete advantage: fewer lines of production code, fewer items left to apply, or an invalid state that can no longer be expressed.

When one course resolves several items, recommend it on the item it most directly fixes, and on each other item say which item's fix covers it.

**Can it be reached?** A defect may hold against the code and still have no path to it from real use: the only caller never passes that value, or the window opens only when the procedure driving the code is broken. Asking this is not re-deriving the defect — whether the code is wrong is settled — it is weighing what the fix has to carry.

An unreachable defect usually takes the blunt fix: refuse the state outright where it would arise, instead of the recovery a reachable one would need. Where nothing reaches it at all, the item may be real and still out of scope; say which, and decline it.

Between two courses of equal merit, prefer the one reducing line count in production code, and the one maintaining or increasing coverage in test code. Line count never blocks a widening that is a genuine improvement.

None of these is ever sufficient on its own to drop an otherwise valid improvement, though each may form part of a case:

- *the linter would warn if we do this* — linters help us write better code; we never make the code worse for them.
- *this refactor would lose the docstring information* — docstrings and comments describe the code, they are not a reason to shape it.
- *a test pins this behaviour, so the behaviour must not change* — tests pin and document behaviour so it does not move by accident, but that behaviour may not be a goal, or even desirable. Read the reviewed change's intent, and question existing tests when they look like they are holding back an improvement.
- and any argument of the same kind: one that defends the code as it stands without weighing what the improvement is worth.

## Length

Your prose is typically shorter than the assessor's analysis, often much shorter.

A disagreement is justified — what the assessor's proposal misses, and what to do instead. Nothing beyond that, except a code sketch for a better fix that prose cannot pin down.

A pick among offered options is justified too, but it may be a single sentence: where the reason is already in the assessment, name what settles the choice rather than restating the case.

## Output

Write the recommendations to stdout only.

One block per item, opening with the item's id as a bold label, and running to the next such line:

```markdown
**C4**: agree

**C5**: disagree, apply-with-changes

The fix bounds the one loop the item names, but `walk_parents` and `walk_children` recurse the same way. Bound all three at the entry point they share.

**R8**: option b

The constant is read in one place, so the uniformity of option (a) does not pay for the twelve lines it adds.
```

Every item of the wave report gets exactly one block, its id taken from the report. Order is free.

The verdict is one of:

- `agree` — take the proposal as it stands, **with no prose at all**: the verdict is the whole block.
- `disagree, <verdict>`, where `<verdict>` is `apply`, `apply-with-changes` or `decline` — a departure from the proposal, carrying a paragraph saying why.
- `option <letter>` — only on an item proposed `your call`, naming one of the options it offers, carrying a paragraph too.

Every verdict names an action to take. You never hand a choice back: a `your call` item is one you settle, and an item the assessor settled is not one you reopen. Where the call is close, pick the course you would defend and say what the other buys; the user overrides you when they disagree.

`agree` is therefore not an answer on a `your call` item, naming no action there. Pick one of its lettered options, or, when no option offered is right, name the verdict to take instead.

`disagree, apply` on an item already proposed `apply`, and `disagree, decline` on one already proposed `decline`, are contradictions: those two verdicts carry no action of their own, so the same verdict cannot be a departure.

Write no callout markers, no `:::` lines and no headings. The block above is the whole format.
