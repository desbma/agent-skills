#!/usr/bin/env python3
"""Tests for the diagram layout checker."""

import contextlib
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Generator
from importlib.machinery import ModuleSpec, SourceFileLoader
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("dot-check")
_loader = SourceFileLoader("dot_check", str(SCRIPT))
dot_check = importlib.util.module_from_spec(ModuleSpec("dot_check", _loader))
_loader.exec_module(dot_check)

# Pinned layout, positions in points, in the font the skill sets
HEADER = (
    "layout=neato; inputscale=72; splines=line; node [shape=box];"
    'fontname="DejaVu Sans,sans-serif"; node [fontname="DejaVu Sans,sans-serif"];'
    'edge [fontname="DejaVu Sans,sans-serif"];'
)
# Line printed when Graphviz has no neato layout
NEATO_WARNING = "Warning: the neato layout is missing, Debian and Ubuntu ship it in the libgvplugin-neato-layout8 package"


def without_numbers(lines: list[str]) -> list[str]:
    """Replace the numbers in LINES by N."""
    return [re.sub(r"\d+(\.\d+)?", "N", line) for line in lines]


def messages(findings: list["dot_check.Finding"]) -> list[str]:
    """Return the messages of FINDINGS, without their positions."""
    return [message for message, _ in findings]


def positions(findings: list["dot_check.Finding"]) -> list[tuple[int, int]]:
    """Return the positions of FINDINGS, rounded to the point."""
    return [(round(x), round(y)) for _, (x, y) in findings]


class CheckTest(unittest.TestCase):
    """Finding layout problems in a rendered diagram."""

    def check(self, body: str) -> "dot_check.Report":
        """Lay out a pinned digraph with BODY, and return its report."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.dot"
            path.write_text(f"digraph {{ {HEADER} {body} }}")
            return dot_check.check(*dot_check.render(path))

    def assert_no_defects(self, body: str) -> None:
        """Assert that a pinned digraph with BODY has no defect."""
        self.assertEqual(messages(self.check(body).defects), [])

    def test_clean(self) -> None:
        """Report nothing on attached arrows, at either end, with a label clear of everything."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="200,0!"]; c [pos="200,-100!"];
            a -> b [taillabel="lab", labelangle=30, labeldistance=5];
            a -> c [dir=both];
        """)
        self.assertEqual(messages(report.defects), [])
        self.assertEqual(messages(report.crossings), [])

    def test_formatted(self) -> None:
        """Take the differently formatted runs of a label as one line."""
        self.assert_no_defects("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [taillabel=<<b>bold</b> plain>, labelangle=30, labeldistance=5];
        """)

    def test_several_graphs(self) -> None:
        """Refuse a file holding more than one graph."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.dot"
            path.write_text("graph { a; }\ngraph { b; }\n")
            with self.assertRaisesRegex(ValueError, "more than one graph"):
                dot_check.render(path)

    def test_size(self) -> None:
        """Measure the SVG, its margin, scale and rotation included."""
        for attributes, size in (
            ("", (262, 144)),
            ('size="2,2";', (144, 79)),
            ("rotate=90;", (144, 262)),
        ):
            with self.subTest(attributes):
                report = self.check(f'{attributes} a [pos="0,0!"]; b [pos="200,100!"];')
                self.assertEqual(report.size, size)

    def test_thick(self) -> None:
        """Find the tip of an arrowhead wider than long."""
        self.assert_no_defects("""
            a [pos="0,0!"]; b [pos="200,0!"];
            a -> b [penwidth=12];
        """)

    def test_thick_border(self) -> None:
        """Measure arrow ends and arrowhead angles against the edge of a thick outline, not its middle."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="200,0!", penwidth=5];
            a -> b;
            c [pos="0,-100!", penwidth=5]; d [pos="200,-100!"];
            c -> d [tailclip=false];
            e [pos="0,-167!", width=2]; f [pos="200,-300!", width=2, penwidth=5];
            e -> f;
        """)
        self.assertEqual(
            without_numbers(messages(report.defects)),
            [
                "c -> d: tail Npt off the outline of c",
                "e -> f: head meets the outline of f at N°",
            ],
        )

    def test_thick_label_border(self) -> None:
        """Measure arrow ends against the width of their outline's own line, not of a thicker one in its label."""
        report = self.check("""
            a [pos="0,0!", width=2, height=1, style=rounded,
               label=<<table border="3"><tr><td>a</td></tr></table>>];
            b [pos="300,125!", width=2, height=1];
            a -> b;
        """)
        self.assertEqual(
            without_numbers(messages(report.defects)),
            ["a -> b: tail Npt off the outline of a, at a rounded corner"],
        )

    def test_transparent_border(self) -> None:
        """Measure arrow ends against the fill of a box whose thick outline is transparent."""
        report = self.check("""
            a [pos="0,0!"];
            b [pos="200,0!", penwidth=5, color=transparent, style=filled, fillcolor=lightgray];
            a -> b;
        """)
        self.assertEqual(
            without_numbers(messages(report.defects)),
            ["a -> b: head Npt off the outline of b"],
        )

    def test_rounded_corner(self) -> None:
        """Report arrow ends on the square corner of a rounded box, naming the corner only there."""
        report = self.check("""
            node [style="rounded,filled"];
            a [pos="0,0!"]; b [pos="200,100!"]; c [pos="0,100!"];
            a -> b [tailport=ne, headport=sw];
            c -> b [tailclip=false];
            d [pos="0,-200!", penwidth=5]; e [pos="200,-67!", penwidth=5];
            d -> e;
        """)
        self.assertEqual(
            without_numbers(messages(report.defects)),
            [
                "a -> b: tail Npt off the outline of a, at a rounded corner",
                "a -> b: head Npt off the outline of b, at a rounded corner",
                "c -> b: tail Npt off the outline of c",
                "d -> e: tail Npt off the outline of d, at a rounded corner",
                "d -> e: head Npt off the outline of e, at a rounded corner",
            ],
        )

    def test_shallow_arrowhead(self) -> None:
        """Report arrowheads, at the head or the tail, meeting their box almost along a side."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="200,30!"];
            a -> b [headport=n];
            c [pos="0,-200!"]; d [pos="200,-170!"];
            d -> c [dir=back, tailport=n];
        """)
        self.assertEqual(
            without_numbers(messages(report.defects)),
            [
                "a -> b: head meets the outline of b at N°",
                "d -> c: tail meets the outline of d at N°",
            ],
        )
        self.assertEqual(positions(report.defects), [(231, 4), (231, 204)])

    def test_steep_arrowhead(self) -> None:
        """Report an arrowhead meeting its box at 35°, but not one at 45°."""
        report = self.check("""
            a [pos="36,133!"]; b [pos="200,0!"];
            a -> b [headport=n];
            c [pos="259,159!"]; d [pos="400,0!"];
            c -> d [headport=n];
        """)
        self.assertEqual(
            messages(report.defects), ["a -> b: head meets the outline of b at 35.0°"]
        )

    def test_corner_arrowhead(self) -> None:
        """Measure an arrowhead meeting a square corner against the side it lies along."""
        self.assert_no_defects("""
            a [pos="400,18!"]; b [pos="200,0!"]; c [pos="0,-18!"];
            a -> b [headport=ne];
            c -> b [headport=sw];
        """)

    def test_collapsed_arrowhead(self) -> None:
        """Skip the angle of arrowheads drawn at zero size."""
        self.assert_no_defects("""
            a [pos="0,0!"]; b [pos="200,0!"];
            a -> b [dir=both, arrowsize=0];
        """)

    def test_transparent_arrowhead(self) -> None:
        """Skip arrowheads drawn in a transparent color."""
        self.assert_no_defects("""
            a [pos="0,0!"]; b [pos="200,30!"];
            a -> b [headport=n, color="transparent:red"];
        """)

    def test_arrowheads_overlap(self) -> None:
        """Report arrowheads drawn over or against each other, but neither close ones still apart nor arrows starting from the same point."""
        report = self.check("""
            a [pos="140,0!"]; b [pos="0,90!"]; c [pos="250,90!"];
            b -> c; a -> c [headport=w];
            b -> a [tailport=e];
            d [pos="0,-200!"]; e [pos="0,-280!"]; f [pos="300,-240!"];
            d -> f; e -> f;
            g [pos="0,-400!"]; h [pos="84,-400!"];
            g -> h [dir=both, arrowsize=2];
        """)
        self.assertEqual(
            messages(report.defects),
            [
                "a -> c: head overlaps the head of b -> c",
                "g -> h: tail overlaps the head of g -> h",
            ],
        )

    def test_note_fold(self) -> None:
        """Report an arrow leaving a note through its folded corner."""
        report = self.check("""
            a [pos="0,0!", shape=note]; b [pos="300,200!"];
            a -> b;
        """)
        self.assertEqual(
            without_numbers(messages(report.defects)),
            ["a -> b: tail Npt off the outline of a"],
        )

    def test_flat_arrowheads(self) -> None:
        """Find the tips of arrowheads ending in a flat side or an open line."""
        self.assert_no_defects("""
            a [pos="0,0!"]; b [pos="300,300!"]; c [pos="300,0!"];
            a -> b [dir=both, arrowtail=crow, arrowhead=box];
            a -> c [dir=both, arrowtail=curve, arrowhead=tee];
        """)

    def test_sections(self) -> None:
        """Find the end of an arrow drawn in successive colors."""
        self.assert_no_defects("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [dir=none, color="red;0.5:blue"];
        """)

    def test_compound(self) -> None:
        """Measure the ends of arrows clipped to frames against the frames."""
        self.assert_no_defects("""
            layout=dot; compound=true;
            subgraph cluster_a { a; } subgraph cluster_b { b; }
            a -> b [ltail=cluster_a, lhead=cluster_b];
        """)

    def test_compound_in_frame(self) -> None:
        """Report an arrowhead clipped to a frame against the frame around it."""
        report = self.check("""
            layout=dot; compound=true;
            subgraph cluster_outer { subgraph cluster_inner { a; } }
            a -> b [ltail=cluster_inner, dir=back];
        """)
        self.assertEqual(
            messages(report.defects), ["a -> b: tail touches frame cluster_outer"]
        )

    def test_inside(self) -> None:
        """Report an arrow starting from the middle of its box."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="200,0!"];
            a -> b [tailclip=false];
        """)
        self.assertEqual(
            without_numbers(messages(report.defects)),
            ["a -> b: tail Npt off the outline of a"],
        )
        self.assertEqual(positions(report.defects), [(31, 22)])

    def test_unbordered(self) -> None:
        """Skip invisible arrows, and the ends of arrows on nodes drawn without an outline, inside a frame or not."""
        self.assert_no_defects("""
            a [pos="0,0!"]; b [pos="200,0!"];
            w [pos="100,100!", shape=point, style=invis];
            h [pos="200,100!", shape=plain, label=<<table><tr><td>h</td></tr></table>>];
            subgraph cluster_x {
                j [shape=point, style=invis, width=0, pos="60,60!"];
                k [shape=point, style=invis, width=0, pos="140,140!"];
            }
            a -> w -> h;
            a -> b [style=invis, tailclip=false];
            a -> b [color=transparent, tailclip=false];
        """)

    def test_through(self) -> None:
        """Report an arrow passing through a box other than its ends."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="150,0!"]; c [pos="300,0!"];
            a -> c;
        """)
        self.assertEqual(messages(report.defects), ["a -> c: passes through b"])

    def test_through_frame(self) -> None:
        """Report an arrow passing through a frame, but not one leaving it once."""
        report = self.check("""
            subgraph cluster_x {
                m [pos="100,0!"];
                j [shape=point, style=invis, width=0, pos="60,-30!"];
                k [shape=point, style=invis, width=0, pos="140,50!"];
            }
            p [pos="-50,35!"]; q [pos="250,35!"];
            p -> q; m -> p;
        """)
        self.assertEqual(
            messages(report.defects), ["p -> q: passes through frame cluster_x"]
        )
        self.assertEqual(positions(report.defects), [(141, 22)])

    def test_frame_in_frame(self) -> None:
        """Count a box drawn inside a frame as inside it, though declared in another frame."""
        self.assert_no_defects("""
            subgraph cluster_outer {
                j [shape=point, style=invis, width=0, pos="-60,-60!"];
                k [shape=point, style=invis, width=0, pos="400,60!"];
            }
            subgraph cluster_inner {
                m [pos="200,0!"];
                l [shape=point, style=invis, width=0, pos="157,-34!"];
                n [shape=point, style=invis, width=0, pos="243,34!"];
            }
            p [pos="200,-150!"];
            p -> m;
        """)

    def test_frame_corner(self) -> None:
        """Count an arrow leaving its frame through a corner once."""
        self.assert_no_defects("""
            subgraph cluster_x {
                m [pos="0,0!"];
                j [shape=point, style=invis, width=0, pos="-50,-50!"];
                k [shape=point, style=invis, width=0, pos="50,50!"];
            }
            p [pos="200,200!"]; m -> p;
        """)

    def test_out_of_frame(self) -> None:
        """Report an arrow leaving its frame and coming back."""
        report = self.check("""
            splines=true;
            subgraph cluster_x {
                a [pos="0,0!"]; m [pos="100,0!"]; b [pos="200,0!"];
                j [shape=point, style=invis, width=0, pos="-40,-23!"];
                k [shape=point, style=invis, width=0, pos="240,23!"];
            }
            a -> b;
        """)
        self.assertEqual(
            messages(report.defects), ["a -> b: leaves and re-enters frame cluster_x"]
        )

    def test_out_of_frame_to_outside(self) -> None:
        """Report an arrow to a box outside its frame leaving it more than once."""
        report = self.check("""
            splines=true;
            subgraph cluster_x {
                a [pos="0,0!"]; m [pos="100,0!"];
                j [shape=point, style=invis, width=0, pos="-40,-23!"];
                k [shape=point, style=invis, width=0, pos="340,23!"];
            }
            b [pos="400,0!"];
            a -> b;
        """)
        self.assertEqual(
            messages(report.defects), ["a -> b: leaves and re-enters frame cluster_x"]
        )

    def test_multicolored_out_of_frame(self) -> None:
        """Count a multicolored arrow leaving its frame once, straight or sloped."""
        self.assert_no_defects("""
            subgraph cluster_x {
                a [pos="0,0!"];
                j [shape=point, style=invis, width=0, pos="-40,-30!"];
                k [shape=point, style=invis, width=0, pos="40,30!"];
            }
            b [pos="150,150!"]; c [pos="0,-150!"];
            a -> b [color="red:blue"]; a -> c [color="red:blue:green"];
        """)

    def test_transparent_frame(self) -> None:
        """Skip frames drawn in a transparent color."""
        self.assert_no_defects("""
            subgraph cluster_x {
                color=transparent;
                m [pos="100,0!"]; k [shape=point, style=invis, width=0, pos="100,60!"];
            }
            p [pos="-50,40!"]; q [pos="250,40!"];
            p -> q;
        """)

    def test_empty_subgraphs(self) -> None:
        """Skip frames and subgraphs holding no node."""
        self.assert_no_defects("layout=dot; subgraph cluster_x {} subgraph y {} a;")

    def test_box_on_frame(self) -> None:
        """Report boxes against a frame line, from inside or outside, but not boxes 8pt clear of it."""
        report = self.check("""
            subgraph cluster_x {
                j [shape=point, style=invis, width=0, pos="-100,-100!"];
                k [shape=point, style=invis, width=0, pos="300,100!"];
                a [pos="-73,0!"]; b [pos="100,-74!"];
            }
            c [pos="329,0!"];
        """)
        self.assertEqual(
            messages(report.defects),
            ["a: touches frame cluster_x", "c: touches frame cluster_x"],
        )
        self.assertEqual(positions(report.defects), [(4, 122), (406, 122)])

    def test_arrowhead_on_frame(self) -> None:
        """Report an arrowhead too close to a frame line, but not one entering a frame padded 16pt."""
        report = self.check("""
            subgraph cluster_x {
                m [pos="0,0!"];
                j [shape=point, style=invis, width=0, pos="-35,-31!"];
                k [shape=point, style=invis, width=0, pos="35,31!"];
            }
            subgraph cluster_y {
                n [pos="300,0!"];
                l [shape=point, style=invis, width=0, pos="257,-34!"];
                o [shape=point, style=invis, width=0, pos="343,34!"];
            }
            p [pos="0,-150!"]; q [pos="300,-150!"];
            p -> m; q -> n;
        """)
        self.assertEqual(
            messages(report.defects), ["p -> m: head touches frame cluster_x"]
        )

    def test_end_on_frame(self) -> None:
        """Measure the ends of arrows on invisible points against the frame line under them."""
        report = self.check("""
            subgraph cluster_x {
                m [pos="0,0!"];
                j [shape=point, style=invis, width=0, pos="-60,-40!"];
                k [shape=point, style=invis, width=0, pos="60,40!"];
            }
            e [shape=point, style=invis, width=0, pos="-60.5,20!"];
            f [shape=point, style=invis, width=0, pos="-62.5,-20!"];
            g [shape=point, style=invis, width=0, pos="60.5,0!"];
            p [pos="-200,20!"]; q [pos="-200,-20!"]; r [pos="200,0!"];
            p -> e; q -> f [dir=none]; g -> r [dir=back];
        """)
        self.assertEqual(
            without_numbers(messages(report.defects)),
            ["q -> f: head Npt off the outline of frame cluster_x"],
        )

    def test_through_frame_to_its_line(self) -> None:
        """Report an arrow crossing a frame to end on its far line."""
        report = self.check("""
            subgraph cluster_x {
                j [shape=point, style=invis, width=0, pos="-60,-60!"];
                k [shape=point, style=invis, width=0, pos="60,60!"];
            }
            a [shape=point, style=invis, width=0, pos="-60,-30!"];
            p [pos="200,-30!"];
            p -> a;
        """)
        self.assertEqual(
            messages(report.defects), ["p -> a: passes through frame cluster_x"]
        )

    def test_text_by_frame(self) -> None:
        """Leave the end of an arrow on bare text near a frame line unattached."""
        self.assert_no_defects("""
            subgraph cluster_x {
                j [shape=point, style=invis, width=0, pos="-100,-50!"];
                k [shape=point, style=invis, width=0, pos="100,50!"];
                t [shape=plain, label="foo", pos="-86,0!"];
            }
            b [pos="-250,0!"];
            t -> b;
        """)

    def test_end_between_frames(self) -> None:
        """Attach an arrow end to the nearest of two frame lines, not the first declared."""
        self.assert_no_defects("""
            subgraph cluster_a {
                j [shape=point, style=invis, width=0, pos="-100,-50!"];
                k [shape=point, style=invis, width=0, pos="0,50!"];
            }
            subgraph cluster_b {
                l [shape=point, style=invis, width=0, pos="4,-50!"];
                m [shape=point, style=invis, width=0, pos="104,50!"];
            }
            g [shape=point, style=invis, width=0, pos="4,-50.5!"];
            r [pos="4,-150!"];
            g -> r;
        """)

    def test_gradient(self) -> None:
        """Report an arrow passing through boxes filled with gradients."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            c [pos="100,0!", style=filled, fillcolor="red:blue"];
            d [pos="200,0!", style=radial, fillcolor="red:blue"];
            a -> b;
        """)
        self.assertEqual(
            messages(report.defects),
            ["a -> b: passes through c", "a -> b: passes through d"],
        )

    def test_transparent_node(self) -> None:
        """Let arrows pass through nodes drawn in transparent colors."""
        self.assert_no_defects("""
            a [pos="0,0!"]; b [pos="300,0!"]; c [pos="150,0!", color=transparent, label=""];
            a -> b;
        """)

    def test_through_table(self) -> None:
        """Report an arrow passing through the borders of an HTML table."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            c [pos="150,0!", shape=plain, label=<<table><tr><td>c</td></tr></table>>];
            a -> b;
        """)
        self.assertEqual(messages(report.defects), ["a -> b: passes through c"])

    def test_parallel(self) -> None:
        """Follow each line of a multicolored arrow on its own."""
        self.assert_no_defects("""
            splines=true;
            a [pos="0,0!"]; b [pos="300,0!"]; c [pos="150,0!"];
            a -> b [color="red:blue"];
        """)

    def test_crossing(self) -> None:
        """Count crossing arrows, but not arrows meeting at a shared end."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="0,200!"]; c [pos="300,0!"]; d [pos="300,200!"];
            a -> d; b -> c;
            e [pos="0,400!"]; f [pos="300,400!"];
            e -> f [headport=w, dir=none]; b -> f [headport=w, dir=none];
        """)
        self.assertEqual(messages(report.defects), [])
        self.assertEqual(messages(report.crossings), ["a -> d crosses b -> c"])

    def test_positions(self) -> None:
        """Place findings in points from the top left corner of the SVG, its margin, scale and rotation included, whatever the graph's id and class."""
        for attributes, position in (
            # Graphviz accepts the pinning mark of a point on the pad, and ignores it
            ('pad="0.2,0.1!"', (191.4, 125.2)),
            ('size="2,2"', (72.0, 48.5)),
            ("rotate=90", (122.0, 181.0)),
            ('id="overview"', (181.0, 122.0)),
            ('class="overview"', (181.0, 122.0)),
        ):
            with self.subTest(attributes):
                report = self.check(f"""
                    {attributes};
                    a [pos="0,0!"]; b [pos="0,200!"]; c [pos="300,0!"]; d [pos="300,200!"];
                    a -> d; b -> c;
                """)
                self.assertEqual(
                    [
                        (message, (round(x, 1), round(y, 1)))
                        for message, (x, y) in report.crossings
                    ],
                    [("a -> d crosses b -> c", position)],
                )

    def test_regular_edge_label(self) -> None:
        """Report an ordinary label drawn across its sloped arrow."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,200!"];
            a -> b [label="across"];
        """)
        self.assertEqual(
            messages(report.defects), ['label "across" of a -> b: touches a -> b']
        )

    def test_label_on_line(self) -> None:
        """Report a label drawn across its own arrow."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [taillabel="across", labelangle=0, labeldistance=10];
        """)
        self.assertEqual(
            messages(report.defects), ['label "across" of a -> b: touches a -> b']
        )
        self.assertEqual(positions(report.defects), [(158, 23)])

    def test_transparent_label(self) -> None:
        """Skip labels drawn in a transparent color."""
        self.assert_no_defects("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [taillabel="hidden", labelfontcolor=transparent, labelangle=0, labeldistance=10];
        """)

    def test_label_on_arrowhead(self) -> None:
        """Report a label drawn over an arrowhead."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [arrowsize=2, headlabel="x", labelangle=0, labeldistance=1];
        """)
        self.assertEqual(
            messages(report.defects), ['label "x" of a -> b: touches a -> b']
        )

    def test_label_of_transparent(self) -> None:
        """Report a label of a transparent arrow drawn over a box."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [color=transparent, taillabel="shown", labelangle=180, labeldistance=2.7];
        """)
        self.assertEqual(
            messages(report.defects), ['label "shown" of a -> b: touches a']
        )

    def test_node_text(self) -> None:
        """Report the text of a node without outline drawn over an arrow, but not over its own arrows."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"]; c [pos="150,0!", shape=plain, label="bare"];
            d [pos="0,100!", shape=plain]; e [pos="300,100!", shape=plain];
            a -> b; d -> e;
        """)
        self.assertEqual(
            messages(report.defects), ['label "bare" of c: touches a -> b']
        )

    def test_external_label(self) -> None:
        """Report the external label of a box drawn over the box's own arrow."""
        report = self.check("""
            a [pos="0,0!", xlabel="outer"]; b [pos="-200,100!"];
            a -> b;
        """)
        self.assertIn('label "outer" of a: touches a -> b', messages(report.defects))

    def test_label_on_box(self) -> None:
        """Report a label drawn over a box."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [taillabel="boxed", labelangle=0, labeldistance=0.5];
        """)
        self.assertEqual(
            messages(report.defects),
            [
                'label "boxed" of a -> b: touches a -> b',
                'label "boxed" of a -> b: touches a',
            ],
        )

    def test_label_in_ellipse(self) -> None:
        """Report a label drawn inside an ellipse."""
        report = self.check("""
            node [shape=ellipse, width=2, height=1];
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [taillabel="hidden", labelangle=180, labeldistance=7.2];
        """)
        self.assertEqual(
            messages(report.defects), ['label "hidden" of a -> b: touches a']
        )

    def test_label_on_label(self) -> None:
        """Report labels drawn over each other."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"]; c [pos="0,60!"]; d [pos="300,60!"];
            a -> b [taillabel="one", labelangle=60, labeldistance=3.5];
            c -> d [taillabel="two", labelangle=-60, labeldistance=3.5];
        """)
        self.assertEqual(
            messages(report.defects),
            ['label "one" of a -> b: touches label "two" of c -> d'],
        )

    def test_label_on_frame(self) -> None:
        """Report a label drawn over a frame line."""
        report = self.check("""
            subgraph cluster_x {
                label="frame"; x [pos="316,0!"]; k [pos="450,100!", style=invis];
                j [shape=point, style=invis, width=0, pos="273,-30!"];
            }
            e [pos="0,0!"];
            e -> x [taillabel="framed", labelangle=8.1, labeldistance=24.85];
        """)
        self.assertEqual(
            messages(report.defects),
            ['label "framed" of e -> x: touches frame "frame"'],
        )

    def test_title(self) -> None:
        """Report a frame title touching an arrow."""
        report = self.check("""
            subgraph cluster_x {
                label="frame"; node [height=0.3];
                p [pos="0,0!"]; q [pos="300,0!"];
                j [shape=point, style=invis, width=0, pos="-40,-20!"];
                k [shape=point, style=invis, width=0, pos="340,18!"];
            }
            p -> q;
        """)
        self.assertEqual(messages(report.defects), ['title "frame": touches p -> q'])

    def test_borderless_title(self) -> None:
        """Report the title of a frame drawn without border touching an arrow."""
        report = self.check("""
            subgraph cluster_x { peripheries=0; label="frame"; x [pos="0,0!"]; k [pos="200,100!", style=invis]; }
            p [pos="-200,104!"]; q [pos="400,104!"];
            p -> q;
        """)
        self.assertEqual(messages(report.defects), ['title "frame": touches p -> q'])


class GeometryTest(unittest.TestCase):
    """Tracing drawn lines."""

    def test_piecewise_curve(self) -> None:
        """Follow each cubic span of a curve."""
        points = [
            (0, 0),
            (0, 100),
            (100, 100),
            (100, 0),
            (100, -100),
            (200, -100),
            (200, 0),
        ]
        lines = dot_check.trace([{"op": "b", "points": points}])
        self.assertTrue(dot_check.touches((45, 70, 55, 80), lines))
        self.assertTrue(dot_check.touches((145, -80, 155, -70), lines))
        self.assertFalse(dot_check.touches((45, -5, 55, 5), lines))


class MainTest(unittest.TestCase):
    """Running the checker on a .dot file."""

    def run_main(self, body: str) -> subprocess.CompletedProcess[str]:
        """Run the checker on a pinned digraph with BODY, and capture its output and exit status."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.dot"
            path.write_text(f"digraph {{ {HEADER} {body} }}")
            return subprocess.run(
                [sys.executable, str(SCRIPT), str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                text=True,
            )

    def test_crossings_only(self) -> None:
        """Print crossings and the size, and succeed."""
        result = self.run_main("""
            a [pos="0,0!"]; b [pos="0,200!"]; c [pos="300,0!"]; d [pos="300,200!"];
            a -> d; b -> c;
        """)
        self.assertEqual(
            result.stdout,
            "Crossing at (181, 122): a -> d crosses b -> c\nSize: 362 × 244pt, 0 defects, 1 crossing\n",
        )
        self.assertEqual(result.returncode, 0)

    def test_defects(self) -> None:
        """Print defects and the size, and fail."""
        result = self.run_main("""
            a [pos="0,0!"]; b [pos="150,0!"]; c [pos="300,0!"];
            a -> c;
        """)
        self.assertEqual(
            result.stdout,
            "Defect at (154, 22): a -> c: passes through b\nSize: 362 × 44pt, 1 defect, 0 crossings\n",
        )
        self.assertEqual(result.returncode, 1)

    def test_font(self) -> None:
        """Print a font drawn with another file than the one measured as a defect, before layout defects, but not one drawn with the same file, and fail."""
        result = self.run_main("""
            a [pos="0,0!", fontname="DejaVu Sans Bold"];
            b [pos="100,0!"]; c [pos="200,0!"];
            a -> c;
        """)
        self.assertRegex(
            result.stdout,
            r'^Defect: font "DejaVu Sans Bold": measured with /.*/DejaVuSans-Bold\.ttf, drawn with /.*\n'
            r"Defect at \(104, 22\): a -> c: passes through b\n"
            r"Size: 262 × 44pt, 2 defects, 0 crossings\n$",
        )
        self.assertEqual(result.returncode, 1)

    def test_unresolved_font(self) -> None:
        """Print a font Graphviz cannot resolve as a defect, and fail."""
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "fonts.conf"
            config.write_text("<fontconfig></fontconfig>")
            with mock.patch.dict(os.environ, FONTCONFIG_FILE=str(config)):
                result = self.run_main('a [pos="0,0!"];')
        self.assertRegex(
            result.stdout,
            r'^Defect: font "DejaVu Sans,sans-serif": measured with an unresolved font, drawn with .*\n'
            r"Size: .*, 1 defect, 0 crossings\n$",
        )
        self.assertEqual(result.returncode, 1)

    def test_font_list(self) -> None:
        """Check a font list starting with a dash, and succeed."""
        result = self.run_main('a [pos="0,0!", fontname="-apple-system,sans-serif"];')
        self.assertEqual(result.stdout, "Size: 62 × 44pt, 0 defects, 0 crossings\n")
        self.assertEqual(result.returncode, 0)

    @contextlib.contextmanager
    def without_neato(self) -> Generator[None]:
        """Hide Graphviz's neato layout from the runs within."""
        log = subprocess.run(
            ["dot", "-v", "-Tjson"],
            input="digraph {}",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
        ).stderr
        libdir = Path(re.findall(r'^libdir = "(.*)"$', log, re.MULTILINE)[0])
        with tempfile.TemporaryDirectory() as tmp:
            for plugin in libdir.glob("libgvplugin_*"):
                if "neato" not in plugin.name:
                    (Path(tmp) / plugin.name).symlink_to(plugin)
            with mock.patch.dict(os.environ, GVBINDIR=tmp):
                # Lists the plugins found in GVBINDIR for Graphviz to load
                subprocess.run(
                    ["dot", "-c"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    check=True,
                )
                yield

    def test_missing_neato(self) -> None:
        """Warn that the neato layout is missing without counting it as a defect, and succeed."""
        with self.without_neato():
            result = self.run_main("layout=dot; a;")
        self.assertEqual(
            result.stdout,
            f"{NEATO_WARNING}\nSize: 62 × 44pt, 0 defects, 0 crossings\n",
        )
        self.assertEqual(result.returncode, 0)

    def test_missing_neato_layout(self) -> None:
        """Warn that the neato layout is missing also when the diagram uses it, and fail."""
        with self.without_neato():
            result = self.run_main("a;")
        self.assertIn(f"{NEATO_WARNING}\n", result.stdout)
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
