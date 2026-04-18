import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parser import parse_prefix, parse_attributed_body


class TestParsePrefix:
    def test_no_prefix_returns_inject(self):
        result = parse_prefix("what is the build status?")
        assert result["action"] == "inject"
        assert result["prompt"] == "what is the build status?"
        assert result["directory_alias"] is None

    def test_new_prefix_default_dir(self):
        result = parse_prefix("new: set up a python project")
        assert result["action"] == "spawn"
        assert result["prompt"] == "set up a python project"
        assert result["directory_alias"] == "default"

    def test_new_prefix_with_alias(self):
        result = parse_prefix("new:centralis: fix the auth handler")
        assert result["action"] == "spawn"
        assert result["prompt"] == "fix the auth handler"
        assert result["directory_alias"] == "centralis"

    def test_new_prefix_case_insensitive(self):
        result = parse_prefix("New:Nexus: check the build")
        assert result["action"] == "spawn"
        assert result["prompt"] == "check the build"
        assert result["directory_alias"] == "nexus"

    def test_new_prefix_with_home_alias(self):
        result = parse_prefix("new:home: clean up dotfiles")
        assert result["action"] == "spawn"
        assert result["prompt"] == "clean up dotfiles"
        assert result["directory_alias"] == "home"

    def test_new_prefix_with_frontend_alias(self):
        result = parse_prefix("new:frontend: update the login page")
        assert result["action"] == "spawn"
        assert result["prompt"] == "update the login page"
        assert result["directory_alias"] == "frontend"

    def test_new_prefix_unknown_alias_treated_as_default(self):
        result = parse_prefix("new:unknown: do something")
        assert result["action"] == "spawn"
        assert result["prompt"] == "unknown: do something"
        assert result["directory_alias"] == "default"

    def test_empty_text_returns_none(self):
        result = parse_prefix("")
        assert result is None

    def test_whitespace_only_returns_none(self):
        result = parse_prefix("   ")
        assert result is None


class TestParseAttributedBody:
    def test_none_returns_none(self):
        assert parse_attributed_body(None) is None

    def test_empty_bytes_returns_none(self):
        assert parse_attributed_body(b"") is None

    def test_extracts_nsstring(self):
        text = b"Hello world"
        blob = b"\x00\x00NSString\x00\x2B" + bytes([len(text)]) + text
        result = parse_attributed_body(blob)
        assert result == "Hello world"

    def test_no_nsstring_marker_returns_none(self):
        assert parse_attributed_body(b"some random bytes without marker") is None
