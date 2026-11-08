---
name: challenge-handoff
description: Adversarially review a handoff document against the code and every source it depends on, and append to it a single verified path forward, or confirm its plan.
argument-hint: "<HANDOFF_FILE>"
disable-model-invocation: true
---

# Challenge handoff

Review the handoff document given as argument adversarially: treat every claim, diagnosis and plan in it as unproven until you have checked it yourself. Then append to it a section that gives one verified path forward, or confirms that its plan holds as written.

## Investigate

Read the document, the sibling documents it points to, and everything it references. Then dig as deep as the problem requires: the code paths involved, the source of dependencies, libraries, the kernel or any upstream project, issue trackers, documentation, the web. Prove behavior by running it: build, reproduce the problem, write throwaway tests, prototype the fix, in a scratch copy of the project, or in a VM when the host cannot run it.

All of this is yours to do without asking. Never offer the user an investigation or an experiment, and never ask whether to go further: go further.

Edit no file of the project: the handoff document is the only file you change.

Check:

- every factual claim of the document against its source;
- that the diagnosis names the root cause, not a symptom;
- that the plan fixes the root cause in every case and at every site, and breaks nothing else: try to break it, through edge cases, error paths, concurrency, and callers the document does not mention;
- for a solution the document missed that is correct where its plan fails, complete where it falls short, or much simpler.

Keep the document's plan unless it fails these checks or such a solution exists. An option the document records as rejected by the user stays rejected, and the reason they gave constrains every solution you consider.

## Decisions

Settle by yourself every choice that the facts, the project's conventions and the user's recorded preferences settle. Put a decision to the user only when it hinges on their preference and every option carries a real cost, like breaking an interface, adding a dependency, or trading speed for simplicity; a missing fact is never a reason to ask. Raise all such decisions in one message once the investigation is done, each with its options, their costs, and your recommendation first. Wait for the answers, then verify the path they lead to like any other before writing it.

## The appended section

Never remove or reword anything already in the document. Append one section at its end, headed `## Settled path <YYYY-MM-DD>`, after any earlier such section.

**The plan holds** only when the document already names a single path with no open point, and that path passed every check. The section then states that the plan stands as written and needs no change, followed by what you checked to conclude so: the claims verified, the cases exercised, the experiments run and their outcome.

**Otherwise**, the section opens with the sentence "This section overrides anything above that conflicts with it.", then holds:

1. **Findings**: what the document got wrong or missed, each with its evidence: file and line, failing case, upstream behavior, experiment output.
2. **Rejected approaches**: each approach of the document you do not keep, with why it is incorrect or incomplete, from the evidence.
3. **Path forward**: the solution, why it works and what it covers that the rejected approaches miss; then the steps to implement it: the files and functions to change, the tests to write first and what they must show, and the check proving the work is done. A decision the user made in answer to your questions appears here as a fixed constraint, with their reason.

Write it with these rules:

- Give one path. No alternative, option, open question or deferred choice, and none of "consider", "optionally", "if you prefer" or "you could".
- Write the rationale as fact backed by evidence, not as a weighing of options.
- Write instructions for whoever implements the path, not a reply to the document's author.
- Point to what the document already states correctly instead of repeating it.

## Report

When done, give the user the document's absolute path, whether its plan holds or was replaced, and the finding that decided it, in a few lines.
