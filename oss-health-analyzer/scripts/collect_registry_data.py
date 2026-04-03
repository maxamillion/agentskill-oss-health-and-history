# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.31,<3",
# ]
# ///
"""
Collect package data from various package registries.

Queries the appropriate registry API for download stats, latest version,
publication date, and dependent package counts.

Usage:
  uv run collect_registry_data.py --registry REGISTRY --package PACKAGE

Where REGISTRY is one of:
  pypi        - Python Package Index (pypi.org)
  npm         - Node Package Manager (npmjs.com)
  crates      - Rust crate registry (crates.io)
  maven       - Maven Central (search.maven.org)
  rubygems    - Ruby gems (rubygems.org)
  nuget       - .NET packages (nuget.org)
  packagist   - PHP Composer packages (packagist.org)
  hex         - Elixir/Erlang packages (hex.pm)

Examples:
  uv run collect_registry_data.py --registry pypi --package flask
  uv run collect_registry_data.py --registry npm --package express
  uv run collect_registry_data.py --registry crates --package serde
  uv run collect_registry_data.py --registry rubygems --package rails
  uv run collect_registry_data.py --registry packagist --package laravel/framework
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

# Shared session with reasonable timeout
_session = requests.Session()
_session.headers["User-Agent"] = "oss-health-analyzer/1.0"
TIMEOUT = 20


def _get_json(url: str, params: dict | None = None) -> Any:
    """GET a URL and return parsed JSON, or raise with a clear message."""
    try:
        resp = _session.get(url, params=params, timeout=TIMEOUT)
    except requests.ConnectionError as e:
        raise RuntimeError(f"Connection error fetching {url}: {e}") from e
    except requests.Timeout:
        raise RuntimeError(f"Timeout fetching {url}") from None

    if resp.status_code == 404:
        return None  # Package not found
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")
    return resp.json()


# ---------------------------------------------------------------------------
# Registry collectors
# ---------------------------------------------------------------------------


def collect_pypi(package: str) -> dict:
    """Query PyPI for package metadata and download stats."""
    result: dict[str, Any] = {
        "registry": "pypi",
        "package": package,
        "registry_url": f"https://pypi.org/project/{package}/",
    }

    # Main package metadata
    data = _get_json(f"https://pypi.org/pypi/{package}/json")
    if data is None:
        result["error"] = f"Package '{package}' not found on PyPI."
        return result

    info = data.get("info", {})
    result["latest_version"] = info.get("version")
    result["summary"] = info.get("summary")
    result["author"] = info.get("author")
    result["license"] = info.get("license")
    result["requires_python"] = info.get("requires_python")
    result["project_urls"] = info.get("project_urls")

    # Get the upload date of the latest version
    releases = data.get("releases", {})
    latest_ver = info.get("version", "")
    if latest_ver in releases and releases[latest_ver]:
        latest_files = releases[latest_ver]
        dates = [
            f.get("upload_time_iso_8601") or f.get("upload_time", "")
            for f in latest_files
        ]
        dates = [d for d in dates if d]
        if dates:
            result["latest_version_date"] = sorted(dates)[-1]

    # Download stats from pypistats.org
    try:
        stats = _get_json(f"https://pypistats.org/api/packages/{package}/recent")
        if stats and "data" in stats:
            result["downloads"] = {
                "last_day": stats["data"].get("last_day"),
                "last_week": stats["data"].get("last_week"),
                "last_month": stats["data"].get("last_month"),
                "period": "monthly",
            }
    except RuntimeError:
        result["downloads"] = {
            "note": "Download stats not available from pypistats.org"
        }

    # Dependents count is not directly available from PyPI
    result["dependents_count"] = None
    result["dependents_note"] = (
        "PyPI does not expose dependent package counts directly."
    )

    return result


def collect_npm(package: str) -> dict:
    """Query npm registry for package metadata and download stats."""
    result: dict[str, Any] = {
        "registry": "npm",
        "package": package,
        "registry_url": f"https://www.npmjs.com/package/{package}",
    }

    data = _get_json(f"https://registry.npmjs.org/{package}")
    if data is None:
        result["error"] = f"Package '{package}' not found on npm."
        return result

    dist_tags = data.get("dist-tags", {})
    latest_ver = dist_tags.get("latest", "")
    result["latest_version"] = latest_ver

    # Get date of latest version
    times = data.get("time", {})
    if latest_ver in times:
        result["latest_version_date"] = times[latest_ver]

    # Basic metadata from latest version
    versions = data.get("versions", {})
    if latest_ver in versions:
        ver_data = versions[latest_ver]
        result["summary"] = ver_data.get("description")
        result["license"] = ver_data.get("license")
        result["author"] = (
            ver_data.get("author", {}).get("name")
            if isinstance(ver_data.get("author"), dict)
            else ver_data.get("author")
        )

    # Download stats
    try:
        dl_data = _get_json(
            f"https://api.npmjs.org/downloads/point/last-week/{package}"
        )
        if dl_data:
            result["downloads"] = {
                "last_week": dl_data.get("downloads"),
                "period": "weekly",
            }
    except RuntimeError:
        result["downloads"] = {"note": "Download stats not available."}

    # Dependents count via npm search (approximate)
    try:
        search = _get_json(
            "https://registry.npmjs.org/-/v1/search",
            params={"text": f"dependencies:{package}", "size": "1"},
        )
        if search:
            result["dependents_count"] = search.get("total", None)
    except RuntimeError:
        result["dependents_count"] = None

    return result


def collect_crates(package: str) -> dict:
    """Query crates.io for Rust crate metadata."""
    result: dict[str, Any] = {
        "registry": "crates",
        "package": package,
        "registry_url": f"https://crates.io/crates/{package}",
    }

    data = _get_json(f"https://crates.io/api/v1/crates/{package}")
    if data is None:
        result["error"] = f"Crate '{package}' not found on crates.io."
        return result

    crate = data.get("crate", {})
    result["latest_version"] = crate.get("newest_version")
    result["summary"] = crate.get("description")
    result["downloads"] = {
        "total": crate.get("downloads"),
        "recent": crate.get("recent_downloads"),
        "period": "recent (last 90 days) + all-time total",
    }

    # Get latest version date from versions array
    versions = data.get("versions", [])
    if versions:
        # Versions are returned newest-first
        result["latest_version_date"] = versions[0].get("created_at")
        result["license"] = versions[0].get("license")

    # Reverse dependencies
    try:
        rev_deps = _get_json(
            f"https://crates.io/api/v1/crates/{package}/reverse_dependencies",
            params={"per_page": "1"},
        )
        if rev_deps and "meta" in rev_deps:
            result["dependents_count"] = rev_deps["meta"].get("total")
    except RuntimeError:
        result["dependents_count"] = None

    return result


def collect_maven(package: str) -> dict:
    """Query Maven Central for Java/Kotlin/Scala package metadata."""
    result: dict[str, Any] = {
        "registry": "maven",
        "package": package,
        "registry_url": f"https://central.sonatype.com/search?q={package}",
    }

    # Maven search expects groupId:artifactId or just a search term
    params: dict[str, str]
    if ":" in package:
        group, artifact = package.split(":", 1)
        params = {"q": f'g:"{group}" AND a:"{artifact}"', "rows": "1", "wt": "json"}
    else:
        params = {"q": package, "rows": "1", "wt": "json"}

    data = _get_json("https://search.maven.org/solrsearch/select", params=params)
    if data is None:
        result["error"] = f"Package '{package}' not found on Maven Central."
        return result

    docs = data.get("response", {}).get("docs", [])
    if not docs:
        result["error"] = f"Package '{package}' not found on Maven Central."
        return result

    doc = docs[0]
    result["latest_version"] = doc.get("latestVersion")
    result["group_id"] = doc.get("g")
    result["artifact_id"] = doc.get("a")

    timestamp = doc.get("timestamp")
    if timestamp:
        from datetime import datetime, timezone

        try:
            result["latest_version_date"] = datetime.fromtimestamp(
                timestamp / 1000, tz=timezone.utc
            ).isoformat()
        except (ValueError, OSError):
            pass

    result["version_count"] = doc.get("versionCount")
    result["downloads"] = {
        "note": "Maven Central does not provide public download statistics."
    }
    result["dependents_count"] = None

    return result


def collect_rubygems(package: str) -> dict:
    """Query RubyGems for gem metadata."""
    result: dict[str, Any] = {
        "registry": "rubygems",
        "package": package,
        "registry_url": f"https://rubygems.org/gems/{package}",
    }

    data = _get_json(f"https://rubygems.org/api/v1/gems/{package}.json")
    if data is None:
        result["error"] = f"Gem '{package}' not found on RubyGems."
        return result

    result["latest_version"] = data.get("version")
    result["summary"] = data.get("info")
    result["license"] = ", ".join(data.get("licenses", []))
    result["authors"] = data.get("authors")

    result["downloads"] = {
        "total": data.get("downloads"),
        "latest_version": data.get("version_downloads"),
        "period": "all-time total",
    }

    # Version date not directly in this endpoint; use versions API
    try:
        versions = _get_json(f"https://rubygems.org/api/v1/versions/{package}.json")
        if versions and isinstance(versions, list):
            result["latest_version_date"] = versions[0].get("created_at")
    except RuntimeError:
        pass

    # Reverse dependencies
    try:
        rev_deps = _get_json(
            f"https://rubygems.org/api/v1/gems/{package}/reverse_dependencies.json"
        )
        if rev_deps and isinstance(rev_deps, list):
            result["dependents_count"] = len(rev_deps)
    except RuntimeError:
        result["dependents_count"] = None

    return result


def collect_nuget(package: str) -> dict:
    """Query NuGet for .NET package metadata."""
    result: dict[str, Any] = {
        "registry": "nuget",
        "package": package,
        "registry_url": f"https://www.nuget.org/packages/{package}",
    }

    # NuGet v3 registration API
    data = _get_json(
        f"https://api.nuget.org/v3/registration5-gz-semver2/{package.lower()}/index.json"
    )
    if data is None:
        result["error"] = f"Package '{package}' not found on NuGet."
        return result

    items = data.get("items", [])
    if items:
        last_page = items[-1]
        page_items = last_page.get("items")
        if page_items is None:
            # Need to fetch the page
            page_url = last_page.get("@id", "")
            if page_url:
                try:
                    page_data = _get_json(page_url)
                    if page_data:
                        page_items = page_data.get("items", [])
                except RuntimeError:
                    pass
        if page_items:
            latest_entry = page_items[-1]
            catalog = latest_entry.get("catalogEntry", {})
            result["latest_version"] = catalog.get("version")
            result["latest_version_date"] = catalog.get("published")
            result["summary"] = catalog.get("description")
            result["license"] = catalog.get("licenseExpression")
            result["authors"] = catalog.get("authors")

    # Download count from search API
    try:
        search = _get_json(
            "https://azuresearch-usnc.nuget.org/query",
            params={"q": f"packageid:{package}", "take": "1"},
        )
        if search and search.get("data"):
            result["downloads"] = {
                "total": search["data"][0].get("totalDownloads"),
                "period": "all-time total",
            }
    except RuntimeError:
        result["downloads"] = {"note": "Download stats not available."}

    result["dependents_count"] = None
    return result


def collect_packagist(package: str) -> dict:
    """Query Packagist for PHP Composer package metadata."""
    result: dict[str, Any] = {
        "registry": "packagist",
        "package": package,
        "registry_url": f"https://packagist.org/packages/{package}",
    }

    data = _get_json(f"https://repo.packagist.org/p2/{package}.json")
    if data is None:
        result["error"] = f"Package '{package}' not found on Packagist."
        return result

    packages = data.get("packages", {})
    versions_list = packages.get(package, [])
    if not versions_list:
        result["error"] = f"Package '{package}' has no versions on Packagist."
        return result

    # First entry is typically the latest
    latest = versions_list[0]
    result["latest_version"] = latest.get("version")
    result["latest_version_date"] = latest.get("time")
    result["summary"] = latest.get("description")
    result["license"] = ", ".join(latest.get("license", []))

    # Download stats from stats endpoint
    try:
        stats = _get_json(f"https://packagist.org/packages/{package}/stats.json")
        if stats:
            result["downloads"] = {
                "total": stats.get("downloads", {}).get("total"),
                "monthly": stats.get("downloads", {}).get("monthly"),
                "daily": stats.get("downloads", {}).get("daily"),
                "period": "monthly + all-time total",
            }
    except RuntimeError:
        result["downloads"] = {"note": "Download stats not available."}

    # Dependents from package info
    try:
        pkg_info = _get_json(f"https://packagist.org/packages/{package}.json")
        if pkg_info and "package" in pkg_info:
            result["dependents_count"] = pkg_info["package"].get("dependents")
    except RuntimeError:
        result["dependents_count"] = None

    return result


def collect_hex(package: str) -> dict:
    """Query Hex.pm for Elixir/Erlang package metadata."""
    result: dict[str, Any] = {
        "registry": "hex",
        "package": package,
        "registry_url": f"https://hex.pm/packages/{package}",
    }

    data = _get_json(f"https://hex.pm/api/packages/{package}")
    if data is None:
        result["error"] = f"Package '{package}' not found on Hex.pm."
        return result

    result["summary"] = data.get("meta", {}).get("description")
    result["license"] = ", ".join(data.get("meta", {}).get("licenses", []))

    releases = data.get("releases", [])
    if releases:
        latest = releases[0]
        result["latest_version"] = latest.get("version")
        result["latest_version_date"] = latest.get("inserted_at")

    result["downloads"] = data.get("downloads", {})
    if result["downloads"]:
        result["downloads"]["period"] = "all-time + recent"

    result["dependents_count"] = None
    return result


# ---------------------------------------------------------------------------
# Registry dispatch
# ---------------------------------------------------------------------------

REGISTRIES = {
    "pypi": collect_pypi,
    "npm": collect_npm,
    "crates": collect_crates,
    "maven": collect_maven,
    "rubygems": collect_rubygems,
    "nuget": collect_nuget,
    "packagist": collect_packagist,
    "hex": collect_hex,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect package data from a package registry.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported registries:
  pypi       - Python (pypi.org)
  npm        - JavaScript/TypeScript (npmjs.com)
  crates     - Rust (crates.io)
  maven      - Java/Kotlin/Scala (search.maven.org)
  rubygems   - Ruby (rubygems.org)
  nuget      - .NET (nuget.org)
  packagist  - PHP (packagist.org)
  hex        - Elixir/Erlang (hex.pm)

Examples:
  %(prog)s --registry pypi --package flask
  %(prog)s --registry npm --package express
  %(prog)s --registry crates --package serde
  %(prog)s --registry packagist --package laravel/framework
""",
    )
    parser.add_argument(
        "--registry",
        required=True,
        choices=list(REGISTRIES.keys()),
        help="Package registry to query",
    )
    parser.add_argument("--package", required=True, help="Package name to look up")

    args = parser.parse_args()

    collector = REGISTRIES[args.registry]
    try:
        data = collector(args.package)
        print(json.dumps(data, indent=2, default=str))
    except RuntimeError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
