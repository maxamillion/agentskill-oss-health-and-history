# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.31,<3",
# ]
# ///
"""
Collect repository data from GitHub or GitLab APIs.

Outputs a structured JSON object to stdout containing metadata, commit activity,
contributors, issues, pull requests, releases, community profile, CI status,
and detected package ecosystems.

Authentication:
  Set GITHUB_TOKEN or GITLAB_TOKEN environment variables for higher rate limits.
  Without a token, GitHub allows 60 requests/hour; GitLab allows ~300/hour.

Usage:
  uv run collect_repo_data.py --platform github --owner OWNER --repo REPO
  uv run collect_repo_data.py --platform gitlab --owner OWNER --repo REPO
  uv run collect_repo_data.py --platform gitlab --owner OWNER --repo REPO --gitlab-url https://gitlab.example.com
  uv run collect_repo_data.py --url https://github.com/owner/repo

Examples:
  uv run collect_repo_data.py --platform github --owner pallets --repo flask
  uv run collect_repo_data.py --url https://gitlab.com/gitlab-org/gitlab
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote as url_quote

import requests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_url(url: str) -> tuple[str, str, str, str]:
    """Parse a GitHub or GitLab URL into (platform, owner, repo, base_url)."""
    url = url.rstrip("/")
    url = re.sub(r"\.git$", "", url)
    # Strip path suffixes like /tree/main, /issues, /-/blob/... etc.
    url = re.sub(
        r"(/-)?(/(tree|blob|issues|pulls|merge_requests|pipelines|commits|releases|tags|wikis)(/.*)?)?$",
        "",
        url,
    )

    gh_match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", url)
    if gh_match:
        return "github", gh_match.group(1), gh_match.group(2), "https://api.github.com"

    gl_match = re.match(r"https?://([^/]+)/(.+)/([^/]+)", url)
    if gl_match:
        host = gl_match.group(1)
        # Could be gitlab.com or self-hosted
        owner_path = gl_match.group(2)
        repo = gl_match.group(3)
        base = f"https://{host}"
        return "gitlab", owner_path, repo, base

    raise ValueError(f"Could not parse repository URL: {url}")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _days_ago(n: int) -> str:
    """Return ISO 8601 date string for n days ago."""
    return (_now_utc() - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


class ApiError(Exception):
    def __init__(self, status: int, message: str, url: str):
        self.status = status
        self.url = url
        super().__init__(f"HTTP {status} from {url}: {message}")


# ---------------------------------------------------------------------------
# GitHub collector
# ---------------------------------------------------------------------------


class GitHubCollector:
    def __init__(self, owner: str, repo: str):
        self.owner = owner
        self.repo = repo
        self.base = "https://api.github.com"
        self.session = requests.Session()
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self.session.headers["Accept"] = "application/vnd.github+json"
        self.session.headers["X-GitHub-Api-Version"] = "2022-11-28"
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.authenticated = bool(token)
        self.warnings: list[str] = []

    def _get(
        self, path: str, params: dict | None = None, retries: int = 3
    ) -> requests.Response:
        url = f"{self.base}{path}" if path.startswith("/") else path
        for attempt in range(retries):
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 202:
                # GitHub is computing stats; wait and retry
                time.sleep(3)
                continue
            if resp.status_code == 403:
                remaining = resp.headers.get("X-RateLimit-Remaining", "?")
                reset = resp.headers.get("X-RateLimit-Reset", "")
                reset_str = ""
                if reset:
                    try:
                        reset_dt = datetime.fromtimestamp(int(reset), tz=timezone.utc)
                        reset_str = f" (resets at {reset_dt.isoformat()})"
                    except (ValueError, OSError):
                        pass
                raise ApiError(
                    403,
                    f"Rate limited. Remaining: {remaining}{reset_str}. "
                    f"Set GITHUB_TOKEN env var for 5000 requests/hour.",
                    url,
                )
            if resp.status_code == 404:
                raise ApiError(404, "Not found", url)
            if resp.status_code >= 400:
                raise ApiError(resp.status_code, resp.text[:200], url)
            return resp
        # Exhausted retries (likely 202s)
        self.warnings.append(
            f"Stats endpoint {path} returned 202 after {retries} retries; data may be incomplete."
        )
        return resp  # type: ignore[possibly-undefined]

    def _get_json(self, path: str, params: dict | None = None) -> Any:
        return self._get(path, params).json()

    def _paginate(
        self, path: str, params: dict | None = None, max_pages: int = 10
    ) -> list[Any]:
        """Fetch paginated results, following Link headers."""
        params = dict(params or {})
        params.setdefault("per_page", "100")
        results: list[Any] = []
        url: str | None = f"{self.base}{path}"
        page = 0
        while url and page < max_pages:
            resp = self._get(url, params if page == 0 else None)
            data = resp.json()
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
            # Follow next page
            link = resp.headers.get("Link", "")
            next_match = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = next_match.group(1) if next_match else None
            page += 1
        return results

    # -- Data collection methods --

    def metadata(self) -> dict:
        data = self._get_json(f"/repos/{self.owner}/{self.repo}")
        return {
            "name": data.get("name"),
            "full_name": data.get("full_name"),
            "description": data.get("description"),
            "language": data.get("language"),
            "license": data.get("license", {}).get("spdx_id")
            if data.get("license")
            else None,
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues_count": data.get("open_issues_count", 0),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "pushed_at": data.get("pushed_at"),
            "default_branch": data.get("default_branch"),
            "archived": data.get("archived", False),
            "fork": data.get("fork", False),
            "topics": data.get("topics", []),
            "homepage": data.get("homepage"),
            "size_kb": data.get("size", 0),
            "watchers": data.get("subscribers_count", 0),
            "has_discussions": data.get("has_discussions", False),
            "url": f"https://github.com/{self.owner}/{self.repo}",
            "platform": "github",
        }

    def commit_activity(self) -> dict:
        """Weekly commit counts for the last year."""
        raw = self._get_json(f"/repos/{self.owner}/{self.repo}/stats/commit_activity")
        if not isinstance(raw, list):
            self.warnings.append("Commit activity stats not available yet.")
            return {"weekly_commits": [], "total_last_year": 0}

        weekly = []
        for week in raw:
            weekly.append(
                {
                    "week_start": datetime.fromtimestamp(
                        week["week"], tz=timezone.utc
                    ).strftime("%Y-%m-%d"),
                    "commits": week["total"],
                }
            )

        total = sum(w["commits"] for w in weekly)
        return {"weekly_commits": weekly, "total_last_year": total}

    def recent_commits(self, days: int = 60) -> list[dict]:
        """Recent commits on the default branch."""
        since = _days_ago(days)
        commits = self._paginate(
            f"/repos/{self.owner}/{self.repo}/commits",
            params={"since": since, "per_page": "100"},
            max_pages=3,
        )
        result = []
        for c in commits:
            commit_data = c.get("commit", {})
            author_date = commit_data.get("author", {}).get("date", "")
            result.append(
                {
                    "sha": c.get("sha", "")[:8],
                    "date": author_date,
                    "message": commit_data.get("message", "").split("\n")[0][:120],
                    "author": c.get("author", {}).get(
                        "login", commit_data.get("author", {}).get("name", "unknown")
                    ),
                }
            )
        return result

    def contributors(self) -> dict:
        """Contributor stats: top contributors and activity distribution."""
        raw = self._get_json(f"/repos/{self.owner}/{self.repo}/stats/contributors")
        if not isinstance(raw, list):
            self.warnings.append("Contributor stats not available yet.")
            return {
                "top_contributors": [],
                "total_contributors": 0,
                "active_last_90_days": 0,
                "active_prior_90_days": 0,
            }

        now = _now_utc()
        cutoff_90 = now - timedelta(days=90)
        cutoff_180 = now - timedelta(days=180)

        contributors_data = []
        active_last_90 = set()
        active_prior_90 = set()

        for entry in raw:
            author = entry.get("author", {})
            login = author.get("login", "unknown")
            total = entry.get("total", 0)

            # Analyze weekly data for recency
            last_90_commits = 0
            prior_90_commits = 0
            for week in entry.get("weeks", []):
                week_date = datetime.fromtimestamp(week["w"], tz=timezone.utc)
                week_commits = week.get("c", 0)
                if week_date >= cutoff_90 and week_commits > 0:
                    last_90_commits += week_commits
                    active_last_90.add(login)
                elif cutoff_180 <= week_date < cutoff_90 and week_commits > 0:
                    prior_90_commits += week_commits
                    active_prior_90.add(login)

            contributors_data.append(
                {
                    "login": login,
                    "total_commits": total,
                    "commits_last_90_days": last_90_commits,
                    "commits_prior_90_days": prior_90_commits,
                    "avatar_url": author.get("avatar_url", ""),
                }
            )

        # Sort by total commits descending
        contributors_data.sort(key=lambda x: x["total_commits"], reverse=True)

        total_commits_all = sum(c["total_commits"] for c in contributors_data)
        top_10 = contributors_data[:10]
        # Compute percentage for bus factor analysis
        for c in top_10:
            c["percentage"] = (
                round(c["total_commits"] / total_commits_all * 100, 1)
                if total_commits_all
                else 0
            )

        return {
            "top_contributors": top_10,
            "total_contributors": len(contributors_data),
            "active_last_90_days": len(active_last_90),
            "active_prior_90_days": len(active_prior_90),
            "total_commits_all_time": total_commits_all,
        }

    def issues(self) -> dict:
        """Open/closed issue stats and responsiveness."""
        # Open issues
        open_issues = self._paginate(
            f"/repos/{self.owner}/{self.repo}/issues",
            params={"state": "open", "per_page": "100"},
            max_pages=2,
        )
        # Filter out PRs (GitHub issues endpoint includes PRs)
        open_issues = [i for i in open_issues if "pull_request" not in i]
        open_count = len(open_issues)

        # Recently opened (90 days)
        since_90 = _days_ago(90)
        recent_all = self._paginate(
            f"/repos/{self.owner}/{self.repo}/issues",
            params={"state": "all", "since": since_90, "per_page": "100"},
            max_pages=3,
        )
        recent_issues = [i for i in recent_all if "pull_request" not in i]
        recently_opened = [
            i for i in recent_issues if i.get("created_at", "") >= since_90
        ]
        recently_closed = [i for i in recent_issues if i.get("state") == "closed"]

        # Time to first response (sample from recently opened)
        response_times = []
        sample = recently_opened[:20]  # Sample up to 20
        for issue in sample:
            number = issue.get("number")
            comments_count = issue.get("comments", 0)
            if comments_count > 0 and number:
                try:
                    comments = self._get_json(
                        f"/repos/{self.owner}/{self.repo}/issues/{number}/comments",
                        params={"per_page": "1"},
                    )
                    if comments:
                        created = datetime.fromisoformat(
                            issue["created_at"].replace("Z", "+00:00")
                        )
                        first_comment = datetime.fromisoformat(
                            comments[0]["created_at"].replace("Z", "+00:00")
                        )
                        delta_hours = (first_comment - created).total_seconds() / 3600
                        response_times.append(round(delta_hours, 1))
                except (ApiError, KeyError, IndexError):
                    pass

        median_response_hours = None
        if response_times:
            sorted_times = sorted(response_times)
            mid = len(sorted_times) // 2
            median_response_hours = sorted_times[mid]

        return {
            "open_count": open_count,
            "recently_opened_90d": len(recently_opened),
            "recently_closed_90d": len(recently_closed),
            "median_time_to_first_response_hours": median_response_hours,
            "sample_size_for_response_time": len(response_times),
        }

    def pull_requests(self) -> dict:
        """Open/merged/closed PR stats."""
        open_prs = self._paginate(
            f"/repos/{self.owner}/{self.repo}/pulls",
            params={"state": "open", "per_page": "100"},
            max_pages=2,
        )
        open_count = len(open_prs)

        # Recently closed PRs (90 days) — includes merged
        since_90 = _days_ago(90)
        closed_prs = self._paginate(
            f"/repos/{self.owner}/{self.repo}/pulls",
            params={"state": "closed", "since": since_90, "per_page": "100"},
            max_pages=3,
        )
        recently_merged = [
            p for p in closed_prs if p.get("merged_at") and p["merged_at"] >= since_90
        ]
        recently_closed_not_merged = [
            p
            for p in closed_prs
            if not p.get("merged_at") and p.get("closed_at", "") >= since_90
        ]

        return {
            "open_count": open_count,
            "recently_merged_90d": len(recently_merged),
            "recently_closed_not_merged_90d": len(recently_closed_not_merged),
        }

    def releases(self) -> dict:
        """Release history and cadence."""
        releases = self._paginate(
            f"/repos/{self.owner}/{self.repo}/releases",
            params={"per_page": "100"},
            max_pages=3,
        )

        release_list = []
        for r in releases:
            release_list.append(
                {
                    "tag": r.get("tag_name", ""),
                    "name": r.get("name", ""),
                    "date": r.get("published_at") or r.get("created_at", ""),
                    "prerelease": r.get("prerelease", False),
                    "draft": r.get("draft", False),
                }
            )

        # If no releases, check tags
        if not release_list:
            tags = self._paginate(
                f"/repos/{self.owner}/{self.repo}/tags",
                params={"per_page": "50"},
                max_pages=2,
            )
            for t in tags[:50]:
                release_list.append(
                    {
                        "tag": t.get("name", ""),
                        "name": t.get("name", ""),
                        "date": "",  # Tags don't have dates in this endpoint
                        "prerelease": False,
                        "draft": False,
                        "is_tag_only": True,
                    }
                )

        # Compute cadence from non-prerelease, non-draft releases with dates
        dated_releases = [
            r
            for r in release_list
            if r["date"] and not r.get("prerelease") and not r.get("draft")
        ]
        cadence_days = []
        if len(dated_releases) >= 2:
            dates = sorted(
                [
                    datetime.fromisoformat(r["date"].replace("Z", "+00:00"))
                    for r in dated_releases
                ],
                reverse=True,
            )
            for i in range(len(dates) - 1):
                gap = (dates[i] - dates[i + 1]).days
                cadence_days.append(gap)

        latest = release_list[0] if release_list else None

        return {
            "releases": release_list[:30],  # Cap to avoid huge output
            "total_release_count": len(release_list),
            "latest_release": latest,
            "cadence_days_between_releases": cadence_days[:20],
            "average_cadence_days": round(sum(cadence_days) / len(cadence_days), 1)
            if cadence_days
            else None,
        }

    def community(self) -> dict:
        """Community profile and detected files."""
        try:
            profile = self._get_json(
                f"/repos/{self.owner}/{self.repo}/community/profile"
            )
            files = profile.get("files", {})
            return {
                "health_percentage": profile.get("health_percentage"),
                "has_readme": files.get("readme") is not None,
                "has_contributing": files.get("contributing") is not None,
                "has_code_of_conduct": files.get("code_of_conduct") is not None,
                "has_license": files.get("license") is not None,
                "has_issue_template": files.get("issue_template") is not None,
                "has_pull_request_template": files.get("pull_request_template")
                is not None,
            }
        except ApiError:
            return {
                "health_percentage": None,
                "note": "Community profile not available.",
            }

    def ci_status(self) -> dict:
        """Check for CI configuration and latest run status."""
        # Check for GitHub Actions workflows
        try:
            workflows = self._get_json(
                f"/repos/{self.owner}/{self.repo}/actions/workflows",
                params={"per_page": "5"},
            )
            workflow_count = workflows.get("total_count", 0)
            if workflow_count > 0:
                # Get latest run on default branch
                runs = self._get_json(
                    f"/repos/{self.owner}/{self.repo}/actions/runs",
                    params={"per_page": "1", "status": "completed"},
                )
                latest_run = None
                if runs.get("workflow_runs"):
                    r = runs["workflow_runs"][0]
                    latest_run = {
                        "conclusion": r.get("conclusion"),
                        "date": r.get("updated_at", ""),
                        "workflow_name": r.get("name", ""),
                    }
                return {
                    "ci_configured": True,
                    "ci_system": "GitHub Actions",
                    "workflow_count": workflow_count,
                    "latest_run": latest_run,
                }
        except ApiError:
            pass

        return {"ci_configured": False, "ci_system": None, "latest_run": None}

    def detect_ecosystem(self) -> list[dict]:
        """Detect package ecosystem from repo contents."""
        ecosystems = []

        # Check for common config files via the repo tree
        try:
            tree = self._get_json(
                f"/repos/{self.owner}/{self.repo}/git/trees/{self._default_branch()}",
            )
            file_names = {item["path"] for item in tree.get("tree", [])}
        except ApiError:
            file_names = set()

        repo_name = self.repo
        language = self._language

        # Python
        if (
            "pyproject.toml" in file_names
            or "setup.py" in file_names
            or "setup.cfg" in file_names
        ):
            # Try to extract package name from pyproject.toml
            pkg_name = self._detect_python_package_name(file_names)
            ecosystems.append({"registry": "pypi", "package": pkg_name or repo_name})
        elif language and language.lower() == "python":
            ecosystems.append({"registry": "pypi", "package": repo_name})

        # JavaScript / TypeScript
        if "package.json" in file_names:
            pkg_name = self._detect_npm_package_name()
            ecosystems.append({"registry": "npm", "package": pkg_name or repo_name})
        elif language and language.lower() in ("javascript", "typescript"):
            ecosystems.append({"registry": "npm", "package": repo_name})

        # Rust
        if "Cargo.toml" in file_names:
            ecosystems.append({"registry": "crates", "package": repo_name})
        elif language and language.lower() == "rust":
            ecosystems.append({"registry": "crates", "package": repo_name})

        # Java / Kotlin / Scala
        if (
            "pom.xml" in file_names
            or "build.gradle" in file_names
            or "build.gradle.kts" in file_names
        ):
            ecosystems.append(
                {
                    "registry": "maven",
                    "package": repo_name,
                    "note": "Maven group:artifact may differ from repo name",
                }
            )
        elif language and language.lower() in ("java", "kotlin", "scala"):
            ecosystems.append(
                {
                    "registry": "maven",
                    "package": repo_name,
                    "note": "Maven group:artifact may differ from repo name",
                }
            )

        # Ruby
        if "Gemfile" in file_names or any(f.endswith(".gemspec") for f in file_names):
            ecosystems.append({"registry": "rubygems", "package": repo_name})
        elif language and language.lower() == "ruby":
            ecosystems.append({"registry": "rubygems", "package": repo_name})

        # .NET / C#
        if any(f.endswith(".csproj") for f in file_names) or any(
            f.endswith(".fsproj") for f in file_names
        ):
            ecosystems.append({"registry": "nuget", "package": repo_name})
        elif language and language.lower() in ("c#", "f#"):
            ecosystems.append({"registry": "nuget", "package": repo_name})

        # PHP
        if "composer.json" in file_names:
            ecosystems.append(
                {"registry": "packagist", "package": f"{self.owner}/{repo_name}"}
            )
        elif language and language.lower() == "php":
            ecosystems.append(
                {"registry": "packagist", "package": f"{self.owner}/{repo_name}"}
            )

        # Go
        if "go.mod" in file_names:
            ecosystems.append(
                {
                    "registry": "go",
                    "package": f"github.com/{self.owner}/{repo_name}",
                    "note": "Go modules use the repository path as the package identifier",
                }
            )
        elif language and language.lower() == "go":
            ecosystems.append(
                {
                    "registry": "go",
                    "package": f"github.com/{self.owner}/{repo_name}",
                    "note": "Go modules use the repository path as the package identifier",
                }
            )

        # Elixir / Erlang
        if "mix.exs" in file_names:
            ecosystems.append({"registry": "hex", "package": repo_name})

        return ecosystems

    def _default_branch(self) -> str:
        if not hasattr(self, "_default_branch_cache"):
            data = self._get_json(f"/repos/{self.owner}/{self.repo}")
            self._default_branch_cache: str = data.get("default_branch", "main")
            self._language: str | None = data.get("language")
        return self._default_branch_cache

    def _detect_python_package_name(self, file_names: set[str]) -> str | None:
        """Try to read package name from pyproject.toml."""
        if "pyproject.toml" not in file_names:
            return None
        try:
            resp = self._get(f"/repos/{self.owner}/{self.repo}/contents/pyproject.toml")
            import base64

            content_data = resp.json()
            if content_data.get("encoding") == "base64":
                content = base64.b64decode(content_data["content"]).decode("utf-8")
            else:
                content = content_data.get("content", "")
            # Simple regex to find name in [project] or [tool.poetry] section
            match = re.search(
                r'^\s*name\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE
            )
            if match:
                return match.group(1)
        except (ApiError, Exception):
            pass
        return None

    def _detect_npm_package_name(self) -> str | None:
        """Try to read package name from package.json."""
        try:
            import base64

            resp = self._get(f"/repos/{self.owner}/{self.repo}/contents/package.json")
            content_data = resp.json()
            if content_data.get("encoding") == "base64":
                content = base64.b64decode(content_data["content"]).decode("utf-8")
            else:
                content = content_data.get("content", "")
            pkg = json.loads(content)
            return pkg.get("name")
        except (ApiError, json.JSONDecodeError, Exception):
            pass
        return None

    def collect_all(self) -> dict:
        """Collect all data and return as a single dict."""
        result: dict[str, Any] = {}
        errors: list[str] = []

        # Metadata first (sets _language and _default_branch_cache)
        try:
            result["metadata"] = self.metadata()
            self._language = result["metadata"].get("language")
        except ApiError as e:
            errors.append(f"metadata: {e}")
            result["metadata"] = {}

        # Parallel-safe: each section is independent
        sections: list[tuple[str, Any]] = [
            ("commits", self.commit_activity),
            ("recent_commits", lambda: self.recent_commits(60)),
            ("contributors", self.contributors),
            ("issues", self.issues),
            ("pull_requests", self.pull_requests),
            ("releases", self.releases),
            ("community", self.community),
            ("ci", self.ci_status),
            ("ecosystem", self.detect_ecosystem),
        ]

        for name, fn in sections:
            try:
                result[name] = fn() if callable(fn) else fn
            except ApiError as e:
                errors.append(f"{name}: {e}")
                result[name] = {}

        result["errors"] = errors
        result["warnings"] = self.warnings
        if not self.authenticated:
            result["warnings"].append(
                "Running without authentication. GitHub rate limit is 60 requests/hour. "
                "Set GITHUB_TOKEN for 5000 requests/hour."
            )
        result["collected_at"] = _now_utc().isoformat()
        return result


# ---------------------------------------------------------------------------
# GitLab collector
# ---------------------------------------------------------------------------


class GitLabCollector:
    def __init__(self, owner: str, repo: str, base_url: str = "https://gitlab.com"):
        self.owner = owner
        self.repo = repo
        self.base = base_url.rstrip("/")
        self.project_path = f"{owner}/{repo}"
        self.project_id = url_quote(self.project_path, safe="")
        self.session = requests.Session()
        token = os.environ.get("GITLAB_TOKEN")
        if token:
            self.session.headers["PRIVATE-TOKEN"] = token
        self.authenticated = bool(token)
        self.warnings: list[str] = []

    def _get(self, path: str, params: dict | None = None) -> requests.Response:
        url = f"{self.base}/api/v4{path}" if path.startswith("/") else path
        resp = self.session.get(url, params=params, timeout=30)
        if resp.status_code == 404:
            raise ApiError(404, "Not found", url)
        if resp.status_code == 403:
            raise ApiError(403, "Forbidden — set GITLAB_TOKEN env var.", url)
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text[:200], url)
        return resp

    def _get_json(self, path: str, params: dict | None = None) -> Any:
        return self._get(path, params).json()

    def _paginate(
        self, path: str, params: dict | None = None, max_pages: int = 10
    ) -> list[Any]:
        params = dict(params or {})
        params.setdefault("per_page", "100")
        results: list[Any] = []
        page = 1
        while page <= max_pages:
            params["page"] = str(page)
            resp = self._get(path, params)
            data = resp.json()
            if not data:
                break
            if isinstance(data, list):
                results.extend(data)
                if len(data) < int(params["per_page"]):
                    break
            else:
                results.append(data)
                break
            page += 1
        return results

    def metadata(self) -> dict:
        data = self._get_json(f"/projects/{self.project_id}")
        return {
            "name": data.get("name"),
            "full_name": data.get("path_with_namespace"),
            "description": data.get("description"),
            "language": None,  # GitLab doesn't have a single language field
            "license": None,
            "stars": data.get("star_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues_count": data.get("open_issues_count", 0),
            "created_at": data.get("created_at"),
            "updated_at": data.get("last_activity_at"),
            "pushed_at": data.get("last_activity_at"),
            "default_branch": data.get("default_branch"),
            "archived": data.get("archived", False),
            "fork": data.get("forked_from_project") is not None,
            "topics": data.get("topics", data.get("tag_list", [])),
            "homepage": data.get("web_url"),
            "watchers": 0,
            "has_discussions": False,
            "url": data.get("web_url", f"{self.base}/{self.project_path}"),
            "platform": "gitlab",
        }

    def commit_activity(self) -> dict:
        """Approximate weekly commit counts using GitLab's statistics."""
        # GitLab doesn't have a direct equivalent to GitHub's commit_activity.
        # We'll fetch recent commits and bin them by week.
        since = _days_ago(365)
        commits = self._paginate(
            f"/projects/{self.project_id}/repository/commits",
            params={"since": since, "per_page": "100"},
            max_pages=10,
        )

        from collections import defaultdict

        weekly: dict[str, int] = defaultdict(int)
        for c in commits:
            date_str = c.get("committed_date", c.get("created_at", ""))
            if date_str:
                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    week_start = (dt - timedelta(days=dt.weekday())).strftime(
                        "%Y-%m-%d"
                    )
                    weekly[week_start] += 1
                except ValueError:
                    pass

        weekly_list = [
            {"week_start": k, "commits": v} for k, v in sorted(weekly.items())
        ]
        total = sum(w["commits"] for w in weekly_list)
        return {"weekly_commits": weekly_list, "total_last_year": total}

    def recent_commits(self, days: int = 60) -> list[dict]:
        since = _days_ago(days)
        commits = self._paginate(
            f"/projects/{self.project_id}/repository/commits",
            params={"since": since, "per_page": "100"},
            max_pages=3,
        )
        result = []
        for c in commits:
            result.append(
                {
                    "sha": c.get("short_id", c.get("id", "")[:8]),
                    "date": c.get("committed_date", c.get("created_at", "")),
                    "message": c.get("title", c.get("message", ""))[:120],
                    "author": c.get("author_name", "unknown"),
                }
            )
        return result

    def contributors(self) -> dict:
        try:
            contribs = self._paginate(
                f"/projects/{self.project_id}/repository/contributors",
                max_pages=5,
            )
        except ApiError:
            return {
                "top_contributors": [],
                "total_contributors": 0,
                "active_last_90_days": 0,
                "active_prior_90_days": 0,
            }

        contribs.sort(key=lambda x: x.get("commits", 0), reverse=True)
        total_commits = sum(c.get("commits", 0) for c in contribs)
        top_10 = []
        for c in contribs[:10]:
            commits = c.get("commits", 0)
            top_10.append(
                {
                    "login": c.get("name", "unknown"),
                    "total_commits": commits,
                    "percentage": round(commits / total_commits * 100, 1)
                    if total_commits
                    else 0,
                }
            )

        return {
            "top_contributors": top_10,
            "total_contributors": len(contribs),
            "active_last_90_days": None,
            "active_prior_90_days": None,
            "total_commits_all_time": total_commits,
            "note": "GitLab contributor API does not provide time-based activity breakdown.",
        }

    def issues(self) -> dict:
        # Open issues
        open_data = self._get_json(
            f"/projects/{self.project_id}/issues_statistics",
        )
        stats = open_data.get("statistics", {}).get("counts", {})
        open_count = stats.get("opened", 0)

        # Recently created (90 days)
        since_90 = _days_ago(90)
        recent = self._paginate(
            f"/projects/{self.project_id}/issues",
            params={"created_after": since_90, "per_page": "100"},
            max_pages=3,
        )
        recently_opened = len(recent)
        recently_closed = len([i for i in recent if i.get("state") == "closed"])

        return {
            "open_count": open_count,
            "recently_opened_90d": recently_opened,
            "recently_closed_90d": recently_closed,
            "median_time_to_first_response_hours": None,
            "note": "Time-to-first-response not computed for GitLab (would require per-issue note fetching).",
        }

    def pull_requests(self) -> dict:
        """Merge requests in GitLab."""
        since_90 = _days_ago(90)

        open_mrs = self._paginate(
            f"/projects/{self.project_id}/merge_requests",
            params={"state": "opened", "per_page": "100"},
            max_pages=2,
        )
        recent_merged = self._paginate(
            f"/projects/{self.project_id}/merge_requests",
            params={"state": "merged", "created_after": since_90, "per_page": "100"},
            max_pages=3,
        )
        recent_closed = self._paginate(
            f"/projects/{self.project_id}/merge_requests",
            params={"state": "closed", "created_after": since_90, "per_page": "100"},
            max_pages=2,
        )

        return {
            "open_count": len(open_mrs),
            "recently_merged_90d": len(recent_merged),
            "recently_closed_not_merged_90d": len(recent_closed),
        }

    def releases(self) -> dict:
        releases = self._paginate(
            f"/projects/{self.project_id}/releases",
            params={"per_page": "100"},
            max_pages=3,
        )
        release_list = []
        for r in releases:
            release_list.append(
                {
                    "tag": r.get("tag_name", ""),
                    "name": r.get("name", ""),
                    "date": r.get("released_at", r.get("created_at", "")),
                    "prerelease": False,
                    "draft": False,
                }
            )

        if not release_list:
            tags = self._paginate(
                f"/projects/{self.project_id}/repository/tags",
                params={"per_page": "50"},
                max_pages=2,
            )
            for t in tags[:50]:
                commit_date = ""
                if t.get("commit", {}).get("committed_date"):
                    commit_date = t["commit"]["committed_date"]
                release_list.append(
                    {
                        "tag": t.get("name", ""),
                        "name": t.get("name", ""),
                        "date": commit_date,
                        "is_tag_only": True,
                    }
                )

        dated_releases = [r for r in release_list if r["date"]]
        cadence_days = []
        if len(dated_releases) >= 2:
            dates = sorted(
                [
                    datetime.fromisoformat(r["date"].replace("Z", "+00:00"))
                    for r in dated_releases
                ],
                reverse=True,
            )
            for i in range(len(dates) - 1):
                gap = (dates[i] - dates[i + 1]).days
                cadence_days.append(gap)

        latest = release_list[0] if release_list else None
        return {
            "releases": release_list[:30],
            "total_release_count": len(release_list),
            "latest_release": latest,
            "cadence_days_between_releases": cadence_days[:20],
            "average_cadence_days": round(sum(cadence_days) / len(cadence_days), 1)
            if cadence_days
            else None,
        }

    def community(self) -> dict:
        # GitLab doesn't have a community profile endpoint; check for files
        result = {
            "health_percentage": None,
            "has_readme": False,
            "has_contributing": False,
            "has_code_of_conduct": False,
            "has_license": False,
        }
        try:
            tree = self._get_json(
                f"/projects/{self.project_id}/repository/tree",
                params={"per_page": "100"},
            )
            file_names = {item["name"].lower() for item in tree}
            result["has_readme"] = any(f.startswith("readme") for f in file_names)
            result["has_contributing"] = any(
                f.startswith("contributing") for f in file_names
            )
            result["has_code_of_conduct"] = any(
                "code_of_conduct" in f for f in file_names
            )
            result["has_license"] = any(
                f.startswith("license")
                or f.startswith("licence")
                or f.startswith("copying")
                for f in file_names
            )
        except ApiError:
            pass
        return result

    def ci_status(self) -> dict:
        try:
            pipelines = self._get_json(
                f"/projects/{self.project_id}/pipelines",
                params={"per_page": "1", "order_by": "updated_at", "sort": "desc"},
            )
            if pipelines:
                p = pipelines[0]
                return {
                    "ci_configured": True,
                    "ci_system": "GitLab CI",
                    "latest_run": {
                        "conclusion": p.get("status"),
                        "date": p.get("updated_at", ""),
                        "workflow_name": f"Pipeline #{p.get('id', '')}",
                    },
                }
        except ApiError:
            pass
        return {"ci_configured": False, "ci_system": None, "latest_run": None}

    def detect_ecosystem(self) -> list[dict]:
        ecosystems = []
        try:
            tree = self._get_json(
                f"/projects/{self.project_id}/repository/tree",
                params={"per_page": "100"},
            )
            file_names = {item["name"] for item in tree}
        except ApiError:
            file_names = set()

        repo_name = self.repo

        if "pyproject.toml" in file_names or "setup.py" in file_names:
            ecosystems.append({"registry": "pypi", "package": repo_name})
        if "package.json" in file_names:
            ecosystems.append({"registry": "npm", "package": repo_name})
        if "Cargo.toml" in file_names:
            ecosystems.append({"registry": "crates", "package": repo_name})
        if "pom.xml" in file_names or "build.gradle" in file_names:
            ecosystems.append({"registry": "maven", "package": repo_name})
        if "Gemfile" in file_names or any(f.endswith(".gemspec") for f in file_names):
            ecosystems.append({"registry": "rubygems", "package": repo_name})
        if "composer.json" in file_names:
            ecosystems.append(
                {"registry": "packagist", "package": f"{self.owner}/{repo_name}"}
            )
        if "go.mod" in file_names:
            ecosystems.append(
                {"registry": "go", "package": f"gitlab.com/{self.owner}/{repo_name}"}
            )
        if "mix.exs" in file_names:
            ecosystems.append({"registry": "hex", "package": repo_name})

        return ecosystems

    def collect_all(self) -> dict:
        result: dict[str, Any] = {}
        errors: list[str] = []

        try:
            result["metadata"] = self.metadata()
        except ApiError as e:
            errors.append(f"metadata: {e}")
            result["metadata"] = {}

        sections: list[tuple[str, Any]] = [
            ("commits", self.commit_activity),
            ("recent_commits", lambda: self.recent_commits(60)),
            ("contributors", self.contributors),
            ("issues", self.issues),
            ("pull_requests", self.pull_requests),
            ("releases", self.releases),
            ("community", self.community),
            ("ci", self.ci_status),
            ("ecosystem", self.detect_ecosystem),
        ]

        for name, fn in sections:
            try:
                result[name] = fn() if callable(fn) else fn
            except ApiError as e:
                errors.append(f"{name}: {e}")
                result[name] = {}

        result["errors"] = errors
        result["warnings"] = self.warnings
        if not self.authenticated:
            result["warnings"].append(
                "Running without authentication. Set GITLAB_TOKEN for higher rate limits."
            )
        result["collected_at"] = _now_utc().isoformat()
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect repository data from GitHub or GitLab APIs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --platform github --owner pallets --repo flask
  %(prog)s --platform gitlab --owner gitlab-org --repo gitlab
  %(prog)s --url https://github.com/psf/requests
  %(prog)s --platform gitlab --owner mygroup/subgroup --repo myproject --gitlab-url https://gitlab.example.com

Environment variables:
  GITHUB_TOKEN   GitHub personal access token (raises rate limit to 5000/hr)
  GH_TOKEN       Alternative GitHub token variable
  GITLAB_TOKEN   GitLab personal access token
""",
    )
    parser.add_argument("--url", help="Full repository URL (auto-detects platform)")
    parser.add_argument(
        "--platform", choices=["github", "gitlab"], help="Platform: github or gitlab"
    )
    parser.add_argument("--owner", help="Repository owner or namespace")
    parser.add_argument("--repo", help="Repository name")
    parser.add_argument(
        "--gitlab-url",
        default="https://gitlab.com",
        help="GitLab instance URL (default: https://gitlab.com)",
    )

    args = parser.parse_args()

    if args.url:
        try:
            platform, owner, repo, base_url = _parse_url(args.url)
        except ValueError as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)
        if args.platform:
            platform = args.platform
        if platform == "gitlab" and base_url != "https://api.github.com":
            args.gitlab_url = base_url
    elif args.platform and args.owner and args.repo:
        platform = args.platform
        owner = args.owner
        repo = args.repo
    else:
        parser.error("Provide either --url or all of --platform, --owner, and --repo")
        return  # unreachable

    try:
        if platform == "github":
            collector = GitHubCollector(owner, repo)
        elif platform == "gitlab":
            collector = GitLabCollector(owner, repo, args.gitlab_url)
        else:
            print(
                json.dumps({"error": f"Unsupported platform: {platform}"}),
                file=sys.stderr,
            )
            sys.exit(1)

        data = collector.collect_all()
        print(json.dumps(data, indent=2, default=str))
    except ApiError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
    except requests.ConnectionError as e:
        print(json.dumps({"error": f"Connection error: {e}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
