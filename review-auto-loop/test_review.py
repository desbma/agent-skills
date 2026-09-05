#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["tabulate"]
# ///
"""Tests for the review wave report builder."""

import contextlib
import importlib.util
import io
import os
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

    def test_item_is_dedented_and_unmarked(self) -> None:
        """An item loses its list marker and the indentation of its continuation."""
        item = review.reviewer_items(CAPTURE)[1]
        self.assertTrue(item.startswith("**Bound the layer walk** — `src/build.rs"))
        self.assertIn("\n**Severity**: major\n", item)
        self.assertIn("\n```rust\n", item)
        self.assertTrue(item.endswith("**Estimated delta**: +8 lines"))

    def test_nested_numbers_are_not_items(self) -> None:
        """A numbered list inside an item does not open one."""
        self.assertEqual(sorted(review.reviewer_item_spans(NESTED)), [1, 2])
        self.assertTrue(review.reviewer_items(NESTED)[2].startswith("**Second**"))

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

    def test_quote_code_spans_tags(self) -> None:
        """A tag in the reviewer's prose is code-spanned, one inside a fence left alone."""
        self.assertEqual(
            review.quote("A <details> fold.\n\n```html\n<details>\n```"),
            ["> A `<details>` fold.", ">", "> ```html", "> <details>", "> ```"],
        )


class RenderProseTest(unittest.TestCase):
    """Linking the item ids mentioned in prose, and code-spanning the tags it names."""

    def render(self, line: str) -> str:
        """The line after the prose pass."""
        return review.render_prose([line], TARGETS)[0]

    def test_known_ids_become_links(self) -> None:
        """An id with a heading in the change links to it, across reports too."""
        self.assertEqual(self.render("Same as C7."), "Same as [C7](#c7-run-2-item-1).")
        self.assertEqual(self.render("See R2"), "See [R2](wave1.md#r2-run-1-item-2)")

    def test_negatives(self) -> None:
        """Hex strings, longer ids, lowercase and unknown ids are left alone."""
        for line in ("5FC8D9", "C71 and C7x", "c7", "C9", "0xC7"):
            self.assertEqual(self.render(line), line)

    def test_protected_spans(self) -> None:
        """Quoted items, headings, code spans and existing links are left alone."""
        for line in (
            "> C7 as the reviewer wrote it",
            "> a <details> fold, as the reviewer wrote it",
            "### C7 (run 2, item 1)",
            "the `C7` symbol",
            "the ``C7`` symbol",
            "the `<details>` element",
            "at <https://example.test/C7>",
            "already [C7](#c7-run-2-item-1)",
            "already [the `<details>` fold](#c7-run-2-item-1)",
        ):
            self.assertEqual(self.render(line), line)

    def test_tags_become_code_spans(self) -> None:
        """A tag the prose names is code-spanned, so the renderer displays it."""
        self.assertEqual(
            self.render("one closed <details> before the index"),
            "one closed `<details>` before the index",
        )
        for line, rendered in (
            ("</details>", "`</details>`"),
            ("<br/>", "`<br/>`"),
            ('<div class="x">', '`<div class="x">`'),
            ("Vec<u8>", "Vec`<u8>`"),
        ):
            self.assertEqual(self.render(line), rendered)

    def test_angle_spans_that_are_no_tags(self) -> None:
        """An autolink, a bare comparison and the report's own comment are left alone."""
        for line in (
            "<user@example.test>",
            "the <T: Clone> bound",
            "a < b and c > d",
            f"<!-- review: change_id={CHANGE_ID} wave=1 -->",
        ):
            self.assertEqual(self.render(line), line)

    def test_a_spanned_tag_is_stable(self) -> None:
        """A second pass leaves an already spanned tag alone."""
        once = self.render("one closed <details> fold")
        self.assertEqual(self.render(once), once)

    def test_fenced_block(self) -> None:
        """Ids and tags inside a fenced block are left alone, whatever the fence."""
        lines = ["```", "C7", "```", "~~~", "C7", "~~~", "````", "```", "C7", "````"]
        self.assertEqual(review.render_prose([*lines, "C7"], TARGETS), [*lines, LINKED])
        fenced = ["```html", "<details>", "```"]
        self.assertEqual(
            review.render_prose([*fenced, "<details>"], TARGETS),
            [*fenced, "`<details>`"],
        )


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

    def test_loop_caps_cover_every_domain(self) -> None:
        """The loop caps of a review comment read back in canonical order."""
        self.assertEqual(
            list(
                review.parse_loop_caps(
                    "correctness:2,readability:2,tests:1,docs:0"
                ).items()
            ),
            [("correctness", 2), ("readability", 2), ("tests", 1), ("docs", 0)],
        )
        for value in ("correctness:2,readability:2", "correctness:2,x:1", "docs:1"):
            with self.assertRaises(SystemExit):
                review.parse_loop_caps(value)


class LoopCapsTest(unittest.TestCase):
    """Deriving the caps of a loop from the size of the reviewed change."""

    def caps(self, summary: str) -> dict[str, int]:
        """The loop caps derived from a diff stat summary."""
        with mock.patch.object(review, "diff_summary", return_value=summary):
            return review.derive_loop_caps(CHANGE_ID)

    def test_the_code_domains_scale_with_the_insertions(self) -> None:
        """The correctness and readability caps follow the lines the change adds."""
        for insertions, cap in (
            (0, 1),
            (99, 1),
            (100, 2),
            (999, 2),
            (1000, 3),
            (5000, 4),
        ):
            self.assertEqual(
                self.caps(f"1 file changed, {insertions} insertions(+)"),
                {"correctness": cap, "readability": cap, "tests": 1, "docs": 1},
            )

    def test_a_change_that_only_deletes_adds_nothing(self) -> None:
        """A summary without an insertion count reads as no line added."""
        self.assertEqual(self.caps("1 file changed, 40 deletions(-)")["correctness"], 1)

    def test_an_unreadable_summary_is_refused(self) -> None:
        """A last diff stat line that is not a summary fails instead of counting zero."""
        with self.assertRaises(SystemExit):
            self.caps("M review-auto-loop/review")

    def test_a_repeat_lowers_the_caps_without_disabling_a_domain(self) -> None:
        """Repeating drops each cap by one, floored at one, an excluded domain staying out."""
        self.assertEqual(
            review.repeated_caps(
                {"correctness": 3, "readability": 1, "tests": 1, "docs": 0}
            ),
            {"correctness": 2, "readability": 1, "tests": 1, "docs": 0},
        )


class SlugTest(unittest.TestCase):
    """Anchors derived from item headings."""

    def test_item_heading(self) -> None:
        """Punctuation is dropped and spaces become hyphens."""
        self.assertEqual(review.slug("C7 (run 2, item 1)"), "c7-run-2-item-1")


class CliFixture(unittest.TestCase):
    """Driving the script through its own parser, as the skill's shell calls do."""

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

    def assert_cli_error(self, *argv: Any, stdin: str | None = None) -> None:
        """Assert that a subcommand exits instead of running."""
        with self.assertRaises(SystemExit):
            self.run_cli(*argv, stdin=stdin)


class WaveFixture(CliFixture):
    """A review dir carrying one phase A wave, and the helpers driving it."""

    def setUp(self) -> None:
        """Create a review dir and the wave 1 report of a phase A wave."""
        self.review_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.jj = self.enterContext(
            mock.patch.multiple(
                review, resolve_change_id=mock.DEFAULT, diff_summary=mock.DEFAULT
            )
        )
        self.jj["resolve_change_id"].return_value = CHANGE_ID
        self.jj["diff_summary"].return_value = "2 files changed, 30 insertions(+)"
        self.report = self.init(
            self.review_dir,
            "A",
            "--revision",
            REVISION,
            "--cap",
            "correctness=2",
            "--cap",
            "readability=2",
        )

    def init(self, *argv: Any) -> Path:
        """Open a wave and return the report path it printed under the change it resolved."""
        return Path(self.run_cli("init", *argv).splitlines()[1])

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
        identifiers = self.imported_assessed("correctness")
        self.run_cli("report", "format", self.report)
        for identifier, verdict in zip(
            identifiers, ("applied", "applied-with-changes")
        ):
            self.decide(identifier, verdict)
        second = self.init(self.review_dir, "B")
        Path(self.review_dir, f"{REV}-wave2-tests", "run1.md").write_text(ONE_ITEM)
        return second

    def decided_second_wave(self) -> None:
        """Run the phase B wave to its decision too, so a third wave can open over it."""
        second = self.second_wave()
        Path(self.review_dir, f"{REV}-wave2-docs", "run1.md").write_text("Nothing.\n")
        identifier = self.imported("tests", 1, second)[0]
        self.assess(identifier, report=second)
        self.run_cli("report", "format", second)
        self.decide(identifier, report=second)

    def imported(
        self, domain: str, run: int = 1, report: Path | None = None
    ) -> list[str]:
        """Import a run's items into the report and return the ids they were given."""
        target = self.report if report is None else report
        out = self.run_cli("item", "import", target, domain, run)
        return [line.split()[1] for line in out.splitlines()]

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

    def decide(
        self,
        identifier: str,
        verdict: str = "applied",
        reason: str = "as proposed",
        report: Path | None = None,
    ) -> None:
        """Record an item's decision, the defaults standing for taking the proposal."""
        self.run_cli(
            "item",
            "decide",
            self.report if report is None else report,
            identifier,
            "--verdict",
            verdict,
            stdin=reason,
        )

    def imported_assessed(self, domain: str, run: int = 1) -> list[str]:
        """Import a run's items and assess them all, so the report holds complete entries."""
        identifiers = self.imported(domain, run)
        for identifier in identifiers:
            self.assess(identifier)
        return identifiers


class WaveTest(WaveFixture):
    """The command line against a review dir on disk."""

    def test_init_writes_the_doc_and_chains(self) -> None:
        """Init creates the report with its comment, the chain dirs, and names them."""
        self.jj["resolve_change_id"].assert_called_once_with(REVISION)
        self.assertRegex(self.report.name, rf"{REV}-wave1-\d{{12}}\.md")
        self.assertEqual(
            self.report.read_text(),
            f"<!-- review: change_id={CHANGE_ID} wave=1 "
            "loop=correctness:2,readability:2,tests:1,docs:1 "
            "correctness=2 readability=2 -->\n",
        )
        for domain in ("correctness", "readability"):
            self.assertTrue(Path(self.review_dir, f"{REV}-wave1-{domain}").is_dir())

    def test_init_names_the_change_it_resolved(self) -> None:
        """The change comes first, so later waves can pin the loop to it."""
        review_dir = Path(self.review_dir, "named")
        review_dir.mkdir()
        out = self.run_cli("init", review_dir, "A", "--revision", REVISION)
        self.assertEqual(out.splitlines()[0], CHANGE_ID)

    def test_init_defaults_to_the_latest_non_empty_change(self) -> None:
        """A wave opened without a revision reviews the latest non-empty change."""
        review_dir = Path(self.review_dir, "default")
        review_dir.mkdir()
        self.run_cli("init", review_dir, "A")
        self.assertEqual(
            self.jj["resolve_change_id"].call_args.args, (review.DEFAULT_REVSET,)
        )

    def test_init_numbers_the_waves(self) -> None:
        """The wave number follows the reports the review dir already holds."""
        self.assertRegex(self.second_wave().name, rf"{REV}-wave2-\d{{12}}\.md")

    def test_init_waits_for_the_previous_wave(self) -> None:
        """A wave waits for the preceding report's format, then for its decisions."""
        self.complete_wave()
        with self.assertRaisesRegex(SystemExit, "Wave 1 is not formatted yet"):
            self.run_cli("init", self.review_dir, "B")
        self.imported_assessed("correctness")
        self.run_cli("report", "format", self.report)
        with self.assertRaisesRegex(SystemExit, "Item C1 .* has no decision"):
            self.run_cli("init", self.review_dir, "B")

    def test_init_repeats_a_phase_with_lower_caps(self) -> None:
        """A repeated phase runs on the loop caps lowered by one, the loop caps standing."""
        self.decided_second_wave()
        third = review.read_metadata(self.init(self.review_dir, "A", "--repeat"))
        self.assertEqual(third.domain_caps, {"correctness": 1, "readability": 1})
        self.assertEqual(third.loop_caps["correctness"], 2)

    def test_init_refuses_a_first_repeat(self) -> None:
        """The first wave of a loop has no phase to repeat."""
        review_dir = Path(self.review_dir, "fresh")
        review_dir.mkdir()
        self.assert_cli_error("init", review_dir, "A", "--repeat")

    def test_a_later_cap_overrides_one_wave_alone(self) -> None:
        """A cap given after the first wave leaves the loop caps alone."""
        self.decided_second_wave()
        third = review.read_metadata(
            self.init(self.review_dir, "A", "--cap", "correctness=4")
        )
        self.assertEqual(third.domain_caps["correctness"], 4)
        self.assertEqual(third.loop_caps["correctness"], 2)

    def test_init_skips_an_excluded_chain(self) -> None:
        """A domain capped at zero gets no chain dir, and is not named."""
        review_dir = Path(self.review_dir, "excluded-chain")
        review_dir.mkdir()
        out = self.run_cli("init", review_dir, "B", "--cap", "docs=0")
        self.assertEqual(out.splitlines()[2:], ["tests"])
        self.assertTrue(Path(review_dir, f"{REV}-wave1-tests").is_dir())
        self.assertFalse(Path(review_dir, f"{REV}-wave1-docs").exists())

    def test_import_creates_sections_in_canonical_order(self) -> None:
        """The readability section follows the correctness one whatever the order of the calls."""
        self.capture("readability", 1)
        self.capture("correctness", 1)
        self.assertEqual(self.imported("readability"), ["R1", "R2"])
        self.assertEqual(self.imported("correctness"), ["C1", "C2"])
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
                "### R2 (run 1, item 2)",
            ],
        )
        self.assertIn("> **Bound the layer walk** — `src/build.rs:133-147`", lines)
        self.assertIn(">", lines)

    def test_import_takes_the_whole_capture(self) -> None:
        """Every item of the run lands in the report, under the heading of the id it took."""
        self.capture("correctness", 1)
        self.assertEqual(
            self.run_cli("item", "import", self.report, "correctness", 1).splitlines(),
            ["### C1 (run 1, item 1)", "### C2 (run 1, item 2)"],
        )
        self.capture("correctness", 2, ONE_ITEM)
        self.assertEqual(self.imported("correctness", 2), ["C3"])

    def test_import_rejections(self) -> None:
        """An unknown capture, an inactive domain, a second import and a broken item all fail."""
        self.capture("correctness", 1)
        self.assert_cli_error("item", "import", self.report, "correctness", 2)
        self.assert_cli_error("item", "import", self.report, "tests", 1)
        self.imported("correctness")
        self.assert_cli_error("item", "import", self.report, "correctness", 1)
        self.capture("readability", 1, "1. no title\n\nprose\n")
        self.assert_cli_error("item", "import", self.report, "readability", 1)

    def test_a_broken_item_imports_nothing(self) -> None:
        """A capture whose second item is malformed leaves the first one out too."""
        self.capture(
            "correctness",
            1,
            ONE_ITEM + "\n2. **No severity** — `a.py:1`\n\n   prose\n",
        )
        self.assert_cli_error("item", "import", self.report, "correctness", 1)
        self.assertNotIn("###", self.report.read_text())

    def test_assess_writes_the_claim_and_proposal(self) -> None:
        """The assessment lands below the quote, with the justification between its two lines."""
        self.capture("correctness", 1)
        self.assess(
            self.imported("correctness")[0],
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
        identifier = self.imported("correctness")[0]
        self.assess(identifier)
        self.assess(
            identifier,
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
        identifier = self.imported("correctness")[0]
        self.assess(
            identifier, stdin="Reproduced with:\n\n```sh\n# run it\nreview\n```"
        )
        self.decide(identifier)
        self.assertIn("**Decision**: applied — as proposed", self.report.read_text())

    def test_reassessment_replaces_a_quoting_justification(self) -> None:
        """An assessment that quotes something is replaced whole, quote included."""
        self.capture("correctness", 1)
        identifier = self.imported("correctness")[0]
        self.assess(identifier, stdin="The reviewer writes:\n\n> a quoted line")
        self.assess(identifier, stdin="Simpler after all.")
        text = self.report.read_text()
        self.assertEqual(text.count("**Claim**"), 1)
        self.assertNotIn("> a quoted line", text)

    def test_a_prose_heading_does_not_end_a_section(self) -> None:
        """The next item follows the previous one whose assessment holds a `##` line."""
        self.capture("correctness", 1)
        self.capture("correctness", 2, ONE_ITEM)
        self.assess(
            self.imported("correctness")[0], stdin="Like:\n\n```markdown\n## Items\n```"
        )
        self.imported("correctness", 2)
        lines = self.report.read_text().splitlines()
        self.assertLess(
            lines.index("**Proposal**: apply"), lines.index("### C3 (run 2, item 1)")
        )

    def test_a_fenced_item_heading_does_not_end_an_item(self) -> None:
        """An item heading inside a fenced sample leaves the assessment reachable and intact."""
        self.capture("correctness", 1)
        identifier = self.imported("correctness")[0]
        self.assess(
            identifier, stdin="Like:\n\n```markdown\n### C9 (run 3, item 1)\n```"
        )
        self.decide(identifier)
        text = self.report.read_text()
        self.assertIn("**Decision**: applied — as proposed", text)
        self.assertIn("### C9 (run 3, item 1)", text)

    def test_a_fenced_decision_does_not_decide_the_item(self) -> None:
        """A decision line inside a fenced sample does not stand for the user's decision."""
        self.complete_wave()
        first, second = self.imported("correctness")
        self.assess(
            first, stdin="Like:\n\n```markdown\n**Decision**: applied — why\n```"
        )
        self.assess(second)
        self.run_cli("report", "format", self.report)
        with self.assertRaisesRegex(SystemExit, f"Item {first} .* has no decision"):
            self.run_cli("init", self.review_dir, "B")

    def test_a_fenced_domain_heading_does_not_open_a_section(self) -> None:
        """A domain heading inside a fenced sample does not take the next domain's items."""
        self.capture("correctness", 1)
        self.capture("readability", 1, ONE_ITEM)
        self.assess(
            self.imported("correctness")[0],
            stdin="Like:\n\n```markdown\n## Readability\n```",
        )
        self.imported("readability")
        self.assertEqual(self.report.read_text().count("## Readability"), 2)

    def test_assess_argument_rules(self) -> None:
        """The parser takes a severity exactly where the claim calls for one, with the proposal's own tail."""
        self.capture("correctness", 1)
        base = ["item", "assess", self.report, self.imported("correctness")[0]]
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
            self.imported("correctness")[0],
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

    def test_assess_code_spans_a_tag_in_its_prose(self) -> None:
        """A tag named in an option or a justification reaches the report as a code span."""
        self.capture("correctness", 1)
        self.assess(
            self.imported("correctness")[0],
            "give the pack one closed <details> fold",
            "leave it out",
            severity="minor",
            proposal="your-call",
            stdin="A <details> fold costs one line.",
        )
        text = self.report.read_text()
        self.assertIn("A `<details>` fold costs one line.\n", text)
        self.assertIn("- (a) give the pack one closed `<details>` fold\n", text)

    def test_decide(self) -> None:
        """A decision needs an assessment, reads stdin, and links the ids in its reason."""
        self.capture("correctness", 1)
        self.imported("correctness")
        self.assert_cli_error(
            "item", "decide", self.report, "C1", "--verdict", "applied", stdin="x"
        )
        self.assess("C1", stdin="Confirmed.")
        self.decide("C1", "applied-with-changes", "folded into C1's fix")
        text = self.report.read_text()
        self.assertIn(
            "**Decision**: applied with changes — folded into "
            "[C1](#c1-run-1-item-1)'s fix\n",
            text,
        )

    def test_blank_prose_is_refused(self) -> None:
        """A justification or a reason made of whitespace is refused, and nothing is written."""
        self.capture("correctness", 1)
        identifier = self.imported("correctness")[0]
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
        self.imported_assessed("correctness")
        self.decide("C1")
        self.decide("C1", "declined", "reverted afterwards")
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
        first, second = self.imported("correctness")
        self.assess(first)
        self.assess(
            second,
            "bound it in the caller",
            claim="partly-holds",
            proposal="apply-with-changes",
            stdin="Only the retry path can overrun it.",
        )
        third, fourth = self.imported("readability")
        self.assess(
            third,
            "C1 already covers it",
            claim="does-not-hold",
            severity=None,
            proposal="decline",
            stdin="Subsumed by C1.",
        )
        self.assess(
            fourth,
            "split it",
            "leave it",
            severity="minor",
            proposal="your-call",
            stdin="Both are defensible.",
        )
        recap = self.run_cli("report", "format", self.report)
        self.assertEqual(
            recap,
            "4 items · 1 apply · 1 apply with changes · 1 decline · 1 your call\n\n"
            "- apply: C1\n- apply with changes: C2\n"
            "- decline: R1\n- your call: R2\n",
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
        first, second = self.imported("correctness")
        with self.assertRaisesRegex(SystemExit, "C1 has no single claim"):
            self.run_cli("report", "format", self.report)
        self.assess(first)
        with self.assertRaisesRegex(SystemExit, "C2 has no single claim"):
            self.run_cli("report", "format", self.report)
        self.assess(second)
        self.assertEqual(
            self.run_cli("report", "format", self.report),
            "2 items · 2 apply\n\n- apply: C1, C2\n",
        )

    def test_findings_on_the_cap_run_are_complete(self) -> None:
        """A chain that finds items on its last allowed run has run to its end."""
        self.capture("correctness", 1, ONE_ITEM)
        self.capture("correctness", 2, ONE_ITEM)
        self.capture("readability", 1, "Nothing to report.\n")
        self.imported_assessed("correctness", 1)
        self.imported_assessed("correctness", 2)
        self.assertEqual(
            self.run_cli("report", "format", self.report),
            "2 items · 2 apply\n\n- apply: C1, C2\n",
        )

    def test_an_excluded_domain_is_not_awaited(self) -> None:
        """Formatting waits only on the chains of the domains the caps left active."""
        review_dir = Path(self.review_dir, "excluded")
        review_dir.mkdir()
        report = self.init(review_dir, "B", "--cap", "docs=0")
        Path(review_dir, f"{REV}-wave1-tests", "run1.md").write_text("Nothing yet.\n")
        self.assertEqual(self.run_cli("report", "format", report), "")
        self.assertIn(
            "- **Config**: tests ≤1 · docs =0", report.read_text().splitlines()
        )

    def test_format_runs_again_over_its_own_output(self) -> None:
        """Formatting a formatted report replaces its top part and index."""
        self.complete_wave()
        first, second = self.imported("correctness")
        self.assess(first)
        self.assess(second, stdin="# Review wave 2 — example\n")
        self.run_cli("report", "format", self.report)
        self.assess(first, "not worth it", proposal="decline")
        self.run_cli("report", "format", self.report)
        lines = self.report.read_text().splitlines()
        self.assertEqual(lines.count(f"# Review wave 1 — {REV}"), 1)
        self.assertEqual(lines.count("## Items"), 1)
        self.assertIn("  - [C1 / major / holds, decline](#c1-run-1-item-1)", lines)

    def test_format_signs_the_report(self) -> None:
        """A footer naming the skill and the time of the format closes the report."""
        self.complete_wave()
        self.imported_assessed("correctness")
        self.run_cli("report", "format", self.report)
        self.assertRegex(
            self.report.read_text().splitlines()[-1],
            r'^<p style="[^"]+">generated by <a href="https://github\.com/desbma/'
            r'agent-skills/tree/master/review-auto-loop">review-auto-loop</a> on '
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}</p>$",
        )

    def test_format_replaces_its_own_footer(self) -> None:
        """Formatting a formatted report leaves one footer, still closing it."""
        self.complete_wave()
        self.imported_assessed("correctness")
        self.run_cli("report", "format", self.report)
        self.run_cli("report", "format", self.report)
        lines = self.report.read_text().splitlines()
        self.assertEqual([line for line in lines if line.startswith("<p ")], lines[-1:])

    def test_report_format_without_items(self) -> None:
        """A wave that yielded nothing gets its top part, no index and no recap."""
        self.capture("correctness", 1, "No item to report.\n")
        self.capture("readability", 1, "No item to report.\n")
        self.assertEqual(self.run_cli("report", "format", self.report), "")
        lines = self.report.read_text().splitlines()
        self.assertEqual(lines[2], f"# Review wave 1 — {REV}")
        self.assertNotIn("## Items", lines)

    def test_recap_counts_a_single_item(self) -> None:
        """The item count of a one-item wave reads as a singular."""
        self.capture("correctness", 1, ONE_ITEM)
        self.capture("correctness", 2, "Nothing to report.\n")
        self.capture("readability", 1, "Nothing to report.\n")
        self.imported_assessed("correctness")
        self.assertEqual(
            self.run_cli("report", "format", self.report),
            "1 item · 1 apply\n\n- apply: C1\n",
        )

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
        self.assertEqual(self.jj["diff_summary"].call_args.args, (CHANGE_ID,))
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
        identifier = self.imported("tests", 1, second)[0]
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

    def test_decide_writes_above_the_footer(self) -> None:
        """A decision on the last item of a formatted report leaves the footer closing it."""
        self.complete_wave()
        identifiers = self.imported_assessed("correctness")
        self.run_cli("report", "format", self.report)
        self.decide(identifiers[-1])
        lines = self.report.read_text().splitlines()
        self.assertTrue(lines[-1].startswith("<p "))
        self.assertEqual(lines[-3], "**Decision**: applied — as proposed")

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
        self.assertEqual(metadata.loop_caps["tests"], 1)

    def test_metadata_rejections(self) -> None:
        """A report without the comment, without loop caps, or disagreeing with its name, is refused."""
        stray = Path(self.review_dir, f"{REV}-wave3-202608261252.md")
        loop = "loop=correctness:1,readability:1,tests:1,docs:1"
        caps = "correctness=1 readability=1 -->\n"
        for text in (
            "# Not a wave report\n",
            f"<!-- review: change_id={CHANGE_ID} wave=3 {caps}",
            f"<!-- review: change_id={CHANGE_ID} wave=2 {loop} {caps}",
            f"<!-- review: change_id=uqrvytospqyktvkspnpkmrnwpykoqotx wave=3 {loop} {caps}",
        ):
            stray.write_text(text)
            self.assertRaises(SystemExit, review.read_metadata, stray)


class ChainRunTest(WaveFixture):
    """Running a chain's next review and capturing its output."""

    def run_chain(self, domain: str, output: str = ONE_ITEM, status: int = 0) -> str:
        """Run a chain with the reviewer replaced by one writing the given output."""

        def reviewer(
            argv: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            kwargs["stdout"].write(output)
            return subprocess.CompletedProcess(argv, status)

        with (
            mock.patch.object(review, "jj_output", return_value="/repo\n"),
            mock.patch.object(review.subprocess, "run", side_effect=reviewer) as spawn,
        ):
            printed = self.run_cli("chain", "run", self.report, domain)
        self.spawn = spawn
        return printed

    def test_it_captures_the_reviewer_output(self) -> None:
        """The capture takes the run's name once the reviewer is through, and is named."""
        capture = Path(self.chain("correctness"), "run1.md")
        self.assertEqual(self.run_chain("correctness").strip(), str(capture))
        self.assertEqual(capture.read_text(), ONE_ITEM)
        self.assertEqual(list(self.chain("correctness").iterdir()), [capture])

    def test_it_runs_the_reviewer_over_the_change(self) -> None:
        """The reviewer runs from the repository root, on the change, over the chain dir."""
        self.run_chain("readability")
        argv = self.spawn.call_args.args[0]
        self.assertEqual(argv[0], "pi")
        self.assertIn(str(review.SKILLS_DIR / "review-readability"), argv)
        self.assertIn(CHANGE_ID, argv[-1])
        self.assertIn(str(self.chain("readability")), argv[-1])
        self.assertEqual(self.spawn.call_args.kwargs["cwd"], "/repo")

    def test_the_prompt_names_the_chain_dir_absolutely(self) -> None:
        """The reviewer runs from the repository root, so a relative report must still reach it."""

        def reviewer(
            argv: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            kwargs["stdout"].write(ONE_ITEM)
            return subprocess.CompletedProcess(argv, 0)

        with (
            contextlib.chdir(self.review_dir),
            mock.patch.object(review, "jj_output", return_value="/repo\n"),
            mock.patch.object(review.subprocess, "run", side_effect=reviewer) as spawn,
        ):
            self.run_cli("chain", "run", self.report.name, "correctness")
        self.assertIn(str(self.chain("correctness")), spawn.call_args.args[0][-1])

    def test_a_marker_created_after_the_scan_stops_the_run(self) -> None:
        """Two runs racing past the in-flight check do not share one capture."""
        marker = self.running("correctness", 1)
        marker.write_text("the winner's output")
        with (
            mock.patch.object(review, "scan_review_dir", return_value=({}, {})),
            mock.patch.object(review, "jj_output", return_value="/repo\n"),
            mock.patch.object(review.subprocess, "run") as spawn,
            self.assertRaises(SystemExit),
        ):
            self.run_cli("chain", "run", self.report, "correctness")
        spawn.assert_not_called()
        self.assertEqual(marker.read_text(), "the winner's output")

    def test_a_malformed_capture_is_kept_for_repair(self) -> None:
        """Output the format check refuses never becomes a run, and is kept under its own name."""
        with self.assertRaises(SystemExit) as caught:
            self.run_chain("correctness", output="1. no bold title\n")
        rejected = Path(self.chain("correctness"), f"run1.md{review.REJECTED_SUFFIX}")
        self.assertEqual(list(self.chain("correctness").iterdir()), [rejected])
        self.assertEqual(rejected.read_text(), "1. no bold title\n")
        self.assertIn(str(rejected), str(caught.exception))

    def test_a_rejected_capture_does_not_count_as_a_run(self) -> None:
        """The wave still reads, and the chain retries the run the rejected output failed."""
        with self.assertRaises(SystemExit):
            self.run_chain("correctness", output="1. no bold title\n")
        self.run_cli("header", "show", self.report, 1)
        self.run_chain("correctness")
        chain = self.chain("correctness")
        self.assertEqual(Path(chain, "run1.md").read_text(), ONE_ITEM)
        self.assertTrue(Path(chain, f"run1.md{review.REJECTED_SUFFIX}").is_file())

    def test_a_failed_run_leaves_nothing_behind(self) -> None:
        """A reviewer exiting non-zero takes its exit code and leaves no capture."""
        with self.assertRaises(SystemExit) as caught:
            self.run_chain("correctness", status=3)
        self.assertEqual(caught.exception.code, 3)
        self.assertEqual(list(self.chain("correctness").iterdir()), [])

    def test_a_reviewer_that_never_starts_leaves_nothing_behind(self) -> None:
        """A reviewer the system cannot spawn leaves no capture standing in for a run."""
        with (
            mock.patch.object(review, "jj_output", return_value="/repo\n"),
            mock.patch.object(review.subprocess, "run", side_effect=FileNotFoundError),
            self.assertRaises(FileNotFoundError),
        ):
            self.run_cli("chain", "run", self.report, "correctness")
        self.assertEqual(list(self.chain("correctness").iterdir()), [])

    def test_the_next_run_follows_the_captures(self) -> None:
        """A second run of the chain writes the second capture."""
        self.run_chain("correctness")
        self.run_chain("correctness")
        self.assertTrue(Path(self.chain("correctness"), "run2.md").is_file())

    def test_refusals(self) -> None:
        """An inactive domain and a run already in flight are refused."""
        self.assert_cli_error("chain", "run", self.report, "tests")
        self.running("correctness", 1)
        self.assert_cli_error("chain", "run", self.report, "correctness")

    def test_a_chain_that_ended_reports_its_end(self) -> None:
        """A chain out of items or at its cap says so and runs nothing."""
        self.capture("correctness", 1, "Nothing to report.\n")
        self.assertEqual(
            self.run_cli("chain", "run", self.report, "correctness"),
            "Chain correctness ends: run 1 found no item\n",
        )
        self.capture("readability", 1)
        self.capture("readability", 2)
        self.assertEqual(
            self.run_cli("chain", "run", self.report, "readability"),
            "Chain readability ends: it has reached its cap of 2\n",
        )


class WorkflowTest(CliFixture):
    """A whole loop of waves, driven only through the command line."""

    def setUp(self) -> None:
        """Sandbox a review dir, a repository root, and a stub reviewer on PATH."""
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.review_dir, self.bin = root / "reviews", root / "bin"
        self.review_dir.mkdir()
        self.bin.mkdir()
        self.output = self.bin / "output"
        stub = self.bin / "pi"
        stub.write_text(f'#!/bin/sh\ncat "{self.output}"\n')
        stub.chmod(0o755)
        self.enterContext(
            mock.patch.dict(os.environ, {"PATH": f"{self.bin}:{os.environ['PATH']}"})
        )
        jj = self.enterContext(
            mock.patch.multiple(
                review,
                resolve_change_id=mock.DEFAULT,
                diff_summary=mock.DEFAULT,
                jj_output=mock.DEFAULT,
            )
        )
        jj["resolve_change_id"].return_value = CHANGE_ID
        jj["diff_summary"].return_value = "3 files changed, 560 insertions(+)"
        jj["jj_output"].return_value = f"{root}\n"

    def open_wave(self, *argv: Any) -> tuple[Path, list[str]]:
        """Open a wave, returning its report and the domains it says it opened a chain for."""
        printed = self.run_cli(
            "init", self.review_dir, *argv, "--revision", CHANGE_ID
        ).splitlines()
        self.assertEqual(printed[0], CHANGE_ID)
        return Path(printed[1]), printed[2:]

    def review_run(self, report: Path, domain: str, output: str) -> str:
        """Run a chain once, the stub reviewer writing the given output."""
        self.output.write_text(output)
        return self.run_cli("chain", "run", report, domain)

    def chain_to_its_end(
        self, report: Path, domain: str, *outputs: str
    ) -> tuple[list[str], str]:
        """Run a chain over successive reviewer outputs, importing and assessing each run."""
        identifiers = []
        for run, output in enumerate(outputs, start=1):
            self.review_run(report, domain, output)
            self.run_cli("header", "show", report, run)
            for line in self.run_cli(
                "item", "import", report, domain, run
            ).splitlines():
                identifiers.append(line.split()[1])
        for identifier in identifiers:
            self.run_cli(
                "item",
                "assess",
                report,
                identifier,
                "holds",
                "major",
                "apply",
                stdin="The code confirms it.",
            )
        return identifiers, self.review_run(report, domain, "")

    def decide_and_format(self, report: Path, identifiers: list[str]) -> str:
        """Format the wave, then decide every item it holds."""
        recap = self.run_cli("report", "format", report)
        for identifier in identifiers:
            self.run_cli(
                "item",
                "decide",
                report,
                identifier,
                "--verdict",
                "applied",
                stdin="as proposed",
            )
        return recap

    def test_a_loop_of_three_waves(self) -> None:
        """Three waves run end to end, the second phase following the first and repeating it after."""
        first = self.wave_one()
        second = self.wave_two(first)
        self.wave_three(second)

    def wave_one(self) -> Path:
        """Phase A, one chain running out of items before its cap and the other reaching it."""
        report, domains = self.open_wave("A", "--cap", "correctness=3")
        self.assertEqual(domains, ["correctness", "readability"])
        self.assert_cli_error("report", "format", report)
        code, ended = self.chain_to_its_end(
            report, "correctness", CAPTURE, "Nothing to report.\n"
        )
        self.assertEqual(code, ["C1", "C2"])
        self.assertEqual(ended, "Chain correctness ends: run 2 found no item\n")
        prose, ended = self.chain_to_its_end(report, "readability", ONE_ITEM, ONE_ITEM)
        self.assertEqual(prose, ["R1", "R2"])
        self.assertEqual(ended, "Chain readability ends: it has reached its cap of 2\n")
        self.run_cli("header", "show", report, 2)
        recap = self.decide_and_format(report, code + prose)
        self.assertIn("4 items · 4 apply", recap)
        return report

    def wave_two(self, first: Path) -> Path:
        """Phase B over the same change, its two domains capped at one run each."""
        report, domains = self.open_wave("B")
        self.assertEqual(domains, ["tests", "docs"])
        self.assertNotEqual(report, first)
        tests, ended = self.chain_to_its_end(report, "tests", ONE_ITEM)
        self.assertEqual(tests, ["T1"])
        self.assertEqual(ended, "Chain tests ends: it has reached its cap of 1\n")
        docs, _ = self.chain_to_its_end(report, "docs", "Nothing to report.\n")
        self.assertEqual(docs, [])
        self.decide_and_format(report, tests)
        return report

    def wave_three(self, second: Path) -> Path:
        """Phase A again on lowered caps, over a reviewer that drifts from the format once."""
        report, _ = self.open_wave("A", "--repeat")
        self.assertEqual(
            review.read_metadata(report).domain_caps,
            {"correctness": 2, "readability": 1},
        )
        with self.assertRaises(SystemExit) as caught:
            self.review_run(report, "correctness", "1. no bold title\n")
        chain = report.parent / f"{REV}-wave3-correctness"
        rejected = chain / f"run1.md{review.REJECTED_SUFFIX}"
        self.assertIn(str(rejected), str(caught.exception))
        self.assertEqual(rejected.read_text(), "1. no bold title\n")
        self.run_cli("header", "show", report, 1)
        code, ended = self.chain_to_its_end(
            report, "correctness", ONE_ITEM, "Nothing to report.\n"
        )
        self.assertEqual(code, ["C3"])
        self.assertEqual(ended, "Chain correctness ends: it has reached its cap of 2\n")
        self.assertTrue(rejected.is_file())
        self.assertEqual(Path(chain, "run1.md").read_text(), ONE_ITEM)
        self.chain_to_its_end(report, "readability", "Nothing to report.\n")
        self.decide_and_format(report, code)
        self.assertNotEqual(report, second)
        return report


class EntryPointTest(unittest.TestCase):
    """The script as the executable the skill runs."""

    def test_the_executable_dispatches_a_command(self) -> None:
        """Running the file itself reaches the subcommand its arguments name."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp, "missing")
            completed = subprocess.run(
                [SCRIPT, "init", missing, "A"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(f"No such review dir: {missing}", completed.stderr)


if __name__ == "__main__":
    unittest.main()
