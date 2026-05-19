# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What this repo is

This repo is a **suite of four Claude Code skills** that orchestrate upgrading
a Craft CMS 4 project to Craft CMS 5. There is no build, lint, or test step.
The "product" is the SKILL.md files plus their support files. Changes here change
how Claude runs the upgrade against a *separate* target project.

When editing skills, the `skill-creator` skill is the tool for creating,
editing, evaluating, and optimising skills (including the `description`
frontmatter that controls trigger accuracy).

## Skill suite

Each skill is a subdirectory with its own `SKILL.md`. Install by symlinking
or copying each directory into `~/.claude/skills/`:

```
craft-5-preflight/   Audit + Craft-4 duplicate-handle remediation
craft-5-upgrade/     Destructive Craft 5 upgrade (composer, php craft up)
craft-5-linkfield/   Linkfield data migration + template patching
craft-5-supertable/  Optional: Super Table → native Matrix (post-upgrade)
```

Run order: preflight → upgrade → linkfield (if LINKFIELD_PRESENT=yes) → supertable (optional).

All four have `disable-model-invocation: true` — explicit invocation only.

## State file contract

`craft-5-preflight` writes `.craft5-upgrade.md` to the **target** project root.
`craft-5-upgrade` and `craft-5-linkfield` read it and refuse to run if absent.
Each skill appends its phase result:
`PHASE: preflight-done | upgrade-done | linkfield-done`

The state file contains `MYSQL_CMD` (local value) — target projects should add
`.craft5-upgrade.md` to `.gitignore`.

## Architecture

Each skill:
- Has a strictly sequential block structure. Each block ends with a hard STOP.
- Reads only its own `references/` and `scripts/` (never all at once; loaded
  on demand per block).
- The central conditional is `LINKFIELD_PRESENT` (recorded in preflight and
  carried through the state file).

### craft-5-preflight
- `scripts/audit.sh` — read-only audit (P1.7, P1.7a, P1.8): linkfield field
  inventory, Super Table duplicate handles, deprecated template API calls.
- `references/handle-remediation.md` — detailed guide for Block P2
  (duplicate handle renaming on Craft 4, the primary root-cause fix).

### craft-5-upgrade
- `module/` — the Craft module copied into the target project.
  `Module.php` registers console controller namespace; `app.php` is a
  merge-snippet for the target's `config/app.php`;
  `console/controllers/MigrateLinkfieldController.php` is the migration command
  (`run-direct` is the primary path; `run` is the fallback).
- `references/module-setup.md` — Block U1.3 instructions for copying the module.

### craft-5-linkfield
- `scripts/patch-templates.py` — Block L3 template patcher. Hardcoded API
  substitutions plus project-specific handle renames via `--handles` JSON.
  `--dry-run` prints diffs without writing.
- `references/template-migration.md` — API map, null-safety patterns, Super
  Table `.one()` patterns, and the template editing approach.

### craft-5-supertable
- `references/supertable-migration.md` — full instructions for Blocks S1–S7.

## `run-direct` vs `run`

`run-direct` is the **primary** migration path in `craft-5-linkfield`. It:
- Discovers old fields via direct `craft_fields` DB query (no plugin instantiation)
- Auto-creates missing `_v2` native Link fields from raw settings JSON
- Migrates element data directly from `lenz_linkfield` table
- Safe to re-run (idempotent per element)

`run` is the fallback: uses plugin field instantiation to discover fields.
Fails with "No Typed Link Fields found" when the 3.0.0-beta cannot instantiate
Craft 4-era field settings — the common real-site failure mode.

## Editing rules

- The global rules in each SKILL.md are instructions to the *runtime* — mirror
  their intent in any edit: minimal diffs, stop-and-report on error, no
  destructive default behaviour.
- Keep SKILL.md and support files in sync. Block codes are referenced by name
  across files (e.g. audit.sh header cites "P1.7, P1.7a, P1.8"; linkfield
  SKILL.md Block L3 cites `references/template-migration.md`). Renumbering a
  block means updating every cross-reference.
- The migration command is destructive against the target DB. The dry-run-before-
  live ordering and the `echo "yes" |` non-interactive pattern are deliberate
  safety mechanisms — do not collapse them.
- MySQL only. Do not add Postgres paths unless explicitly asked.
- `disable-model-invocation: true` in each SKILL.md frontmatter is intentional.
  Do not remove it.
