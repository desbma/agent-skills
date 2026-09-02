---
name: handoff
description: Summarize the conversation into one self-contained handoff document per divergent path, so a fresh agent can resume any of them without loss.
argument-hint: "[WHAT_TO_RECORD]"
disable-model-invocation: true
---

# Handoff

Write markdown handoff documents that let a fresh agent resume this work with no access to this conversation.

## One document per path

Split the conversation into the lines of work a fresh agent could pick up on its own, and write one document per line: two unrelated bugs discussed in the conversation give two documents. Competing fixes for the same bug are one line of work, and share a single document. A conversation that only ever followed one line yields one document.

## Files

Write them in the exchange dir, named `handoff-<slug>.md`, where `<slug>` is a few kebab-case words naming the path: a fix named "fix A" for a crash on login gives `handoff-fix-A-login-crash.md`.

When a document for the path already exists, update it in place: it has to hold the state of the code and of the proposal as they stand now, so an agent resuming from it never works from a stale one.

When you are done, give the user one line per document: its absolute path, and what it carries in a few words.

## Content

A document is a snapshot of where its path stands, not a log of how it got there: the problem, the state of the code, and the fix or plan the conversation landed on, which takes the bulk of it. Follow with the open points, the first step on resuming, and a few sentences at most on the options dropped along the way and why. Each document stands alone — context shared between paths is written out in full in every one of them, with a one-line pointer to its siblings.

## Rules

- Do not narrate the conversation, and never record a point the user did not settle as decided.
- Do not duplicate what an artifact already holds — a spec, an issue, a commit description, a diff, code in the repository. Reference it by path or URL.
- Do not restate the project's conventions or standing instructions: the next agent reads them from `AGENTS.md`, `CLAUDE.md` and the repository itself.

Arguments, when given, say which paths to record, or what the next session focuses on.
