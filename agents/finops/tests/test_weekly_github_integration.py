"""Tests for the GitHub Integration Agent."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from agents.weekly.github_integration import GitHubIntegrationAgent, FINOPS_LABELS, _get_github_client


class TestGetGithubClient:
    def test_raises_when_no_token(self):
        saved = os.environ.pop("GITHUB_TOKEN", None)
        try:
            with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
                _get_github_client()
        finally:
            if saved:
                os.environ["GITHUB_TOKEN"] = saved

    def test_returns_client_when_token_set(self):
        mock_github_cls = Mock()
        mock_github_cls.return_value = Mock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}), \
             patch("github.Github", mock_github_cls):
            client = _get_github_client()
        mock_github_cls.assert_called_once_with("test-token")


class TestGitHubIntegrationAgentInit:
    def test_init_with_token_sets_env(self):
        with patch.dict(os.environ, {}):
            GitHubIntegrationAgent(token="my-token")
            assert os.environ.get("GITHUB_TOKEN") == "my-token"

    def test_init_without_token_does_not_set_env(self):
        saved = os.environ.pop("GITHUB_TOKEN", None)
        try:
            GitHubIntegrationAgent()
            assert os.environ.get("GITHUB_TOKEN") is None
        finally:
            if saved:
                os.environ["GITHUB_TOKEN"] = saved


class TestPostPRComment:
    def test_post_pr_comment_success(self):
        mock_issue_comment = Mock()
        mock_pr = Mock()
        mock_pr.create_issue_comment.return_value = mock_issue_comment

        mock_repo = Mock()
        mock_repo.get_pull.return_value = mock_pr

        mock_gh = Mock()
        mock_gh.get_repo.return_value = mock_repo

        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("github.Github", return_value=mock_gh):
            agent = GitHubIntegrationAgent()
            agent.post_pr_comment("owner/repo", 42, "## FinOps findings\n\nAll good.")

        mock_repo.get_pull.assert_called_once_with(42)
        mock_pr.create_issue_comment.assert_called_once()

    def test_post_pr_comment_raises_on_error(self):
        mock_gh = Mock()
        mock_gh.get_repo.side_effect = Exception("Network error")

        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("github.Github", return_value=mock_gh):
            agent = GitHubIntegrationAgent()
            with pytest.raises(Exception, match="Network error"):
                agent.post_pr_comment("owner/repo", 42, "body")


class TestCreateCheckAnnotation:
    def test_create_check_annotation_success(self):
        mock_check_run = Mock()
        mock_check_run.name = "FinOps Review"

        mock_repo = Mock()
        mock_repo.create_check_run.return_value = mock_check_run

        mock_gh = Mock()
        mock_gh.get_repo.return_value = mock_repo

        annotations = [
            {
                "path": "main.tf",
                "start_line": 10,
                "end_line": 10,
                "annotation_level": "warning",
                "title": "Missing tag",
                "message": "owner tag is required",
            }
        ]

        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("github.Github", return_value=mock_gh), \
             patch("github.GithubException", Exception):
            agent = GitHubIntegrationAgent()
            agent.create_check_annotation("owner/repo", "abc123", annotations)

        mock_repo.create_check_run.assert_called_once()

    def test_create_check_annotation_raises_on_error(self):
        mock_gh = Mock()
        mock_gh.get_repo.side_effect = Exception("API error")

        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("github.Github", return_value=mock_gh):
            agent = GitHubIntegrationAgent()
            with pytest.raises(Exception):
                agent.create_check_annotation("owner/repo", "sha", [])


class TestCreateIssue:
    def test_create_issue_success(self):
        mock_issue = Mock()
        mock_issue.number = 99

        existing_label = Mock()
        existing_label.name = "finops/open"

        mock_repo = Mock()
        mock_repo.get_labels.return_value = [existing_label]
        mock_repo.create_issue.return_value = mock_issue

        mock_gh = Mock()
        mock_gh.get_repo.return_value = mock_repo

        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("github.Github", return_value=mock_gh), \
             patch("github.GithubException", Exception):
            agent = GitHubIntegrationAgent()
            result = agent.create_issue("owner/repo", "Test Issue", "body", ["finops/open"])

        assert result == 99
        mock_repo.create_issue.assert_called_once()

    def test_create_issue_creates_missing_labels(self):
        mock_issue = Mock()
        mock_issue.number = 100

        mock_repo = Mock()
        mock_repo.get_labels.return_value = []  # No existing labels
        mock_repo.create_issue.return_value = mock_issue

        mock_gh = Mock()
        mock_gh.get_repo.return_value = mock_repo

        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("github.Github", return_value=mock_gh), \
             patch("github.GithubException", Exception):
            agent = GitHubIntegrationAgent()
            result = agent.create_issue("owner/repo", "Title", "body", ["finops/open", "finops/needs-review"])

        assert mock_repo.create_label.call_count == 2

    def test_create_issue_label_creation_failure_logged(self):
        """Label creation failure should not abort issue creation."""
        mock_issue = Mock()
        mock_issue.number = 101

        mock_repo = Mock()
        mock_repo.get_labels.return_value = []
        mock_repo.create_label.side_effect = Exception("label error")
        mock_repo.create_issue.return_value = mock_issue

        mock_gh = Mock()
        mock_gh.get_repo.return_value = mock_repo

        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("github.Github", return_value=mock_gh), \
             patch("github.GithubException", Exception):
            agent = GitHubIntegrationAgent()
            result = agent.create_issue("owner/repo", "Title", "body", ["new-label"])

        # Issue was still created
        assert result == 101

    def test_create_issue_raises_on_api_error(self):
        mock_gh = Mock()
        mock_gh.get_repo.side_effect = Exception("not found")

        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("github.Github", return_value=mock_gh):
            agent = GitHubIntegrationAgent()
            with pytest.raises(Exception):
                agent.create_issue("owner/repo", "title", "body", [])


class TestCreateRemediationPR:
    def test_create_remediation_pr_success(self):
        mock_pr = Mock()
        mock_pr.number = 55

        mock_blob = Mock()
        mock_blob.sha = "blobsha123"

        mock_new_tree = Mock()
        mock_parent_commit = Mock()
        mock_new_commit = Mock()
        mock_new_commit.sha = "commitsha"

        mock_base_tree = Mock()

        mock_branch = Mock()
        mock_branch.commit = Mock()
        mock_branch.commit.sha = "basesha"

        mock_repo = Mock()
        mock_repo.default_branch = "main"
        mock_repo.get_branch.return_value = mock_branch
        mock_repo.create_git_blob.return_value = mock_blob
        mock_repo.get_git_tree.return_value = mock_base_tree
        mock_repo.create_git_tree.return_value = mock_new_tree
        mock_repo.get_git_commit.return_value = mock_parent_commit
        mock_repo.create_git_commit.return_value = mock_new_commit
        mock_repo.create_git_ref.return_value = Mock()
        mock_repo.create_pull.return_value = mock_pr

        mock_gh = Mock()
        mock_gh.get_repo.return_value = mock_repo

        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("github.Github", return_value=mock_gh), \
             patch("github.InputGitTreeElement", Mock()), \
             patch("github.GithubException", Exception):
            agent = GitHubIntegrationAgent()
            result = agent.create_remediation_pr(
                repo="owner/repo",
                branch="finops/fix-vm-sku",
                changes={"main.tf": 'resource "azurerm_linux_virtual_machine" "vm" { size = "Standard_D4s_v3" }'},
                title="Rightsize vm1 to Standard_D4s_v3",
                body="FinOps recommendation: downsize vm1",
            )

        assert result == 55
        mock_repo.create_pull.assert_called_once()

    def test_create_remediation_pr_raises_on_error(self):
        mock_gh = Mock()
        mock_gh.get_repo.side_effect = Exception("repo not found")

        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("github.Github", return_value=mock_gh):
            agent = GitHubIntegrationAgent()
            with pytest.raises(Exception):
                agent.create_remediation_pr("owner/repo", "branch", {}, "title", "body")


class TestFinOpsLabels:
    def test_label_constants(self):
        assert FINOPS_LABELS["open"] == "finops/open"
        assert FINOPS_LABELS["resolved"] == "finops/resolved"
        assert FINOPS_LABELS["suppressed"] == "finops/suppressed"
        assert FINOPS_LABELS["needs_review"] == "finops/needs-review"
