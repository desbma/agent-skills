#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["openai==3.29.0"]
# ///
"""Tests for the web search script."""

import base64
import contextlib
import email.message
import fcntl
import importlib.util
import io
import json
import os
import signal
import stat
import tempfile
import time
import unittest
import urllib.error
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any
from unittest import mock

import httpx2
from openai import OpenAI

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
OUTPUT_TEXT = json.dumps(OUTPUT)
DAY = 24 * 60 * 60


def web_search_call(item_id: str, action: dict[str, Any]) -> dict[str, Any]:
    """Build the stream event closing a hosted web search action."""
    item = {"type": "web_search_call", "id": item_id, "status": "completed"}
    return {"type": "response.output_item.done", "item": {**item, "action": action}}


EVENTS = [
    web_search_call("ws_1", SEARCH),
    web_search_call("ws_2", OPEN_PAGE),
    web_search_call("ws_3", FIND_IN_PAGE),
    web_search_call("ws_4", UNSOURCED_SEARCH),
    {"type": "response.output_text.delta", "delta": OUTPUT_TEXT[:40]},
    {"type": "response.output_text.delta", "delta": OUTPUT_TEXT[40:]},
    {
        "type": "response.output_item.done",
        "item": {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "content": [{"type": "output_text", "text": OUTPUT_TEXT}],
        },
    },
    {"type": "response.completed", "response": {"status": "completed", "output": []}},
]


def jwt(exp: float) -> str:
    """Build an unsigned JWT expiring at the Unix time EXP."""
    claims = json.dumps({"exp": int(exp)}).encode()
    return f"header.{base64.urlsafe_b64encode(claims).decode().rstrip('=')}.signature"


LOGIN = {
    "access_token": jwt(time.time() + 7 * DAY),
    "refresh_token": "refresh-1",
    "id_token": "id-1",
    "account_id": "account-1",
}
EXPIRING_LOGIN = {**LOGIN, "access_token": jwt(time.time() + 60)}
RENEWED_TOKENS = {
    "access_token": jwt(time.time() + 10 * DAY),
    "refresh_token": "refresh-2",
    "id_token": "id-2",
}
RENEWED_LOGIN = {**LOGIN, **RENEWED_TOKENS}
# entry of another hax provider, alongside the ChatGPT login
OTHER_ENTRY = {"api_key": "other-key"}


class SearchTest(unittest.TestCase):
    """Asking the search model through the Codex backend, with the ChatGPT login of hax."""

    def setUp(self) -> None:
        """Set up a hax store holding a valid login, a fake backend and a fake token endpoint."""
        state_home = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, {"XDG_STATE_HOME": state_home}))
        self.store = Path(state_home) / "hax/auth.json"
        self.store.parent.mkdir()
        self.write_store(self.store, LOGIN)
        self.events = EVENTS
        self.requests: list[httpx2.Request] = []
        self.enterContext(mock.patch("openai.OpenAI", side_effect=self.client))
        self.urlopen = self.enterContext(mock.patch("urllib.request.urlopen"))

    @staticmethod
    def write_store(store: Path, login: dict[str, str] | None) -> None:
        """Write a hax store with LOGIN as its ChatGPT login, and no login when None."""
        content: dict[str, Any] = {"other": OTHER_ENTRY}
        if login is not None:
            content["codex"] = login
        store.write_text(json.dumps(content))

    def client(self, **kwargs: Any) -> OpenAI:
        """Build an OpenAI client answering every request with the stream of self.events."""

        def respond(request: httpx2.Request) -> httpx2.Response:
            """Record a request and answer it with the event stream."""
            self.requests.append(request)
            body = "".join(
                f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                for event in self.events
            )
            return httpx2.Response(
                200, headers={"content-type": "text/event-stream"}, text=body
            )

        transport = httpx2.MockTransport(respond)
        return OpenAI(**kwargs, http_client=httpx2.Client(transport=transport))

    def test_request(self) -> None:
        """Send the query with a required live web search, consulted sources, the schema and hidden reasoning."""
        web_search.search(QUERY)
        (request,) = self.requests
        self.assertEqual(
            str(request.url), "https://chatgpt.com/backend-api/codex/responses"
        )
        body = json.loads(request.content)
        self.assertEqual(body["model"], web_search.MODEL)
        self.assertEqual(body["input"], [{"role": "user", "content": QUERY}])
        self.assertEqual(
            body["tools"], [{"type": "web_search", "external_web_access": True}]
        )
        self.assertEqual(body["tool_choice"], "required")
        self.assertEqual(body["include"], ["web_search_call.action.sources"])
        self.assertEqual(body["text"]["format"]["schema"], web_search.SCHEMA)
        self.assertEqual(body["reasoning"], {"effort": web_search.REASONING_EFFORT})
        self.assertIs(body["store"], False)
        self.assertIs(body["stream"], True)

    def test_output(self) -> None:
        """Print the answer without tracking parameters, its sources, and the search actions in order."""
        out = io.StringIO()
        with (
            mock.patch("sys.argv", ["web-search", QUERY]),
            contextlib.redirect_stdout(out),
        ):
            web_search.main()
        self.assertEqual(
            json.loads(out.getvalue()),
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
        self.assertIn("ruff · PyPI", out.getvalue())

    def test_stream_failures(self) -> None:
        """Fail with the backend's reason when the response fails, stops short or errors."""
        for event, reason in (
            (
                {
                    "type": "response.failed",
                    "response": {
                        "status": "failed",
                        "error": {"code": "server_error", "message": "Backend down"},
                    },
                },
                "Backend down",
            ),
            (
                {
                    "type": "response.incomplete",
                    "response": {
                        "status": "incomplete",
                        "incomplete_details": {"reason": "max_output_tokens"},
                    },
                },
                "max_output_tokens",
            ),
            (
                {
                    "type": "error",
                    "code": "rate_limit_exceeded",
                    "message": "Slow down",
                },
                "Slow down",
            ),
        ):
            with self.subTest(event=event["type"]):
                self.events = [EVENTS[0], event]
                with self.assertRaisesRegex(RuntimeError, reason):
                    web_search.search(QUERY)

    def test_unfinished_stream(self) -> None:
        """Fail when the stream ends before the response completes."""
        self.events = EVENTS[:-1]
        with self.assertRaisesRegex(RuntimeError, "before completion"):
            web_search.search(QUERY)

    def test_uses_a_valid_login_as_is(self) -> None:
        """Authenticate with the login of hax, left as is while its access token is valid."""
        web_search.search(QUERY)
        (request,) = self.requests
        self.assertEqual(
            request.headers["authorization"], f"Bearer {LOGIN['access_token']}"
        )
        self.assertEqual(request.headers["chatgpt-account-id"], LOGIN["account_id"])
        self.urlopen.assert_not_called()
        self.assertEqual(
            json.loads(self.store.read_text()), {"other": OTHER_ENTRY, "codex": LOGIN}
        )

    def test_renews_an_expiring_login(self) -> None:
        """Renew an access token about to expire, and save the new tokens in the hax store."""
        self.write_store(self.store, EXPIRING_LOGIN)
        self.urlopen.return_value = io.BytesIO(json.dumps(RENEWED_TOKENS).encode())

        web_search.search(QUERY)

        (renewal,) = self.urlopen.call_args_list
        self.assertEqual(
            renewal.args[0].full_url, "https://auth.openai.com/oauth/token"
        )
        self.assertEqual(
            json.loads(renewal.args[0].data),
            {
                "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
                "grant_type": "refresh_token",
                "refresh_token": "refresh-1",
            },
        )
        self.assertEqual(
            json.loads(self.store.read_text()),
            {"other": OTHER_ENTRY, "codex": RENEWED_LOGIN},
        )
        self.assertEqual(stat.S_IMODE(self.store.stat().st_mode), 0o600)
        (request,) = self.requests
        self.assertEqual(
            request.headers["authorization"],
            f"Bearer {RENEWED_TOKENS['access_token']}",
        )

    def test_adopts_a_login_renewed_meanwhile(self) -> None:
        """Use the login another process renewed while waiting for the hax store lock."""
        self.write_store(self.store, EXPIRING_LOGIN)

        with mock.patch(
            "fcntl.flock",
            side_effect=lambda *_: self.write_store(self.store, RENEWED_LOGIN),
        ):
            web_search.search(QUERY)

        self.urlopen.assert_not_called()
        (request,) = self.requests
        self.assertEqual(
            request.headers["authorization"],
            f"Bearer {RENEWED_TOKENS['access_token']}",
        )

    def test_renews_a_symlinked_login(self) -> None:
        """Renew the login a symlinked store points to, under the exclusive lock of that file."""
        profile = self.store.with_name("auth-pro.json")
        self.write_store(profile, EXPIRING_LOGIN)
        self.store.unlink()
        self.store.symlink_to(profile.name)

        def renew(*_: Any, **__: Any) -> io.BytesIO:
            """Check the lock of the profile is held exclusively, then answer with the renewed tokens."""
            with (
                open(profile.with_name("auth-pro.json.lock"), "a") as probe,
                self.assertRaises(BlockingIOError),
            ):
                fcntl.flock(probe, fcntl.LOCK_SH | fcntl.LOCK_NB)
            return io.BytesIO(json.dumps(RENEWED_TOKENS).encode())

        self.urlopen.side_effect = renew

        web_search.search(QUERY)

        self.assertTrue(self.store.is_symlink())
        self.assertEqual(
            json.loads(profile.read_text()),
            {"other": OTHER_ENTRY, "codex": RENEWED_LOGIN},
        )
        self.assertFalse(self.store.with_name("auth.json.lock").exists())

    def test_default_state_home(self) -> None:
        """Read the hax store under ~/.local/state when XDG_STATE_HOME is unset or empty."""
        home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (home / ".local/state").mkdir(parents=True)
        self.store.parent.rename(home / ".local/state/hax")
        for environ in ({"HOME": str(home)}, {"HOME": str(home), "XDG_STATE_HOME": ""}):
            with (
                self.subTest(environ=environ),
                mock.patch.dict(os.environ, environ, clear=True),
            ):
                web_search.search(QUERY)
                self.assertEqual(
                    self.requests[-1].headers["authorization"],
                    f"Bearer {LOGIN['access_token']}",
                )

    def test_holds_cancellation_until_the_renewal_is_saved(self) -> None:
        """Save the renewed login before ending on a cancellation received during its renewal."""
        self.write_store(self.store, EXPIRING_LOGIN)

        def renew(*_: Any, **__: Any) -> io.BytesIO:
            """Receive a cancellation, then answer with the renewed tokens."""
            signal.raise_signal(signal.SIGINT)
            return io.BytesIO(json.dumps(RENEWED_TOKENS).encode())

        self.urlopen.side_effect = renew

        with self.assertRaises(KeyboardInterrupt):
            web_search.search(QUERY)

        self.assertEqual(
            json.loads(self.store.read_text()),
            {"other": OTHER_ENTRY, "codex": RENEWED_LOGIN},
        )
        self.assertEqual(self.requests, [])

    def test_rejected_renewal(self) -> None:
        """Fail with the token endpoint's reason when it rejects the renewal, leaving the store as is."""
        self.write_store(self.store, EXPIRING_LOGIN)
        body = json.dumps({"error": {"code": "refresh_token_reused"}}).encode()
        self.urlopen.side_effect = urllib.error.HTTPError(
            "https://auth.openai.com/oauth/token",
            401,
            "Unauthorized",
            email.message.Message(),
            io.BytesIO(body),
        )

        with self.assertRaisesRegex(web_search.LoginError, "refresh_token_reused"):
            web_search.search(QUERY)

        self.assertEqual(
            json.loads(self.store.read_text()),
            {"other": OTHER_ENTRY, "codex": EXPIRING_LOGIN},
        )
        self.assertEqual(self.requests, [])

    def test_renewal_without_access_token(self) -> None:
        """Fail when the token endpoint answers without an access token, leaving the store as is."""
        self.write_store(self.store, EXPIRING_LOGIN)
        self.urlopen.return_value = io.BytesIO(
            json.dumps({"refresh_token": "refresh-2"}).encode()
        )

        with self.assertRaisesRegex(web_search.LoginError, "no access token"):
            web_search.search(QUERY)

        self.assertEqual(
            json.loads(self.store.read_text()),
            {"other": OTHER_ENTRY, "codex": EXPIRING_LOGIN},
        )
        self.assertEqual(self.requests, [])

    def test_renewal_keeps_unrenewed_tokens(self) -> None:
        """Keep the stored tokens the token endpoint omits or nulls."""
        self.write_store(self.store, EXPIRING_LOGIN)
        access_token = RENEWED_TOKENS["access_token"]
        self.urlopen.return_value = io.BytesIO(
            json.dumps({"access_token": access_token, "refresh_token": None}).encode()
        )

        web_search.search(QUERY)

        self.assertEqual(
            json.loads(self.store.read_text()),
            {"other": OTHER_ENTRY, "codex": {**LOGIN, "access_token": access_token}},
        )

    def test_missing_login(self) -> None:
        """Fail without a hax store, or without a ChatGPT login in it."""
        for name, prepare in (
            ("no store", self.store.unlink),
            ("no login", lambda: self.write_store(self.store, None)),
        ):
            with self.subTest(name):
                prepare()
                with self.assertRaisesRegex(web_search.LoginError, "/login"):
                    web_search.search(QUERY)
                self.assertEqual(self.requests, [])

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
