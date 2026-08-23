# Agent skills

Personal [coding agent skills](https://agentskills.io/).

---

**This repository contains personal tools that I publish for sharing, documentation and convenience.**

**They may or may not work for your use case, and little effort has been made to support systems and workflows other than the ones I use.**

---

## General

- Skills are agent-agnostic.
- Some skills start `pi` agent subprocesses for reviews, regardless of the main agent.
- Some skills hardcode the model used for reviews. I had the best results with OpenAI's GPT.

## Content

- [`implem-brake`](implem-brake/SKILL.md): Forbid the agent from touching project files until explicitly allowed again, to discuss a change without it jumping to implementation. Invoked manually with `on`/`off`.
- [`review-auto-loop`](review-auto-loop/SKILL.md): Run waves of parallel chains of reviews with external reviewer agents, to balance thoroughness and speed. The user gets presented a report of all findings after each wave, each assessed by the main agent, and can choose which to apply.
- Per-domain review skills (called by the `review-auto-loop` skill):
  - [`review-correctness`](review-correctness/SKILL.md): Look for bugs, logic holes, incomplete changes, hidden quadratic complexity, etc.
  - [`review-readability`](review-readability/SKILL.md): Simplify code, use idiomatic patterns, counter model tendency to write overly verbose code.
  - [`review-tests`](review-tests/SKILL.md): Improve tests, find untested areas or useless tests.
  - [`review-docs`](review-docs/SKILL.md): Find docs or comments that are stale, missing, or breaking written conventions.
- [`rust-project-maintenance`](rust-project-maintenance/SKILL.md): Run mechanical maintenance tasks for Rust projects, pausing for review after each change.
- [`settle-discussion`](settle-discussion/SKILL.md): Variant of the [`grill-me` skill](https://github.com/mattpocock/skills/blob/170ad48655825783d0193e850e31a9aac957bb95/skills/productivity/grilling/SKILL.md) that keeps the state of the discussion in the agent's memory. Ideal for fleshing out an idea into a spec.
- [`wait-what`](wait-what/SKILL.md): Ask for the last message to be pitched again in plain English, to counter the cryptic and overly compressed language Opus 5 tends to use. Variant of the [`wait-what` skill](https://github.com/mattpocock/skills/blob/50777fcc0982d5867997a75a1e0731b9daac94eb/skills/productivity/wait-what/SKILL.md).

## License

[MIT](LICENSE).
