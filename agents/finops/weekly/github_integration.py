"""GitHub Integration Agent — posts PR comments and creates issues/check annotations.

Uses the PyGithub library to interact with the GitHub API for posting
FinOps findings as PR comments, check annotations, and tracking issues.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_GITHUB_TOKEN_ENV = "GITHUB_TOKEN"

FINOPS_LABELS = {
    "open": "finops/open",
    "resolved": "finops/resolved",
    "suppressed": "finops/suppressed",
    "needs_review": "finops/needs-review",
}


def _get_github_client():
    """Return an authenticated PyGithub Github instance.

    Reads the token from the GITHUB_TOKEN environment variable.

    Raises:
        RuntimeError: If GITHUB_TOKEN is not set.
    """
    from github import Github  # imported here to keep SDK import lazy

    token = os.environ.get(_GITHUB_TOKEN_ENV)
    if not token:
        raise RuntimeError(
            f"Environment variable {_GITHUB_TOKEN_ENV} is required for GitHub integration"
        )
    return Github(token)


class GitHubIntegrationAgent:
    """Provides GitHub integration for FinOps recommendations.

    Posts PR comments, creates check annotations, opens tracking issues, and
    optionally creates remediation PRs with Terraform fixes.
    """

    def __init__(self, token: str | None = None) -> None:
        """Initialise the GitHub Integration agent.

        Args:
            token: GitHub personal access token. Defaults to GITHUB_TOKEN env var.
        """
        if token:
            os.environ[_GITHUB_TOKEN_ENV] = token

    def post_pr_comment(self, repo: str, pr_number: int, body: str) -> None:
        """Post a comment on a pull request.

        Args:
            repo: Full repository name (e.g. 'owner/repo').
            pr_number: Pull request number.
            body: Markdown body text of the comment.
        """
        try:
            gh = _get_github_client()
            repository = gh.get_repo(repo)
            pr = repository.get_pull(pr_number)
            pr.create_issue_comment(body)
            logger.info("Posted PR comment on %s#%d", repo, pr_number)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to post PR comment on %s#%d: %s", repo, pr_number, exc)
            raise

    def create_check_annotation(
        self,
        repo: str,
        sha: str,
        annotations: list[dict],
    ) -> None:
        """Create GitHub check annotations for a commit.

        Each annotation dict should have keys: path, start_line, end_line,
        annotation_level ('notice'|'warning'|'failure'), title, message.

        Args:
            repo: Full repository name.
            sha: The commit SHA to annotate.
            annotations: List of annotation dicts.
        """
        try:
            from github import GithubException

            gh = _get_github_client()
            repository = gh.get_repo(repo)

            # Create a check run with the annotations
            check_run = repository.create_check_run(
                name="FinOps Review",
                head_sha=sha,
                status="completed",
                conclusion="neutral",
                output={
                    "title": "FinOps Review Annotations",
                    "summary": f"{len(annotations)} FinOps annotation(s) generated.",
                    "annotations": [
                        {
                            "path": a.get("path", "."),
                            "start_line": a.get("start_line", 1),
                            "end_line": a.get("end_line", 1),
                            "annotation_level": a.get("annotation_level", "notice"),
                            "title": a.get("title", "FinOps Finding"),
                            "message": a.get("message", ""),
                        }
                        for a in annotations[:50]  # GitHub API limit: 50 per request
                    ],
                },
            )
            logger.info("Created check run %s with %d annotations", check_run.name, len(annotations))
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to create check annotations on %s@%s: %s", repo, sha, exc)
            raise

    def create_issue(
        self,
        repo: str,
        title: str,
        body: str,
        labels: list[str],
    ) -> int:
        """Create a GitHub issue for a FinOps recommendation.

        Args:
            repo: Full repository name.
            title: Issue title.
            body: Markdown issue body.
            labels: List of label names to apply.

        Returns:
            The newly created issue number.
        """
        try:
            from github import GithubException

            gh = _get_github_client()
            repository = gh.get_repo(repo)

            # Ensure labels exist
            existing_labels = {lbl.name for lbl in repository.get_labels()}
            label_objects = []
            for label_name in labels:
                if label_name not in existing_labels:
                    try:
                        repository.create_label(
                            name=label_name,
                            color="0075ca",
                            description="FinOps tracking label",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Could not create label %s: %s", label_name, exc)
                label_objects.append(label_name)

            issue = repository.create_issue(title=title, body=body, labels=label_objects)
            logger.info("Created issue #%d on %s: %s", issue.number, repo, title)
            return issue.number
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to create issue on %s: %s", repo, exc)
            raise

    def create_remediation_pr(
        self,
        repo: str,
        branch: str,
        changes: dict,
        title: str,
        body: str,
    ) -> int:
        """Create a remediation pull request with Terraform/config changes.

        Args:
            repo: Full repository name.
            branch: Name of the new branch to create.
            changes: Dict mapping file path → new file content (string).
            title: PR title.
            body: PR description (Markdown).

        Returns:
            The newly created PR number.
        """
        try:
            from github import GithubException, InputGitTreeElement

            gh = _get_github_client()
            repository = gh.get_repo(repo)
            default_branch = repository.default_branch
            base_sha = repository.get_branch(default_branch).commit.sha

            # Create a new tree with the changed files
            elements = []
            for file_path, content in changes.items():
                blob = repository.create_git_blob(content=content, encoding="utf-8")
                elements.append(
                    InputGitTreeElement(
                        path=file_path,
                        mode="100644",
                        type="blob",
                        sha=blob.sha,
                    )
                )

            base_tree = repository.get_git_tree(sha=base_sha, recursive=True)
            new_tree = repository.create_git_tree(elements, base_tree)
            parent_commit = repository.get_git_commit(base_sha)
            new_commit = repository.create_git_commit(
                message=f"finops: {title}\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>",
                tree=new_tree,
                parents=[parent_commit],
            )
            repository.create_git_ref(ref=f"refs/heads/{branch}", sha=new_commit.sha)

            pr = repository.create_pull(
                title=title,
                body=body,
                head=branch,
                base=default_branch,
            )
            # Apply labels
            pr.add_to_labels(FINOPS_LABELS["open"])
            logger.info("Created remediation PR #%d on %s: %s", pr.number, repo, title)
            return pr.number
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to create remediation PR on %s: %s", repo, exc)
            raise
