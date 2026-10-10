#!/usr/bin/env python3
"""Tests for the diagram layout checker."""

import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

SCRIPT = Path(__file__).with_name("dot-check")
_spec = importlib.util.spec_from_loader(
    "dot_check", SourceFileLoader("dot_check", str(SCRIPT))
)
assert _spec is not None and _spec.loader is not None
dot_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dot_check)

# Pinned layout, positions in points
HEADER = "layout=neato; inputscale=72; splines=line; node [shape=box];"


def without_numbers(lines: list[str]) -> list[str]:
    """Replace the numbers in LINES by N."""
    return [re.sub(r"\d+(\.\d+)?", "N", line) for line in lines]


class CheckTest(unittest.TestCase):
    """Finding layout problems in a rendered diagram."""

    def check(self, body: str) -> "dot_check.Report":
        """Lay out a pinned digraph with BODY, and return its report."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.dot"
            path.write_text(f"digraph {{ {HEADER} {body} }}")
            return dot_check.check(dot_check.render(path))

    def test_clean(self) -> None:
        """Report nothing on attached arrows, at either end, with a label clear of everything."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="200,0!"]; c [pos="200,-100!"];
            a -> b [taillabel="lab", labelangle=30, labeldistance=5];
            a -> c [dir=both];
        """)
        self.assertEqual(report.defects, [])
        self.assertEqual(report.crossings, [])

    def test_formatted(self) -> None:
        """Take the differently formatted runs of a label as one line."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [taillabel=<<b>bold</b> plain>, labelangle=30, labeldistance=5];
        """)
        self.assertEqual(report.defects, [])

    def test_size(self) -> None:
        """Measure the drawing."""
        report = self.check('a [pos="0,0!"]; b [pos="200,100!"];')
        self.assertEqual(report.size, (254, 136))

    def test_thick(self) -> None:
        """Find the tip of an arrowhead wider than long."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="200,0!"];
            a -> b [penwidth=12];
        """)
        self.assertEqual(report.defects, [])

    def test_rounded_corner(self) -> None:
        """Report arrow ends on the square corner of a rounded box."""
        report = self.check("""
            node [style=rounded];
            a [pos="0,0!"]; b [pos="200,100!"];
            a -> b [tailport=ne, headport=sw];
        """)
        self.assertEqual(
            without_numbers(report.defects),
            [
                "a -> b: tail Npt off the outline of a",
                "a -> b: head Npt off the outline of b",
            ],
        )

    def test_note_fold(self) -> None:
        """Report an arrow leaving a note through its folded corner."""
        report = self.check("""
            a [pos="0,0!", shape=note]; b [pos="300,200!"];
            a -> b;
        """)
        self.assertEqual(
            without_numbers(report.defects), ["a -> b: tail Npt off the outline of a"]
        )

    def test_flat_arrowheads(self) -> None:
        """Find the tips of arrowheads ending in a flat side or an open line."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,300!"]; c [pos="300,0!"];
            a -> b [dir=both, arrowtail=crow, arrowhead=box];
            a -> c [dir=both, arrowtail=curve, arrowhead=tee];
        """)
        self.assertEqual(report.defects, [])

    def test_sections(self) -> None:
        """Find the end of an arrow drawn in successive colors."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [dir=none, color="red;0.5:blue"];
        """)
        self.assertEqual(report.defects, [])

    def test_compound(self) -> None:
        """Measure the ends of arrows clipped to frames against the frames."""
        report = self.check("""
            layout=dot; compound=true;
            subgraph cluster_a { a; } subgraph cluster_b { b; }
            a -> b [ltail=cluster_a, lhead=cluster_b];
        """)
        self.assertEqual(report.defects, [])

    def test_inside(self) -> None:
        """Report an arrow starting from the middle of its box."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="200,0!"];
            a -> b [tailclip=false];
        """)
        self.assertEqual(
            without_numbers(report.defects), ["a -> b: tail Npt off the outline of a"]
        )

    def test_unbordered(self) -> None:
        """Skip invisible arrows, and the ends of arrows on nodes drawn without an outline."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="200,0!"];
            w [pos="100,100!", shape=point, style=invis];
            h [pos="200,100!", shape=plain, label=<<table><tr><td>h</td></tr></table>>];
            a -> w -> h;
            a -> b [style=invis, tailclip=false];
            a -> b [color=transparent, tailclip=false];
        """)
        self.assertEqual(report.defects, [])

    def test_through(self) -> None:
        """Report an arrow passing through a box other than its ends."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="150,0!"]; c [pos="300,0!"];
            a -> c;
        """)
        self.assertEqual(report.defects, ["a -> c: passes through b"])

    def test_gradient(self) -> None:
        """Report an arrow passing through boxes filled with gradients."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            c [pos="100,0!", style=filled, fillcolor="red:blue"];
            d [pos="200,0!", style=radial, fillcolor="red:blue"];
            a -> b;
        """)
        self.assertEqual(
            report.defects, ["a -> b: passes through c", "a -> b: passes through d"]
        )

    def test_transparent_node(self) -> None:
        """Let arrows pass through nodes drawn in transparent colors."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"]; c [pos="150,0!", color=transparent, label=""];
            a -> b;
        """)
        self.assertEqual(report.defects, [])

    def test_through_table(self) -> None:
        """Report an arrow passing through the borders of an HTML table."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            c [pos="150,0!", shape=plain, label=<<table><tr><td>c</td></tr></table>>];
            a -> b;
        """)
        self.assertEqual(report.defects, ["a -> b: passes through c"])

    def test_parallel(self) -> None:
        """Follow each line of a multicolored arrow on its own."""
        report = self.check("""
            splines=true;
            a [pos="0,0!"]; b [pos="300,0!"]; c [pos="150,0!"];
            a -> b [color="red:blue"];
        """)
        self.assertEqual(report.defects, [])

    def test_crossing(self) -> None:
        """Count crossing arrows, but not arrows meeting at a shared end."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="0,200!"]; c [pos="300,0!"]; d [pos="300,200!"];
            a -> d; b -> c;
            e [pos="0,400!"]; f [pos="300,400!"];
            e -> f [headport=w, dir=none]; b -> f [headport=w, dir=none];
        """)
        self.assertEqual(report.defects, [])
        self.assertEqual(report.crossings, ["a -> d crosses b -> c"])

    def test_regular_edge_label(self) -> None:
        """Report an ordinary label drawn across its sloped arrow."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,200!"];
            a -> b [label="across"];
        """)
        self.assertEqual(report.defects, ['label "across" of a -> b: touches a -> b'])

    def test_label_on_line(self) -> None:
        """Report a label drawn across its own arrow."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [taillabel="across", labelangle=0, labeldistance=10];
        """)
        self.assertEqual(report.defects, ['label "across" of a -> b: touches a -> b'])

    def test_transparent_label(self) -> None:
        """Skip labels drawn in a transparent color."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [taillabel="hidden", labelfontcolor=transparent, labelangle=0, labeldistance=10];
        """)
        self.assertEqual(report.defects, [])

    def test_label_on_arrowhead(self) -> None:
        """Report a label drawn over an arrowhead."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [arrowsize=2, headlabel="x", labelangle=0, labeldistance=1];
        """)
        self.assertEqual(report.defects, ['label "x" of a -> b: touches a -> b'])

    def test_label_of_transparent(self) -> None:
        """Report a label of a transparent arrow drawn over a box."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [color=transparent, taillabel="shown", labelangle=180, labeldistance=2.7];
        """)
        self.assertEqual(report.defects, ['label "shown" of a -> b: touches a'])

    def test_node_text(self) -> None:
        """Report the text of a node without outline drawn over an arrow, but not over its own arrows."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"]; c [pos="150,0!", shape=plain, label="bare"];
            d [pos="0,100!", shape=plain]; e [pos="300,100!", shape=plain];
            a -> b; d -> e;
        """)
        self.assertEqual(report.defects, ['label "bare" of c: touches a -> b'])

    def test_external_label(self) -> None:
        """Report the external label of a box drawn over the box's own arrow."""
        report = self.check("""
            a [pos="0,0!", xlabel="outer"]; b [pos="-200,100!"];
            a -> b;
        """)
        self.assertIn('label "outer" of a: touches a -> b', report.defects)

    def test_label_on_box(self) -> None:
        """Report a label drawn over a box."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"];
            a -> b [taillabel="boxed", labelangle=0, labeldistance=0.5];
        """)
        self.assertEqual(
            report.defects,
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
        self.assertEqual(report.defects, ['label "hidden" of a -> b: touches a'])

    def test_label_on_label(self) -> None:
        """Report labels drawn over each other."""
        report = self.check("""
            a [pos="0,0!"]; b [pos="300,0!"]; c [pos="0,60!"]; d [pos="300,60!"];
            a -> b [taillabel="one", labelangle=60, labeldistance=3.5];
            c -> d [taillabel="two", labelangle=-60, labeldistance=3.5];
        """)
        self.assertEqual(
            report.defects,
            ['label "one" of a -> b: touches label "two" of c -> d'],
        )

    def test_label_on_frame(self) -> None:
        """Report a label drawn over a frame line."""
        report = self.check("""
            subgraph cluster_x { label="frame"; x [pos="300,0!"]; k [pos="450,100!", style=invis]; }
            e [pos="0,0!"];
            e -> x [taillabel="framed", labelangle=8.1, labeldistance=24.85];
        """)
        self.assertEqual(
            report.defects, ['label "framed" of e -> x: touches frame "frame"']
        )

    def test_title(self) -> None:
        """Report a frame title touching an arrow."""
        report = self.check("""
            subgraph cluster_x { label="frame"; x [pos="0,0!"]; k [pos="200,100!", style=invis]; }
            p [pos="-200,104!"]; q [pos="400,104!"];
            p -> q;
        """)
        self.assertEqual(report.defects, ['title "frame": touches p -> q'])

    def test_borderless_title(self) -> None:
        """Report the title of a frame drawn without border touching an arrow."""
        report = self.check("""
            subgraph cluster_x { peripheries=0; label="frame"; x [pos="0,0!"]; k [pos="200,100!", style=invis]; }
            p [pos="-200,104!"]; q [pos="400,104!"];
            p -> q;
        """)
        self.assertEqual(report.defects, ['title "frame": touches p -> q'])


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
            "Crossing: a -> d crosses b -> c\nSize: 354 × 236pt, 0 defects, 1 crossing\n",
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
            "Defect: a -> c: passes through b\nSize: 354 × 36pt, 1 defect, 0 crossings\n",
        )
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
