---
name: oss-health-analyzer
description: >
  Analyze the health of any open source project given its GitHub or GitLab
  repository URL. Produces a comprehensive health assessment report covering
  project history and origins, development activity (commits, releases,
  issues, PRs), contributor health and bus factor risk, package adoption
  and download stats, and community engagement. Use this skill when asked
  to evaluate, assess, audit, review, or check the health of an open source
  project, dependency, or library — even if the user doesn't explicitly say
  "health check" or "health report."
license: MIT
compatibility: >
  Requires Python 3.10+ and uv. Requires internet access for GitHub/GitLab
  APIs and package registries. Set GITHUB_TOKEN or GITLAB_TOKEN environment
  variables for higher API rate limits (recommended).
metadata:
  author: maxamillion
  version: "1.0"
---

# Open Source Project Health Analyzer

Analyze any open source project's health from its GitHub or GitLab URL and
produce a structured markdown report.

## Workflow

Follow these steps in order:

- [ ] Step 1: Parse the repository URL
- [ ] Step 2: Collect repository data via API
- [ ] Step 3: Detect ecosystem and collect package registry data
- [ ] Step 4: Research project history and origins
- [ ] Step 5: Synthesize the health report

## Step 1: Parse the Repository URL

Extract the platform, owner, and repo name from the user-provided URL.

**Supported URL formats:**

| Pattern | Platform |
|---------|----------|
| `github.com/{owner}/{repo}` | GitHub |
| `gitlab.com/{owner}/{repo}` | GitLab |
| `{custom-domain}/{owner}/{repo}` (if user specifies GitLab) | GitLab |

Strip any trailing `.git`, path suffixes (like `/tree/main`), or query strings.
If the URL doesn't match a known pattern, ask the user to clarify.

## Step 2: Collect Repository Data

Run the data collection script. Use `--help` first if you need to see all options.

**GitHub:**
```bash
uv run scripts/collect_repo_data.py --platform github --owner OWNER --repo REPO
```

**GitLab:**
```bash
uv run scripts/collect_repo_data.py --platform gitlab --owner OWNER --repo REPO
```

**GitLab (self-hosted):**
```bash
uv run scripts/collect_repo_data.py --platform gitlab --owner OWNER --repo REPO --gitlab-url https://gitlab.example.com
```

The script outputs a JSON object to stdout with these top-level keys:
- `metadata` — stars, forks, description, language, license, created_at, default_branch
- `commits` — weekly commit counts for the last 12 months, recent commits on the default branch
- `contributors` — top contributors by commit count, active contributors in last 90 / prior 90 days
- `issues` — open count, recently opened/closed counts (90 days), time-to-first-response samples
- `pull_requests` — open count, recently opened/merged/closed counts (90 days)
- `releases` — list of releases with dates and tag names, latest release info
- `community` — detected community files (README, CONTRIBUTING, CODE_OF_CONDUCT, etc.)
- `ci` — whether CI is configured, latest CI run status if detectable
- `ecosystem` — detected package ecosystems and probable package names

**Save the JSON output** for use in subsequent steps. If the script reports errors
(e.g., repo not found, rate limited), relay the error to the user with guidance.

### Rate Limiting

Without a token, GitHub allows 60 requests/hour and GitLab allows ~300/hour.
If you see rate limit errors, tell the user to set `GITHUB_TOKEN` or `GITLAB_TOKEN`:

```bash
export GITHUB_TOKEN=ghp_your_token_here
export GITLAB_TOKEN=glpat-your_token_here
```

## Step 3: Detect Ecosystem and Collect Registry Data

Use the `ecosystem` field from Step 2's output. For each detected ecosystem,
run the registry data collection script:

```bash
uv run scripts/collect_registry_data.py --registry REGISTRY --package PACKAGE_NAME
```

Where `REGISTRY` is one of: `pypi`, `npm`, `crates`, `maven`, `rubygems`, `nuget`,
`packagist`, `hex`.

The script outputs JSON with:
- `latest_version` — the latest published version
- `latest_version_date` — when it was published
- `downloads` — download count and period (e.g., weekly, monthly)
- `dependents_count` — number of dependent packages (if available)
- `registry_url` — link to the package page

If no ecosystem is detected, note this in the report as "No package registry
detected" rather than omitting the section.

## Step 4: Research Project History and Origins

This step requires **your own research capabilities** (web fetching, reading files).
Gather information from these sources, in priority order:

1. **Repository files**: Read the README, CHANGELOG (or CHANGES, HISTORY),
   GOVERNANCE, and any docs/ directory for project history, founding context,
   and stated goals.
2. **Repository metadata**: Check the repo description, topics/tags, and the
   "about" section.
3. **Git history**: The first commit date (from Step 2 data) tells you when
   development started. Major version tags indicate evolutionary milestones.
4. **Web research**: Search for blog posts, announcements, or conference talks
   about the project's creation, major milestones, governance changes, or
   foundation donations. Check if the project belongs to a foundation (Apache,
   CNCF, Linux Foundation, Eclipse, etc.).
5. **Community channels**: Check the README for links to Discord, Slack, Matrix,
   mailing lists, or forums. Note their existence and any visible activity level.

**What to look for:**
- Who created the project (individual, company, foundation)
- Why it was created (founding purpose, problem it solves)
- Key milestones: major version releases, rewrites, license changes, governance
  changes, foundation donations, ownership transfers
- Current roadmap or future plans from official sources
- Community channels and discussion activity

**If information is unavailable**, say so explicitly (e.g., "No public roadmap
was found") rather than guessing or omitting the field.

## Step 5: Synthesize the Health Report

Load the report template from [references/report-template.md](references/report-template.md)
and fill in each section using the data collected in Steps 2-4.

### Computing Derived Metrics

**Overall Health verdict** — Assign one of these based on the combination of signals:
- **Active**: Regular commits (weekly+), recent release (within expected cadence),
  responsive issue handling, multiple active contributors
- **Slowing**: Declining commit frequency, release cadence stretching, fewer active
  contributors than before, but still some activity
- **Stalled**: No substantive commits in 60+ days on the main branch, no recent
  releases, issues going unanswered, but the project hasn't been archived
- **Abandoned**: No activity in 6+ months, archived repo, or maintainer has
  publicly stated the project is unmaintained

**Commit Trend**: Compare the average weekly commits over the last 3 months to the
12-month average. Report as increasing (>20% above average), stable (within 20%),
declining (>20% below average), or dormant (near-zero recent commits).

**Bus Factor Risk**:
- **High**: One contributor accounts for >80% of commits in the last 12 months
- **Medium**: Top 2 contributors account for >80% of commits
- **Low**: Commits are distributed across 3+ significant contributors

**Release Cadence**: Compare the interval between the last two releases to the
historical average interval. Note if the cadence has slowed, accelerated, or stopped.

### Handling Missing Data

For any field where data is unavailable, use one of:
- "Not available — [reason]" (e.g., "Not available — GitLab API does not expose this metric")
- "Not detected" (e.g., no package registry found)
- "Unknown — insufficient data"

Never leave a field blank or omit it from the report.

## Gotchas

- **GitHub's commit activity stats** (`/stats/commit_activity` and `/stats/participation`)
  return HTTP 202 on first request while GitHub computes them. If you get a 202,
  wait 2-3 seconds and retry. The script handles this automatically.
- **GitLab project paths** may contain subgroups (e.g., `gitlab.com/group/subgroup/project`).
  The owner in this case is the full path: `group/subgroup`.
- **Forked repos**: If the repo is a fork, note this prominently. The commit history
  and contributor data may reflect the upstream project, not the fork's own activity.
- **Monorepos**: Some projects live in monorepos (e.g., Babel, React). The repo-level
  stats reflect the entire monorepo, not the individual package.
- **GitHub rate limits** are per-IP for unauthenticated requests. If the user is behind
  a NAT or shared IP, they may hit limits faster. Always recommend setting `GITHUB_TOKEN`.
- **Download stats vary wildly by ecosystem**: npm reports weekly downloads, PyPI reports
  monthly, crates.io reports all-time. Always include the time period alongside the number.
- **Stars/forks are vanity metrics**: They indicate awareness, not necessarily active usage.
  Weight download stats and dependent counts more heavily in the assessment.
- **Archived repos**: Check the `archived` field in metadata. An archived repo should
  always be classified as "Abandoned" regardless of other signals.
