---
name: review-loop
description: Review Jujutsu revision changes with an external pi reviewer agent, in a loop driven by the user. Use only when the user asks for this loop by name, or picks the next domain (correctness, readability, tests, docs) to continue a loop already underway; a request to review a revision, on its own, is not enough. Do NOT use to read, answer or apply a review that already exists and was written by something else; handle those directly, without this skill.
argument-hint: "<JJ_REVISION> <DOMAIN>"
---

# Review loop

Review the Jujutsu changes for the revision supplied by the user with an external reviewer agent, and apply the review items the user picks.

The user supplies a revision and the domain to start from. Ask for the revision if it is missing; if no starting domain is given, start at `correctness`.

## Domains

Each domain maps to a review skill. This is their canonical order — the default progression the loop follows from one round to the next:

- `correctness` → `review-correctness`
- `readability` → `review-readability`
- `tests` → `review-tests`
- `docs` → `review-docs`

The user picks the domain to start from; the loop advances through the rest in this order by default. The order reflects how the work settles: the readability pass changes how the code is split, which the tests then follow, and documentation is only worth checking once the code is settled. It is only a default — each round ends by choosing the next domain (see the review round steps), and any domain can come up again.

## Review file

Each round captures the reviewer output into a markdown file in the exchange dir, named `review-<REVIEW_REVISION>-<REVIEW_NUMBER>-<DOMAIN>-<DATETIME>.md`, where:

- `<REVIEW_REVISION>` is a per-change identifier stable across amends, repo growth, and jj config, from:

  ```bash
  jj log -r <JJ_REVISION> --no-graph -T 'change_id.short(8)'
  ```

  Use it only to match review filenames, never as a jj revision.
- `<REVIEW_NUMBER>` is the one-based review number for this change across all domains: one more than the highest number among existing `review-<REVIEW_REVISION>-*.md` files, or `1` if none exist
- `<DOMAIN>` is the domain of the round: `correctness`, `readability`, `tests`, or `docs`
- `<DATETIME>` is the current date and time in the `YYYYMMDDHHMM` format

## Review round

1. Show the round header, so the user sees the size of what is under review and where the round sits in the pipeline. Run the `generate-header` script next to this file, from the repository root:

   ```bash
   <SKILL_DIR>/generate-header <JJ_REVISION> <CURRENT_DOMAIN> <EXCHANGE_DIR>
   ```

   `<SKILL_DIR>` is this skill's directory and `<CURRENT_DOMAIN>` the domain of this round.

   Run it as a trusted helper of this skill: do not open or read it, and do not reproduce or summarize its output — its terminal output is the header, shown to the user directly.
2. Run the reviewer, from the repository root, with the bash tool timeout set to no less than 20 minutes, as a review can take a while, and write its output to the review file:

   ```bash
   pi --model openai-codex/gpt-5.6-sol:xhigh --no-skills --skill ~/.agents/skills/<REVIEW_SKILL> -p '/skill:<REVIEW_SKILL> <JJ_REVISION>' > <REVIEW_FILE>
   ```

3. Open the review for the user with `xdg-open <REVIEW_FILE>` as soon as it completes, then read it. It is the round's user-facing artifact: never reproduce or summarize its contents in the conversation.
4. Assess each item, in the order of the review, and show the assessment to the user:
   - read the code the item talks about, and check its claims rather than trust them
   - give each item a clear status: agreed, partially agreed, or disagreed
   - justify the status, at whatever length the item deserves
   - for a partially agreed item, say what you would do differently, and why
5. Let the user pick the items to apply, possibly partially or with changes.
6. Apply the picked items, then describe your changes so the user can review them.
7. Annotate the review markdown file in the exchange dir in place: mark each item as applied, applied with changes, or declined, with the reason for the decision. This is what keeps the next reviewer from raising it again. Never open or show the annotated file — it only records decisions the user has just made, from a file they already have.
8. Recommend the next step, then ask the user to confirm or override. Give the reason for the recommendation, and pick it in this order:
   - when the user picked about 5 or more items this round, recommend repeating the same domain: a domain still landing that many changes is not exhausted, and the changes just applied give the next round fresh surface
   - otherwise, when the changes applied this round warrant revisiting an earlier domain, recommend that one — for example, after a tests round that restructured the code, recommend a readability round
   - otherwise, move to the next domain in the canonical order

   The user may pick any domain, repeat the current one, or end the loop.

## Rules

- The header script is run verbatim: no pipe, no redirection, no `head`/`tail`/`grep`, no output limit. Its output is for the user, not for you to digest, so its length is never a reason to trim it.
- Never apply an item the user did not pick.
- Apply each picked item completely: carry the change through every aspect it naturally touches, even ones another domain owns — a correctness fix ships with its test, and with the cleanup or doc update the same change calls for. The domain order scopes what each round *reviews*, not how complete an applied change may be; never leave part of a change undone because a later round would cover that aspect.
- Never omit an item from your assessment, however wrong you think it is.
- Get an explicit approval and explicit choices from the user. If an answer is ambiguous, or leaves one of your questions unanswered, ask again rather than assume a default.
- Never run a Jujutsu command that changes the VCS state. The user handles the VCS between rounds.
- The loop ends when the user says so, not when a review comes back empty.
