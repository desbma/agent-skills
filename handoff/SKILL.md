---
name: handoff
description: Summarize the conversation into one self-contained handoff document per divergent path, so a fresh agent can resume any of them without loss.
argument-hint: "[WHAT_TO_RECORD]"
disable-model-invocation: true
---

# Handoff

Write markdown handoff documents that let a fresh agent resume this work with no access to this conversation.

## One document per path

Split the conversation into the lines of work a fresh agent could pick up on its own, and write one document per line: two unrelated bugs discussed in the conversation give two documents. Changes that belong in the same commit are one line of work and share a single document, whether they are competing fixes for one bug or closely related fixes for several. A conversation that only ever followed one line yields one document.

## Files

Write them in the handoff dir, named `handoff-<date>[-<rank>]-<slug>.md`. `<date>` is when the set of sibling documents was first written, as `YYYYMMDDHHMM`, and every sibling shares it, including one added later. `<slug>` is a few kebab-case words naming the path: a fix for a crash on login, first written on 6 October 2026 at 14:30, gives `handoff-202610061430-fix-login-crash.md`.

When some paths depend on others, every document carries a `<rank>`, its position in an order that handles each path after those it depends on. Fixes for a missing index, a login crash, a login timeout and a logout redirect, where the two login fixes share a commit that needs the index and the redirect fix builds on them, give `handoff-202610061430-1-add-session-index.md`, `handoff-202610061430-2-fix-login-crash-and-timeout.md` and `handoff-202610061430-3-fix-logout-redirect.md`. When all paths are independent, the documents carry no rank.

When a document for the path already exists, whatever its rank, update it in place only while its path holds work left to do: it has to hold the state of the code and of the proposal as they stand now, so an agent resuming from it never works from a stale one. Once the change it describes is implemented, do not update it; ask the user whether to delete it instead. When its rank changes, rename it, and update the pointers its siblings hold to it.

When you are done, give the user one line per document, in rank order: its absolute path, and what it carries in a few words.

## Content

A document is a snapshot of where its path stands, not a log of how it got there: the problem, the state of the code, and the fix or plan the conversation landed on, which takes the bulk of it. Follow with the open points, the first step on resuming, and a few sentences at most on the options dropped along the way and why. Each document stands alone — context shared between paths is written out in full in every one of them, with a one-line pointer to its siblings, naming the ones it depends on.

## Rules

- Do not narrate the conversation, and never record a point the user did not settle as decided.
- Do not duplicate what an artifact already holds — a spec, an issue, a commit description, a diff, code in the repository. Reference it by path or URL.
- Do not restate the project's conventions or standing instructions: the next agent reads them from `AGENTS.md`, `CLAUDE.md` and the repository itself.

Arguments, when given, say which paths to record, or what the next session focuses on.
