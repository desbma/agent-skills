---
name: review-auto-loop
description: Review Jujutsu revision changes with external pi reviewer agents, in waves of parallel per-domain review chains, driven by the user. Use only when the user asks for this loop by name, or gives the go for the next wave of a loop already underway; a request to review a revision, on its own, is not enough. Do NOT use to read, answer or apply a review that already exists and was written by something else; handle those directly, without this skill.
argument-hint: "[JJ_REVISION] [domain=N ...]"
---

# Review auto-loop

Review the Jujutsu changes for the target revision with external reviewer agents, and apply the review items the user picks. Reviews run in waves of two domains in parallel, each domain running a short chain of reviews.

## Domains, phases and config

Each domain maps to an item id prefix: `correctness` → `C`, `readability` → `R`, `tests` → `T`, `docs` → `D`.

A wave runs two domains in parallel: phase A waves run correctness and readability, phase B waves run tests and docs. The split keeps the domains that change production code apart from those that follow it. The loop starts at phase A, and moves between phases as the user decides at the end of each wave.

The `review` script settles the rest of a wave's configuration on its own: it resolves the revision, numbers the wave, and caps every chain — the code domains from the number of lines the revision adds, tests and docs at one run. Two flags of `review init` carry what the user asked for, in the wording of their request:

- `--cap <domain>=<N>` overrides a cap: on the loop's first wave for the whole loop, on a later wave for that wave alone. A cap of `0` excludes the domain; a phase with both domains excluded is skipped.
- `--repeat` opens a wave over the phase the loop already ran, on lower caps.

## Chains

A domain's runs within a wave form a chain. All runs of a chain use the same prompt, which designates the chain's dir as additional previous reviews: a run reads the completed captures of the runs before it, and does not raise their items again. `review chain run` starts the run the chain is due, and says so instead when the chain has ended — on a run that found no item, or at its cap. Launch a chain's next run as soon as the previous one completes; do not wait for its assessment.

## Files

The review dir holds, per reviewed change, one wave report per wave, and one chain dir per chain holding that chain's captures. The `review` script creates and names both, and is the only thing that ever writes there. Captures are reviewer stdout, never annotated: a capture holding no item is a run that found none.

Write a wave report only through the script, and do not open it: run it as a trusted helper of this skill.

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

1. Create the wave, naming its phase:

   ```bash
   <SKILL_DIR>/review init <REVIEW_DIR> <PHASE> [--revision <JJ_REVISION>] [--cap <domain>=<N> ...] [--repeat]
   ```

   On the loop's first wave, pass `--revision` when the user supplied a revision, and leave it out otherwise: the script then resolves the most recent non-empty change. It prints the change it resolved, the wave report path, then the domain of each chain it created. That change is `<JJ_REVISION>` for the whole loop: pass it as `--revision` on every later wave, so every wave reviews that same change, whatever the working copy holds by then. Launch the chains in parallel, in the background, one call each (a run takes 10 to 20 minutes):

   ```bash
   <SKILL_DIR>/review chain run <WAVE_REPORT> <DOMAIN>
   ```

2. Show the header:

   ```bash
   <SKILL_DIR>/review header show <WAVE_REPORT> <RUN>
   ```

   `<RUN>` is the run the display announces: `1` at wave launch, the just-completed run's index on later displays. Its terminal output is the header, shown to the user directly: do not reproduce or summarize it.

3. As each run completes: read the capture whose path it printed, launch the chain's next run with step 1's `review chain run` command — it reports the chain's end when there is none left to run — then show the header again (step 2 command, with the completed run's index), then write the run's items into the wave report:

   ```bash
   <SKILL_DIR>/review item import <WAVE_REPORT> <DOMAIN> <RUN>
   <SKILL_DIR>/review item assess <WAVE_REPORT> <ID> <CLAIM> [<SEVERITY>] <PROPOSAL> [<TAIL> ...] <<'EOF'
   <the justification>
   EOF
   ```

   `item import` quotes every item of the run into the report, in item order, and prints the id it gave each, which is where `<ID>` comes from. The assessment's arguments follow the verdicts: `holds` and `partly-holds` take the `<SEVERITY>` (`critical`, `major` or `minor`), `does-not-hold` takes none; then `apply` takes no `<TAIL>`, `apply-with-changes` and `decline` one text argument, `your-call` two or more. A `<TAIL>` is a command-line argument; only the justification comes from stdin:

   ```bash
   <SKILL_DIR>/review item assess <WAVE_REPORT> R2 partly-holds minor decline '<the tail>' <<'EOF'
   <the justification>
   EOF
   ```

   `item assess` echoes a `your-call`'s options under the item id, lettered in the order given: that letter is what a pick names. Assess each item by reading the code it talks about and checking its claims and its severity rather than trusting them, and justify at whatever length it deserves. Flag items colliding across the wave's two domains so the user can weigh them together; when an item duplicates one from the other domain or from a past wave, say so instead of assessing it twice.

4. When every chain has ended, show the header once more, then write the report's top part, item index and links:

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

8. Summarize the wave — what the user decided, and what the applied changes touched — then lay out the choices for the next step, and ask the user to decide. They are: repeat the current phase, run the other phase, or end the loop.

9. Wait. The user now reviews the changes, may ask questions or request further edits, and squashes into the reviewed revision. Launch the next wave only on their explicit go, never before: reviews must only ever see squashed state.

## Rules

- `review header show` and `review report format` are run verbatim: no pipe, no redirection, no `head`/`tail`/`grep`, no output limit, alone in their call. Their output is for the user, not for you to digest, so its length is never a reason to trim it.
- Issue independent operations together rather than one per turn: several tool calls in one message, several `review` invocations in one shell call.
- Never apply an item the user did not pick.
- Apply each picked item completely: carry the change through every aspect it naturally touches, even ones another domain owns — a correctness fix ships with its test, and with the cleanup or documentation update the same change calls for. Never leave part of a change undone because a later wave would cover that aspect.
- Get an explicit approval and explicit choices from the user. If an answer is ambiguous, or leaves one of your questions unanswered, ask again rather than assume a default.
- Never run a Jujutsu command that changes the VCS state. The user handles the VCS between waves.
- The loop ends when the user says so, not when a wave comes back empty.
