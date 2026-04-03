"""Tests for SDK teammate scope enforcement hooks."""

import pytest

from autoresearch_x.sdk_teammate import _path_matches


class TestPathMatches:
    def test_exact_match(self):
        assert _path_matches("server.py", "server.py") is True

    def test_exact_mismatch(self):
        assert _path_matches("server.py", "client.py") is False

    def test_prefix_match(self):
        assert _path_matches("src/server.py", "src/") is True

    def test_prefix_no_slash(self):
        assert _path_matches("src/server.py", "src/server.py") is True

    def test_suffix_match(self):
        assert _path_matches("server.py", "*.py") is True

    def test_suffix_nested(self):
        assert _path_matches("src/server.py", "*.py") is True

    def test_path_ends_with_pattern(self):
        assert _path_matches("src/server.py", "server.py") is True

    def test_readonly_blocked(self):
        assert _path_matches("bench.py", "bench.py") is True
        assert _path_matches("src/bench.py", "bench.py") is True

    def test_case_sensitive(self):
        assert _path_matches("Server.py", "server.py") is False
