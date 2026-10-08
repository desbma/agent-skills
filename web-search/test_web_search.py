#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["llm==0.36", "llm-openai-codex==0.8.0"]
# ///
"""Tests for the web search script."""

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import types
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any
from unittest import mock

import llm_openai_codex

SCRIPT = Path(__file__).with_name("web-search")
_spec = importlib.util.spec_from_loader(
    "web_search", SourceFileLoader("web_search", str(SCRIPT))
)
assert _spec is not None and _spec.loader is not None
web_search = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(web_search)

QUERY = "What is the latest ruff release?"
PYPI_URL = "https://pypi.org/project/ruff/"
RELEASES_URL = "https://github.com/astral-sh/ruff/releases"
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/Ruff_(software)"
SEARCH = {
    "type": "search",
    "query": "ruff latest release",
    "queries": ["ruff latest release", "site:pypi.org ruff"],
    "sources": [{"type": "url", "url": PYPI_URL}, {"type": "url", "url": RELEASES_URL}],
}
OPEN_PAGE = {"type": "open_page", "url": RELEASES_URL}
FIND_IN_PAGE = {"type": "find_in_page", "url": RELEASES_URL, "pattern": "0.16"}
UNSOURCED_SEARCH = {"type": "search", "queries": ["ruff 0.16.10"], "sources": None}
SOURCES = [
    {"url": PYPI_URL, "title": "ruff · PyPI", "excerpt": "Lists 0.16.10 as latest."}
]
OUTPUT = {
    "answer": (
        f"Ruff 0.16.10 ([pypi.org]({PYPI_URL}?utm_source=openai)), "
        f"see the [releases]({RELEASES_URL}?page=1&utm_source=openai#assets) "
        f"and [Wikipedia]({WIKIPEDIA_URL}?utm_source=openai&utm_source=newsletter), "
        f"at `{PYPI_URL}?utm_source=openai`."
    ),
    "sources": SOURCES,
}


def event(kind: str, **fields: object) -> types.SimpleNamespace:
    """Build a Responses API stream event."""
    return types.SimpleNamespace(type=kind, **fields)


def web_search_call(item_id: str, action: dict[str, Any]) -> types.SimpleNamespace:
    """Build the stream event closing a hosted web search action."""
    item = {"type": "web_search_call", "id": item_id, "status": "completed"}
    return event("response.output_item.done", item={**item, "action": action})


EVENTS = [
    web_search_call("ws_1", SEARCH),
    web_search_call("ws_2", OPEN_PAGE),
    web_search_call("ws_3", FIND_IN_PAGE),
    web_search_call("ws_4", UNSOURCED_SEARCH),
    event("response.output_text.delta", delta=json.dumps(OUTPUT)),
]


class SearchTest(unittest.TestCase):
    """Asking the search model through the Codex backend."""

    def run_main(self, *args: str) -> tuple[str, mock.MagicMock]:
        """Run the script on ARGS against a canned stream, and return its output and the request call."""
        out = io.StringIO()
        with (
            mock.patch("sys.argv", ["web-search", *args]),
            mock.patch.object(
                llm_openai_codex, "get_codex_key", return_value=("token", None)
            ),
            mock.patch("openai.OpenAI") as client,
            contextlib.redirect_stdout(out),
        ):
            create = client.return_value.responses.create
            create.return_value = EVENTS
            web_search.main()
        return out.getvalue(), create

    def test_request(self) -> None:
        """Send the query with a required live web search, consulted sources, the schema and hidden reasoning."""
        _, create = self.run_main(QUERY)
        request = create.call_args.kwargs
        self.assertEqual(request["input"], [{"role": "user", "content": QUERY}])
        self.assertEqual(
            request["tools"], [{"type": "web_search", "external_web_access": True}]
        )
        self.assertEqual(request["tool_choice"], "required")
        self.assertIn("web_search_call.action.sources", request["include"])
        self.assertEqual(request["text"]["format"]["schema"], web_search.SCHEMA)
        self.assertEqual(request["reasoning"], {"effort": web_search.REASONING_EFFORT})

    def test_output(self) -> None:
        """Print the answer without tracking parameters, its sources, and the search actions in order."""
        out, _ = self.run_main(QUERY)
        self.assertEqual(
            json.loads(out),
            {
                "answer": (
                    f"Ruff 0.16.10 ([pypi.org]({PYPI_URL})), "
                    f"see the [releases]({RELEASES_URL}?page=1#assets) "
                    f"and [Wikipedia]({WIKIPEDIA_URL}?utm_source=newsletter), at `{PYPI_URL}`."
                ),
                "sources": SOURCES,
                "searches": [
                    {
                        "type": "search",
                        "queries": SEARCH["queries"],
                        "url": None,
                        "consulted": [PYPI_URL, RELEASES_URL],
                    },
                    {
                        "type": "open_page",
                        "queries": None,
                        "url": RELEASES_URL,
                        "consulted": [],
                    },
                    {
                        "type": "find_in_page",
                        "queries": None,
                        "url": RELEASES_URL,
                        "consulted": [],
                    },
                    {
                        "type": "search",
                        "queries": UNSOURCED_SEARCH["queries"],
                        "url": None,
                        "consulted": [],
                    },
                ],
            },
        )
        self.assertIn("ruff · PyPI", out)

    def test_missing_login(self) -> None:
        """Fail with the plugin's login error when there is no Codex login."""
        with (
            tempfile.TemporaryDirectory() as home,
            mock.patch.dict(
                os.environ,
                {
                    "CODEX_HOME": home,
                    "LLM_OPENAI_CODEX_AUTH_FILE": f"{home}/auth-codex.json",
                },
            ),
        ):
            self.assertRaises(llm_openai_codex.BorrowKeyError, web_search.search, QUERY)

    def test_refuses_anything_but_one_query(self) -> None:
        """Exit with a usage error on no query, an empty one, or more than one."""
        for args in ((), ("",), (QUERY, QUERY)):
            with (
                self.subTest(args=args),
                mock.patch("sys.argv", ["web-search", *args]),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as caught,
            ):
                web_search.main()
            self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
