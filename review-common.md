# Common review instructions

Instructions shared by all `review-*` skills.

## Input

A review targets a single Jujutsu revision, supplied by the user. If no revision is supplied, ask for one.

Run:

```bash
jj show <JJ_REVISION>
```

Replace `<JJ_REVISION>` with the exact revision argument.

Derive the label used to find previous review files:

```bash
jj log -r <JJ_REVISION> --no-graph -T 'change_id.short(8)'
```

Its output is `<REVIEW_REVISION>`, a per-change identifier stable across amends, repo growth, and jj config. Use it only to match review filenames, never as a jj revision.

Focus on the current diff, but do not limit the review to the changed code; related code can be reviewed too when needed.

## Previous reviews

The exchange dir may already contain reviews of the same revision, from a previous run of this skill or from another review domain, as markdown files named `review-<REVIEW_REVISION>-*.md`. Read them all before starting.

Each item of a previous review may be annotated with the decision the user made about it: applied, applied with changes, or declined. Do not raise again an item that appears in a previous review, whether or not it carries a decision yet, and whatever the decision was.

## Output

Write the review to stdout only.

Report at most about 10 items. Report fewer, or none at all, if that is all the review yields, but within that limit do not hold back an item you believe in.

For each item:

- give it a number, so it can be referenced unambiguously
- show code snippets for the suggested change; when the item rewrites existing code, showing it as a before/after pair is encouraged, as it reads better than the proposed code alone — use it where it helps, not for items that only add code

Order items by decreasing impact.
