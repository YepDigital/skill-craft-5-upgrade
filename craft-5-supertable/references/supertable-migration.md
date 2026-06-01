# Super Table → native Matrix migration (optional)

This file is read by `craft-5-supertable` Block S1.2. Sections are numbered
to match the SKILL.md (S1–S7).

This migration is optional. Super Table 4.x (the Craft 5-compatible release)
works in Craft 5, so upgrading to native Matrix is not required. However,
removing the Super Table plugin dependency is recommended as a follow-up
once the site is stable on Craft 5.

Do not run this during the main upgrade. Treat it as a separate task.

Ask the user explicitly whether they want to proceed before starting.

---

## S1 — Audit Super Table fields

- Search `config/project/` for fields with `type: verbb\supertable\fields\SuperTableField`.
- For each field record: handle, name, sub-fields (handles, types), and every entry
  type / section / field layout it appears in.
- Note any handle disambiguation suffixes (e.g. `navLink`, `navLink2`, `navLink3`)
  introduced during the Craft 4 to Craft 5 upgrade. The native Matrix migration is an
  opportunity to rename these to intentional handles.

## S2 — Plan replacement Matrix fields

For each Super Table field, define the equivalent native Matrix field:
- Proposed handle (clean, without numeric suffixes)
- Entry type name and handle
- Sub-field list (handles and types)

Present this plan to the user and wait for approval before proceeding.

## S3 — Create replacement Matrix fields

**Preferred-first path: `php craft super-table/migrate`**

Verbb ships a native migration command (`super-table/migrate`) and Craft 5
auto-converts Matrix blocks to entry types during `php craft up`. Before writing
a custom console command, run:

```bash
php craft super-table/migrate --dry-run
```

If it reports the fields cleanly and its output matches the S2 plan, proceed with
the live run. This is the simpler path — validate against a real upgraded dataset
before deciding the custom approach is needed.

**Fallback — custom console command:**
If `super-table/migrate` is unavailable or produces unexpected output, write a
custom console command following the `MigrateLinkfieldController` pattern. For
each approved field, create the native Matrix field with the agreed handle, entry
type, and sub-fields using `Craft::$app->getFields()->saveField()`.

*Note: the `super-table/migrate` path is documented here as the preferred option
but has not yet been validated against a real upgraded dataset in this suite.
Validate its output against S2 before relying on it over the custom approach.*

## S4 — Migrate data

**If using `super-table/migrate` (from S3):**
The Verbb command handles data migration. Verify element content is transferred
correctly before proceeding to S5.

**If using the custom console command (fallback):**
Write a console command (following the same pattern as `MigrateLinkfieldController`)
to copy element content from Super Table's internal storage to the native Matrix field.
Use `getElementById()` for element loading; do not use `:notempty:` element queries.

## S5 — Update field layouts

Replace Super Table fields with Matrix fields in all element layouts using the
Craft 5 FieldLayout OO API (same approach as `addFieldToLayouts()` in the
linkfield migration controller).

## S6 — Update templates

Super Table and native Matrix share the same `.one()` access pattern in Craft 5,
so template changes should be minimal, primarily handle renames where handles were
cleaned up in S2. Apply null guards and `.one()` patterns as established in the
linkfield migration (see `craft-5-linkfield/references/template-migration.md`).

## S7 — Remove plugin

```bash
composer remove verbb/super-table --no-interaction
php craft project-config/apply
```

Produce a summary of fields converted, elements migrated, templates updated,
and any items requiring manual review.

---

**STOP. Present the S7 report. Await follow-up instructions.**
