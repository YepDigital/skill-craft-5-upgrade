---
name: craft-5-supertable
description: "Use this skill to migrate Super Table fields to native Craft 5 Matrix fields after a Craft 5 upgrade. This is an optional post-upgrade task — Super Table 4.x works in Craft 5, so migration is not required but is recommended to remove the plugin dependency. Triggers: 'migrate Super Table to Matrix', 'Super Table to native Matrix', 'remove Super Table plugin', 'convert Super Table fields', 'craft-5-supertable'. Do NOT use during the main Craft 5 upgrade — this is a separate task run after the site is stable on Craft 5."
disable-model-invocation: true
---

# Craft 5 Super Table → Native Matrix Migration (Optional)

## Overview

Converts Super Table fields to native Craft 5 Matrix fields after the site is
stable on Craft 5. This is a separate post-upgrade task — do not run during the
main upgrade.

**Prerequisites:** Site running on Craft 5, stable and verified.
`craft-5-upgrade` (and `craft-5-linkfield` if applicable) must be complete.
Check `.craft5-upgrade.md` for `PHASE: upgrade-done` or `linkfield-done`.

Super Table 4.x is Craft 5-compatible and works without this migration.
This skill is for projects that want to remove the Super Table plugin dependency
entirely.

**Work through one block at a time. Stop at the end of each block, report
findings, and wait for explicit confirmation before proceeding.**

---

## Global rules

- Never run destructive commands outside their designated block.
- If any command exits non-zero: stop, report full output, wait for
  instructions.
- Report all command output and all file edits with diffs.
- Minimal changes only.
- Ask the user explicitly whether they want to proceed before starting.

---

## BLOCK S1 — Audit Super Table fields

### S1.1 Confirm intent
Ask the user explicitly whether they want to proceed with the Super Table to
native Matrix migration.

### S1.2 Audit
Read `references/supertable-migration.md` in this skill's directory, then:

Search `config/project/` for fields with
`type: verbb\supertable\fields\SuperTableField`.

For each field, record:
- Handle and name
- Sub-fields (handles and types)
- Every entry type / section / field layout it appears in
- Any handle disambiguation suffixes (e.g. `navLink`, `navLink2`, `navLink3`)
  introduced during the Craft 5 upgrade (this migration is an opportunity to
  rename these to intentional handles)

---

**STOP. Report the full audit. Wait for confirmation before Block S2.**

---

## BLOCK S2 — Plan replacement Matrix fields

For each Super Table field, define the equivalent native Matrix field:
- Proposed handle (clean, without numeric suffixes if being remediated)
- Entry type name and handle
- Sub-field list (handles and types)

Present this plan to the user and wait for explicit approval before proceeding.

---

**STOP. Present the plan. Wait for approval.**

---

## BLOCK S3 — Create replacement Matrix fields

**Check `super-table/migrate` first** — Verbb ships a native migration command and
Craft 5 auto-converts Matrix blocks to entry types during `php craft up`, so the
preferred-first path is to run `php craft super-table/migrate` rather than writing
a custom console command. See `references/supertable-migration.md` (S3) for guidance
on evaluating it before falling back to the manual approach below.

For each approved Super Table field, create a new native Craft 5 Matrix field
with the agreed handle, entry type, and sub-fields.

Follow `references/supertable-migration.md` for the exact implementation
approach.

---

**STOP. Report all fields created. Wait for confirmation before Block S4.**

---

## BLOCK S4 — Migrate data

Write a console command following the same pattern as
`MigrateLinkfieldController` (use `getElementById()` for element loading; do
not use `:notempty:` element queries) to copy element content from Super
Table's internal storage to the native Matrix field.

Dry-run first, then live.

---

**STOP. Report dry-run output. Wait for explicit confirmation before live
migration.**

---

## BLOCK S5 — Update field layouts

Replace Super Table fields with Matrix fields in all element layouts using the
Craft 5 FieldLayout OO API (same approach as `addFieldToLayouts()` in
`MigrateLinkfieldController`).

---

**STOP. Report layouts updated. Wait for confirmation before Block S6.**

---

## BLOCK S6 — Update templates

Super Table and native Matrix share the same `.one()` access pattern in Craft 5,
so template changes should be minimal — primarily handle renames where handles
were cleaned up in Block S2.

Apply null guards and `.one()` patterns as established in the linkfield migration
(see `craft-5-linkfield` references if available).

---

**STOP. Report template changes with diffs. Wait for confirmation before
Block S7.**

---

## BLOCK S7 — Remove plugin and finalise

```bash
composer remove verbb/super-table --no-interaction
php craft project-config/apply
```

### S7.1 Final report

Produce a summary:
- Fields converted (Super Table handle → Matrix handle)
- Elements migrated per field
- Templates updated
- Any items requiring manual review

---

**STOP. Present the Block S7 report. Await follow-up instructions.**

---
