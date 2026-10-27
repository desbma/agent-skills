---
name: audit-skill-run
description: Audit recent runs of a skill from their session transcripts, and propose improvements to the skill.
argument-hint: "SKILL [NOTES]"
disable-model-invocation: true
---

# Audit skill run

Audit how the most recent runs of the skill named in the arguments went, from their session transcripts: usually those of the same day or hour. Notes after the skill name say what the user saw or what to focus on.

For each run, assess, among anything else that cost it:

- the wrong turns it took, and what led to each;
- whether its time was well spent;
- where its tokens went, and which were wasted;
- whether the skill's instructions were ambiguous, conflicting or misleading, and where the agent had to improvise.

You may use subagents.

Report your findings, and propose improvements to the skill's prose or helper scripts. Each proposal opens with the issues it fixes and roughly what the run would have saved in turns, time and tokens; the change comes after. Before proposing to change a passage, read its VCS history, so the change does not undo what an earlier one fixed.

**If the runs went well, say so, and propose nothing.** Do not suggest minor improvements for their own sake. A minor issue is acceptable when it comes from an exceptional case and fixing it would degrade more common ones.
