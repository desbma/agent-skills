---
name: review-auto-loop
description: Review Jujutsu revision changes with external pi reviewer agents, in waves of parallel per-domain review chains, driven by the user. Use only when the user asks for this loop by name, or gives the go for the next wave of a loop already underway; a request to review a revision, on its own, is not enough. Do NOT use to read, answer or apply a review that already exists and was written by something else; handle those directly, without this skill.
argument-hint: "[JJ_REVISION] [domain=N ...]"
---

# Review auto-loop

Review the Jujutsu changes for the target revision with external reviewer agents, and apply the review items the user picks. Reviews run in waves of two domains in parallel, each domain running a short chain of reviews.

The user supplies a revision. If they do not, resolve it once, when the loop starts, to the most recent non-empty change:

```bash
jj log -r 'latest(::@ & ~empty())' --no-graph -T 'change_id'
```

Its output is `<JJ_REVISION>` for the whole loop: every wave reviews that same change, whatever the working copy holds by then.

## Domains, phases and config

Each domain maps to a review skill, an item id prefix, and a default cap on chain runs per wave:

- `correctness` → `review-correctness`, prefix `C`, cap from diff size
- `readability` → `review-readability`, prefix `R`, cap from diff size
- `tests` → `review-tests`, prefix `T`, cap 1
- `docs` → `review-docs`, prefix `D`, cap 1

The correctness and readability caps are the same value, derived once at the start of the loop from the number of lines the revision adds — the insertion count on the last line of:

```bash
jj diff -r <JJ_REVISION> --stat | tail -1
```

- under 100 lines → cap 1
- 100 to 1000 lines → cap 2
- 1000 to 5000 lines → cap 3
- over 5000 lines → cap 4

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

Its output is `<REVIEW_REVISION>`, a per-change identifier stable across amends, repo growth, and jj config. Use it only to find the change's files, never as a jj revision.

The review dir holds, per reviewed change:

- Wave reports `<REVIEW_REVISION>-wave<W>-<DATETIME>.md` — one per wave. Each carries the wave's items reproduced faithfully, their assessment, and the user's decisions.
- Chain dirs `<REVIEW_REVISION>-wave<W>-<domain>/` — one per chain, holding its captures `run<K>.md`. Captures are reviewer stdout, never annotated. A run in flight writes `run<K>.md.running` and takes its final name when it completes, so a capture holding no item is a run that found none. A chain dir belongs to its reviews: never write anything in it, it only ever holds the captures.

The `review` script next to this file creates both. Write a wave report only through it, and do not open it: run it as a trusted helper of this skill.

If wave reports for the change already exist, the loop resumes from them: the wave number, the item counters and the past decisions all derive from the review dir.

## Items

Items are numbered with the domain prefix and a counter continuous across the whole loop: `C7` is the seventh correctness item the loop ever produced, whatever its wave.

The claim judges the item as the reviewer wrote it — whether its diagnosis survives reading the code, and how severe what survives is — and nothing else. It never carries a course of action. Assessing an item again replaces its assessment, until the item is decided.

The severity follows the claim: the reviewer's own, kept when it stands, replaced when it does not, the justification then saying what moved it. State it on every item rather than let silence stand for agreement; the reviewer's own stays visible in the quoted item, so a downgrade reads as a disagreement and not as an erasure. A `partly-holds` item is rated on what survives, not on what the reviewer claimed. `does-not-hold` is the one exception: no defect survives, so there is nothing to rate.

The proposal carries the course of action, never empty:

- `apply` — the item's fix, as the item writes it
- `apply-with-changes` — a different change, named by the tail
- `decline` — no change, the tail saying why
- `your-call` — a choice that is genuinely the user's; each tail argument states one option, so a reply can name it

The two are independent. An item whose claim holds still gets `decline` when the fix costs more than the flaw it closes; one whose claim does not hold still gets `apply-with-changes` when checking it uncovered a different, real change. Outside `your-call` the proposal never hedges: "worth doing, or skip" is not a proposal, it is `apply-with-changes` or `your-call`.

The severity is what makes a `decline` legible. Declining a `minor` item needs no defense; declining a `critical` one has to name what outweighs it, and when nothing does, the severity was wrong.

The decision is added once the user has picked, exactly one per item, its reason never empty. Deciding an item again replaces its decision. `applied-with-changes` means the applied change departs from the item as the reviewer wrote it, whoever asked for the departure. Taking the proposal as offered maps verdict for verdict: `apply` to `applied`, `apply-with-changes` to `applied-with-changes`, `decline` to `declined`. A `your-call` item, or a pick that overrides the proposal, takes the verdict the user's choice actually produced.

## Wave round

1. Determine the wave's phase, caps and number `<W>`, then create the wave, naming the phase's two domains:

   ```bash
   <SKILL_DIR>/review init <REVIEW_DIR> <JJ_REVISION> <W> <domain>=<cap> <domain>=<cap>
   ```

   It prints the wave report path, then one `<domain> <CHAIN_DIR>` line per chain. Launch the wave's chains in parallel, in the background, from the repository root (a run takes 10 to 20 minutes):

   ```bash
   pi --model openai-codex/gpt-5.6-sol:xhigh --no-skills --skill ~/.agents/skills/<REVIEW_SKILL> -p '/skill:<REVIEW_SKILL> <JJ_REVISION>. In addition to the previous reviews you find as usual, the directory <CHAIN_DIR> also holds previous reviews of the same revision. Read its *.md files too, and do not raise their items again.' > <CHAIN_DIR>/run<K>.md.running && mv <CHAIN_DIR>/run<K>.md{.running,}
   ```

   The command is identical for every run of a chain, except for its capture's `<K>`.

2. Show the header:

   ```bash
   <SKILL_DIR>/review header show <WAVE_REPORT> <RUN>
   ```

   `<RUN>` is the run the display announces: `1` at wave launch, the just-completed run's index on later displays. Its terminal output is the header, shown to the user directly: do not reproduce or summarize it.

3. As each run completes: read its capture `<CHAIN_DIR>/run<K>.md`, launch the chain's next run if one is due, then show the header again (step 2 command, with the completed run's index), then write its items into the wave report, in item order:

   ```bash
   <SKILL_DIR>/review item add <WAVE_REPORT> <PREFIX> <RUN> <N>
   <SKILL_DIR>/review item assess <WAVE_REPORT> <ID> <CLAIM> [<SEVERITY>] <PROPOSAL> [<TAIL> ...] <<'EOF'
   <the justification>
   EOF
   ```

   `<PREFIX>` is the domain's item id prefix — `C`, `R`, `T` or `D` — and `<N>` the item's number in the capture; `item add` allocates the id and prints the heading it wrote, which is where `<ID>` comes from. The assessment's arguments follow the verdicts: `holds` and `partly-holds` take the `<SEVERITY>` (`critical`, `major` or `minor`), `does-not-hold` takes none; then `apply` takes no `<TAIL>`, `apply-with-changes` and `decline` one text argument, `your-call` two or more. A `<TAIL>` is a command-line argument; only the justification comes from stdin:

   ```bash
   <SKILL_DIR>/review item assess <WAVE_REPORT> R2 partly-holds minor decline '<the tail>' <<'EOF'
   <the justification>
   EOF
   ```

   `item assess` echoes the proposal it wrote, lettering a `your-call`'s options in the order given: that letter is what a pick names. Assess it by reading the code it talks about and checking its claims and its severity rather than trusting them, and justify at whatever length it deserves. Flag items colliding across the wave's two domains so the user can weigh them together; when an item duplicates one from the other domain or from a past wave, say so instead of assessing it twice.

4. When every chain is done, show the header once more, then write the report's top part, item index and links:

   ```bash
   <SKILL_DIR>/review report format <WAVE_REPORT>
   ```

   It refuses a wave whose chains are unfinished, or whose items are not all in the report and assessed. Run it again after any later change to an assessment: it replaces the top part and the index it generated. It prints the wave's recap, grouped by proposal verdict; show it to the user as it comes. Then open the wave report for them with `xdg-open <WAVE_REPORT>`. It is the wave's user-facing artifact: never reproduce or summarize its contents in the conversation.

5. Let the user pick, item by item. A bare `apply` resolves against that item's proposal, never against the reviewer's text:

   - proposed `apply` or `apply-with-changes` — carry out the proposal
   - proposed `decline` — the user is overriding the decline; carry out the item as the reviewer wrote it, and say so before acting
   - proposed `your-call` — a bare `apply` is not an answer; ask which option

   A pick may also override the proposal with an instruction of its own, which then replaces it. If their reply asks anything, answer it and change nothing, then wait again: the next message carries the picks, or more questions. Move to step 6 only on a reply that asks nothing.

6. Apply the picked items in canonical domain order — correctness, readability, tests, docs. When two picked items collide, apply the correctness one first and adapt the other to the resulting code. Describe your changes so the user can review them.

7. Record the decisions, one invocation per item:

   ```bash
   <SKILL_DIR>/review item decide <WAVE_REPORT> <ID> --verdict <VERDICT> <<'EOF'
   <the reason>
   EOF
   ```

   Run it again for an item whose decision changes later: it replaces the decision. Never open or show the annotated report — it only records decisions the user has just made, from a report they already have.

8. Lay out the choices for the next step, and ask the user to decide. They are: repeat the current phase, run the other phase, or end the loop. Give the facts that bear on the choice — how many items the user picked, whether a chain was still yielding items when it hit its cap, and what the applied changes touched.

9. Wait. The user now reviews the changes, may ask questions or request further edits, and squashes into the reviewed revision. Launch the next wave only on their explicit go, never before: reviews must only ever see squashed state.

## Rules

- `review header show` and `review report format` are run verbatim: no pipe, no redirection, no `head`/`tail`/`grep`, no output limit, alone in their call. Their output is for the user, not for you to digest, so its length is never a reason to trim it.
- Issue independent operations together rather than one per turn: several tool calls in one message, several `review` invocations in one shell call.
- Never apply an item the user did not pick.
- Apply each picked item completely: carry the change through every aspect it naturally touches, even ones another domain owns — a correctness fix ships with its test, and with the cleanup or documentation update the same change calls for. Never leave part of a change undone because a later wave would cover that aspect.
- Never omit an item from the wave report, however wrong you think it is.
- Get an explicit approval and explicit choices from the user. If an answer is ambiguous, or leaves one of your questions unanswered, ask again rather than assume a default.
- Never run a Jujutsu command that changes the VCS state. The user handles the VCS between waves.
- The loop ends when the user says so, not when a wave comes back empty.
