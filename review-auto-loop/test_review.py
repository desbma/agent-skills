#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["tabulate"]
# ///
"""Tests for the review wave report builder."""

import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any
from unittest import mock

SCRIPT = Path(__file__).with_name("review")
_spec = importlib.util.spec_from_loader(
    "review", SourceFileLoader("review", str(SCRIPT))
)
assert _spec is not None and _spec.loader is not None
review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(review)

CHANGE_ID = "onupomnnpqyktvkspnpkmrnwpykoqotx"
REVISION = "@-"
REV = CHANGE_ID[:8]
TARGETS = {"C7": "#c7-run-2-item-1", "R2": "wave1.md#r2-run-1-item-2"}
LINKED = "[C7](#c7-run-2-item-1)"

CAPTURE = """\
Reviewing the changes.

1. **Bound the layer walk** — `src/build.rs:133-147`

   **Severity**: major

   The builder walks an unbounded stack.

   ```rust
   3. not an item
   ensure!(stack.len() <= MAX, "too many layers");
   ```

   **Estimated delta**: +8 lines

2. **Drop the unused branch** — `src/read.rs:20`

   **Severity**: minor

   Nothing reaches it.

   **Estimated delta**: -12 lines
"""


ONE_ITEM = """\
1. **Bound the layer walk** — `src/build.rs:133-147`

   **Severity**: major

   The builder walks an unbounded stack.

   **Estimated delta**: +8 lines
"""

NESTED = """\
1. **First** — `a.py:1`

   **Severity**: minor

   In two steps:

   1. read it
   2. write it

   **Estimated delta**: +1 lines

2. **Second** — `b.py:2`

   **Severity**: minor

   Prose.

   **Estimated delta**: +2 lines
"""


class RawReviewTest(unittest.TestCase):
    """Reading items out of a reviewer capture."""

    def test_spans_ignore_fenced_lines(self) -> None:
        """A numbered line inside a code fence does not open an item."""
        self.assertEqual(sorted(review.reviewer_item_spans(CAPTURE)), [1, 2])
        self.assertEqual(review.reviewer_item_count(CAPTURE), 2)

    def test_item_is_dedented_and_unmarked(self) -> None:
        """An item loses its list marker and the indentation of its continuation."""
        with tempfile.TemporaryDirectory() as tmp:
            capture = Path(tmp, "run1.md")
            capture.write_text(CAPTURE)
            item = review.reviewer_item(capture, 1)
        self.assertTrue(item.startswith("**Bound the layer walk** — `src/build.rs"))
        self.assertIn("\n**Severity**: major\n", item)
        self.assertIn("\n```rust\n", item)
        self.assertTrue(item.endswith("**Estimated delta**: +8 lines"))

    def test_nested_numbers_are_not_items(self) -> None:
        """A numbered list inside an item does not open one."""
        self.assertEqual(sorted(review.reviewer_item_spans(NESTED)), [1, 2])
        with tempfile.TemporaryDirectory() as tmp:
            capture = Path(tmp, "run1.md")
            capture.write_text(NESTED)
            self.assertTrue(review.reviewer_item(capture, 2).startswith("**Second**"))

    def test_repeated_and_skipped_numbers(self) -> None:
        """Item numbers that repeat or skip one are refused."""
        for text in ("1. a\n\n1. b\n", "1. a\n\n3. b\n"):
            self.assertRaises(SystemExit, review.reviewer_item_spans, text)

    def test_spans_ignore_every_fence_form(self) -> None:
        """Tilde fences and fences longer than three backticks hide their numbers."""
        text = (
            "1. a\n\n~~~\n2. not an item\n~~~\n\n"
            "````\n```\n3. not an item\n````\n\n2. b\n"
        )
        self.assertEqual(sorted(review.reviewer_item_spans(text)), [1, 2])

    def test_format_checks(self) -> None:
        """An item is rejected without a title, a severity paragraph or a delta."""
        capture = Path("run1.md")
        good = "**T** — `a.py:1`\n\n**Severity**: major\n\nprose\n\n**Estimated delta**: +1 lines"
        review.check_reviewer_item(good, capture, 1)
        for broken in (
            "no title here\n\n**Severity**: major\n\n**Estimated delta**: +1 lines",
            "**T** — `a.py:1`\n\nprose\n\n**Estimated delta**: +1 lines",
            "**T** — `a.py:1`\n**Severity**: major\n\n**Estimated delta**: +1 lines",
            "**T** — `a.py:1`\n\n**Severity**: major\n\nprose",
        ):
            with self.assertRaises(SystemExit):
                review.check_reviewer_item(broken, capture, 1)

    def test_quote(self) -> None:
        """Every line takes the blockquote prefix, blank ones becoming a bare marker."""
        self.assertEqual(review.quote("a\n\nb"), ["> a", ">", "> b"])


class LinkifyTest(unittest.TestCase):
    """Turning item ids mentioned in prose into links."""

    def linkify(self, line: str) -> str:
        """The line after the link pass."""
        return review.linkify([line], TARGETS)[0]

    def test_known_ids_become_links(self) -> None:
        """An id with a heading in the change links to it, across reports too."""
        self.assertEqual(self.linkify("Same as C7."), "Same as [C7](#c7-run-2-item-1).")
        self.assertEqual(self.linkify("See R2"), "See [R2](wave1.md#r2-run-1-item-2)")

    def test_negatives(self) -> None:
        """Hex strings, longer ids, lowercase and unknown ids are left alone."""
        for line in ("5FC8D9", "C71 and C7x", "c7", "C9", "0xC7"):
            self.assertEqual(self.linkify(line), line)

    def test_protected_spans(self) -> None:
        """Quoted items, headings, code spans and existing links are left alone."""
        for line in (
            "> C7 as the reviewer wrote it",
            "### C7 (run 2, item 1)",
            "the `C7` symbol",
            "the ``C7`` symbol",
            "at <https://example.test/C7>",
            "already [C7](#c7-run-2-item-1)",
        ):
            self.assertEqual(self.linkify(line), line)

    def test_fenced_block(self) -> None:
        """Ids inside a fenced block are left alone, whatever the fence."""
        lines = ["```", "C7", "```", "~~~", "C7", "~~~", "````", "```", "C7", "````"]
        self.assertEqual(review.linkify([*lines, "C7"], TARGETS), [*lines, LINKED])


class JjQueryTest(unittest.TestCase):
    """The jj queries behind the reviewed change and its diff stat."""

    def test_diff_summary_is_the_last_stat_line(self) -> None:
        """The diff stat comes back as its last line, for the revision asked."""
        stat = "M review\n 2 files changed, 30 insertions(+)"
        with mock.patch.object(review, "jj_output", return_value=stat) as jj_output:
            self.assertEqual(
                review.diff_summary("@-"), " 2 files changed, 30 insertions(+)"
            )
        self.assertIn("@-", jj_output.call_args.args[0])

    def test_a_single_change(self) -> None:
        """A revision matching one change gives its id, and reaches the jj command."""
        with mock.patch.object(
            review, "jj_output", return_value=f"{CHANGE_ID}\n"
        ) as jj_output:
            self.assertEqual(review.resolve_change_id("@-"), CHANGE_ID)
        self.assertIn("@-", jj_output.call_args.args[0])

    def test_anything_else(self) -> None:
        """A revset matching several changes, or none, is refused."""
        for out in (f"{CHANGE_ID}\n{CHANGE_ID}\n", ""):
            with mock.patch.object(review, "jj_output", return_value=out):
                self.assertRaises(SystemExit, review.resolve_change_id, "@ | @-")


class AssessHelpTest(unittest.TestCase):
    """The help of the assess command, where a refused invocation looks next."""

    def test_it_lists_every_form(self) -> None:
        """Every claim and proposal pair is spelled out, with the tail it takes."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            review.build_parser().parse_args(["item", "assess", "--help"])
        body = out.getvalue().split("forms:\n", 1)[1]
        forms = [
            line.partition(" id ")[2] for line in body.splitlines() if line.strip()
        ]
        self.assertEqual(
            forms,
            [
                "holds {critical,major,minor} apply",
                "holds {critical,major,minor} apply-with-changes ACTION",
                "holds {critical,major,minor} decline REASON",
                "holds {critical,major,minor} your-call OPTION OPTION [OPTION ...]",
                "partly-holds {critical,major,minor} apply",
                "partly-holds {critical,major,minor} apply-with-changes ACTION",
                "partly-holds {critical,major,minor} decline REASON",
                "partly-holds {critical,major,minor} your-call OPTION OPTION [OPTION ...]",
                "does-not-hold apply",
                "does-not-hold apply-with-changes ACTION",
                "does-not-hold decline REASON",
                "does-not-hold your-call OPTION OPTION [OPTION ...]",
            ],
        )


class CapsTest(unittest.TestCase):
    """Reading the domain caps of a phase off the command line."""

    def test_caps_take_the_order_of_the_phase(self) -> None:
        """The caps come back in canonical domain order, whatever the order given."""
        self.assertEqual(
            list(review.parse_domain_caps(["readability=3", "correctness=2"]).items()),
            [("correctness", 2), ("readability", 3)],
        )
        self.assertEqual(
            list(review.parse_domain_caps(["docs=0", "tests=1"]).items()),
            [("tests", 1), ("docs", 0)],
        )

    def test_rejections(self) -> None:
        """A cross-phase pair, a fully excluded phase and malformed pairs are refused."""
        for pairs in (
            ["correctness=1", "docs=1"],
            ["correctness=0", "readability=0"],
            ["correctness=1", "correctness=2"],
            ["correctness", "readability=1"],
            ["correctness=x", "readability=1"],
        ):
            with self.assertRaises(SystemExit):
                review.parse_domain_caps(pairs)


class SlugTest(unittest.TestCase):
    """Anchors derived from item headings."""

    def test_item_heading(self) -> None:
        """Punctuation is dropped and spaces become hyphens."""
        self.assertEqual(review.slug("C7 (run 2, item 1)"), "c7-run-2-item-1")


class WaveTest(unittest.TestCase):
    """The command line against a review dir on disk."""

    def setUp(self) -> None:
        """Create a review dir and the wave 1 report of a phase A wave."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.review_dir = Path(self.tmp.name)
        patch = mock.patch.multiple(
            review, resolve_change_id=mock.DEFAULT, diff_summary=mock.DEFAULT
        )
        self.jj = patch.start()
        self.addCleanup(patch.stop)
        self.jj["resolve_change_id"].return_value = CHANGE_ID
        self.jj["diff_summary"].return_value = "2 files changed, 30 insertions(+)"
        out = self.run_cli(
            "init", self.review_dir, REVISION, "1", "correctness=2", "readability=2"
        )
        self.report = Path(out.splitlines()[0])

    def run_cli(self, *argv: Any, stdin: str | None = None) -> str:
        """Run one subcommand and return what it printed."""
        out = io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(io.StringIO()),
            mock.patch("sys.stdin", io.StringIO(stdin or "")),
        ):
            args = review.build_parser().parse_args([str(arg) for arg in argv])
            args.func(args)
        return out.getvalue()

    def chain(self, domain: str) -> Path:
        """The chain dir of a domain of the wave."""
        return Path(self.review_dir, f"{REV}-wave1-{domain}")

    def capture(self, domain: str, run: int, text: str = CAPTURE) -> None:
        """Write a completed chain capture for a run of the wave."""
        Path(self.chain(domain), f"run{run}.md").write_text(text)

    def running(self, domain: str, run: int) -> Path:
        """Write the capture of a run still in flight."""
        capture = Path(self.chain(domain), f"run{run}.md{review.RUNNING_SUFFIX}")
        capture.write_text("")
        return capture

    def complete_wave(self) -> None:
        """Give both chains of the wave an end, the correctness one holding the items."""
        self.capture("correctness", 1)
        self.capture("correctness", 2, "Nothing to report.\n")
        self.capture("readability", 1, "Nothing to report.\n")

    def second_wave(self) -> Path:
        """Run wave 1 to its decisions in production order, then open a phase B wave over it."""
        self.complete_wave()
        identifiers = [self.add_assessed("C", 1, number) for number in (1, 2)]
        self.run_cli("report", "format", self.report)
        for identifier, verdict in zip(
            identifiers, ("applied", "applied-with-changes")
        ):
            self.run_cli(
                "item",
                "decide",
                self.report,
                identifier,
                "--verdict",
                verdict,
                stdin="as proposed",
            )
        second = Path(
            self.run_cli(
                "init", self.review_dir, REVISION, "2", "tests=1", "docs=1"
            ).splitlines()[0]
        )
        Path(self.review_dir, f"{REV}-wave2-tests", "run1.md").write_text(ONE_ITEM)
        return second

    def add(
        self, prefix: str, run: int, number: int, report: Path | None = None
    ) -> str:
        """Quote an item into the report and return the id it was given."""
        target = self.report if report is None else report
        return self.run_cli("item", "add", target, prefix, run, number).split()[1]

    def assess(
        self,
        identifier: str,
        *tail: Any,
        claim: str = "holds",
        severity: str | None = "major",
        proposal: str = "apply",
        stdin: str = "The code confirms it.",
        report: Path | None = None,
    ) -> str:
        """Assess an item, the defaults standing for an ordinary holds and apply."""
        return self.run_cli(
            "item",
            "assess",
            self.report if report is None else report,
            identifier,
            claim,
            *([] if severity is None else [severity]),
            proposal,
            *tail,
            stdin=stdin,
        )

    def add_assessed(self, prefix: str, run: int, number: int) -> str:
        """Quote an item and assess it, so the report holds a complete entry."""
        identifier = self.add(prefix, run, number)
        self.assess(identifier)
        return identifier

    def assert_cli_error(self, *argv: Any, stdin: str | None = None) -> None:
        """Assert that a subcommand exits instead of running."""
        with self.assertRaises(SystemExit):
            self.run_cli(*argv, stdin=stdin)

    def test_init_writes_the_doc_and_chains(self) -> None:
        """Init creates the report with its comment, the chain dirs, and prints them."""
        self.jj["resolve_change_id"].assert_called_once_with(REVISION)
        self.assertRegex(self.report.name, rf"{REV}-wave1-\d{{12}}\.md")
        self.assertEqual(
            self.report.read_text(),
            f"<!-- review: change_id={CHANGE_ID} wave=1 correctness=2 readability=2 -->\n",
        )
        for domain in ("correctness", "readability"):
            self.assertTrue(Path(self.review_dir, f"{REV}-wave1-{domain}").is_dir())

    def test_init_refuses_a_second_doc(self) -> None:
        """A wave that already has a report is not initialized again."""
        self.assert_cli_error(
            "init", self.review_dir, REVISION, "1", "correctness=2", "readability=2"
        )

    def test_init_skips_an_excluded_chain(self) -> None:
        """A domain capped at zero gets no chain dir."""
        out = self.run_cli("init", self.review_dir, REVISION, "2", "tests=1", "docs=0")
        self.assertEqual(len(out.splitlines()), 2)
        self.assertTrue(Path(self.review_dir, f"{REV}-wave2-tests").is_dir())
        self.assertFalse(Path(self.review_dir, f"{REV}-wave2-docs").exists())

    def test_add_creates_sections_in_canonical_order(self) -> None:
        """The readability section follows the correctness one whatever the order of the calls."""
        self.capture("readability", 1)
        self.capture("correctness", 1)
        self.assertEqual(
            self.run_cli("item", "add", self.report, "R", 1, 1).strip(),
            "### R1 (run 1, item 1)",
        )
        self.add("C", 1, 1)
        self.add("C", 1, 2)
        lines = self.report.read_text().splitlines()
        headings = [line for line in lines if line.startswith("#")]
        self.assertEqual(
            headings,
            [
                "## Correctness",
                "### C1 (run 1, item 1)",
                "### C2 (run 1, item 2)",
                "## Readability",
                "### R1 (run 1, item 1)",
            ],
        )
        self.assertIn("> **Bound the layer walk** — `src/build.rs:133-147`", lines)
        self.assertIn(">", lines)

    def test_add_allocates_the_next_id(self) -> None:
        """The id follows the domain's counter, and the heading names the one assigned."""
        self.capture("correctness", 1)
        self.assertEqual(
            self.run_cli("item", "add", self.report, "C", 1, 1).strip(),
            "### C1 (run 1, item 1)",
        )
        self.assertEqual(
            self.run_cli("item", "add", self.report, "C", 1, 2).strip(),
            "### C2 (run 1, item 2)",
        )

    def test_add_rejections(self) -> None:
        """An unknown capture, an unknown item, an inactive domain and a broken item all fail."""
        self.capture("correctness", 1)
        self.assert_cli_error("item", "add", self.report, "C", 2, 1)
        self.assert_cli_error("item", "add", self.report, "C", 1, 3)
        self.assert_cli_error("item", "add", self.report, "T", 1, 1)
        self.capture("readability", 1, "1. no title\n\nprose\n")
        self.assert_cli_error("item", "add", self.report, "R", 1, 1)

    def test_assess_writes_the_claim_and_proposal(self) -> None:
        """The assessment lands below the quote, with the justification between its two lines."""
        self.capture("correctness", 1)
        self.assess(
            self.add("C", 1, 1),
            "bound it in the caller",
            claim="partly-holds",
            severity="minor",
            proposal="apply-with-changes",
            stdin="Only the retry path can overrun it.",
        )
        text = self.report.read_text()
        self.assertIn(
            "**Claim**: partly holds, minor\n\nOnly the retry path can overrun it.\n\n"
            "**Proposal**: apply with changes — bound it in the caller\n",
            text,
        )

    def test_assess_overwrites_and_keeps_the_quote(self) -> None:
        """Assessing twice replaces the assessment and leaves the quoted item alone."""
        self.capture("correctness", 1)
        self.assess(
            self.add_assessed("C", 1, 1),
            "the branch is reachable",
            claim="does-not-hold",
            severity=None,
            proposal="decline",
            stdin="The invariant does not hold.",
        )
        text = self.report.read_text()
        self.assertNotIn("**Claim**: holds, major", text)
        self.assertIn("**Claim**: does not hold\n", text)
        self.assertIn("> **Bound the layer walk**", text)

    def test_an_assessment_may_hold_a_hash_line(self) -> None:
        """A `#` line inside a justification does not end the item."""
        self.capture("correctness", 1)
        identifier = self.add("C", 1, 1)
        self.assess(
            identifier, stdin="Reproduced with:\n\n```sh\n# run it\nreview\n```"
        )
        self.run_cli(
            "item",
            "decide",
            self.report,
            identifier,
            "--verdict",
            "applied",
            stdin="as proposed",
        )
        self.assertIn("**Decision**: applied — as proposed", self.report.read_text())

    def test_reassessment_replaces_a_quoting_justification(self) -> None:
        """An assessment that quotes something is replaced whole, quote included."""
        self.capture("correctness", 1)
        identifier = self.add("C", 1, 1)
        self.assess(identifier, stdin="The reviewer writes:\n\n> a quoted line")
        self.assess(identifier, stdin="Simpler after all.")
        text = self.report.read_text()
        self.assertEqual(text.count("**Claim**"), 1)
        self.assertNotIn("> a quoted line", text)

    def test_a_prose_heading_does_not_end_a_section(self) -> None:
        """The next item follows the previous one whose assessment holds a `##` line."""
        self.capture("correctness", 1)
        self.assess(self.add("C", 1, 1), stdin="Like:\n\n```markdown\n## Items\n```")
        self.add("C", 1, 2)
        lines = self.report.read_text().splitlines()
        self.assertLess(
            lines.index("**Proposal**: apply"), lines.index("### C2 (run 1, item 2)")
        )

    def test_assess_argument_rules(self) -> None:
        """The parser takes a severity exactly where the claim calls for one, with the proposal's own tail."""
        self.capture("correctness", 1)
        base = ["item", "assess", self.report, self.add("C", 1, 1)]
        for extra in (
            ["holds", "apply"],
            ["does-not-hold", "minor", "decline", "x"],
            ["holds", "minor", "apply", "x"],
            ["holds", "minor", "apply-with-changes"],
            ["holds", "minor", "decline"],
            ["holds", "minor", "your-call", "a"],
            ["nearly-holds", "minor", "apply"],
        ):
            self.assert_cli_error(*base, *extra, stdin="prose")

    def test_assess_your_call_renders_its_options(self) -> None:
        """A your-call proposal spells its options out as a lettered list."""
        self.capture("correctness", 1)
        out = self.assess(
            self.add("C", 1, 1),
            "split it",
            "leave it",
            severity="minor",
            proposal="your-call",
            stdin="Both are defensible.",
        )
        self.assertEqual(
            out, "**Proposal**: your call:\n- (a) split it\n- (b) leave it\n"
        )
        self.assertIn(
            "**Proposal**: your call:\n\n- (a) split it\n- (b) leave it\n",
            self.report.read_text(),
        )

    def test_decide(self) -> None:
        """A decision needs an assessment, reads stdin, and links the ids in its reason."""
        self.capture("correctness", 1)
        self.add("C", 1, 1)
        self.assert_cli_error(
            "item", "decide", self.report, "C1", "--verdict", "applied", stdin="x"
        )
        self.assess("C1", stdin="Confirmed.")
        self.run_cli(
            "item",
            "decide",
            self.report,
            "C1",
            "--verdict",
            "applied-with-changes",
            stdin="folded into C1's fix",
        )
        text = self.report.read_text()
        self.assertIn(
            "**Decision**: applied with changes — folded into "
            "[C1](#c1-run-1-item-1)'s fix\n",
            text,
        )

    def test_blank_prose_is_refused(self) -> None:
        """A justification or a reason made of whitespace is refused, and nothing is written."""
        self.capture("correctness", 1)
        identifier = self.add("C", 1, 1)
        before = self.report.read_text()
        self.assert_cli_error(
            "item",
            "assess",
            self.report,
            identifier,
            "holds",
            "major",
            "apply",
            stdin=" \n",
        )
        self.assertEqual(self.report.read_text(), before)
        self.assess(identifier)
        before = self.report.read_text()
        self.assert_cli_error(
            "item",
            "decide",
            self.report,
            identifier,
            "--verdict",
            "applied",
            stdin=" \n",
        )
        self.assertEqual(self.report.read_text(), before)

    def test_decide_overwrites_and_keeps_the_assessment(self) -> None:
        """Deciding twice replaces the decision and leaves the assessment alone."""
        self.capture("correctness", 1)
        self.add_assessed("C", 1, 1)
        self.run_cli(
            "item",
            "decide",
            self.report,
            "C1",
            "--verdict",
            "applied",
            stdin="as proposed",
        )
        self.run_cli(
            "item",
            "decide",
            self.report,
            "C1",
            "--verdict",
            "declined",
            stdin="reverted afterwards",
        )
        text = self.report.read_text()
        self.assertNotIn("as proposed", text)
        self.assertEqual(text.count("**Decision**"), 1)
        self.assertIn(
            "**Proposal**: apply\n\n**Decision**: declined — reverted afterwards\n",
            text,
        )

    def test_report_format(self) -> None:
        """The top part, the index and the links land in one pass, and the recap is printed."""
        self.capture("correctness", 2, "Nothing to report.\n")
        self.capture("readability", 2, "Nothing to report.\n")
        self.complete_wave()
        self.capture("readability", 1)
        self.add_assessed("C", 1, 1)
        self.assess(
            self.add("C", 1, 2),
            "bound it in the caller",
            claim="partly-holds",
            proposal="apply-with-changes",
            stdin="Only the retry path can overrun it.",
        )
        self.assess(
            self.add("R", 1, 1),
            "C1 already covers it",
            claim="does-not-hold",
            severity=None,
            proposal="decline",
            stdin="Subsumed by C1.",
        )
        self.assess(
            self.add("R", 1, 2),
            "split it",
            "leave it",
            severity="minor",
            proposal="your-call",
            stdin="Both are defensible.",
        )
        recap = self.run_cli("report", "format", self.report)
        self.assertEqual(
            recap,
            "apply: C1 (major)\napply with changes: C2 (major)\n"
            "decline: R1\nyour call: R2 (minor)\n",
        )
        lines = self.report.read_text().splitlines()
        self.assertTrue(lines[0].startswith("<!-- review:"))
        self.assertEqual(lines[2], f"# Review wave 1 — {REV}")
        self.assertIn("- **Config**: correctness ≤2 · readability ≤2", lines)
        self.assertIn("## Items", lines)
        self.assertEqual(
            lines[lines.index("## Items") + 2 : lines.index("## Correctness") - 1],
            [
                "- Correctness",
                "  - [C1 / major / holds, apply](#c1-run-1-item-1)",
                (
                    "  - [C2 / minor / partly holds, major, apply with changes]"
                    "(#c2-run-1-item-2)"
                ),
                "- Readability",
                "  - [R1 / major / does not hold, decline](#r1-run-1-item-1)",
                "  - [R2 / minor / holds, your call](#r2-run-1-item-2)",
            ],
        )
        self.assertIn("**Proposal**: apply", lines)
        self.assertIn("Subsumed by [C1](#c1-run-1-item-1).", lines)

    def test_format_waits_for_the_chains(self) -> None:
        """A chain in flight, one that never ran, and one due another run all block it."""
        self.running("correctness", 1)
        self.capture("readability", 1, "Nothing to report.\n")
        with self.assertRaisesRegex(
            SystemExit, "correctness still has a run in flight"
        ):
            self.run_cli("report", "format", self.report)
        self.running("correctness", 1).unlink()
        with self.assertRaisesRegex(SystemExit, "correctness has not run"):
            self.run_cli("report", "format", self.report)
        self.capture("correctness", 1)
        with self.assertRaisesRegex(SystemExit, "correctness is due another run"):
            self.run_cli("report", "format", self.report)

    def test_format_requires_every_item_assessed(self) -> None:
        """Every captured item is in the report exactly once, with one assessment."""
        self.complete_wave()
        with self.assertRaisesRegex(SystemExit, "exactly once"):
            self.run_cli("report", "format", self.report)
        self.add_assessed("C", 1, 1)
        second = self.add("C", 1, 2)
        with self.assertRaisesRegex(SystemExit, "C2 has no single claim"):
            self.run_cli("report", "format", self.report)
        self.assess(second)
        self.assertEqual(
            self.run_cli("report", "format", self.report),
            "apply: C1 (major), C2 (major)\n",
        )

    def test_findings_on_the_cap_run_are_complete(self) -> None:
        """A chain that finds items on its last allowed run has run to its end."""
        self.capture("correctness", 1, ONE_ITEM)
        self.capture("correctness", 2, ONE_ITEM)
        self.capture("readability", 1, "Nothing to report.\n")
        self.add_assessed("C", 1, 1)
        self.add_assessed("C", 2, 1)
        self.assertEqual(
            self.run_cli("report", "format", self.report),
            "apply: C1 (major), C2 (major)\n",
        )

    def test_an_excluded_domain_is_not_awaited(self) -> None:
        """Formatting waits only on the chains of the domains the caps left active."""
        review_dir = Path(self.review_dir, "excluded")
        review_dir.mkdir()
        report = Path(
            self.run_cli(
                "init", review_dir, REVISION, "1", "tests=1", "docs=0"
            ).splitlines()[0]
        )
        Path(review_dir, f"{REV}-wave1-tests", "run1.md").write_text("Nothing yet.\n")
        self.assertEqual(self.run_cli("report", "format", report), "")
        self.assertIn(
            "- **Config**: tests ≤1 · docs =0", report.read_text().splitlines()
        )

    def test_format_runs_again_over_its_own_output(self) -> None:
        """Formatting a formatted report replaces its top part and index."""
        self.complete_wave()
        identifier = self.add_assessed("C", 1, 1)
        self.assess(self.add("C", 1, 2), stdin="# Review wave 2 — example\n")
        self.run_cli("report", "format", self.report)
        self.assess(identifier, "not worth it", proposal="decline")
        self.run_cli("report", "format", self.report)
        lines = self.report.read_text().splitlines()
        self.assertEqual(lines.count(f"# Review wave 1 — {REV}"), 1)
        self.assertEqual(lines.count("## Items"), 1)
        self.assertIn("  - [C1 / major / holds, decline](#c1-run-1-item-1)", lines)

    def test_report_format_without_items(self) -> None:
        """A wave that yielded nothing gets its top part, no index and no recap."""
        self.capture("correctness", 1, "No item to report.\n")
        self.capture("readability", 1, "No item to report.\n")
        self.assertEqual(self.run_cli("report", "format", self.report), "")
        lines = self.report.read_text().splitlines()
        self.assertEqual(lines[2], f"# Review wave 1 — {REV}")
        self.assertNotIn("## Items", lines)

    def test_report_grid_is_right_aligned(self) -> None:
        """Every column of the markdown grid carries a right-alignment marker."""
        self.capture("correctness", 1, "No item to report.\n")
        self.capture("readability", 1, "No item to report.\n")
        self.run_cli("report", "format", self.report)
        rule = next(
            line
            for line in self.report.read_text().splitlines()
            if set(line) == {"|", "-", ":"}
        )
        cells = rule.strip("|").split("|")
        self.assertEqual(len(cells), len(review.DOMAIN_NAMES) + 1)
        self.assertTrue(all(cell.endswith(":") for cell in cells))

    def test_header_show(self) -> None:
        """The header frames the wave title, its config, the diff stat and the run grid."""
        self.capture("correctness", 1)
        self.capture("readability", 1)
        self.running("readability", 2)
        out = self.run_cli("header", "show", self.report, 1).splitlines()
        self.jj["diff_summary"].assert_called_once_with(CHANGE_ID)
        self.assertIn(" Wave 1, run 1 — 3 total reviews", out)
        self.assertIn(" Wave config: correctness ≤2 · readability ≤2", out)
        self.assertIn(" 2 files changed, 30 insertions(+)", out)
        self.assertTrue(any(review.RUNNING_STR in line for line in out))

    def test_grid_is_ruled_not_boxed(self) -> None:
        """The grid draws column rules and no box around itself."""
        self.capture("correctness", 1)
        self.capture("readability", 1)
        out = self.run_cli("header", "show", self.report, 1).splitlines()
        head = next(line for line in out if "│" in line)
        self.assertTrue(head.startswith("  "))
        self.assertEqual(head.count("│"), len(review.DOMAIN_NAMES))
        self.assertFalse(any(set("╭╮╰╯├┤┬┴") & set(line) for line in out))

    def test_grid_rules_the_waves_apart(self) -> None:
        """A rule runs below the domains and between two waves."""
        second = self.second_wave()
        out = self.run_cli("header", "show", second, 1).splitlines()
        self.assertEqual(sum(set(line) == {"─", "┼"} for line in out), 2)

    def test_grid_counts_a_past_wave_decisions(self) -> None:
        """A past wave's cell counts the items it found and how many of its decisions applied."""
        second = self.second_wave()
        out = self.run_cli("header", "show", second, 1).splitlines()
        self.assertTrue(any("1+1/2" in line for line in out))

    def test_links_reach_a_past_wave_report(self) -> None:
        """An id from a past wave links to its heading in that wave's own report."""
        second = self.second_wave()
        identifier = self.add("T", 1, 1, report=second)
        self.assess(identifier, stdin="Same as C1.", report=second)
        self.assertIn(
            f"Same as [C1]({self.report.name}#c1-run-1-item-1).", second.read_text()
        )

    def test_decide_after_formatting(self) -> None:
        """A decision lands below its proposal on a report that carries its generated sections."""
        self.second_wave()
        text = self.report.read_text()
        self.assertEqual(text.count("## Items"), 1)
        self.assertIn(
            "**Proposal**: apply\n\n**Decision**: applied — as proposed\n", text
        )
        self.assertIn(
            "**Proposal**: apply\n\n**Decision**: applied with changes — as proposed\n",
            text,
        )

    def test_an_empty_capture_is_a_completed_run(self) -> None:
        """A run that printed nothing is complete, having found no item."""
        self.capture("correctness", 1, "")
        out = self.run_cli("header", "show", self.report, 1)
        self.assertNotIn(review.RUNNING_STR, out)
        self.assertIn(" Wave 1, run 1 — 1 total reviews", out.splitlines())

    def test_metadata_is_read_back(self) -> None:
        """The report's comment carries the revision, the wave and the caps of the wave."""
        metadata = review.read_metadata(self.report)
        self.assertEqual(metadata.short_change_id, REV)
        self.assertEqual(metadata.change_id, CHANGE_ID)
        self.assertEqual(metadata.wave, 1)
        self.assertEqual(metadata.active, ("correctness", "readability"))

    def test_metadata_rejections(self) -> None:
        """A report without the comment, or with one disagreeing with its name, is refused."""
        stray = Path(self.review_dir, f"{REV}-wave3-202608261252.md")
        caps = "correctness=1 readability=1 -->\n"
        for text in (
            "# Not a wave report\n",
            f"<!-- review: change_id={CHANGE_ID} wave=2 {caps}",
            f"<!-- review: change_id=uqrvytospqyktvkspnpkmrnwpykoqotx wave=3 {caps}",
        ):
            stray.write_text(text)
            self.assertRaises(SystemExit, review.read_metadata, stray)


class EntryPointTest(unittest.TestCase):
    """The script as the executable the skill runs."""

    def test_the_executable_dispatches_a_command(self) -> None:
        """Running the file itself reaches the subcommand its arguments name."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp, "missing")
            completed = subprocess.run(
                [SCRIPT, "init", missing, "@", "1", "correctness=1", "readability=1"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(f"No such review dir: {missing}", completed.stderr)


if __name__ == "__main__":
    unittest.main()
