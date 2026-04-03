# Open Source Project Health Analyzer

An [AgentSkill](https://agentskills.io/) that evaluates the health of any open
source project given its GitHub or GitLab URL. It produces a comprehensive
markdown report covering project history, development activity, contributor
health, release cadence, package adoption, and community engagement.

## What It Does

Given a repository URL, the skill instructs your coding agent to:

1. **Collect repository data** via the GitHub/GitLab API (commits, issues, PRs,
   releases, contributors, CI status)
2. **Query package registries** (PyPI, npm, crates.io, Maven, RubyGems, NuGet,
   Packagist, Hex) for download stats and version info
3. **Research project history** using the agent's own web and file reading
   capabilities
4. **Synthesize a structured health report** with an overall health verdict
   (Active / Slowing / Stalled / Abandoned), risk analysis, and adoption guidance

## Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** (for running the bundled scripts)
- **Internet access** (for API calls to GitHub/GitLab and package registries)
- **API tokens** (optional but recommended):
  - `GITHUB_TOKEN` — raises GitHub API rate limit from 60 to 5,000 requests/hour
  - `GITLAB_TOKEN` — needed for private GitLab projects

## Installation

### Claude Code

```bash
# Install the skill directly
claude skill add ./oss-health-analyzer

# Or if you cloned this repo elsewhere:
claude skill add /path/to/agentskill-oss-health-and-history/oss-health-analyzer
```

### VS Code / GitHub Copilot

Copy the skill directory into your project's skills location:

```bash
mkdir -p .agents/skills
cp -r oss-health-analyzer .agents/skills/
```

Then in Copilot Chat (Agent mode), the skill will be auto-discovered. Type
`/skills` to verify `oss-health-analyzer` appears.

### Cursor

Copy the skill directory into your project's skills location:

```bash
mkdir -p .cursor/skills
cp -r oss-health-analyzer .cursor/skills/
```

### OpenCode

Add the skill path to your OpenCode configuration:

```bash
cp -r oss-health-analyzer ~/.opencode/skills/
```

### Gemini CLI

```bash
mkdir -p .gemini/skills
cp -r oss-health-analyzer .gemini/skills/
```

### Goose

```bash
mkdir -p .goose/skills
cp -r oss-health-analyzer .goose/skills/
```

### OpenHands

Copy the skill into your OpenHands workspace skills directory:

```bash
cp -r oss-health-analyzer /path/to/workspace/.openhands/skills/
```

### Other Agents

Any agent that supports the [AgentSkills](https://agentskills.io/) format can
use this skill. Copy the `oss-health-analyzer/` directory to your agent's skill
discovery location. Refer to your agent's documentation for the exact path.

## Usage

Once installed, ask your agent something like:

- "Analyze the health of https://github.com/pallets/flask"
- "Is this dependency well-maintained? https://github.com/expressjs/express"
- "Give me a health report for https://gitlab.com/gitlab-org/gitlab"
- "Evaluate https://github.com/rust-lang/rust as a dependency"
- "Check if this project is still active: https://github.com/example/project"

The agent will activate the skill, run the data collection scripts, research
the project's history, and produce a structured markdown health report.

## Skill Structure

```
oss-health-analyzer/
├── SKILL.md                        # Skill metadata and agent instructions
├── scripts/
│   ├── collect_repo_data.py        # GitHub/GitLab API data collection
│   └── collect_registry_data.py    # Package registry lookups
└── references/
    └── report-template.md          # Output report template
```

## Report Sections

The generated report includes:

| Section | Contents |
|---------|----------|
| **Overall Health** | Active / Slowing / Stalled / Abandoned verdict with justification |
| **Project History & Origins** | Founding context, creator, purpose, milestones |
| **Development Activity** | Commit trends, releases, issues/PRs, contributors, bus factor, CI |
| **User Adoption & Community** | Stars/forks, downloads, dependents, community channels |
| **Key Risks & Observations** | Actionable risk list for potential adopters |
| **Summary** | Narrative synthesis with adoption guidance |

## Supported Platforms & Registries

**Repository platforms:**
- GitHub (github.com)
- GitLab (gitlab.com and self-hosted instances)

**Package registries:**
- PyPI (Python)
- npm (JavaScript/TypeScript)
- crates.io (Rust)
- Maven Central (Java/Kotlin/Scala)
- RubyGems (Ruby)
- NuGet (.NET)
- Packagist (PHP)
- Hex.pm (Elixir/Erlang)

## License

MIT -- see [LICENSE](LICENSE).
