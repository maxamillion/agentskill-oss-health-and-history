# Report Template

Use this template for the health report output. Fill in every field. If data
is unavailable, write "Not available — [reason]" rather than leaving it blank.

---

# [Project Name] — Open Source Health Report

**Repository:** [URL]
**Report Date:** [YYYY-MM-DD]
**Overall Health:** [Active / Slowing / Stalled / Abandoned] — [one-sentence justification]

## Project History & Origins

[Narrative summary: founding context, creator, purpose, key milestones, evolution
over time. Use bullet points for timeline events.]

- **[YYYY]** — [milestone description]
- **[YYYY]** — [milestone description]

## Development Activity

- **Last Substantive Commit:** [date, brief description]
- **Commit Trend (12 mo):** [increasing / stable / declining / dormant] — [X commits/week avg over last 3 months vs Y commits/week 12-month avg]
- **Latest Release:** [version, date, registry if applicable]
- **Release Cadence:** [description of pattern — e.g., "Releases every ~6 weeks; last release was 3 months ago, suggesting a slowdown"]
- **Open Issues:** [count] | **Open PRs:** [count]
- **Issues Responsiveness (last 90 days):** [X opened, Y closed, median time-to-first-response: Z hours]
- **Active Contributors (last 90 days):** [count] ([up/down/stable] from [count] in prior 90 days)
- **Bus Factor Risk:** [Low / Medium / High] — [brief explanation, e.g., "Top contributor accounts for 45% of commits; 3 others contribute >10% each"]
- **CI Status:** [CI system name, latest build status, or "Not detected"]

## User Adoption & Community

- **Stars:** [count] | **Forks:** [count] | **Watchers:** [count]
- **Package Downloads:** [count and period, e.g., "1.2M weekly downloads on npm"] ([trend if detectable])
- **Known Dependents:** [count if available, or "Not available — [reason]"]
- **Community Channels:** [list any discovered channels and their activity level, e.g., "Discord (5,000 members, active daily)", "GitHub Discussions (enabled, 50 discussions in last 90 days)"]

## Key Risks & Observations

- [Risk or observation 1 — e.g., "Primary maintainer has not committed in 120 days"]
- [Risk or observation 2 — e.g., "No release in 8 months despite active commit history"]
- [Risk or observation 3 — e.g., "License changed from MIT to AGPL in v3.0"]
- [Risk or observation 4 — e.g., "43 open security-related issues"]

## Summary

[2-3 paragraph narrative synthesizing the above into actionable guidance for
someone deciding whether to adopt or continue depending on this project.

Paragraph 1: Overall state of the project — is it healthy, slowing, or at risk?
What are the strongest positive signals?

Paragraph 2: Key concerns and risks. What should a potential adopter watch out for?
Are there mitigations (e.g., active fork, corporate backing)?

Paragraph 3: Recommendation — is this a safe dependency to adopt today? What would
change that assessment? What should the user monitor going forward?]
