from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest


class AccountPageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.forms = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.add(values["id"])
        if tag == "form" and "id" in values:
            self.forms.add(values["id"])
        if tag == "a" and "href" in values:
            self.links.append(values["href"])


def test_account_page_contains_login_recovery_invitation_and_profile_flows():
    page = Path(__file__).resolve().parents[2] / "login.html"
    parser = AccountPageParser()
    parser.feed(page.read_text(encoding="utf-8"))

    assert {"login-view", "forgot-view", "invite-view", "reset-view", "account-view"} <= parser.ids
    assert {
        "login-form",
        "forgot-form",
        "set-password-form",
        "reset-form",
        "first-password-form",
        "change-form",
    } <= parser.forms
    assert "google-login" in parser.ids
    assert "github-login" in parser.ids


def test_account_page_uses_versioned_api_and_does_not_embed_provider_secrets():
    page = Path(__file__).resolve().parents[2] / "login.html"
    source = page.read_text(encoding="utf-8")

    assert 'meta name="hw-api-base"' in source
    assert "/account/password/login" in source
    assert "/account/password/reset/confirm" in source
    assert "/account/oauth/" in source
    assert "CLIENT_SECRET" not in source
    assert "HW_OAUTH_ENCRYPTION_KEY" not in source



def test_account_page_inline_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed in this test environment")

    page = Path(__file__).resolve().parents[2] / "login.html"
    source = page.read_text(encoding="utf-8")
    script = source.split("<script>", 1)[1].split("</script>", 1)[0]
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as handle:
        handle.write(script)
        handle.flush()
        subprocess.run([node, "--check", handle.name], check=True, capture_output=True, text=True)
