---
name: review-auto-loop
description: Review Jujutsu revision changes with external pi reviewer agents, in waves of parallel per-domain review chains, driven by the user. Use only when the user asks for this loop by name, or gives the go for the next wave of a loop already underway; a request to review a revision, on its own, is not enough. Do NOT use to read, answer or apply a review that already exists and was written by something else; handle those directly, without this skill.
argument-hint: "<JJ_REVISION> [domain=N ...]"
---

# Review auto-loop

Review the Jujutsu changes for the revision supplied by the user with external reviewer agents, and apply the review items the user picks. Reviews run in waves of two domains in parallel, each domain running a short chain of reviews.

The user supplies a revision; ask for it if it is missing.

## Domains, phases and config

Each domain maps to a review skill, an item id prefix, and a default cap on chain runs per wave:

- `correctness` → `review-correctness`, prefix `C`, cap 2
- `readability` → `review-readability`, prefix `R`, cap 2
- `tests` → `review-tests`, prefix `T`, cap 1
- `docs` → `review-docs`, prefix `D`, cap 1

A wave runs two domains in parallel: phase A waves run correctness and readability, phase B waves run tests and docs. The split keeps the domains that change production code apart from those that follow it. The loop starts at phase A, and moves between phases as the user decides at the end of each wave.

Arguments after the revision override the caps, canonically `domain=N` (for example `correctness=3 docs=0`); free-form phrasing is accepted. A cap of `0` excludes the domain for the whole loop; a phase with both domains excluded is skipped.

When the user repeats a phase, they may override the caps for that wave only. The default for a repeated wave is the loop cap minus one per domain, floored at 1 for domains whose loop cap is at least 1 — repeating never silently disables a domain, and further repeats keep this same default.

## Chains

A domain's runs within a wave form a chain. All runs of a chain use the same prompt, which designates the chain's dir as additional previous reviews: a run reads the completed captures of the runs before it, and does not raise their items again. A run that reports no items ends its chain early; otherwise the chain stops at the cap. Launch a chain's next run as soon as the previous one completes; do not wait for its assessment.

## Files

Derive the label used in file names:

```bash
jj log -r <JJ_REVISION> --no-graph -T 'change_id.short(8)'
```

Its output is `<REVIEW_REVISION>`, a per-change identifier stable across amends, repo growth, and jj config. Use it only in file names, never as a jj revision.

The exchange dir holds, per reviewed change:

- Wave docs `review-<REVIEW_REVISION>-wave<W>-<DATETIME>.md` — one per wave, where `<W>` is the one-based wave number and `<DATETIME>` the wave's start date and time in the `YYYYMMDDHHMM` format. Each carries the wave's items reproduced faithfully, their assessment, and the user's decisions.
- Chain dirs `review-<REVIEW_REVISION>-wave<W>-<domain>/` — one per chain, holding its captures `run<K>.md`, where `<K>` is the run's one-based position in the chain. Captures are reviewer stdout: never annotated, and empty until their run completes — an empty file is an in-flight run. A chain dir belongs to its reviews: never write anything in it, it only ever holds the captures.

If wave docs for the change already exist, the loop resumes from them: the wave number, the item counters and the past decisions all derive from the exchange dir.

## Wave doc

Items are numbered with the domain prefix and a counter continuous across the whole loop: `C7` is the seventh correctness item the loop ever produced, whatever its wave. A wave doc contains one section per domain, items in id order, each formatted as:

```markdown
### C7 (run 1, item 3)

<the item, reproduced faithfully from the raw file>

**Assessment**: agreed | partially agreed | disagreed

<the justification prose>

**Decision**: applied | applied with changes | declined — reason
```

The heading's `run` and `item` locate the item in its raw file. The `**Assessment**` line carries the verdict alone; the justification follows as prose. The `**Decision**` line is added at annotation time, and must end up present on every item. Keep these exact formats: the header script parses headings and decision lines, and fails loudly otherwise.

## Wave round

1. Determine the wave's phase, caps and number `<W>`, note the wave's `<DATETIME>` (`date +%Y%m%d%H%M`), create the wave's chain dirs, then launch its chains in parallel, in the background, from the repository root (a run takes 10 to 20 minutes):

   ```bash
   pi --model openai-codex/gpt-5.6-sol:xhigh --no-skills --skill ~/.agents/skills/<REVIEW_SKILL> -p '/skill:<REVIEW_SKILL> <JJ_REVISION>. In addition to the previous reviews you find as usual, the directory <CHAIN_DIR> also holds previous reviews of the same revision. Read its *.md files too, and do not raise their items again.' > <CHAIN_DIR>/run<K>.md
   ```

   `<CHAIN_DIR>` is the chain's absolute directory. The command is identical for every run of a chain, except for its capture's `<K>`.

2. Show the header by running the `generate-header` script next to this file, from the repository root:

   ```bash
   <SKILL_DIR>/generate-header <JJ_REVISION> <EXCHANGE_DIR> <W> <RUN> <PHASE> correctness=N readability=N tests=N docs=N
   ```

   `<RUN>` is the run the display announces: `1` at wave launch, the just-completed run's index on later displays. `<PHASE>` is `A` or `B`. The config values are the wave's effective caps.

   Run it as a trusted helper of this skill: do not open or read it, and do not reproduce or summarize its output — its terminal output is the header, shown to the user directly.

3. As each run completes: launch the chain's next run if one is due, then show the header again (step 2 command, with the completed run's index), then read its capture `<CHAIN_DIR>/run<K>.md` and assess its items into the wave doc: read the code each item talks about and check its claims rather than trust them; give each item a status — agreed, partially agreed, or disagreed — justified at whatever length it deserves; for a partially agreed item, say what you would do differently and why; flag items colliding across the wave's two domains so the user can weigh them together; when an item duplicates one from the other domain or from a past wave, record that instead of assessing it twice. Present assessments in item id order.

4. When every chain is done, show the header once more, then open the wave doc for the user with `xdg-open <WAVE_DOC>`. It is the wave's user-facing artifact: never reproduce or summarize its contents in the conversation. Follow with a one-line recap grouping every item: apply, apply with changes, decline, open — open being the calls that are genuinely the user's (collisions, tradeoffs).

5. Let the user pick the items to apply, possibly partially or with changes.

6. Apply the picked items in canonical domain order — correctness, readability, tests, docs. When two picked items collide, apply the correctness one first and adapt the other to the resulting code. Describe your changes so the user can review them.

7. Annotate the wave doc in place: add every item's `**Decision**` line, with the reason for the decision. Never open or show the annotated doc — it only records decisions the user has just made, from a doc they already have.

8. Recommend the next step, with the reason for the recommendation, and ask the user to decide, picking it in this order:
   - after a phase A wave where the user picked about 5 or more items, or where a chain was still yielding items when it hit its cap: repeat phase A — the domains are not exhausted, and the applied changes give the next wave fresh surface
   - after any other phase A wave: move to phase B
   - after a phase B wave whose applied items restructured enough code to warrant it: return to phase A
   - after any other phase B wave: end the loop

9. Wait. The user now reviews the changes, may ask questions or request further edits, and squashes into the reviewed revision. Launch the next wave only on their explicit go, never before: reviews must only ever see squashed state.

## Rules

- The header script is run verbatim: no pipe, no redirection, no `head`/`tail`/`grep`, no output limit. Its output is for the user, not for you to digest, so its length is never a reason to trim it.
- Never apply an item the user did not pick.
- Apply each picked item completely: carry the change through every aspect it naturally touches, even ones another domain owns — a correctness fix ships with its test, and with the cleanup or doc update the same change calls for. Never leave part of a change undone because a later wave would cover that aspect.
- Never omit an item from your assessment, however wrong you think it is.
- Get an explicit approval and explicit choices from the user. If an answer is ambiguous, or leaves one of your questions unanswered, ask again rather than assume a default.
- Never run a Jujutsu command that changes the VCS state. The user handles the VCS between waves.
- The loop ends when the user says so, not when a wave comes back empty.
