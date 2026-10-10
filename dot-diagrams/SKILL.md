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

After every change, run `make`, then:

1. Run `<skill-dir>/dot-check name.dot`, where `<skill-dir>` is the directory you read this file from. It lists the defects: arrow ends off their node's drawn outline, arrows through boxes, labels touching an arrow, a box, a frame or another label. Then it lists the crossings between arrows, and prints the drawing's size. It exits with status 1 on defects. It lays the `.dot` file out again with `dot`, without the build's command line options: set the layout engine and its options in the file.
2. Look at the result: rasterize the SVG with `rsvg-convert name.svg -o <scratchpad>/name.png`, or, when its look depends on the page embedding it (for example a slide), screenshot that page with a headless browser. The PNG is for your own check, show the user the SVG. Zoom on dense areas, with `rsvg-convert -z 2` and a crop: a gap of a few points disappears in a full view.

Show the user a diagram once `dot-check` reports no defects, or say which remain and why.

## Layout and text

- Readability over completeness: show the main flow and leave details to the prose. Split into several diagrams rather than cramming one.
- **Tangled arrows are the first thing that makes a diagram unreadable.** Keep arrows short and straight, with as few crossings as possible. Curve an arrow when that untangles the drawing.
- Align boxes on shared rows and columns, as far as the other aims allow.
- Draw the nodes the user agreed on. When the layout would read better with nodes added, merged or duplicated, propose it rather than doing it.
- Labels are a few words. Label an edge only when its meaning is not obvious.
- Give each node role its own style. Add a legend only as a last resort.
- Keep fonts and text sizes the same across the project's diagrams. Use the Graphviz default font and size unless the context needs others, then set them once at the top of the file, not on single nodes or edges.

## Graphviz behavior

- Graphviz ends an arrow on a node's polygon, even where the drawing departs from it: the corners of `style=rounded` boxes, the fold of a `note`. An arrow landing near such a corner stops short of the line.
- `samehead` and `sametail` on `constraint=false` edges can start or end an arrow away from its node.
- `dot` places nodes in rows and columns of its own. When they are not the ones you want, pin positions by hand with `neato` rather than piling up `dot` workarounds: `layout=neato`, `inputscale=72` for positions in points, `pos="x,y!"` on every node, `splines=line`. Then:
  - A frame hugs its nodes and its title lands on them: widen it with an invisible node in its corner.
  - Nested frames are not drawn.
  - A `label` or `xlabel` on a sloped arrow may be drawn across it: place it with `taillabel`, `labelangle` and `labeldistance` instead.
- Place boxes yourself: a scripted search over positions burns CPU without reaching a usable layout.

## Source

- Comment groups of nodes and layout tricks. No dead code, no attribute set to its default value.
