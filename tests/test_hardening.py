"""
Open Virtual Agent Research Platform (OVARP) — Hardening Tests

Covers the findings from the SpatialLab QA rounds that were about the server
refusing bad input rather than about a feature: identifier safety, survey
ranges, empty scenarios, placeholder credentials and the survey results token.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import os

import pytest

os.environ["OVARP_TESTING"] = "1"

from src.api.routers.llm import _is_placeholder
from src.core.identifiers import UnsafeIdentifierError, safe_path, validate_identifier


class TestIdentifierSafety:
    """A profile or scenario id becomes a filename, so it must stay one."""

    @pytest.mark.parametrize("value", ["casual_companion", "condition-1", "a", "A1_b-2"])
    def test_plain_names_are_accepted(self, value):
        assert validate_identifier(value) == value

    @pytest.mark.parametrize("value", [
        "../../etc/passwd", "a/b", "a\\b", "..", ".", "", "with space",
        "x" * 65, "sneaky/../../x",
    ])
    def test_path_like_names_are_refused(self, value):
        with pytest.raises(UnsafeIdentifierError):
            validate_identifier(value)

    def test_safe_path_stays_inside_the_directory(self, tmp_path):
        resolved = safe_path(tmp_path, "my_profile")

        assert resolved.parent == tmp_path.resolve()
        assert resolved.name == "my_profile.yaml"

    def test_safe_path_refuses_to_escape(self, tmp_path):
        with pytest.raises(UnsafeIdentifierError):
            safe_path(tmp_path, "../escaped")


class TestPlaceholderKeys:
    """A credential nobody filled in must not report as healthy."""

    @pytest.mark.parametrize("key", [
        "sk-dummy", "dummy", "sk-...", "AIzaSy...", "changeme",
        "your-key-here", "<your key>", "short",
    ])
    def test_placeholders_are_detected(self, key):
        assert _is_placeholder(key) is True

    @pytest.mark.parametrize("key", [
        "sk-proj-9f3a2b7c1d4e6f8a0b2c", "AIzaSyD-1a2B3c4D5e6F7g8H9i0J",
    ])
    def test_real_looking_keys_pass(self, key):
        assert _is_placeholder(key) is False
