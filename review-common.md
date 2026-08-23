# Common review instructions

Instructions shared by all `review-*` skills.

## Input

A review targets a single Jujutsu revision, supplied by the user as `<JJ_REVISION>`. If none is supplied, resolve it to the most recent non-empty change:

```bash
jj log -r 'latest(::@ & ~empty())' --no-graph -T 'change_id'
```

Whether given or resolved, `<JJ_REVISION>` is fixed for the whole review: use that exact value everywhere below.

Run:

```bash
jj show <JJ_REVISION>
```

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
- open it with its severity on its own line, `Severity: critical`, `Severity: major` or `Severity: minor`
- show code snippets for the suggested change; when the item rewrites existing code, showing it as a before/after pair is encouraged, as it reads better than the proposed code alone — use it where it helps, not for items that only add code

Severity rates the consequence of leaving the item unfixed — how bad it is, and how readily it is reached. It rates neither the effort of fixing it nor how strongly you believe the item is right:

- `critical` — a severe consequence, on a path ordinary use reaches
- `major` — a real consequence, but bounded, recoverable, or on a path only some runs reach
- `minor` — a narrow or cosmetic consequence, or one only a maintainer pays

Each domain anchors these levels to its own kind of consequence, and some domains have no reachable `critical`. Rate an item against those anchors, never against the other items of the review: a review that yields only minor items reports only minor items.

Order items by decreasing impact.
