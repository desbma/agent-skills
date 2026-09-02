---
name: settle-discussion
description: Discuss a plan, decision, or idea point by point with the user, recording each settled decision in a memory file that serves as a decision log and as input for a future implementor agent.
argument-hint: "<TOPIC>"
disable-model-invocation: true
---

# Settle discussion

Interview the user relentlessly about every aspect of this until you reach a shared understanding. Walk down each branch of the decision tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing. Asking multiple questions at once is bewildering.

If a *fact* can be found by exploring the environment (filesystem, tools, etc.), look it up rather than asking the user. The *decisions*, though, are theirs — put each one to them and wait for their answer.

Do not act on it until the user confirms you have reached a shared understanding.

## Decision log

Keep a decision log in a single memory file of type `project` for the topic, following your memory system's format, and index it in `MEMORY.md`. It is the durable record of the discussion: a log of every decision with its reasons, written for a future implementor agent who lacks this conversation.

Update it between questions: after each of the user's answers, before asking the next question, record the outcome of the point just discussed.

## Recording rules

- A direct, settled answer is approval: record the decision, with the reasons given.
- If the user's message contains questions, their decision is not settled — treat the exchange as a discussion, not an interview. Answer them, keep discussing, and once it converges, state the decision as you would record it and ask them to confirm before writing it.
- Record a point as decided only on the user's explicit approval. Leaving one point of a message unanswered is not approving that point.
- A point that ends without approval is recorded as **undecided**, with the options considered and where the discussion left off.
