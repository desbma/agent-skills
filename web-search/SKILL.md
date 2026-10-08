---
name: web-search
description: Search the web and get a cited answer. Use for current information, or facts beyond your training data or that you are unsure of.
---

# web-search

Run `<skill-dir>/web-search QUERY`, where `<skill-dir>` is the directory you read this file from. The script hands the query to a search agent, which runs its own web searches, reads the pages and answers in 5 to 20 seconds. Write the query as a question to that agent, with the context it needs, not as search keywords: `'What changed in the latest ruff release?'` rather than `'ruff changelog'`.

Do not search for what local files or commands can answer.

The script prints a JSON object:

- `answer`: the answer, with inline links to its sources.
- `sources`: the pages backing the answer, each with `url`, `title` and `excerpt`. An excerpt is the search model's paraphrase, not a quote: open the page when you need its exact wording.
- `searches`: what the search model did, in order: a `search` with its `queries` and the URLs it `consulted`, or an `open_page` or `find_in_page` on a `url`.

A `BorrowKeyError` means the Codex login could not be loaded or refreshed: report its message to the user.
