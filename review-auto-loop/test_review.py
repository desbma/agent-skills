#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["markdown-it-py", "tabulate"]
# ///
"""Tests for the review wave report builder."""

import argparse
import contextlib
import importlib.util
import io
import os
import re
import subprocess
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any, ClassVar
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
ASSESSOR = "Opus 5 xhigh"
TARGETS = {"C7": "#c7-run-2-item-1", "R2": "wave1.md#r2-run-1-item-2"}
LINKED = "[C7](#c7-run-2-item-1)"

ONE_ITEM = """\
1. **Bound the layer walk** — `src/build.rs:133-147`

   **Severity**: major

   **Issue**:

   The builder walks an unbounded stack.

   **Proposed change**:

   ```rust
   3. not an item
   ensure!(stack.len() <= MAX, "too many layers");
   ```

   **Estimated delta**: +8 lines
"""

CAPTURE = f"""\
Reviewing the changes.

{ONE_ITEM}
2. **Drop the unused branch** — `src/read.rs:20`

   **Severity**: minor

   **Issue**:

   Nothing reaches it.

   **Proposed change**:

   Delete it.

   **Estimated delta**: -12 lines
"""

SUMMARY = "The change bounds the layer walk, and drops a branch nothing reaches.\n"
DIFF = "Author: A\n\n    bound the walk\n\nM src/build.rs\n"

ISSUE, CHANGE = "**Issue**:\n\nprose", "**Proposed change**:\n\nprose"
GOOD_ITEM = (
    f"**T** — `a.py:1`\n\n**Severity**: major\n\n{ISSUE}\n\n{CHANGE}\n\n"
    "**Estimated delta**: +1 lines"
)
SECOND_FINDING = (
    "**Drop the unused branch** — `src/read.rs:20`\n\n**Severity**: minor\n\n"
    "**Issue**:\n\nNothing reaches it.\n\n**Proposed change**:\n\nDelete it.\n\n"
    "**Estimated delta**: -1 lines\n"
)


class RawReviewTest(unittest.TestCase):
    """Reading items out of a reviewer capture."""

    def test_spans_ignore_fenced_lines(self) -> None:
        """Skip a numbered line inside a code fence instead of opening an item."""
        self.assertEqual(sorted(review.reviewer_item_spans(CAPTURE)), [1, 2])

    def test_item_is_dedented_and_unmarked(self) -> None:
        """Strip an item's list marker and the indentation of its continuation."""
        item = review.reviewer_items(CAPTURE)[1]
        self.assertTrue(item.startswith("**Bound the layer walk** — `src/build.rs"))
        self.assertIn("\n**Severity**: major\n", item)
        self.assertIn("\n```rust\n", item)
        self.assertTrue(item.endswith("**Estimated delta**: +8 lines"))

    def test_nested_numbers_are_not_items(self) -> None:
        """Keep a numbered list inside an item from opening one."""
        text = "1. **First**\n\n   1. read it\n   2. write it\n\n2. **Second**"
        self.assertEqual(sorted(review.reviewer_item_spans(text)), [1, 2])
        self.assertTrue(review.reviewer_items(text)[2].startswith("**Second**"))

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
        """Reject an item without a title, without a label, with one twice, or with one out of its own paragraph."""
        capture = Path("run1.md")
        review.check_reviewer_item(GOOD_ITEM, capture, 1)
        for broken in (
            GOOD_ITEM.replace("**T** — `a.py:1`", "no title here"),
            GOOD_ITEM.replace("**Severity**: major\n\n", ""),
            GOOD_ITEM.replace("`a.py:1`\n\n**Severity**", "`a.py:1`\n**Severity**"),
            GOOD_ITEM.replace("**Severity**: major\n\n", "**Severity**: major\n"),
            GOOD_ITEM.replace(f"{ISSUE}\n\n", ""),
            GOOD_ITEM.replace(f"{CHANGE}\n\n", ""),
            GOOD_ITEM.replace(ISSUE, "**Issue**:\nprose"),
            GOOD_ITEM.replace(CHANGE, "**Proposed change**:\nprose"),
            GOOD_ITEM.replace("\n\n**Estimated delta**: +1 lines", ""),
            GOOD_ITEM.replace("\n\n**Estimated delta**", "\n**Estimated delta**"),
            GOOD_ITEM.replace("+1 lines", "bananas"),
            GOOD_ITEM.replace(ISSUE, "**Issue**:"),
            GOOD_ITEM.replace(CHANGE, "**Proposed change**:"),
            f"{GOOD_ITEM}\n\n{SECOND_FINDING}",
        ):
            with self.assertRaises(SystemExit):
                review.check_reviewer_item(broken, capture, 1)

    def test_format_checks_accept_every_delta_form(self) -> None:
        """Accept a zero count, a singular unit, and a range carrying a qualifier."""
        capture = Path("run1.md")
        for delta in (
            "0 lines",
            "-1 line",
            "+8 to 15 lines including a regression test",
        ):
            review.check_reviewer_item(GOOD_ITEM.replace("+1 lines", delta), capture, 1)

    def test_format_checks_name_the_form_they_want(self) -> None:
        """Report a label written in another shape as the form the item lacks, not as a missing block."""
        capture = Path("run1.md")
        for old, new, form in (
            ("major", "high", "**Severity**: <critical, major or minor>"),
            (ISSUE, "**Issue**: prose", "**Issue**:"),
            (CHANGE, "**Proposed change**: prose", "**Proposed change**:"),
            (
                "**Estimated delta**:",
                "**Estimated delta:**",
                "**Estimated delta**: <count> lines",
            ),
        ):
            with self.assertRaises(SystemExit) as caught:
                review.check_reviewer_item(GOOD_ITEM.replace(old, new), capture, 1)
            self.assertIn(f'"{form}"', str(caught.exception))

    def test_format_checks_read_the_labels_outside_fences(self) -> None:
        """Take a label inside a fenced sample as neither the item's own nor a substitute for it."""
        capture = Path("run1.md")
        fence = "```markdown\n**Issue**:\n\n**Estimated delta**: +1 lines\n```"
        sample = GOOD_ITEM.replace(CHANGE, f"**Proposed change**:\n\n{fence}")
        review.check_reviewer_item(sample, capture, 1)
        for broken in (
            sample.replace(f"{ISSUE}\n\n", ""),
            sample.removesuffix("\n\n**Estimated delta**: +1 lines"),
        ):
            with self.assertRaises(SystemExit):
                review.check_reviewer_item(broken, capture, 1)

    def test_quote(self) -> None:
        """Prefix every line with the blockquote marker, a blank one becoming a bare marker."""
        self.assertEqual(review.quote("a\n\nb"), ["> a", ">", "> b"])

    def test_quote_leaves_a_fenced_block_alone(self) -> None:
        """Keep a fenced block's tags and hash lines, neutralizing the prose around it."""
        self.assertEqual(
            review.quote("A <details> fold.\n\n```python\n# a <details> fold\n```"),
            [
                "> A `<details>` fold.",
                ">",
                "> ```python",
                "> # a <details> fold",
                "> ```",
            ],
        )

    def test_quote_neutralizes_markup(self) -> None:
        """Strip a heading's marker, and keep the HTML around it from reaching the report live."""
        for item, quoted in (
            ("## A <details> fold", "> A `<details>` fold"),
            ("##\tA <details> fold", "> A `<details>` fold"),
            ("- [the <details> fold](x)", "> - [the `<details>` fold](x)"),
            ("> quoting a <details> fold", "> > quoting a `<details>` fold"),
            ("<!-- a <details> fold -->", "> `<!-- a <details> fold -->`"),
            (
                "<!-- a fold\nspanning two lines -->",
                "> `<!-- a fold`\n> spanning two lines -->",
            ),
            ("<details\n  open>", "> &lt;details\n>   open>"),
            (r"\<!-- a note -->", r"> \<!-- a note -->"),
            (r"a \<details> fold", r"> a \<details> fold"),
        ):
            self.assertEqual(review.quote(item), quoted.splitlines())


class RenderProseTest(unittest.TestCase):
    """Linking the item ids mentioned in prose, and code-spanning the tags it names."""

    def render(self, line: str) -> str:
        """Return the line after the prose pass."""
        return review.render_prose([line], TARGETS)[0]

    def test_known_ids_become_links(self) -> None:
        """Link an id with a heading in the change to it, across reports too."""
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
            "#### C7 (run 2, item 1)",
            "the `C7` symbol",
            "the ``C7`` symbol",
            "the `<details>` element",
            "at <https://example.test/C7>",
            "already [C7](#c7-run-2-item-1)",
            "already [the `<details>` fold](#c7-run-2-item-1)",
        ):
            self.assertEqual(self.render(line), line)

    def test_tags_become_code_spans(self) -> None:
        """Code-span a tag the prose names, so the renderer displays it."""
        self.assertEqual(
            self.render("one closed <details> before the index"),
            "one closed `<details>` before the index",
        )
        for line, rendered in (
            ("</details>", "`</details>`"),
            ("<br/>", "`<br/>`"),
            ('<div class="x">', '`<div class="x">`'),
            ("Vec<u8>", "Vec`<u8>`"),
            ("a stray <!-- note --> in prose", "a stray `<!-- note -->` in prose"),
            ("<!-- unclosed", "`<!-- unclosed`"),
            ("[C7 and <details>](x)", "[C7 and `<details>`](x)"),
        ):
            self.assertEqual(self.render(line), rendered)

    def test_an_opening_angle_alone_is_escaped(self) -> None:
        """Escape an angle no tag closes, so a tag split over two lines cannot open one."""
        self.assertEqual(self.render("a <details"), "a &lt;details")

    def test_angle_spans_that_are_no_tags(self) -> None:
        """Leave an autolink and a bare comparison alone."""
        for line in (
            "<user@example.test>",
            "the <T: Clone> bound",
            "a < b and c > d",
            r"an escaped \<details> fold",
        ):
            self.assertEqual(self.render(line), line)

    def test_a_spanned_tag_is_stable(self) -> None:
        """Leave an already spanned tag alone on a second pass."""
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
        """Return the diff stat as its last line, for the revision asked."""
        stat = "M review\n 2 files changed, 30 insertions(+)"
        with mock.patch.object(review, "jj_output", return_value=stat) as jj_output:
            self.assertEqual(
                review.diff_summary("@-"), " 2 files changed, 30 insertions(+)"
            )
        self.assertIn("@-", jj_output.call_args.args[0])

    def test_a_single_change(self) -> None:
        """Give the id of a revision matching one change, and reach the jj command with it."""
        with mock.patch.object(
            review, "jj_output", return_value=f"{CHANGE_ID}\n"
        ) as jj_output:
            self.assertEqual(review.resolve_change_id("@-"), CHANGE_ID)
        self.assertIn("@-", jj_output.call_args.args[0])

    def test_anything_else(self) -> None:
        """Refuse a revset matching several changes, or none."""
        for out in (f"{CHANGE_ID}\n{CHANGE_ID}\n", ""):
            with mock.patch.object(review, "jj_output", return_value=out):
                self.assertRaises(SystemExit, review.resolve_change_id, "@ | @-")


class AssessHelpTest(unittest.TestCase):
    """The help of the assess command, where a refused invocation looks next."""

    def test_it_lists_every_form(self) -> None:
        """Spell out every claim and proposal pair, with the tail it takes."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            review.build_parser().parse_args(["item", "assess", "--help"])
        body = out.getvalue().split("forms:\n", 1)[1]
        forms = [
            line.partition(" id ")[2] for line in body.splitlines() if line.strip()
        ]
        rated = "{critical,major,minor}"
        claims = (f"holds {rated}", f"partly-holds {rated}", "does-not-hold")
        proposals = (
            "apply [DELTA]",
            "apply-with-changes ACTION DELTA",
            "decline REASON",
            "your-call OPTION OPTION [OPTION ...]",
        )
        self.assertEqual(
            forms, [f"{claim} {proposal}" for claim in claims for proposal in proposals]
        )


class CapsTest(unittest.TestCase):
    """Reading the domain caps of a wave off the command line."""

    def test_caps_take_the_canonical_domain_order(self) -> None:
        """Return the caps in canonical domain order, whatever the order given."""
        self.assertEqual(
            list(review.parse_domain_caps(["readability=3", "correctness=2"]).items()),
            [("correctness", 2), ("readability", 3)],
        )
        self.assertEqual(
            list(review.parse_domain_caps(["docs=0", "tests=1"]).items()),
            [("tests", 1), ("docs", 0)],
        )

    def test_a_wave_holds_the_domains_it_names(self) -> None:
        """Domains no phase groups, and a domain on its own, carry their caps."""
        self.assertEqual(
            list(review.parse_domain_caps(["tests=1", "readability=2"]).items()),
            [("readability", 2), ("tests", 1)],
        )
        self.assertEqual(review.parse_domain_caps(["docs=1"]), {"docs": 1})

    def test_rejections(self) -> None:
        """Refuse a wave without a domain, one fully excluded, and malformed pairs."""
        for pairs in (
            [],
            ["correctness=0", "readability=0"],
            ["correctness=1", "correctness=2"],
            ["correctness", "readability=1"],
            ["correctness=x", "readability=1"],
        ):
            with self.assertRaises(SystemExit):
                review.parse_domain_caps(pairs)

    def test_loop_caps_cover_every_domain(self) -> None:
        """Read the loop caps of a review comment back in canonical order."""
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
        """Derive the loop caps from a diff stat summary."""
        with mock.patch.object(review, "diff_summary", return_value=summary):
            return review.derive_loop_caps(CHANGE_ID)

    def test_the_code_domains_scale_with_the_insertions(self) -> None:
        """Scale the correctness and readability caps with the lines the change adds."""
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
        """Read a summary without an insertion count as no line added."""
        self.assertEqual(self.caps("1 file changed, 40 deletions(-)")["correctness"], 1)

    def test_an_unreadable_summary_is_refused(self) -> None:
        """Fail on a last diff stat line that is not a summary, instead of counting zero."""
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


class DeltaTextTest(unittest.TestCase):
    """Line counts as a proposal states them."""

    def test_it_signs_every_count_but_zero(self) -> None:
        """Sign every count but zero, and follow its magnitude with the unit."""
        for delta, rendered in ((4, "+4 lines"), (-1, "-1 line"), (0, "0 lines")):
            self.assertEqual(review.delta_text(delta), rendered)


class LetteredOptionsTest(unittest.TestCase):
    """Lettering the options a your call offers."""

    def lettered(self, count: int) -> list[str]:
        """Letter that many options, the two first taken apart as the parser takes them."""
        options = [f"option {number}" for number in range(count)]
        return review.lettered_options(
            argparse.Namespace(option=options[:2], more=options[2:])
        )

    def test_the_options_are_lettered_in_order(self) -> None:
        """Letter each option from a, in the order it was given."""
        self.assertEqual(self.lettered(26)[-1], "(z) option 25")

    def test_an_option_past_the_alphabet_is_refused(self) -> None:
        """Fail on an option the alphabet cannot letter, instead of lettering it outside it."""
        self.assertRaises(IndexError, self.lettered, 27)


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

    def run_init(self, *argv: Any, assessor: str = ASSESSOR) -> str:
        """Open a wave under an assessor and return what it printed."""
        return self.run_cli("init", *argv, "--assessor", assessor)

    def run_with_agent(self, *argv: Any, output: str, status: int = 0) -> str:
        """Run a subcommand with the agent replaced by one writing the given output."""

        def jj(args: list[str]) -> str:
            return "/repo\n" if args == ["root"] else DIFF

        def agent(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            kwargs["stdout"].write(output)
            return subprocess.CompletedProcess(args, status)

        with (
            mock.patch.object(review, "jj_output", side_effect=jj),
            mock.patch.object(review.subprocess, "run", side_effect=agent) as spawn,
        ):
            self.spawn = spawn
            return self.run_cli(*argv)


class WaveFixture(CliFixture):
    """A review dir carrying one phase A wave, and the helpers driving it."""

    init_args: tuple[str, ...] = ()

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
            *self.init_args,
        )

    def init(self, *argv: Any, assessor: str = ASSESSOR) -> Path:
        """Open a wave and return the report path it printed."""
        return Path(self.run_init(*argv, assessor=assessor).splitlines()[1])

    def chain(self, domain: str) -> Path:
        """Return the chain dir of a domain of the wave."""
        return Path(self.review_dir, f"{REV}-wave1-{domain}")

    def capture(self, domain: str, run: int, text: str = CAPTURE) -> None:
        """Write a completed chain capture for a run of the wave."""
        Path(self.chain(domain), f"run{run}.md").write_text(text)

    def running(self, domain: str, run: int) -> Path:
        """Write the capture of a run still in flight."""
        capture = Path(self.chain(domain), f"run{run}.md{review.RUNNING_SUFFIX}")
        capture.write_text("")
        return capture

    def write_summary(self, report: Path | None = None, text: str = SUMMARY) -> Path:
        """Write a wave's change summary, as a completed summary run would."""
        path = review.summary_path(
            review.read_metadata(self.report if report is None else report)
        )
        path.write_text(text)
        return path

    def complete_wave(self) -> None:
        """Give both chains of the wave an end, the correctness one holding the items."""
        self.capture("correctness", 1)
        self.capture("correctness", 2, "Nothing to report.\n")
        self.capture("readability", 1, "Nothing to report.\n")
        self.write_summary()

    def ready(self) -> list[str]:
        """Run the wave to where its report can be formatted: every chain ended, every item assessed."""
        self.complete_wave()
        return self.imported_assessed("correctness")

    def judge(
        self, *identifiers: str, output: str | None = None, report: Path | None = None
    ) -> str:
        """Run a wave's judge, the agent agreeing with every item unless another output is given."""
        agreed = "\n\n".join(f"**{identifier}**: agree" for identifier in identifiers)
        return self.run_with_agent(
            "judge",
            "run",
            self.report if report is None else report,
            output=agreed if output is None else output,
        )

    def judge_if_due(self, *identifiers: str, report: Path | None = None) -> None:
        """Run the judge of a wave whose loop enabled one."""
        target = self.report if report is None else report
        if review.read_metadata(target).judge is not None:
            self.judge(*identifiers, report=target)

    def second_wave(self, assessor: str = ASSESSOR) -> Path:
        """Run wave 1 to its decisions in production order, then open a phase B wave over it."""
        identifiers = self.ready()
        self.judge_if_due(*identifiers)
        self.run_cli("report", "format", self.report)
        for identifier, verdict in zip(
            identifiers, ("applied", "applied-with-changes")
        ):
            self.decide(identifier, verdict)
        second = self.init(self.review_dir, "B", assessor=assessor)
        Path(self.review_dir, f"{REV}-wave2-tests", "run1.md").write_text(ONE_ITEM)
        self.write_summary(second)
        return second

    def decided_second_wave(self) -> Path:
        """Run the phase B wave to its decision too, so a third wave can open over it."""
        second = self.second_wave()
        Path(self.review_dir, f"{REV}-wave2-docs", "run1.md").write_text("Nothing.\n")
        identifier = self.imported("tests", 1, second)[0]
        self.assess(identifier, report=second)
        self.judge_if_due(identifier, report=second)
        self.run_cli("report", "format", second)
        self.decide(identifier, report=second)
        return second

    def third_wave(self, *judge: str) -> Path:
        """Open a phase A wave over two decided ones, its correctness chain holding the items."""
        third = self.init(self.review_dir, "A", *judge)
        chain = Path(self.review_dir, f"{REV}-wave3-correctness")
        Path(chain, "run1.md").write_text(CAPTURE)
        Path(chain, "run2.md").write_text("Nothing.\n")
        Path(self.review_dir, f"{REV}-wave3-readability", "run1.md").write_text(
            "Nothing.\n"
        )
        self.write_summary(third)
        return third

    def imported(
        self, domain: str, run: int = 1, report: Path | None = None
    ) -> list[str]:
        """Import a run's items into the report and return the ids they were given."""
        target = self.report if report is None else report
        return self.run_cli("item", "import", target, domain, run).split()

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
        reasoning: str = "as proposed",
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
            stdin=reasoning,
        )

    def imported_assessed(
        self, domain: str, run: int = 1, report: Path | None = None
    ) -> list[str]:
        """Import a run's items and assess them all, so the report holds complete entries."""
        identifiers = self.imported(domain, run, report)
        for identifier in identifiers:
            self.assess(identifier, report=report)
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
            f"assessor='{ASSESSOR}' correctness=2 readability=2 -->\n",
        )
        for domain in ("correctness", "readability"):
            self.assertTrue(Path(self.review_dir, f"{REV}-wave1-{domain}").is_dir())

    def test_init_names_the_change_it_resolved(self) -> None:
        """Print the change first, so later waves can pin the loop to it."""
        review_dir = Path(self.review_dir, "named")
        review_dir.mkdir()
        out = self.run_init(review_dir, "A", "--revision", REVISION)
        self.assertEqual(out.splitlines()[0], CHANGE_ID)

    def test_init_defaults_to_the_latest_non_empty_change(self) -> None:
        """Review the latest non-empty change when a wave opens without a revision."""
        review_dir = Path(self.review_dir, "default")
        review_dir.mkdir()
        self.run_init(review_dir, "A")
        self.assertEqual(
            self.jj["resolve_change_id"].call_args.args, (review.DEFAULT_REVSET,)
        )

    def test_init_validates_the_assessor_name(self) -> None:
        """Close up the assessor's whitespace, and refuse a name no report can carry."""
        review_dir = Path(self.review_dir, "assessor")
        review_dir.mkdir()
        for assessor in (" ", "Author's Model", "Model --> preview"):
            with self.assertRaises(SystemExit):
                self.run_init(review_dir, "A", assessor=assessor)
        out = self.run_init(review_dir, "A", assessor=" \tOpus  \n 5  xhigh ")
        self.assertEqual(
            review.read_metadata(Path(out.splitlines()[1])).assessor, ASSESSOR
        )

    def test_init_numbers_the_waves(self) -> None:
        """Number the wave after the reports the review dir already holds."""
        self.assertRegex(self.second_wave().name, rf"{REV}-wave2-\d{{12}}\.md")

    def test_a_later_wave_names_its_own_assessor(self) -> None:
        """Record the assessor a wave was opened under, not the preceding wave's."""
        second = self.second_wave(assessor="Sonnet 5 medium")
        self.assertEqual(review.read_metadata(second).assessor, "Sonnet 5 medium")

    def test_init_waits_for_the_previous_wave(self) -> None:
        """Wait for the preceding report's format, then for its decisions."""
        self.complete_wave()
        with self.assertRaisesRegex(SystemExit, "Wave 1 is not formatted yet"):
            self.init(self.review_dir, "B")
        self.imported_assessed("correctness")
        self.run_cli("report", "format", self.report)
        with self.assertRaisesRegex(SystemExit, "Item C1 .* has no decision"):
            self.init(self.review_dir, "B")

    def test_init_repeats_a_phase_with_lower_caps(self) -> None:
        """Run a repeated phase on the loop caps lowered by one, the loop caps standing."""
        self.decided_second_wave()
        third = review.read_metadata(self.init(self.review_dir, "A", "--repeat"))
        self.assertEqual(third.domain_caps, {"correctness": 1, "readability": 1})
        self.assertEqual(third.loop_caps["correctness"], 2)

    def test_init_refuses_a_first_repeat(self) -> None:
        """Refuse a repeat on the first wave of a loop, with no phase to repeat yet."""
        review_dir = Path(self.review_dir, "fresh")
        review_dir.mkdir()
        self.assert_cli_error(
            "init", review_dir, "A", "--repeat", "--assessor", ASSESSOR
        )

    def test_a_later_cap_overrides_one_wave_alone(self) -> None:
        """Leave the loop caps alone on a cap given after the first wave."""
        self.decided_second_wave()
        third = review.read_metadata(
            self.init(self.review_dir, "A", "--cap", "correctness=4")
        )
        self.assertEqual(third.domain_caps["correctness"], 4)
        self.assertEqual(third.loop_caps["correctness"], 2)

    def test_init_skips_an_excluded_chain(self) -> None:
        """Give a domain capped at zero no chain dir, and leave it unnamed."""
        review_dir = Path(self.review_dir, "excluded-chain")
        review_dir.mkdir()
        out = self.run_init(review_dir, "B", "--cap", "docs=0")
        self.assertEqual(out.splitlines()[2:], ["tests"])
        self.assertTrue(Path(review_dir, f"{REV}-wave1-tests").is_dir())
        self.assertFalse(Path(review_dir, f"{REV}-wave1-docs").exists())

    def test_init_takes_a_hand_picked_domain_list(self) -> None:
        """Run a wave named by its domains whatever phase groups each."""
        review_dir = Path(self.review_dir, "hand-picked")
        review_dir.mkdir()
        out = self.run_init(
            review_dir, "tests,readability", "--cap", "tests=2"
        ).splitlines()
        self.assertEqual(out[2:], ["readability", "tests"])
        self.assertEqual(
            Path(out[1]).read_text(),
            f"<!-- review: change_id={CHANGE_ID} wave=1 "
            "loop=correctness:1,readability:1,tests:2,docs:1 "
            f"assessor='{ASSESSOR}' readability=1 tests=2 -->\n",
        )
        for domain in ("readability", "tests"):
            self.assertTrue(Path(review_dir, f"{REV}-wave1-{domain}").is_dir())

    def test_init_refuses_a_malformed_domain_list(self) -> None:
        """Fail on an unknown domain, a repeated one, a phase inside a list, and an empty name."""
        review_dir = Path(self.review_dir, "malformed")
        review_dir.mkdir()
        for domains in ("prose", "tests,tests", "A,B", "tests,", ""):
            self.assert_cli_error("init", review_dir, domains, "--assessor", ASSESSOR)

    def test_init_names_no_judge_by_default(self) -> None:
        """Leave a loop nobody asked a judge for without a judge field."""
        metadata = review.read_metadata(self.report)
        self.assertEqual((metadata.loop_judge, metadata.judge), (None, None))

    def test_an_unjudged_loop_takes_a_judge_on_a_later_wave(self) -> None:
        """Turn the judge on for one wave of a loop that opened without one."""
        self.decided_second_wave()
        third = review.read_metadata(
            self.init(self.review_dir, "A", "--judge", "astra")
        )
        self.assertEqual((third.loop_judge, third.judge), (None, "astra"))

    def test_import_creates_sections_in_canonical_order(self) -> None:
        """Put the readability section after the correctness one whatever the order of the calls."""
        self.capture("readability", 1)
        self.capture("correctness", 1)
        self.assertEqual(self.imported("readability"), ["R1", "R2"])
        self.assertEqual(self.imported("correctness"), ["C1", "C2"])
        lines = self.report.read_text().splitlines()
        headings = [line for line in lines if line.startswith("#")]
        self.assertEqual(
            headings,
            [
                "### Correctness",
                "#### C1 (run 1, item 1)",
                "#### C2 (run 1, item 2)",
                "### Readability",
                "#### R1 (run 1, item 1)",
                "#### R2 (run 1, item 2)",
            ],
        )
        self.assertIn("> **Bound the layer walk** — `src/build.rs:133-147`", lines)
        self.assertIn(">", lines)

    def test_import_takes_the_whole_capture(self) -> None:
        """Land every item of the run in the report, printing its id on a line of its own."""
        self.capture("correctness", 1)
        self.assertEqual(
            self.run_cli("item", "import", self.report, "correctness", 1).splitlines(),
            ["C1", "C2"],
        )
        self.capture("correctness", 2, ONE_ITEM)
        self.assertEqual(self.imported("correctness", 2), ["C3"])

    def test_import_rejections(self) -> None:
        """Fail on an unknown capture, an inactive domain, a second import, and a broken item."""
        self.capture("correctness", 1)
        self.assert_cli_error("item", "import", self.report, "correctness", 2)
        self.assert_cli_error("item", "import", self.report, "tests", 1)
        self.imported("correctness")
        self.assert_cli_error("item", "import", self.report, "correctness", 1)
        self.capture("readability", 1, "1. no title\n\nprose\n")
        self.assert_cli_error("item", "import", self.report, "readability", 1)

    def test_a_broken_item_imports_nothing(self) -> None:
        """Leave the first item out too when a capture's second one is malformed."""
        self.capture(
            "correctness",
            1,
            ONE_ITEM + "\n2. **No severity** — `a.py:1`\n\n   prose\n",
        )
        self.assert_cli_error("item", "import", self.report, "correctness", 1)
        self.assertNotIn("###", self.report.read_text())

    def test_assess_writes_the_claim_and_proposal(self) -> None:
        """Write the assessment below the quote, its analysis between the claim and the proposal, and print nothing."""
        self.capture("correctness", 1)
        out = self.assess(
            self.imported("correctness")[0],
            "bound it in the caller",
            3,
            claim="partly-holds",
            severity="minor",
            proposal="apply-with-changes",
            stdin="Only the retry path can overrun it.",
        )
        text = self.report.read_text()
        self.assertEqual(out, "")
        self.assertIn(
            "**Claim**: partly holds, minor\n\n**Analysis**:\n\n"
            "Only the retry path can overrun it.\n\n"
            "**Proposal**: apply with changes — bound it in the caller (+3 lines)\n",
            text,
        )

    def test_assess_revises_the_estimate_of_an_apply(self) -> None:
        """Take a delta on an apply only as a revision of the item's estimate."""
        self.capture("correctness", 1)
        identifier = self.imported("correctness")[0]
        self.assess(identifier, -2, stdin="The item over-counts its own fix.")
        self.assertIn(
            "**Proposal**: apply (revised estimate: -2 lines)",
            self.report.read_text(),
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

    def test_a_decided_item_is_not_reassessed(self) -> None:
        """Refuse a new assessment on a decided item, leaving its decision as it stands."""
        self.capture("correctness", 1)
        identifier = self.imported_assessed("correctness")[0]
        self.decide(identifier)
        decided = self.report.read_text()
        with self.assertRaises(SystemExit):
            self.assess(identifier, stdin="Worth another look.")
        self.assertEqual(self.report.read_text(), decided)

    def test_an_assessment_may_hold_a_hash_line(self) -> None:
        """Keep a `#` line inside an analysis from ending the item."""
        self.capture("correctness", 1)
        identifier = self.imported("correctness")[0]
        self.assess(
            identifier, stdin="Reproduced with:\n\n```sh\n# run it\nreview\n```"
        )
        self.decide(identifier)
        self.assertIn("**Decision**: applied", self.report.read_text())

    def test_reassessment_replaces_a_quoting_analysis(self) -> None:
        """Replace an assessment that quotes something whole, quote included."""
        self.capture("correctness", 1)
        identifier = self.imported("correctness")[0]
        self.assess(identifier, stdin="The reviewer writes:\n\n> a quoted line")
        self.assess(identifier, stdin="Simpler after all.")
        text = self.report.read_text()
        self.assertEqual(text.count("**Claim**"), 1)
        self.assertNotIn("> a quoted line", text)

    def test_a_prose_heading_does_not_end_a_section(self) -> None:
        """Put the next item after the previous one whose assessment holds a `##` line."""
        self.capture("correctness", 1)
        self.capture("correctness", 2, ONE_ITEM)
        self.assess(
            self.imported("correctness")[0], stdin="Like:\n\n```markdown\n## Items\n```"
        )
        self.imported("correctness", 2)
        lines = self.report.read_text().splitlines()
        self.assertLess(
            lines.index("**Proposal**: apply"), lines.index("#### C3 (run 2, item 1)")
        )

    def test_a_fenced_item_heading_does_not_end_an_item(self) -> None:
        """Leave the assessment reachable and intact under an item heading inside a fenced sample."""
        self.capture("correctness", 1)
        identifier = self.imported("correctness")[0]
        self.assess(
            identifier, stdin="Like:\n\n```markdown\n#### C9 (run 3, item 1)\n```"
        )
        self.decide(identifier)
        text = self.report.read_text()
        self.assertIn("**Decision**: applied", text)
        self.assertIn("#### C9 (run 3, item 1)", text)

    def test_a_fenced_decision_does_not_decide_the_item(self) -> None:
        """Refuse a decision line inside a fenced sample as the user's decision."""
        self.complete_wave()
        first, second = self.imported("correctness")
        self.assess(first, stdin="Like:\n\n```markdown\n**Decision**: applied\n```")
        self.assess(second)
        self.run_cli("report", "format", self.report)
        with self.assertRaisesRegex(SystemExit, f"Item {first} .* has no decision"):
            self.init(self.review_dir, "B")

    def test_a_fenced_decision_leaves_the_item_open(self) -> None:
        """Keep an item assessable under an analysis quoting a decision, the real decision going below it."""
        self.capture("correctness", 1)
        identifier = self.imported("correctness")[0]
        analysis = "Like:\n\n```markdown\n**Decision**: applied\n```"
        self.assess(identifier, stdin=analysis)
        self.assess(identifier, stdin=analysis)
        self.decide(identifier)
        self.assertIn(
            "**Proposal**: apply\n\n**Decision**: applied\n\n**Reasoning**:\n\n"
            "as proposed",
            self.report.read_text(),
        )

    def test_an_analysis_reading_as_a_decision_leaves_the_item_open(self) -> None:
        """Keep an item assessable under an analysis stating a decision in its own prose, and keep its text."""
        self.capture("correctness", 1)
        identifier = self.imported("correctness")[0]
        analysis = "Wave 1 said:\n\n**Decision**: applied\n\nwhich no longer holds."
        self.assess(identifier, stdin=analysis)
        self.assess(identifier, stdin=analysis)
        self.decide(identifier)
        text = self.report.read_text()
        self.assertIn("which no longer holds.", text)
        self.assertIn(
            "**Proposal**: apply\n\n**Decision**: applied\n\n**Reasoning**:\n\n"
            "as proposed",
            text,
        )

    def test_an_analysis_reading_as_a_decision_leaves_the_wave_open(self) -> None:
        """Refuse a decision line an analysis writes as the user's decision."""
        self.complete_wave()
        first, second = self.imported("correctness")
        self.assess(first, stdin="Once decided:\n\n**Decision**: applied")
        self.assess(second)
        self.run_cli("report", "format", self.report)
        with self.assertRaisesRegex(SystemExit, f"Item {first} .* has no decision"):
            self.init(self.review_dir, "B")

    def test_a_fenced_domain_heading_does_not_open_a_section(self) -> None:
        """Keep a domain heading inside a fenced sample from taking the next domain's items."""
        self.capture("correctness", 1)
        self.capture("readability", 1, ONE_ITEM)
        self.assess(
            self.imported("correctness")[0],
            stdin="Like:\n\n```markdown\n### Readability\n```",
        )
        self.imported("readability")
        self.assertEqual(self.report.read_text().count("### Readability"), 2)

    def test_assess_argument_rules(self) -> None:
        """Take a severity exactly where the claim calls for one, with the proposal's own tail."""
        self.capture("correctness", 1)
        base = ["item", "assess", self.report, self.imported("correctness")[0]]
        for extra in (
            ["holds", "apply"],
            ["does-not-hold", "minor", "decline", "x"],
            ["holds", "minor", "apply", "x"],
            ["holds", "minor", "apply-with-changes"],
            ["holds", "minor", "apply-with-changes", "x"],
            ["holds", "minor", "apply-with-changes", "x", "a few"],
            ["holds", "minor", "decline"],
            ["holds", "minor", "your-call", "a"],
            ["holds", "minor", "your-call", "a", "3"],
            ["holds", "minor", "your-call", "-4", "b"],
            ["holds", "minor", "your-call", "a", "b", "0"],
            ["nearly-holds", "minor", "apply"],
        ):
            self.assert_cli_error(*base, *extra, stdin="prose")

    def test_assess_your_call_renders_its_options(self) -> None:
        """Spell a your-call proposal's options out as a lettered list, echoed under the item id."""
        self.capture("correctness", 1)
        identifier = self.imported("correctness")[0]
        out = self.assess(
            identifier,
            "split it",
            "leave it",
            severity="minor",
            proposal="your-call",
            stdin="Both are defensible.",
        )
        self.assertEqual(out, f"{identifier} (a) split it\n{identifier} (b) leave it\n")
        self.assertIn(
            "**Proposal**: your call:\n\n- (a) split it\n- (b) leave it\n",
            self.report.read_text(),
        )

    def test_assess_code_spans_a_tag_in_its_prose(self) -> None:
        """Send a tag named in an option or an analysis to the report as a code span."""
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
        """Require an assessment, read stdin, and link the ids in the reasoning."""
        self.capture("correctness", 1)
        self.imported("correctness")
        self.assert_cli_error(
            "item", "decide", self.report, "C1", "--verdict", "applied", stdin="x"
        )
        self.assess("C1", stdin="Confirmed.")
        self.decide(
            "C1",
            "applied-with-changes",
            "folded into C1's fix\n\nthe cleanup it called for followed",
        )
        text = self.report.read_text()
        self.assertIn(
            "**Decision**: applied with changes\n\n**Reasoning**:\n\nfolded into "
            "[C1](#c1-run-1-item-1)'s fix\n\nthe cleanup it called for followed\n",
            text,
        )

    def test_blank_prose_is_refused(self) -> None:
        """Refuse an analysis or a reasoning made of whitespace, and write nothing."""
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
            "**Proposal**: apply\n\n**Decision**: declined\n\n"
            "**Reasoning**:\n\nreverted afterwards\n",
            text,
        )

    def test_report_format(self) -> None:
        """Write the top part, the summary, the index and the links in one pass, and print the recap."""
        self.capture("correctness", 2, "Nothing to report.\n")
        self.capture("readability", 2, "Nothing to report.\n")
        self.complete_wave()
        self.capture("readability", 1)
        self.write_summary(text="The page now closes its <details> fold.\n")
        first, second = self.imported("correctness")
        self.assess(first)
        self.assess(
            second,
            "bound it in the caller",
            3,
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
            lines[lines.index("## Items") + 2 : lines.index("### Correctness") - 1],
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
        summary = lines.index("The page now closes its `<details>` fold.")
        grid = max(index for index, line in enumerate(lines) if line.startswith("|"))
        self.assertLess(lines.index("## Review status"), grid)
        self.assertLess(grid, lines.index("## Change summary"))
        self.assertLess(lines.index("## Change summary"), summary)
        self.assertLess(summary, lines.index("## Items"))

    def test_a_revised_estimate_reaches_the_index_and_the_decision(self) -> None:
        """Format, index, recap and decide an apply carrying a revised estimate like a bare one."""
        self.complete_wave()
        first, second = self.imported("correctness")
        self.assess(first, -2, stdin="The item over-counts its own fix.")
        self.assess(second, stdin="The estimate covers it.")
        recap = self.run_cli("report", "format", self.report)
        self.assertEqual(recap, "2 items · 2 apply\n\n- apply: C1, C2\n")
        self.decide(first)
        lines = self.report.read_text().splitlines()
        self.assertIn("  - [C1 / major / holds, apply](#c1-run-1-item-1)", lines)
        self.assertIn("**Decision**: applied", lines)

    def test_format_waits_for_the_chains(self) -> None:
        """Block on a chain in flight, on one that never ran, and on one due another run."""
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

    def test_format_waits_for_the_summary(self) -> None:
        """Block the format on a missing change summary, and on one still in flight."""
        self.ready()
        summary = self.write_summary()
        summary.unlink()
        with self.assertRaisesRegex(SystemExit, "No change summary"):
            self.run_cli("report", "format", self.report)
        summary.with_name(summary.name + review.RUNNING_SUFFIX).write_text("")
        with self.assertRaisesRegex(SystemExit, "summary is still in flight"):
            self.run_cli("report", "format", self.report)

    def test_format_requires_every_item_assessed(self) -> None:
        """Require every captured item in the report exactly once, with one assessment."""
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
        """Count a chain that finds items on its last allowed run as run to its end."""
        self.capture("correctness", 1, ONE_ITEM)
        self.capture("correctness", 2, ONE_ITEM)
        self.capture("readability", 1, "Nothing to report.\n")
        self.write_summary()
        self.imported_assessed("correctness", 1)
        self.imported_assessed("correctness", 2)
        self.assertEqual(
            self.run_cli("report", "format", self.report),
            "2 items · 2 apply\n\n- apply: C1, C2\n",
        )

    def test_format_names_the_models(self) -> None:
        """Open the status list with the assessing model, then the reviewing one."""
        self.ready()
        self.run_cli("report", "format", self.report)
        self.assertIn(
            f"## Review status\n\n- **Assessor model**: {ASSESSOR}\n"
            f"- **Reviewer model**: {review.REVIEWER_MODEL_NAME}\n",
            self.report.read_text(),
        )

    def test_an_excluded_domain_is_not_awaited(self) -> None:
        """Formatting waits only on the chains of the domains the caps left active."""
        review_dir = Path(self.review_dir, "excluded")
        review_dir.mkdir()
        report = self.init(review_dir, "B", "--cap", "docs=0")
        Path(review_dir, f"{REV}-wave1-tests", "run1.md").write_text("Nothing yet.\n")
        self.write_summary(report)
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
        """Close the report with a footer naming the skill and the time of the format."""
        self.ready()
        self.run_cli("report", "format", self.report)
        self.assertRegex(
            self.report.read_text().splitlines()[-1],
            r'^<p style="[^"]+">generated by <a href="https://github\.com/desbma/'
            r'agent-skills/tree/master/review-auto-loop">review-auto-loop</a> on '
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}</p>$",
        )

    def test_format_replaces_its_own_footer(self) -> None:
        """Formatting a formatted report leaves one footer, still closing it."""
        self.ready()
        self.run_cli("report", "format", self.report)
        self.run_cli("report", "format", self.report)
        lines = self.report.read_text().splitlines()
        self.assertEqual([line for line in lines if line.startswith("<p ")], lines[-1:])

    def test_report_format_without_items(self) -> None:
        """Give a wave that yielded nothing its top part, no index and no recap."""
        self.capture("correctness", 1, "No item to report.\n")
        self.capture("readability", 1, "No item to report.\n")
        self.write_summary()
        self.assertEqual(self.run_cli("report", "format", self.report), "")
        lines = self.report.read_text().splitlines()
        self.assertEqual(lines[2], f"# Review wave 1 — {REV}")
        self.assertNotIn("## Items", lines)

    def test_recap_counts_a_single_item(self) -> None:
        """Read the item count of a one-item wave as a singular."""
        self.capture("correctness", 1, ONE_ITEM)
        self.capture("correctness", 2, "Nothing to report.\n")
        self.capture("readability", 1, "Nothing to report.\n")
        self.write_summary()
        self.imported_assessed("correctness")
        self.assertEqual(
            self.run_cli("report", "format", self.report),
            "1 item · 1 apply\n\n- apply: C1\n",
        )

    def test_report_grid_is_right_aligned(self) -> None:
        """Give every column of the markdown grid a right-alignment marker."""
        self.capture("correctness", 1, "No item to report.\n")
        self.capture("readability", 1, "No item to report.\n")
        self.write_summary()
        self.run_cli("report", "format", self.report)
        rule = next(
            line
            for line in self.report.read_text().splitlines()
            if set(line) == {"|", "-", ":"}
        )
        cells = rule.strip("|").split("|")
        self.assertEqual(len(cells), len(review.Domain) + 1)
        self.assertTrue(all(cell.endswith(":") for cell in cells))

    def test_header_show(self) -> None:
        """Frame the wave title, its config, the diff stat and the run grid in the header."""
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
        """Draw the grid's column rules, and no box around it."""
        self.capture("correctness", 1)
        self.capture("readability", 1)
        out = self.run_cli("header", "show", self.report, 1).splitlines()
        head = next(line for line in out if "│" in line)
        self.assertTrue(head.startswith("  "))
        self.assertEqual(head.count("│"), len(review.Domain))
        self.assertFalse(any(set("╭╮╰╯├┤┬┴") & set(line) for line in out))

    def test_grid_rules_the_waves_apart(self) -> None:
        """Run a rule below the domains and between two waves."""
        second = self.second_wave()
        out = self.run_cli("header", "show", second, 1).splitlines()
        self.assertEqual(sum(set(line) == {"─", "┼"} for line in out), 2)

    def test_grid_counts_a_past_wave_decisions(self) -> None:
        """Count in a past wave's cell the items it found and how many of its decisions applied."""
        second = self.second_wave()
        out = self.run_cli("header", "show", second, 1).splitlines()
        self.assertTrue(any("1+1/2" in line for line in out))

    def test_links_reach_a_past_wave_report(self) -> None:
        """Link an id from a past wave to its heading in that wave's own report."""
        second = self.second_wave()
        identifier = self.imported("tests", 1, second)[0]
        self.assess(identifier, stdin="Same as C1.", report=second)
        self.assertIn(
            f"Same as [C1]({self.report.name}#c1-run-1-item-1).", second.read_text()
        )

    def test_decide_after_formatting(self) -> None:
        """Land a decision below its proposal on a report that carries its generated sections."""
        self.second_wave()
        text = self.report.read_text()
        self.assertEqual(text.count("## Items"), 1)
        self.assertIn("**Proposal**: apply\n\n**Decision**: applied\n", text)
        self.assertIn(
            "**Proposal**: apply\n\n**Decision**: applied with changes\n", text
        )

    def test_decide_writes_above_the_footer(self) -> None:
        """Leave the footer closing a formatted report on a decision on its last item."""
        identifiers = self.ready()
        self.run_cli("report", "format", self.report)
        self.decide(identifiers[-1])
        lines = self.report.read_text().splitlines()
        self.assertTrue(lines[-1].startswith("<p "))
        self.assertEqual(
            lines[-7:-1],
            ["**Decision**: applied", "", "**Reasoning**:", "", "as proposed", ""],
        )

    def test_an_empty_capture_is_a_completed_run(self) -> None:
        """Count a run that printed nothing as complete, having found no item."""
        self.capture("correctness", 1, "")
        out = self.run_cli("header", "show", self.report, 1)
        self.assertNotIn(review.RUNNING_STR, out)
        self.assertIn(" Wave 1, run 1 — 1 total reviews", out.splitlines())

    def test_metadata_is_read_back(self) -> None:
        """Carry the revision, the wave, its caps and its assessor in the report's comment."""
        metadata = review.read_metadata(self.report)
        self.assertEqual(metadata.short_change_id, REV)
        self.assertEqual(metadata.change_id, CHANGE_ID)
        self.assertEqual(metadata.wave, 1)
        self.assertEqual(metadata.active, ("correctness", "readability"))
        self.assertEqual(metadata.loop_caps["tests"], 1)
        self.assertEqual(metadata.assessor, ASSESSOR)

    def test_metadata_rejections(self) -> None:
        """Refuse a report without the comment, without loop caps or assessor, or disagreeing with its name."""
        stray = Path(self.review_dir, f"{REV}-wave3-202608261252.md")
        loop = "loop=correctness:1,readability:1,tests:1,docs:1"
        assessor = f"assessor='{ASSESSOR}'"
        caps = "correctness=1 readability=1 -->\n"
        for text in (
            "# Not a wave report\n",
            f"<!-- review: change_id={CHANGE_ID} wave=3 {assessor} {caps}",
            f"<!-- review: change_id={CHANGE_ID} wave=3 {loop} {caps}",
            f"<!-- review: change_id={CHANGE_ID} wave=2 {loop} {assessor} {caps}",
            (
                f"<!-- review: change_id=uqrvytospqyktvkspnpkmrnwpykoqotx wave=3 "
                f"{loop} {assessor} {caps}"
            ),
        ):
            stray.write_text(text)
            self.assertRaises(SystemExit, review.read_metadata, stray)


class JudgedFixture(WaveFixture):
    """A review dir whose loop was opened under the astra judge."""

    init_args = ("--judge", "astra")


class JudgeSettingTest(JudgedFixture):
    """The judge a loop runs under, and the override one of its waves may carry."""

    def test_init_records_the_judge_of_the_loop(self) -> None:
        """Record the judge of the first wave as the loop's own and as the wave's."""
        metadata = review.read_metadata(self.report)
        self.assertEqual((metadata.loop_judge, metadata.judge), ("astra", "astra"))
        self.assertIn("loop_judge=astra judge=astra", self.report.read_text())

    def test_a_later_wave_inherits_the_judge(self) -> None:
        """Judge a later wave the loop's own judge, with no flag to restate."""
        second = review.read_metadata(self.second_wave())
        self.assertEqual((second.loop_judge, second.judge), ("astra", "astra"))

    def test_a_later_wave_overrides_the_judge_for_itself(self) -> None:
        """Take a judge named after the first wave for that wave alone, the loop's standing."""
        self.decided_second_wave()
        third = review.read_metadata(
            self.init(self.review_dir, "A", "--judge", "fable")
        )
        self.assertEqual((third.loop_judge, third.judge), ("astra", "fable"))

    def test_the_wave_after_an_override_reverts_to_the_loop(self) -> None:
        """Leave a wave that asked for no judge unjudged, and revert to the loop's judge on the next."""
        self.decided_second_wave()
        third = self.init(self.review_dir, "A", "--judge", "none")
        metadata = review.read_metadata(third)
        self.assertEqual((metadata.loop_judge, metadata.judge), ("astra", None))
        self.assertIn("loop_judge=astra ", third.read_text())
        self.assertNotIn(" judge=", third.read_text())
        Path(self.review_dir, f"{REV}-wave3-correctness", "run1.md").write_text(
            "Nothing.\n"
        )
        Path(self.review_dir, f"{REV}-wave3-readability", "run1.md").write_text(
            "Nothing.\n"
        )
        self.write_summary(third)
        self.run_cli("report", "format", third)
        fourth = review.read_metadata(self.init(self.review_dir, "A"))
        self.assertEqual((fourth.loop_judge, fourth.judge), ("astra", "astra"))

    def test_an_unknown_judge_is_refused(self) -> None:
        """Refuse an alias no runner knows, on the command line and in a report's comment."""
        review_dir = Path(self.review_dir, "unknown")
        review_dir.mkdir()
        self.assert_cli_error(
            "init", review_dir, "A", "--assessor", ASSESSOR, "--judge", "solon"
        )
        stray = Path(self.review_dir, f"{REV}-wave3-202608261252.md")
        stray.write_text(
            f"<!-- review: change_id={CHANGE_ID} wave=3 "
            "loop=correctness:1,readability:1,tests:1,docs:1 "
            f"assessor='{ASSESSOR}' judge=solon correctness=1 -->\n"
        )
        self.assertRaises(SystemExit, review.read_metadata, stray)


class JudgeArgvTest(unittest.TestCase):
    """The command line each judge alias runs under."""

    def test_astra_runs_under_pi(self) -> None:
        """Run astra as a pi agent over the repository's judge skill, reading and searching only."""
        argv = review.judge_argv("astra", "judge it")
        self.assertEqual(argv[0], "pi")
        self.assertIn("openai-codex/gpt-6-astra:xhigh", argv)
        self.assertIn(str(review.SKILLS_DIR / "review-judge"), argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "read,grep,find,ls")
        self.assertEqual(argv[-1], "/skill:review-judge judge it")

    def test_fable_runs_under_claude(self) -> None:
        """Run fable as a claude agent resolving the judge skill by name, reading and searching only."""
        argv = review.judge_argv("fable", "judge it")
        self.assertEqual(argv[0], "claude")
        self.assertIn("claude-fable-5-1", argv)
        self.assertEqual(argv[argv.index("--effort") + 1], "xhigh")
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob")
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(argv[-1], "/review-judge judge it")


class JudgeCheckTest(unittest.TestCase):
    """The checks a judgment passes before it reaches the wave report."""

    PROPOSALS: ClassVar[dict[str, tuple[str, list[str]]]] = {
        "C1": ("apply", []),
        "C2": ("decline", []),
        "R1": ("your call", ["a", "b"]),
    }
    WHOLE = "**C1**: agree\n\n**C2**: agree\n\n**R1**: option b\n\nShorter.\n"

    def check(
        self, text: str, proposals: dict[str, tuple[str, list[str]]] | None = None
    ) -> None:
        """Check a judgment written to a file, as its capture holds it."""
        with tempfile.TemporaryDirectory() as tmp:
            capture = Path(tmp, "judge.md")
            capture.write_text(text)
            review.check_judgment(
                self.PROPOSALS if proposals is None else proposals, capture
            )

    def test_a_whole_judgment_passes(self) -> None:
        """Accept a judgment ruling once on each item with the prose its verdict calls for, in any order."""
        self.check(self.WHOLE)
        self.check("**R1**: option b\n\nShorter.\n\n**C2**: agree\n\n**C1**: agree\n")

    def test_it_covers_the_wave_and_nothing_else(self) -> None:
        """Refuse a judgment leaving an item out, naming an item the wave has not, or ruling twice."""
        for text, refusal in (
            ("**C1**: agree\n\n**R1**: option b\n\nShorter.\n", "no action for C2"),
            (f"{self.WHOLE}\n**T9**: agree\n", "the wave has not: T9"),
            (f"{self.WHOLE}\n**C1**: agree\n", "rules on C1 twice"),
        ):
            with self.assertRaisesRegex(SystemExit, refusal):
                self.check(text)

    def test_prose_stands_exactly_where_the_verdict_departs(self) -> None:
        """Refuse an agreement that argues its case, and a departure that does not."""
        with self.assertRaisesRegex(SystemExit, "C1 .* still argues"):
            self.check(self.WHOLE.replace("**C1**: agree", "**C1**: agree\n\nGood."))
        with self.assertRaisesRegex(SystemExit, "R1 .* without saying why"):
            self.check(self.WHOLE.replace("option b\n\nShorter.", "option b"))

    def test_a_your_call_is_not_agreed_with(self) -> None:
        """Refuse an agreement on a your call."""
        with self.assertRaisesRegex(SystemExit, "R1 .* agrees with a your call"):
            self.check(self.WHOLE.replace("option b\n\nShorter.", "agree"))

    def test_an_option_is_one_the_proposal_offers(self) -> None:
        """Refuse a letter the your call does not offer, and any letter on another proposal."""
        with self.assertRaisesRegex(SystemExit, "R1 .* picks an option"):
            self.check(self.WHOLE.replace("option b", "option c"))
        with self.assertRaisesRegex(SystemExit, "C1 .* picks an option"):
            self.check(self.WHOLE.replace("**C1**: agree", "**C1**: option a\n\nWhy."))

    def test_a_departure_departs(self) -> None:
        """Refuse a departure from apply to apply and from decline to decline, those naming no change."""
        for old, new, refused in (
            ("**C1**: agree", "**C1**: disagree, apply\n\nWhy.", "C1 .* departs"),
            ("**C2**: agree", "**C2**: disagree, decline\n\nWhy.", "C2 .* departs"),
        ):
            with self.assertRaisesRegex(SystemExit, refused):
                self.check(self.WHOLE.replace(old, new))

    def test_a_departure_naming_another_change_stands(self) -> None:
        """Accept a departure to apply-with-changes from every other proposal and from itself, and one off every option."""
        self.check(
            "**C1**: disagree, apply-with-changes\n\nWiden it.\n\n"
            "**C2**: disagree, apply-with-changes\n\nBound the caller instead.\n\n"
            "**R1**: disagree, decline\n\nNeither option is worth it.\n"
        )
        self.check(
            "**C1**: disagree, apply-with-changes\n\nBound the caller instead.\n\n"
            "**C2**: agree\n\n**R1**: option b\n\nShorter.\n",
            {**self.PROPOSALS, "C1": ("apply with changes", [])},
        )

    def test_a_judgment_handing_the_choice_back_is_refused(self) -> None:
        """Refuse a verdict sending an item to the user: every verdict names an action to take."""
        for text in (
            (
                "**C1**: disagree, your-call\n\nNot mine to settle.\n\n"
                "**C2**: agree\n\n**R1**: option b\n\nShorter.\n"
            ),
            (
                "**C1**: agree\n\n**C2**: agree\n\n"
                "**R1**: disagree, your-call\n\nNeither option fits.\n"
            ),
        ):
            with self.assertRaises(SystemExit):
                self.check(text)

    def test_a_fenced_sample_opens_no_block(self) -> None:
        """Keep a block the judge's prose quotes inside a fence from ruling on an item."""
        self.check(
            "**C1**: agree\n\n**C2**: agree\n\n**R1**: option b\n\n"
            "As in:\n\n```markdown\n**C1**: disagree, decline\n```\n"
        )

    def test_prose_reading_as_the_report_structure_is_refused(self) -> None:
        """Refuse prose carrying a line the wave report would read as its own structure."""
        for line in (
            "**Judge**: agree",
            "**Proposal**: apply",
            "**Decision**: applied",
            "#### C9 (run 1, item 1)",
            "### Readability",
        ):
            with self.assertRaisesRegex(SystemExit, "C1 .* reads as the report"):
                self.check(
                    self.WHOLE.replace(
                        "**C1**: agree", f"**C1**: disagree, decline\n\n{line}"
                    )
                )
        self.check(
            self.WHOLE.replace(
                "**C1**: agree",
                "**C1**: disagree, decline\n\nAs in:\n\n```markdown\n"
                "**Judge**: agree\n```",
            )
        )

    def test_a_preamble_before_the_first_block_is_refused(self) -> None:
        """Refuse a judgment opening on prose above its first block."""
        with self.assertRaisesRegex(SystemExit, "before its first"):
            self.check(f"Here is what I make of the wave.\n\n{self.WHOLE}")


class JudgeRunTest(JudgedFixture):
    """Running the wave's judge and splicing its recommendations into the report."""

    def empty_wave(self) -> None:
        """End every chain of the wave on a run that found nothing."""
        self.capture("correctness", 1, "Nothing to report.\n")
        self.capture("readability", 1, "Nothing to report.\n")
        self.write_summary()

    def test_it_captures_the_judgment_and_prints_it(self) -> None:
        """Name the capture after the wave, and print its content and nothing else."""
        self.ready()
        output = "**C1**: agree\n\n**C2**: disagree, decline\n\nThe fix costs more.\n"
        self.assertEqual(self.judge(output=output), output)
        capture = review.judge_path(review.read_metadata(self.report))
        self.assertEqual(capture.read_text(), output)

    def test_it_runs_the_judge_from_the_repository_root(self) -> None:
        """Run the wave's own judge alias, from the root the reviewers run from."""
        self.ready()
        self.judge("C1", "C2")
        self.assertEqual(self.spawn.call_args.args[0][0], "pi")
        self.assertIn("openai-codex/gpt-6-astra:xhigh", self.spawn.call_args.args[0])
        self.assertEqual(self.spawn.call_args.kwargs["cwd"], "/repo")

    def test_it_runs_the_judge_the_wave_names(self) -> None:
        """Run the alias of the wave's own judge, not the one the loop opened under."""
        self.decided_second_wave()
        third = self.third_wave("--judge", "fable")
        identifiers = self.imported_assessed("correctness", report=third)
        self.judge(*identifiers, report=third)
        self.assertEqual(self.spawn.call_args.args[0][0], "claude")

    def test_the_prompt_names_every_input(self) -> None:
        """Name the report, the diff dump and the summary, all absolute, and no earlier wave."""
        self.ready()
        self.judge("C1", "C2")
        prompt = self.spawn.call_args.args[0][-1]
        metadata = review.read_metadata(self.report)
        self.assertIn(str(self.report.resolve()), prompt)
        self.assertIn(str(review.summary_path(metadata).resolve()), prompt)
        self.assertNotIn("Earlier waves", prompt)

    def test_the_prompt_names_the_earlier_wave_reports(self) -> None:
        """List the report of every earlier wave of the same review, oldest first."""
        second = self.decided_second_wave()
        third = self.third_wave()
        identifiers = self.imported_assessed("correctness", report=third)
        self.judge(*identifiers, report=third)
        prompt = self.spawn.call_args.args[0][-1]
        self.assertIn(
            "Earlier waves of this review: "
            f"{self.report.resolve()}, {second.resolve()}.",
            prompt,
        )

    def test_the_diff_dump_is_handed_over_then_deleted(self) -> None:
        """Write the reviewed change to a file the prompt names, and leave nothing behind."""
        self.ready()
        seen: dict[str, str] = {}

        def agent(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            named = re.search(r"reviewed change is in (\S+), its summary", argv[-1])
            assert named is not None
            seen["path"] = named.group(1)
            seen["diff"] = Path(named.group(1)).read_text()
            kwargs["stdout"].write("**C1**: agree\n\n**C2**: agree\n")
            return subprocess.CompletedProcess(argv, 0)

        def jj(args: list[str]) -> str:
            return "/repo\n" if args == ["root"] else DIFF

        with (
            mock.patch.object(review, "jj_output", side_effect=jj) as queried,
            mock.patch.object(review.subprocess, "run", side_effect=agent),
        ):
            self.run_cli("judge", "run", self.report)
        self.assertEqual(seen["diff"], DIFF)
        self.assertFalse(Path(seen["path"]).exists())
        self.assertIn(
            ["show", CHANGE_ID], [call.args[0] for call in queried.mock_calls]
        )

    def test_it_refuses_a_second_run(self) -> None:
        """Refuse to judge a wave that already carries a judgment."""
        self.ready()
        self.judge("C1", "C2")
        with self.assertRaisesRegex(SystemExit, "already judged"):
            self.judge("C1", "C2")

    def test_it_refuses_a_wave_with_no_item(self) -> None:
        """Refuse a wave whose chains all ended without an item, and format it all the same."""
        self.empty_wave()
        with self.assertRaisesRegex(SystemExit, "no item to judge"):
            self.judge()
        self.assertEqual(self.run_cli("report", "format", self.report), "")
        self.assertNotIn("**Judge**", self.report.read_text())

    def test_it_refuses_a_wave_with_no_summary(self) -> None:
        """Refuse a wave whose change summary has not landed, before the judge starts."""
        self.ready()
        review.summary_path(review.read_metadata(self.report)).unlink()
        with self.assertRaisesRegex(SystemExit, "No change summary"):
            self.judge("C1", "C2")
        self.spawn.assert_not_called()

    def test_it_refuses_an_unassessed_wave(self) -> None:
        """Refuse a wave whose items are not all imported, and one whose items are not all assessed."""
        self.complete_wave()
        with self.assertRaisesRegex(SystemExit, "exactly once"):
            self.judge()
        first, _ = self.imported("correctness")
        self.assess(first)
        with self.assertRaisesRegex(SystemExit, "C2 has no single claim"):
            self.judge("C1", "C2")

    def test_it_refuses_a_wave_whose_chains_are_unfinished(self) -> None:
        """Refuse a wave a chain has not run to its end."""
        self.capture("correctness", 1)
        self.capture("readability", 1, "Nothing to report.\n")
        self.write_summary()
        self.imported_assessed("correctness")
        with self.assertRaisesRegex(SystemExit, "correctness is due another run"):
            self.judge("C1", "C2")

    def test_a_refused_judgment_is_kept_for_repair(self) -> None:
        """Keep a capture the checks refuse under its own name, the report untouched."""
        self.ready()
        before = self.report.read_text()
        with self.assertRaises(SystemExit) as caught:
            self.judge(output="**C1**: agree\n")
        capture = review.judge_path(review.read_metadata(self.report))
        rejected = capture.with_name(capture.name + review.REJECTED_SUFFIX)
        self.assertEqual(rejected.read_text(), "**C1**: agree\n")
        self.assertIn(str(rejected), str(caught.exception))
        self.assertEqual(self.report.read_text(), before)
        self.judge("C1", "C2")

    def test_a_report_that_moved_under_the_judge_is_refused(self) -> None:
        """Refuse a judgment ruling on assessments the report no longer carries."""
        identifiers = self.ready()

        def agent(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            self.assess(identifiers[0], "the fix costs more", proposal="decline")
            kwargs["stdout"].write("**C1**: agree\n\n**C2**: agree\n")
            return subprocess.CompletedProcess(argv, 0)

        def jj(args: list[str]) -> str:
            return "/repo\n" if args == ["root"] else DIFF

        with (
            mock.patch.object(review, "jj_output", side_effect=jj),
            mock.patch.object(review.subprocess, "run", side_effect=agent),
            self.assertRaisesRegex(SystemExit, "report changed while the judge ran"),
        ):
            self.run_cli("judge", "run", self.report)
        self.assertNotIn("**Judge**", self.report.read_text())

    def test_an_assessment_that_already_rules_is_refused(self) -> None:
        """Refuse to judge a wave whose assessment carries a recommendation of its own."""
        self.complete_wave()
        first, second = self.imported("correctness")
        self.assess(first, stdin="**Judge**: agree")
        self.assess(second)
        with self.assertRaisesRegex(SystemExit, "C1 already carries a judge"):
            self.judge(first, second)

    def test_a_failed_run_leaves_nothing_behind(self) -> None:
        """Take the exit code of a judge exiting non-zero, and leave no capture."""
        self.ready()
        with self.assertRaises(SystemExit) as caught:
            self.run_with_agent("judge", "run", self.report, output="", status=3)
        self.assertEqual(caught.exception.code, 3)
        self.assertFalse(review.judge_path(review.read_metadata(self.report)).exists())


class JudgeReportTest(JudgedFixture):
    """What a judged wave's report, index and recap carry beyond an unjudged one's."""

    def setUp(self) -> None:
        """Run the wave to where the judge is due, its two correctness items assessed."""
        super().setUp()
        self.ready()

    def your_call(self, identifier: str = "C2") -> None:
        """Turn an item's proposal into a your call offering two lettered options."""
        self.assess(
            identifier,
            "split it",
            "leave it",
            severity="minor",
            proposal="your-call",
            stdin="Both are defensible.",
        )

    def test_an_agreement_is_a_bare_note(self) -> None:
        """Render an agreement as a note callout carrying the verdict and nothing else."""
        self.judge("C1", "C2")
        self.assertIn("::: note\n**Judge**: agree\n:::\n", self.report.read_text())

    def test_a_departure_and_a_pick_carry_their_own_callout(self) -> None:
        """Render a disagreement as a warning and a lettered pick as a tip, each under the item its block names."""
        self.your_call()
        self.judge(
            output=(
                "**C2**: option b\n\nUniformity is not worth twelve lines.\n\n"
                "**C1**: disagree, apply-with-changes\n\nWiden it to the caller.\n"
            )
        )
        text = self.report.read_text()
        self.assertIn(
            "::: warning\n**Judge**: disagree, apply-with-changes\n\n"
            "Widen it to the caller.\n:::\n",
            text,
        )
        self.assertIn(
            "::: tip\n**Judge**: option b\n\n"
            "Uniformity is not worth twelve lines.\n:::\n",
            text,
        )
        self.assertLess(text.index("Widen it to the caller."), text.index("#### C2"))
        self.assertLess(text.index("#### C2"), text.index("Uniformity is not worth"))

    def test_the_block_sits_between_the_proposal_and_the_decision(self) -> None:
        """Land the recommendation below the proposal it rules on, and above the user's decision."""
        self.judge("C1", "C2")
        self.run_cli("report", "format", self.report)
        self.decide("C1")
        lines = self.report.read_text().splitlines()
        self.assertLess(lines.index("**Proposal**: apply"), lines.index("::: note"))
        self.assertLess(lines.index("::: note"), lines.index("**Decision**: applied"))

    def test_the_block_leaves_the_item_countable_and_decidable(self) -> None:
        """Keep the claim and proposal counts of a judged item, and its decision, intact."""
        self.judge("C1", "C2")
        self.run_cli("report", "format", self.report)
        self.decide("C1")
        self.decide("C2", "declined", "not worth it")
        text = self.report.read_text()
        self.assertEqual(text.count("**Claim**"), 2)
        self.assertEqual(text.count("**Proposal**"), 2)
        self.assertEqual(text.count("**Decision**"), 2)

    def test_a_fenced_judge_line_leaves_the_item_countable(self) -> None:
        """Keep a judge label the prose quotes inside a fence from counting as a second recommendation."""
        self.judge(
            output=(
                "**C1**: agree\n\n**C2**: disagree, decline\n\nThe format is:\n\n"
                "```markdown\n**Judge**: agree\n```\n"
            )
        )
        recap = self.run_cli("report", "format", self.report)
        self.assertIn("│  - disagreed: C2\n", recap)
        self.assertIn("```markdown\n**Judge**: agree\n```", self.report.read_text())

    def test_the_prose_links_the_items_it_names(self) -> None:
        """Link an item id the judge's prose mentions to its heading, as every other block does."""
        self.judge(
            output="**C1**: agree\n\n**C2**: disagree, decline\n\nC1 already covers it.\n"
        )
        self.assertIn(
            "[C1](#c1-run-1-item-1) already covers it.", self.report.read_text()
        )

    def test_the_status_list_names_the_judge_model(self) -> None:
        """Name the judging model below the reviewing one in the report's status list."""
        self.judge("C1", "C2")
        self.run_cli("report", "format", self.report)
        self.assertIn(
            f"- **Reviewer model**: {review.REVIEWER_MODEL_NAME}\n"
            f"- **Judge model**: {review.JUDGE_MODELS['astra']}\n",
            self.report.read_text(),
        )

    def test_the_index_carries_the_verdict_of_every_item(self) -> None:
        """Append the recommendation to every index entry, an agreement included."""
        self.your_call()
        self.judge(output="**C1**: agree\n\n**C2**: option b\n\nShorter.\n")
        self.run_cli("report", "format", self.report)
        lines = self.report.read_text().splitlines()
        self.assertIn(
            "  - [C1 / major / holds, apply / agree](#c1-run-1-item-1)", lines
        )
        self.assertIn(
            "  - [C2 / minor / holds, your call / option b](#c2-run-1-item-2)", lines
        )

    def test_the_recap_frames_each_agent_apart(self) -> None:
        """Print the assessor's recap and the judge's as two labelled sections behind a bar."""
        self.your_call()
        self.judge(output="**C1**: agree\n\n**C2**: option b\n\nShorter.\n")
        self.assertEqual(
            self.run_cli("report", "format", self.report),
            "Assessor:\n"
            "│  2 items · 1 apply · 1 your call\n"
            "│\n"
            "│  - apply: C1\n"
            "│  - your call: C2\n"
            "\n"
            "Judge:\n"
            "│  2 items · 1 agreed · 1 picked\n"
            "│\n"
            "│  - agreed: C1\n"
            "│  - picked: C2 (b)\n",
        )

    def test_a_departure_from_the_proposal_counts_as_a_disagreement(self) -> None:
        """Count a recommendation naming a verdict other than the proposal's among the departures."""
        self.judge(
            output="**C1**: agree\n\n**C2**: disagree, decline\n\nIt costs more.\n"
        )
        recap = self.run_cli("report", "format", self.report)
        self.assertIn("│  2 items · 1 agreed · 1 disagreed\n", recap)
        self.assertIn("│  - disagreed: C2\n", recap)

    def test_format_requires_a_recommendation_on_every_item(self) -> None:
        """Refuse to format a judged wave the judge has not ruled on."""
        with self.assertRaisesRegex(
            SystemExit, "C1 has no single judge recommendation"
        ):
            self.run_cli("report", "format", self.report)

    def test_reassessing_voids_the_judgment_in_place(self) -> None:
        """Replace the recommendation of a re-assessed item with a note saying it no longer stands."""
        self.judge("C1", "C2")
        self.assess("C1", "not worth it", proposal="decline", stdin="A second look.")
        text = self.report.read_text()
        self.assertIn(
            f"::: important\n**Judge**: {review.VOIDED_JUDGMENT}\n:::\n", text
        )
        self.assertEqual(text.count("**Judge**"), 2)
        recap = self.run_cli("report", "format", self.report)
        self.assertIn("│  - not judged: C1\n", recap)
        self.assertIn(
            "  - [C1 / major / holds, decline / not judged](#c1-run-1-item-1)",
            self.report.read_text().splitlines(),
        )

    def test_voiding_a_judgment_twice_leaves_one_note(self) -> None:
        """Keep one void note on an item re-assessed again after its judgment was voided."""
        self.judge("C1", "C2")
        self.assess("C1", "not worth it", proposal="decline", stdin="A second look.")
        self.assess("C1", stdin="A third look.")
        self.assertEqual(self.report.read_text().count(review.VOIDED_JUDGMENT), 1)


class JudgeGridTest(JudgedFixture):
    """The judge's own row of the run grid, in the header and in the report."""

    def mark(self, suffix: str) -> None:
        """Write the judgment capture a judge run leaves behind in that state."""
        capture = review.judge_path(review.read_metadata(self.report))
        capture.with_name(capture.name + suffix).write_text("")

    def header(self, report: Path | None = None) -> list[str]:
        """Print a wave header and return its lines."""
        return self.run_cli(
            "header", "show", self.report if report is None else report, 1
        ).splitlines()

    def rows(self, lines: list[str]) -> list[str]:
        """Collect the judge rows of a rendered grid."""
        return [line for line in lines if line.strip().startswith("judge")]

    def state(self, lines: list[str]) -> str:
        """Read the judge row's state back, centred over the domain columns it fuses."""
        rule = next(line for line in lines if set(line) == {"─", "┼"})
        (row,) = self.rows(lines)
        self.assertEqual(row.count("│"), 1)
        self.assertEqual(row.index("│"), rule.index("┼"))
        cell = row[row.index("│") + 1 :]
        pad = (len(rule) - rule.index("┼") - 1 - len(cell.strip())) // 2
        self.assertEqual(cell, " " * pad + cell.strip())
        return cell.strip()

    def test_the_config_line_names_the_judge(self) -> None:
        """Name the wave's judge on the config line, by its alias rather than its model."""
        self.ready()
        self.assertIn(
            " Wave config: correctness ≤2 · readability ≤2 · Astra judge",
            self.header(),
        )

    def test_a_judge_that_has_not_run_has_no_row(self) -> None:
        """Leave the grid alone until the judgment of the wave starts."""
        self.ready()
        self.assertEqual(self.rows(self.header()), [])

    def test_a_running_judge_is_shown_running(self) -> None:
        """Say the judge is running while its capture is still in flight."""
        self.ready()
        self.mark(review.RUNNING_SUFFIX)
        self.assertEqual(self.state(self.header()), review.RUNNING_STR)

    def test_a_judged_wave_is_shown_done(self) -> None:
        """Say the judgment is done, with no icon, once the capture is final."""
        self.ready()
        self.judge("C1", "C2")
        self.assertEqual(self.state(self.header()), "done")

    def test_a_refused_judgment_shows_no_row(self) -> None:
        """Read a judgment the checks refused as a wave no judgment ran for."""
        self.ready()
        self.mark(review.REJECTED_SUFFIX)
        self.assertEqual(self.rows(self.header()), [])

    def test_the_row_belongs_to_the_wave_it_judged(self) -> None:
        """Keep an earlier wave's judgment under its own runs, above the rule opening the next wave."""
        second = self.second_wave()
        lines = self.header(second)
        (row,) = self.rows(lines)
        index = lines.index(row)
        self.assertIn("run 2", lines[index - 1])
        self.assertEqual(set(lines[index + 1]), {"─", "┼"})

    def test_the_report_ticks_every_domain_the_wave_ran(self) -> None:
        """Mark the judgment in the report grid under each domain of the wave, and nowhere else."""
        self.ready()
        self.judge("C1", "C2")
        self.run_cli("report", "format", self.report)
        self.assertIn(
            "|        judge |           ✓ |           ✓ |       |      |",
            self.report.read_text().splitlines(),
        )


class UnjudgedWaveTest(WaveFixture):
    """A wave of a loop that enabled no judge."""

    def test_the_report_and_the_recap_carry_no_judgment(self) -> None:
        """Format a wave with no callout, no judge block and no judge recap."""
        identifiers = self.ready()
        recap = self.run_cli("report", "format", self.report)
        text = self.report.read_text()
        self.assertNotIn("Judge", text)
        self.assertNotIn("judge", text)
        self.assertNotIn(":::", text)
        self.assertNotIn("judge", self.run_cli("header", "show", self.report, 1))
        self.assertNotIn("│", recap)
        self.assertEqual(recap, "2 items · 2 apply\n\n- apply: C1, C2\n")
        for identifier in identifiers:
            self.decide(identifier)

    def test_an_assessment_that_rules_on_itself_is_refused(self) -> None:
        """Refuse to format a wave whose assessment carries a judgment no judge wrote."""
        self.complete_wave()
        first, second = self.imported("correctness")
        self.assess(first, stdin="**Judge**: agree")
        self.assess(second)
        with self.assertRaisesRegex(SystemExit, "C1 already carries a judge"):
            self.run_cli("report", "format", self.report)

    def test_judge_run_refuses_a_wave_that_runs_no_judge(self) -> None:
        """Refuse to judge a wave whose loop enabled no judge, before it looks at anything else."""
        with self.assertRaisesRegex(SystemExit, "runs no judge"):
            self.judge()


class ChainRunTest(WaveFixture):
    """Running a chain's next review and capturing its output."""

    def run_chain(self, domain: str, output: str = ONE_ITEM, status: int = 0) -> str:
        """Run a chain with the reviewer replaced by one writing the given output."""
        return self.run_with_agent(
            "chain", "run", self.report, domain, output=output, status=status
        )

    def test_it_captures_the_reviewer_output(self) -> None:
        """Name the capture after the run once the reviewer is through, and print its path."""
        capture = Path(self.chain("correctness"), "run1.md")
        self.assertEqual(self.run_chain("correctness").strip(), str(capture))
        self.assertEqual(capture.read_text(), ONE_ITEM)
        self.assertEqual(list(self.chain("correctness").iterdir()), [capture])

    def test_it_runs_the_reviewer_over_the_change(self) -> None:
        """Run the reviewer from the repository root, on the change, over the chain dir."""
        self.run_chain("readability")
        argv = self.spawn.call_args.args[0]
        self.assertEqual(argv[0], "pi")
        self.assertIn(review.REVIEWER_MODEL, argv)
        self.assertIn(str(review.SKILLS_DIR / "review-readability"), argv)
        self.assertIn(CHANGE_ID, argv[-1])
        self.assertIn(str(self.chain("readability")), argv[-1])
        self.assertEqual(self.spawn.call_args.kwargs["cwd"], "/repo")

    def test_the_prompt_names_the_chain_dir_absolutely(self) -> None:
        """Expand a relative report to an absolute chain dir, for the reviewer at the repository root."""

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
        """Keep two runs racing past the in-flight check from sharing one capture."""
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

    def test_a_capture_numbering_no_item_is_kept_for_repair(self) -> None:
        """Refuse a review whose items carry no number, instead of reading it as a run that found nothing."""
        unnumbered = ONE_ITEM.replace("1. ", "#### ")
        with self.assertRaises(SystemExit) as caught:
            self.run_chain("correctness", output=unnumbered)
        rejected = Path(self.chain("correctness"), f"run1.md{review.REJECTED_SUFFIX}")
        self.assertEqual(rejected.read_text(), unnumbered)
        self.assertIn("outside any numbered item", str(caught.exception))

    def test_a_capture_numbering_one_of_two_items_is_kept_for_repair(self) -> None:
        """Refuse a finding the capture leaves unnumbered, instead of folding it into the item above."""
        with self.assertRaises(SystemExit) as caught:
            self.run_chain("correctness", output=f"{ONE_ITEM}\n{SECOND_FINDING}")
        self.assertIn("more than one", str(caught.exception))

    def test_a_capture_opening_on_an_unnumbered_item_is_kept_for_repair(self) -> None:
        """Refuse a finding above the first numbered one, instead of dropping it from the review."""
        with self.assertRaises(SystemExit) as caught:
            self.run_chain("correctness", output=f"{SECOND_FINDING}\n{ONE_ITEM}")
        self.assertIn("outside any numbered item", str(caught.exception))

    def test_a_rejected_capture_does_not_count_as_a_run(self) -> None:
        """Keep the wave readable, and retry the run the rejected output failed."""
        with self.assertRaises(SystemExit):
            self.run_chain("correctness", output="1. no bold title\n")
        self.run_cli("header", "show", self.report, 1)
        self.run_chain("correctness")
        chain = self.chain("correctness")
        self.assertEqual(Path(chain, "run1.md").read_text(), ONE_ITEM)
        self.assertTrue(Path(chain, f"run1.md{review.REJECTED_SUFFIX}").is_file())

    def test_a_failed_run_leaves_nothing_behind(self) -> None:
        """Take the exit code of a reviewer exiting non-zero, and leave no capture."""
        with self.assertRaises(SystemExit) as caught:
            self.run_chain("correctness", status=3)
        self.assertEqual(caught.exception.code, 3)
        self.assertEqual(list(self.chain("correctness").iterdir()), [])

    def test_a_reviewer_that_never_starts_leaves_nothing_behind(self) -> None:
        """Leave no capture standing in for a run the system cannot spawn."""
        with (
            mock.patch.object(review, "jj_output", return_value="/repo\n"),
            mock.patch.object(review.subprocess, "run", side_effect=FileNotFoundError),
            self.assertRaises(FileNotFoundError),
        ):
            self.run_cli("chain", "run", self.report, "correctness")
        self.assertEqual(list(self.chain("correctness").iterdir()), [])

    def test_the_next_run_follows_the_captures(self) -> None:
        """Write the second capture on a second run of the chain."""
        self.run_chain("correctness")
        self.run_chain("correctness")
        self.assertTrue(Path(self.chain("correctness"), "run2.md").is_file())

    def test_refusals(self) -> None:
        """Refuse an inactive domain and a run already in flight."""
        self.assert_cli_error("chain", "run", self.report, "tests")
        self.running("correctness", 1)
        self.assert_cli_error("chain", "run", self.report, "correctness")

    def test_a_chain_that_ended_reports_its_end(self) -> None:
        """Report the end of a chain out of items or at its cap, and run nothing."""
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


class SummaryCheckTest(unittest.TestCase):
    """The prose check the capture of a change summary must pass."""

    def check(self, text: str) -> None:
        """Check a summary written to a file, as its capture holds it."""
        with tempfile.TemporaryDirectory() as tmp:
            capture = Path(tmp, "summary.md")
            capture.write_text(text)
            review.check_summary(capture)

    def test_paragraphs_of_prose(self) -> None:
        """Prose passes, the code spans it names included."""
        self.check("The change bounds the walk.\n\nIt renames `build` to `walk`.\n")

    def test_rejections(self) -> None:
        """Refuse every block construct a renderer would show as more than a paragraph."""
        for text in (
            "",
            " \n\n \n",
            "Prose.\n\n```rust\nlet x = 1;\n```\n",
            "## Summary\n\nProse.\n",
            "Summary\n-------\n\nProse.\n",
            "- bounds the walk\n- drops a branch\n",
            "1. bounds the walk\n",
            "Prose.\n\n    let x = 1;\n",
            "> bounds the walk\n",
            "| a | b |\n|---|---|\n| 1 | 2 |\n",
            "Prose.\n\n---\n\nMore prose.\n",
        ):
            with self.assertRaises(SystemExit):
                self.check(text)


class SummaryRunTest(WaveFixture):
    """Running the change summary of a wave and capturing its output."""

    def setUp(self) -> None:
        """Name the capture the summary run of the wave writes."""
        super().setUp()
        self.summary = review.summary_path(review.read_metadata(self.report))

    def run_summary(self, output: str = SUMMARY) -> str:
        """Run the wave's summary with the agent replaced by one writing the given output."""
        return self.run_with_agent("summary", "run", self.report, output=output)

    def test_it_runs_and_captures_one_summary(self) -> None:
        """Run the agent over the change, name its output the summary, and follow it with no second run."""
        self.assertEqual(self.run_summary().strip(), str(self.summary))
        self.assertEqual(self.summary.read_text(), SUMMARY)
        argv = self.spawn.call_args.args[0]
        self.assertEqual(argv[0], "pi")
        self.assertIn(review.SUMMARY_MODEL, argv)
        self.assertIn(str(review.SKILLS_DIR / "summarize-change"), argv)
        self.assertEqual(
            argv[-1],
            f"/skill:summarize-change {CHANGE_ID}. Summarize that exact revision.",
        )
        self.assertEqual(self.spawn.call_args.kwargs["cwd"], "/repo")
        self.assert_cli_error("summary", "run", self.report)

    def test_output_that_is_not_prose_is_kept_for_repair(self) -> None:
        """Output the prose check refuses never becomes the summary, and the wave still reads."""
        with self.assertRaises(SystemExit) as caught:
            self.run_summary(output="## Summary\n\nProse.\n")
        rejected = self.summary.with_name(self.summary.name + review.REJECTED_SUFFIX)
        self.assertEqual(rejected.read_text(), "## Summary\n\nProse.\n")
        self.assertIn(str(rejected), str(caught.exception))
        self.assertFalse(self.summary.exists())
        self.run_cli("header", "show", self.report, 1)
        self.run_summary()
        self.assertEqual(self.summary.read_text(), SUMMARY)


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
        printed = self.run_init(
            self.review_dir, *argv, "--revision", CHANGE_ID
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
            identifiers.extend(
                self.run_cli("item", "import", report, domain, run).split()
            )
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

    def summary_run(self, report: Path) -> str:
        """Summarize the change of a wave, the stub agent writing the prose."""
        self.output.write_text(SUMMARY)
        return self.run_cli("summary", "run", report)

    def judge_run(self, report: Path, *identifiers: str) -> str:
        """Judge a wave, the stub agent agreeing with every item it holds."""
        self.output.write_text(
            "\n\n".join(f"**{identifier}**: agree" for identifier in identifiers)
        )
        return self.run_cli("judge", "run", report)

    def decide_and_format(self, report: Path, identifiers: list[str]) -> str:
        """Summarize the change, format the wave, then decide every item it holds."""
        self.summary_run(report)
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

    def test_a_judged_wave(self) -> None:
        """Run a wave under a judge end to end, its recommendations reaching the report and the recap."""
        report, _ = self.open_wave("correctness,docs", "--judge", "astra")
        code, _ = self.chain_to_its_end(
            report, "correctness", ONE_ITEM, "Nothing to report.\n"
        )
        self.chain_to_its_end(report, "docs", "Nothing to report.\n")
        self.summary_run(report)
        self.assert_cli_error("report", "format", report)
        self.assertEqual(self.judge_run(report, *code), "**C1**: agree")
        recap = self.run_cli("report", "format", report)
        self.assertEqual(recap.splitlines()[-1], "│  - agreed: C1")
        lines = report.read_text().splitlines()
        self.assertIn(f"- **Judge model**: {review.JUDGE_MODELS['astra']}", lines)
        self.assertIn(
            "  - [C1 / major / holds, apply / agree](#c1-run-1-item-1)", lines
        )
        self.assertIn("::: note", lines)
        self.run_cli(
            "item", "decide", report, "C1", "--verdict", "applied", stdin="as proposed"
        )
        self.assertIn("**Decision**: applied", report.read_text())

    def test_a_wave_over_hand_picked_domains(self) -> None:
        """Cross the phase split on a wave named by its domains, and format it like any other."""
        report, domains = self.open_wave("correctness,docs")
        self.assertEqual(domains, ["correctness", "docs"])
        code, ended = self.chain_to_its_end(
            report, "correctness", ONE_ITEM, "Nothing to report.\n"
        )
        self.assertEqual(ended, "Chain correctness ends: it has reached its cap of 2\n")
        docs, ended = self.chain_to_its_end(report, "docs", ONE_ITEM)
        self.assertEqual(ended, "Chain docs ends: it has reached its cap of 1\n")
        self.assertEqual(code + docs, ["C1", "D1"])
        recap = self.decide_and_format(report, code + docs)
        self.assertIn("2 items · 2 apply", recap)
        self.assertIn(
            "- **Config**: correctness ≤2 · docs ≤1", report.read_text().splitlines()
        )


class EntryPointTest(unittest.TestCase):
    """The script as the executable the skill runs."""

    def test_the_executable_dispatches_a_command(self) -> None:
        """Running the file itself reaches the subcommand its arguments name."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp, "missing")
            completed = subprocess.run(
                [SCRIPT, "init", missing, "A", "--assessor", ASSESSOR],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(f"No such review dir: {missing}", completed.stderr)


if __name__ == "__main__":
    unittest.main()
