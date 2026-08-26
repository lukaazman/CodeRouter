import base64
import hashlib
import json
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import codex_free_wrapper as wrapper
from tests.ui_test_helpers import build_hidden_app


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self, _limit):
        return self.payload

    def close(self):
        return None


class OpenRouterAuthTests(unittest.TestCase):
    def test_pkce_pair_matches_s256(self):
        verifier, challenge = wrapper.create_openrouter_pkce_pair()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        self.assertGreaterEqual(len(verifier), 43)
        self.assertEqual(challenge, expected)
        self.assertNotIn("=", challenge)

    def test_auth_url_is_localhost_only_and_contains_pkce_fields(self):
        callback = "http://localhost:43127/oauth/callback"
        url = wrapper.build_openrouter_auth_url(callback, "challenge-value")
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["callback_url"], [callback])
        self.assertEqual(query["code_challenge"], ["challenge-value"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["key_label"], ["CodeRouter"])
        for invalid in (
            "https://localhost:43127/oauth/callback",
            "http://example.test:43127/oauth/callback",
            "http://localhost/oauth/callback",
        ):
            with self.assertRaises(ValueError):
                wrapper.build_openrouter_auth_url(invalid, "challenge-value")

    def test_callback_parser_never_returns_provider_error_details(self):
        code, error = wrapper.parse_openrouter_callback_url(
            "http://localhost:43127/oauth/callback?code=one-time-code"
        )
        self.assertEqual(code, "one-time-code")
        self.assertEqual(error, "")

        code, error = wrapper.parse_openrouter_callback_url(
            "http://localhost:43127/oauth/callback?error=provider-secret-error"
        )
        self.assertEqual(code, "")
        self.assertEqual(error, "OpenRouter authorization was not completed.")
        self.assertNotIn("provider-secret-error", error)

    def test_exchange_posts_pkce_payload_without_bearer_header(self):
        captured = {}
        api_key = "sk-or-v1-test-key"

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(json.dumps({"key": api_key}).encode("utf-8"))

        result = wrapper.exchange_openrouter_oauth_code(
            "one-time-code",
            "verifier-value",
            opener=opener,
        )
        self.assertEqual(result, api_key)
        request = captured["request"]
        self.assertEqual(request.full_url, wrapper.OPENROUTER_AUTH_KEYS_URL)
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {
                "code": "one-time-code",
                "code_verifier": "verifier-value",
                "code_challenge_method": "S256",
            },
        )

    def test_exchange_errors_are_generic_and_do_not_echo_credentials(self):
        code = "one-time-code"
        verifier = "verifier-value"

        def rejected(_request, timeout):
            raise HTTPError(wrapper.OPENROUTER_AUTH_KEYS_URL, 401, "secret detail", {}, None)

        with self.assertRaises(RuntimeError) as context:
            wrapper.exchange_openrouter_oauth_code(code, verifier, opener=rejected)
        message = str(context.exception)
        self.assertIn("sign-in rejected", message)
        self.assertNotIn(code, message)
        self.assertNotIn(verifier, message)
        self.assertNotIn("secret detail", message)

        with self.assertRaises(RuntimeError) as context:
            wrapper.exchange_openrouter_oauth_code(
                code,
                verifier,
                opener=lambda _request, **_kwargs: FakeResponse(b"{}"),
            )
        self.assertNotIn(code, str(context.exception))
        self.assertNotIn(verifier, str(context.exception))

    def test_local_secret_boundary_is_explicit(self):
        root = Path(__file__).resolve().parents[1]
        gitignore = (root / ".gitignore").read_text(encoding="utf-8")
        example = json.loads((root / "local_config.example.json").read_text(encoding="utf-8"))
        self.assertIn("local_config.json", gitignore)
        self.assertIn("local_config.*.json", gitignore)
        self.assertEqual(example["openrouter_api_key"], "")


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class OpenRouterAuthUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            tk.Tcl()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tcl unavailable: {exc}")

    def setUp(self):
        self.config_dir = tempfile.TemporaryDirectory()
        self.original_config_path = wrapper.CONFIG_PATH
        wrapper.CONFIG_PATH = Path(self.config_dir.name) / "local_config.json"
        with mock.patch.object(wrapper.webbrowser, "open") as opened:
            self.app = build_hidden_app(wrapper)
            opened.assert_not_called()

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.config_dir.cleanup()

    def test_connection_control_is_progressively_disclosed(self):
        self.assertEqual(self.app.openrouter_connect_button.grid_info(), {})
        self.app.trust_settings_button.invoke()
        self.assertNotEqual(self.app.openrouter_connect_button.grid_info(), {})
        self.assertEqual(self.app.openrouter_connect_button.cget("text"), "Connect OpenRouter")

    def test_status_and_metadata_never_show_local_key(self):
        secret = "sk-or-v1-local-only-test-key"
        self.app.api_key = secret
        self.app._refresh_trust_settings_surface()
        self.app._set_trust_settings_disclosure(True)
        detail = self.app.trust_settings_detail_text.get()
        self.assertIn("OpenRouter: connected · local key ready", detail)
        self.assertNotIn(secret, detail)
        self.assertNotIn("Bearer", detail)


if __name__ == "__main__":
    unittest.main()
