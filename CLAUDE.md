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
- `scripts/audit.py` — read-only audit (P1.7, P1.7a, P1.7b, P1.7c, P1.7d, P1.8,
  P1.8b, P1.10b, P1.12, P1.13, P1.14): linkfield inventory, Super Table duplicate
  handles, non-ST duplicate handles, URL→Link auto-promotion candidates, global
  duplicate handles, deprecated API calls, handle reference files, bootstrap
  customisations, afterSave* plugins (classified into field/content = keep enabled,
  deploy/notification = disable, unconfirmed = review), composer post-update-cmd,
  Redactor→CKEditor candidates.
  - **Field inventory has two sources.** When `--mysql-cmd`/`--db-name` (from
    P1.2) are passed, the `fields` DB table is **authoritative** and is
    cross-checked against project config (`CONFIG/DB MISMATCH` is flagged); the
    summary records `FIELD_INVENTORY_SOURCE: db`. Without them, a recursive
    project-config parser is the offline fallback (`FIELD_INVENTORY_SOURCE:
    config`, not authoritative). The config parser loads **both**
    `superTableBlockTypes/` and `matrixBlockTypes/` external blocks and recurses
    into nested block types (ST-inside-Matrix) — earlier versions missed Matrix
    block fields, ST-in-Matrix, and block-type-nested URL/Redactor fields.
  - `scripts/tests/` — fixture project + `test_audit.py`. Runs with no deps:
    `python3 craft-5-preflight/scripts/tests/test_audit.py` (or under pytest).
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

## Native-tooling decisions

These decisions were researched and recorded to avoid rediscovery. See
`native-craft-5-opps.md` for full spike notes and rationale.

- **`fields/merge` / `fields/auto-merge` — not adopted as default.** Stability
  over optimization: duplicate fields after upgrade are an acceptable outcome.
  `auto-merge` only reduces field count and carries known relation-merge bugs for
  max-relations=1 fields (#15869, #16198, #16444). Steps remain in upgrade U3.3
  and linkfield L4.5 as **optional and discouraged** opt-in only.

- **Content migrations (`php craft migrate/create`) — not adopted** for the
  linkfield data migration. The explicit dry-run → inspect → `echo "yes" |` → live
  gating on a destructive DB op is deliberately safer than "run once, tracked."

- **`run-direct` stays custom.** The linkfield 3.0.0-beta cannot instantiate
  Craft 4-era field settings, so `MigrateLinkfieldController run-direct` bypasses
  the plugin entirely and reads `lenz_linkfield` / `craft_fields` directly. No
  native command does this — it is the irreducible core of the migration.

- **`super-table/migrate` — opportunity documented, not validated.** Verbb ships
  `php craft super-table/migrate` and Craft 5 auto-converts Matrix blocks to entry
  types during `php craft up`. The supertable skill notes this as the preferred-first
  path to evaluate (S3 in `supertable-migration.md`), with the existing custom console
  command as the fallback pending real-data validation.

- **`stimmt/craft-mcp` — optional post-upgrade verification aid.** Craft 5-only,
  dev-only, install transiently, remove after sign-off. Not a skill dependency.
  See `craft-5-linkfield/references/post-upgrade-verification.md`.

- **Never disable field/content plugins for the upgrade (Hyper postmortem).**
  Field plugins (Hyper, Super Table, CKEditor, Redactor, Formie, linkfield, and
  anything registering a field/block/element type) ship content migrations that
  run during `php craft up` against the still-present Craft 4 content tables.
  Disabling one serializes its fields as `craft\fields\MissingField` into project
  config and skips its migration — irreversible once Craft drops the source tables
  (`matrixcontent_*`, `stc_*`). The `afterSave*` heuristic alone cannot tell a
  field plugin from a deploy/notification plugin, so P1.12 now classifies each into
  `FIELD_PLUGINS_KEEP_ENABLED` (never disable), `PLUGINS_TO_DISABLE_FOR_UPGRADE`
  (deploy/notification only), and `PLUGINS_FOR_MANUAL_REVIEW` (default: leave
  enabled). U2.6 adds a field/content render gate before any commit.

## Editing rules

- The global rules in each SKILL.md are instructions to the *runtime* — mirror
  their intent in any edit: minimal diffs, stop-and-report on error, no
  destructive default behaviour.
- Keep SKILL.md and support files in sync. Block codes are referenced by name
  across files (e.g. audit.py header cites "P1.7, P1.7a, P1.7b, P1.8 ..."; linkfield
  SKILL.md Block L3 cites `references/template-migration.md`). Renumbering a
  block means updating every cross-reference.
- The migration command is destructive against the target DB. The dry-run-before-
  live ordering and the `echo "yes" |` non-interactive pattern are deliberate
  safety mechanisms — do not collapse them.
- MySQL only. Do not add Postgres paths unless explicitly asked.
- `disable-model-invocation: true` in each SKILL.md frontmatter is intentional.
  Do not remove it.
