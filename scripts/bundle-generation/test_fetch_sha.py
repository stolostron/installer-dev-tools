#!/usr/bin/env python3
"""
Unit tests for the fetch_sha_from_git_remote function.

All network access is mocked so the suite runs offline and on restricted
CI runners.
"""

import unittest
from unittest.mock import patch, MagicMock

from utils.git_sha_fetcher import fetch_sha_from_git_remote

VALID_SHA = "a" * 40  # 40-char hex string


class TestFetchShaFromGitRemote(unittest.TestCase):
    """Test cases for fetch_sha_from_git_remote function."""

    @patch("utils.git_sha_fetcher.Git")
    def test_returns_sha_for_valid_branch(self, mock_git_cls):
        """Mocked ls-remote returning a valid SHA line."""
        mock_git_cls.return_value.ls_remote.return_value = (
            f"{VALID_SHA}\trefs/heads/master"
        )

        sha = fetch_sha_from_git_remote(
            "https://github.com/openshift/hive.git", "master"
        )

        self.assertEqual(sha, VALID_SHA)
        mock_git_cls.return_value.ls_remote.assert_called_once_with(
            "https://github.com/openshift/hive.git", "refs/heads/master"
        )

    @patch("utils.git_sha_fetcher.Git")
    def test_invalid_branch_raises_value_error(self, mock_git_cls):
        """Empty ls-remote output → ValueError."""
        mock_git_cls.return_value.ls_remote.return_value = ""

        with self.assertRaises(ValueError) as ctx:
            fetch_sha_from_git_remote(
                "https://github.com/openshift/hive.git",
                "this-branch-does-not-exist",
            )

        self.assertIn("No output from git ls-remote", str(ctx.exception))

    @patch("utils.git_sha_fetcher.Git")
    def test_invalid_repo_raises_exception(self, mock_git_cls):
        """git ls-remote itself raises → propagated."""
        mock_git_cls.return_value.ls_remote.side_effect = Exception(
            "fatal: repository not found"
        )

        with self.assertRaises(Exception):
            fetch_sha_from_git_remote(
                "https://github.com/nonexistent/repository-12345.git",
                "master",
            )

    @patch("utils.git_sha_fetcher.Git")
    def test_invalid_sha_format_raises_value_error(self, mock_git_cls):
        """ls-remote returning malformed output → ValueError."""
        mock_git_cls.return_value.ls_remote.return_value = (
            "not-a-sha\trefs/heads/master"
        )

        with self.assertRaises(ValueError) as ctx:
            fetch_sha_from_git_remote(
                "https://github.com/openshift/hive.git", "master"
            )

        self.assertIn("Invalid SHA format", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
