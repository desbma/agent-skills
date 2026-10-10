---
name: dot-diagrams
description: Conventions for Graphviz .dot diagrams and their SVG renders. Load before creating or changing any .dot file, however small the change and even in passing during an unrelated task, and when the user asks for a diagram, schema or sketch of an architecture, workflow or data flow.
---

# Dot diagrams

## Build

- Edit the `.dot` source only, the SVG is a build output never edited by hand.
- Generate SVGs with `make`, using the project's existing Makefile if any, otherwise one next to the `.dot` files:

  ```make
  all: $(patsubst %.dot,%.svg,$(wildcard *.dot))

  %.svg: %.dot
  	dot -Tsvg $< -o $@
  ```

- Gitignore the SVG, unless a Markdown file hosted on a public forge embeds it: then commit it, so the forge renders it inline.

## Check

After every change, run `make` and look at the result: rasterize the SVG with `rsvg-convert name.svg -o <scratchpad>/name.png`, or, when its look depends on the page embedding it (for example a slide), screenshot that page with a headless browser.

## Layout and text

- Readability over completeness: show the main flow and leave details to the prose. Split into several diagrams rather than cramming one.
- Arrange nodes in rows and columns, with straight edges.
- Labels are a few words. Label an edge only when its meaning is not obvious.
- Give each node role its own style. Add a legend only as a last resort.
- Keep fonts and text sizes the same across the project's diagrams. Use the Graphviz default font and size unless the context needs others, then set them once at the top of the file, not on single nodes or edges.

## Source

- Comment groups of nodes and layout tricks. No dead code, no attribute set to its default value.
