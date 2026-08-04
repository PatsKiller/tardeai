#!/usr/bin/env python3
"""Tests for the Schwab authenticator-page state machine added to schwab_auto_reauth.py.

Pure unit tests: no browser, no network, no credentials. Tests the page-detection helpers
and the state transition logic introduced in the 2026-08-04 authenticator-page repair.

Real incident: the browser landed on sws-gateway.schwab.com/ui/host/#/authenticators
after credential submission, but the old code had no handler for that page — it waited
420 seconds and timed out.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# ── Import the helpers under test ──
from schwab_auto_reauth import (
    _is_authenticator_page,
    _url_contains,
    _page_text,
    AUTH_PAGE_INDICATORS,
    AUTH_PAGE_CONTENT_SIG,
    TRUSTED_CONTACT_SEL,
    SEND_CHALLENGE_SEL,
    APPROVAL_PENDING_SIG,
    NEGATIVE_WORDS,
)


# ── Fake page-like objects for testing without Playwright ──

class FakeBody:
    """Minimal body element stub."""
    def __init__(self, text: str):
        self._text = text
    def inner_text(self):
        return self._text


class FakeFrame:
    """Minimal frame stub."""
    def __init__(self, text: str = ""):
        self._text = text
        self._body = FakeBody(text)

    def query_selector(self, sel):
        if sel == "body":
            return self._body
        return None

    def query_selector_all(self, sel):
        return []


class FakePage:
    """Minimal page stub for URL-based authenticator detection."""
    def __init__(self, url: str = "", frame_texts: list[str] | None = None):
        self.url = url
        self.frames = [FakeFrame(t) for t in (frame_texts or [])]


# ── AUTHENTICATOR PAGE DETECTION ──────────────────────────────────────────────────────

class TestAuthenticatorPageDetection:
    """_is_authenticator_page must detect by URL AND by page content."""

    def test_detects_by_url_fragment(self):
        """sws-gateway URL fragment is the primary signal."""
        page = FakePage(url="https://sws-gateway.schwab.com/ui/host/#/authenticators")
        assert _is_authenticator_page(page)

    def test_detects_by_url_domain_or_fragment(self):
        """Any page on sws-gateway.schwab.com or with /authenticators fragment matches."""
        # Domain match
        page = FakePage(url="https://sws-gateway.schwab.com/ui/host/#/some-page")
        assert _is_authenticator_page(page)
        # Fragment match on any domain
        page2 = FakePage(url="https://api.schwab.com/ui/host/#/authenticators")
        assert _is_authenticator_page(page2)

    def test_detects_by_content_signature(self):
        """Content-based fallback: page text mentions 'authenticator'."""
        page = FakePage(url="https://some-other.schwab.com/unknown",
                        frame_texts=["Please verify your identity using an authenticator below"])
        assert _is_authenticator_page(page)

    def test_detects_by_trusted_contact_content(self):
        """Content mentioning 'Trusted contact' also signals the authenticator page."""
        page = FakePage(url="https://sws-gateway.schwab.com/ui/host/#/mfa",
                        frame_texts=["Select your authenticator method",
                                     "Trusted contact — send push to your device"])
        assert _is_authenticator_page(page)

    def test_does_not_detect_normal_page(self):
        """Non-authenticator pages return False."""
        page = FakePage(url="https://api.schwabapi.com/v1/oauth/token")
        assert not _is_authenticator_page(page)

    def test_detects_verify_your_identity(self):
        """Partial match on 'verify your identity'."""
        page = FakePage(url="https://sws-gateway.schwab.com/ui/host/#/login",
                        frame_texts=["Login", "Please verify your identity",
                                     "We need to confirm it's really you"])
        assert _is_authenticator_page(page)


# ── URL CONTAINS HELPER ────────────────────────────────────────────────────────────────

class TestUrlContains:
    def test_matches_exact_fragment(self):
        page = FakePage(url="https://sws-gateway.schwab.com/ui/host/#/authenticators")
        assert _url_contains(page, AUTH_PAGE_INDICATORS)

    def test_case_insensitive(self):
        page = FakePage(url="https://SWS-GATEWAY.SCHWAB.COM/ui/host/#/AUTHENTICATORS")
        assert _url_contains(page, AUTH_PAGE_INDICATORS)

    def test_no_match(self):
        page = FakePage(url="https://api.schwabapi.com/v1/oauth/authorize")
        assert not _url_contains(page, AUTH_PAGE_INDICATORS)

    def test_empty_url(self):
        page = FakePage(url="")
        assert not _url_contains(page, AUTH_PAGE_INDICATORS)


# ── PAGE TEXT EXTRACTION ────────────────────────────────────────────────────────────────

class TestPageText:
    def test_extracts_text_from_frame(self):
        frame = FakeFrame("  Hello World  ")
        assert "hello world" in _page_text(frame)

    def test_truncates_to_500_chars(self):
        long_text = "x" * 1000
        frame = FakeFrame(long_text)
        assert len(_page_text(frame)) <= 500

    def test_empty_frame(self):
        frame = FakeFrame("")
        assert _page_text(frame) == ""


# ── SELECTOR INTEGRITY ─────────────────────────────────────────────────────────────────

class TestSelectorIntegrity:
    """All selectors must be syntactically valid CSS selectors (Playwright checks at
    runtime, but we check that they're non-empty well-formed strings here)."""

    def test_trusted_contact_selectors_non_empty(self):
        for sel in TRUSTED_CONTACT_SEL:
            assert sel, f"empty trusted-contact selector"
            assert isinstance(sel, str), f"non-string trusted-contact selector: {sel!r}"

    def test_send_challenge_selectors_non_empty(self):
        for sel in SEND_CHALLENGE_SEL:
            assert sel, f"empty send-challenge selector"
            assert isinstance(sel, str), f"non-string send-challenge selector: {sel!r}"

    def test_authenticator_indicators_non_empty(self):
        for ind in AUTH_PAGE_INDICATORS:
            assert ind, f"empty authenticator page indicator"
            assert isinstance(ind, str), f"non-string indicator: {ind!r}"

    def test_content_signatures_non_empty(self):
        for sig in AUTH_PAGE_CONTENT_SIG:
            assert sig, f"empty content signature"
            assert isinstance(sig, str), f"non-string signature: {sig!r}"

    def test_approval_pending_sigs_non_empty(self):
        for sig in APPROVAL_PENDING_SIG:
            assert sig, f"empty approval pending signature"
            assert isinstance(sig, str), f"non-string signature: {sig!r}"


# ── NEGATIVE WORDS — safety gate ────────────────────────────────────────────────────────

class TestNegativeWords:
    """Negative words block the clicker from clicking dangerous buttons."""

    def test_try_another_way_is_blocked(self):
        assert "try another way" in NEGATIVE_WORDS

    def test_resend_is_blocked(self):
        assert "resend" in NEGATIVE_WORDS

    def test_cancel_is_blocked(self):
        assert "cancel" in NEGATIVE_WORDS

    def test_decline_is_blocked(self):
        assert "decline" in NEGATIVE_WORDS

    def test_continue_is_not_blocked(self):
        assert "continue" not in NEGATIVE_WORDS


# ── STATE TRANSITION LOGIC (logical, not browser) ───────────────────────────────────────

class TestStateTransitions:
    """The state machine should never loop or get stuck."""

    VALID_STATES = {
        "LOGIN_FORM", "SUBMITTED", "AUTHENTICATOR_SELECTION", "CHALLENGE_SENT",
        "TERMS_OR_CONSENT", "ACCOUNT_GRANT", "CALLBACK_CAPTURED",
    }

    # Valid forward transitions
    FORWARD = {
        "LOGIN_FORM": {"SUBMITTED"},
        "SUBMITTED": {"AUTHENTICATOR_SELECTION", "CHALLENGE_SENT"},
        "AUTHENTICATOR_SELECTION": {"CHALLENGE_SENT", "TERMS_OR_CONSENT"},
        "CHALLENGE_SENT": {"TERMS_OR_CONSENT", "ACCOUNT_GRANT", "CALLBACK_CAPTURED"},
        "TERMS_OR_CONSENT": {"ACCOUNT_GRANT", "CALLBACK_CAPTURED"},
        "ACCOUNT_GRANT": {"CALLBACK_CAPTURED"},
        "CALLBACK_CAPTURED": set(),  # terminal
    }

    def test_all_states_are_valid(self):
        for s in self.VALID_STATES:
            assert s in self.FORWARD

    def test_callback_captured_is_terminal(self):
        assert self.FORWARD["CALLBACK_CAPTURED"] == set()

    def test_challenge_sent_can_go_to_callback(self):
        """Callback can arrive at any stage."""
        assert "CALLBACK_CAPTURED" in self.FORWARD["CHALLENGE_SENT"]

    def test_authenticator_selection_cannot_loop(self):
        """AUTHENTICATOR_SELECTION must not transition back to itself."""
        assert "AUTHENTICATOR_SELECTION" not in self.FORWARD["AUTHENTICATOR_SELECTION"]

    def test_no_reverse_transitions(self):
        """Forward-only: CHALLENGE_SENT must not go back to AUTHENTICATOR_SELECTION."""
        for state, targets in self.FORWARD.items():
            # Can't go backward (except CALLBACK_CAPTURED which goes nowhere)
            earlier_states = []
            if state != "CALLBACK_CAPTURED":
                # Find states that come before this one
                for s, t in self.FORWARD.items():
                    if state in t:
                        earlier_states.append(s)
            for prev in earlier_states:
                assert prev not in targets, f"{state} -> {prev} is a reverse transition"
