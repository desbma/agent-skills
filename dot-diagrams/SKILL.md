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

1. Run `<skill-dir>/dot-check name.dot`, where `<skill-dir>` is the directory you read this file from. It prints the defects, then the crossings between arrows, then the drawing's size. It exits with status 1 on defects. Set the layout engine and its options in the `.dot` file, not on the build's command line.
2. Look at the result: rasterize the SVG itself with `rsvg-convert name.svg -o <scratchpad>/name.png`, not `dot -Tpng`, which draws with Graphviz's own renderer and fonts. When its look depends on the page embedding it (for example a slide), screenshot that page with a headless browser instead. The PNG is for your own check, show the user the SVG. Zoom on dense areas and crop: images are scaled down before you see them, and a gap of a few points disappears in a full view. `rsvg-convert` zooms and crops in one command, with a negative offset and a page size in pixels after the zoom. For example, this takes the 1900 × 750px area at (1300, 350) of a 2× render:

   ```sh
   rsvg-convert -z 2 --left=-1300px --top=-350px --page-width=1900px --page-height=750px name.svg -o <scratchpad>/crop.png
   ```

Show the user a diagram once `dot-check` reports no defects, or say which remain and why.

## Layout and text

- Readability over completeness: show the main flow and leave details to the prose. Split into several diagrams rather than cramming one.
- **Untangle arrows first:** keep them short and straight, with as few crossings as possible. Curve an arrow when that untangles the drawing.
- Align boxes on shared rows and columns, as far as the other aims allow.
- Draw the nodes the user agreed on. When the layout would read better with nodes added, merged or duplicated, propose it rather than doing it.
- Labels are a few words. Label an edge only when its meaning is not obvious.
- Give each node role its own style. Add a legend only as a last resort.
- Draw boxes with rounded corners: set `node [shape=box, style=rounded]` once at the top of the file. A node or role that sets its own `style` replaces the whole list, so repeat `rounded` in it, as in `style="rounded,filled"`.
- Draw boxes as rectangles clearly wider than tall, about twice or more. Give a box room for its arrows by widening it or aiming them with ports.
- Leave a margin around the drawing with `pad=0.2` on the graph.
- Set `fontname="DejaVu Sans,sans-serif"` at the top of the file on `graph`, `node` and `edge`, unless the user or the page embedding the diagram needs another font: the graph's font does not carry over to nodes and edges. Keep text sizes the same across the project's diagrams.

## Graphviz behavior

- To fix an arrow end that stops short at a rounded corner or at the fold of a `note`, widen the box with `width`, or aim that end at the middle of the side facing the arrow with a compass port (`tailport=e`, `headport=w`). Aim an arrowhead meeting its box at a shallow angle the same way, at the left or right side when the arrow runs more across than up or down, at the top or bottom otherwise, then move the boxes farther apart if `dot-check` still reports it. In a `dot` layout, a port also reroutes the arrow, and can bend it. Corner ports (`ne`, `sw`, ...) sit on the square corner, off the drawn line. A port shared by two arrows stacks their heads.
- `samehead` and `sametail` on `constraint=false` edges can start or end an arrow away from its node.
- `dot` chooses the order within each row itself: `rank=same` fixes a row, but `group`, `weight` and invisible edges only nudge the order. When the drawing needs the order within rows set too, pin positions by hand with `neato`: `layout=neato`, `inputscale=72` for positions in points, `pos="x,y!"` on every node, `splines=line`, not `splines=true`, whose arrows detour around boxes and out of frames. Then:
  - `Layout type: "neato" not recognized` means its plugin is missing: Debian and Ubuntu ship it in its own package, `libgvplugin-neato-layout8`, for the user to install.
  - A frame hugs its nodes, ignores `margin`, and its title lands on them: pad it with two invisible corner nodes, `[shape=point, style=invis, width=0, pos="x,y!"]`, the same distance beyond its outer boxes on every side: 8pt, or 16pt when an arrow crosses the frame. Add 20pt more at the top when the frame has a title. `width=0` keeps them from taking the size set by the frame's `node [width=...]`.
  - Nested frames are not drawn: declare the inner frame on its own, and place its nodes inside the outer one.
  - A `label` or `xlabel` on a sloped arrow may be drawn across it: place it with `taillabel`, `labelangle` and `labeldistance` instead.
- Place boxes yourself: try a change and read what `dot-check` reports, rather than working out its effects in advance or running a scripted search over positions.

## Source

- Comment groups of nodes and layout tricks. No dead code, no attribute set to its default value.
