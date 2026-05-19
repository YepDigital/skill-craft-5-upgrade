# Craft 5 Upgrade Skill Suite

Four Claude Code skills that orchestrate upgrading a Craft CMS 4 project to
Craft CMS 5, including migration of `sebastianlenz/linkfield` (Typed Link Field)
to Craft 5's native Link field.

## Skills

| Skill | Directory | Purpose |
|-------|-----------|---------|
| `craft-5-preflight` | `craft-5-preflight/` | Audit + Craft-4 duplicate-handle remediation |
| `craft-5-upgrade` | `craft-5-upgrade/` | Destructive upgrade (Composer, `php craft up`) |
| `craft-5-linkfield` | `craft-5-linkfield/` | Linkfield data migration + template patching |
| `craft-5-supertable` | `craft-5-supertable/` | Optional: Super Table → native Matrix |

## Run order

```
craft-5-preflight   → all projects
craft-5-upgrade     → all projects (after preflight-done)
craft-5-linkfield   → projects with sebastianlenz/linkfield only (after upgrade-done)
craft-5-supertable  → optional, any time after upgrade-done
```

## Install

This repo lives at `~/.claude/skills/craft-5-upgrade/`. Claude Code discovers
nested skill directories automatically. The skills are registered as:

| Skill ID | Directory |
|----------|-----------|
| `craft-5-upgrade:craft-5-preflight` | `craft-5-preflight/` |
| `craft-5-upgrade:craft-5-upgrade` | `craft-5-upgrade/` |
| `craft-5-upgrade:craft-5-linkfield` | `craft-5-linkfield/` |
| `craft-5-upgrade:craft-5-supertable` | `craft-5-supertable/` |

No extra installation steps needed — cloning to `~/.claude/skills/craft-5-upgrade/`
is sufficient. Skills trigger via their `description` frontmatter or explicit
`/craft-5-preflight` etc. invocation.

## State file

`craft-5-preflight` writes `.craft5-upgrade.md` to the target project root.
Subsequent skills read it and refuse to run if absent or out of phase.
Add `.craft5-upgrade.md` to the target project's `.gitignore` (contains
`MYSQL_CMD`, a local value).

## Key design decisions

- **Duplicate handles fixed on Craft 4** — `craft-5-preflight` Block P2 renames
  duplicate Super Table sub-field handles before the upgrade. This eliminates
  the non-deterministic Craft 5 deduplication (`handle` → `handle2`) that was
  the primary source of silent empty-URL failures in templates.

- **`run-direct` as primary migration path** — `MigrateLinkfieldController`'s
  `actionRunDirect()` bypasses plugin field instantiation, auto-creates `_v2`
  native fields from raw DB settings JSON, and migrates element data directly.
  Works when `sebastianlenz/linkfield 3.0.0-beta` cannot instantiate Craft 4-era
  field settings (the common real-site failure mode for `actionRun()`).

- **State file bridges skills** — critical session values (`LINKFIELD_PRESENT`,
  `MYSQL_CMD`, linkfield inventory, handle remediations, template audit files)
  are written to disk, not carried only in conversation memory.

- **MySQL only** — Postgres is not supported.
