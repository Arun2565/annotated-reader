# Agent Skills Repository

Skills for AI coding agents following the [Agent Skills](https://agentskills.io/) standard.

## Structure

```
skills/<skill-name>/
├── SKILL.md          # Required - instructions for the agent
├── scripts/          # Optional - helper scripts
└── references/       # Optional - supporting documentation
```

## Adding a New Skill

1. Create `skills/<skill-name>/SKILL.md` with YAML frontmatter
2. Add scripts and references as needed
3. Run `node scripts/build-discovery-index.mjs <base-url>` to rebuild
