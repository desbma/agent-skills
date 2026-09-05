---
name: summarize-change
description: Summarize the changes of a Jujutsu revision, as high level prose.
argument-hint: "[JJ_REVISION]"
disable-model-invocation: true
---

# Summarize Jujutsu changes

Describe what the Jujutsu changes for the target revision do, in prose.

## Input

A summary targets a single Jujutsu revision, supplied by the user as `<JJ_REVISION>`. If none is supplied, resolve it to the most recent non-empty change:

```bash
jj log -r 'latest(::@ & ~empty())' --no-graph -T 'change_id'
```

Whether given or resolved, `<JJ_REVISION>` is fixed for the whole summary: use that exact value everywhere below.

Run:

```bash
jj show <JJ_REVISION>
```

Read the surrounding code wherever the diff alone does not say what the changed code does.

## Main goals

Describe the change from the diff. The revision description says what its author meant to do; the summary says what the code does, and never restates the description.

- Describe, never interpret: say what the code now does, not why it was written, what it enables, or what it improves
- Stay high level: no code, no pseudo code, no file by file walkthrough, no line references
- Give each unrelated change a paragraph of its own, ordered by decreasing weight in the diff
- When a feature or a bug fix comes with its tests or its documentation, they earn at most a trailing clause; when the change is itself test or documentation work, describe it as the subject it is

## Output

Write the summary to stdout only.

One or more paragraphs, and nothing else: no heading, no list, no code block, no blockquote, no table. A code span naming a symbol the change touches is fine.

Two to five sentences per paragraph, and under 200 words in total.
