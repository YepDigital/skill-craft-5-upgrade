# Block 7 — Super Table to native Matrix migration (optional)

This block is optional. Super Table 4.x (the Craft 5-compatible release) works in Craft 5,
so this upgrade is not required. However, removing the Super Table plugin dependency and
replacing it with Craft 5's native Matrix field is recommended as a follow-up.

Do not run this block during the main upgrade. Treat it as a separate task once the
site is stable on Craft 5.

Ask the user explicitly whether they want to proceed with this block before starting.

---

## 7.1 Audit Super Table fields

- Search `config/project/` for fields with `type: verbb\supertable\fields\SuperTableField`.
- For each field record: handle, name, sub-fields (handles, types), and every entry
  type / section / field layout it appears in.
- Note any handle disambiguation suffixes (e.g. `navLink`, `navLink2`, `navLink3`)
  introduced during the Craft 4 to Craft 5 upgrade. The native Matrix migration is an
  opportunity to rename these to intentional handles.

## 7.2 Plan replacement Matrix fields

For each Super Table field, define the equivalent native Matrix field:
- Proposed handle (clean, without numeric suffixes)
- Entry type name and handle
- Sub-field list (handles and types)

Present this plan to the user and wait for approval before proceeding.

## 7.3 Create replacement Matrix fields

For each approved Super Table field, create a new native Craft 5 Matrix field
with the agreed handle, entry type, and sub-fields. Use `Craft::$app->getFields()->saveField()`.

## 7.4 Migrate data

Write a console command (following the same pattern as `MigrateLinkfieldController`)
to copy element content from Super Table's internal storage to the native Matrix field.
Use `getElementById()` for element loading; do not use `:notempty:` element queries.

## 7.5 Update field layouts

Replace Super Table fields with Matrix fields in all element layouts using the
Craft 5 FieldLayout OO API (same approach as `addFieldToLayouts()` in the
linkfield migration controller).

## 7.6 Update templates

Super Table and native Matrix share the same `.one()` access pattern in Craft 5,
so template changes should be minimal, primarily handle renames. Apply null guards
and `.one()` patterns as established in Block 5.

## 7.7 Remove plugin

```bash
composer remove verbb/super-table --no-interaction
php craft project-config/apply
```

## 7.8 Report

Produce a summary of fields converted, elements migrated, templates updated,
and any items requiring manual review.

---

**STOP. Present the Block 7 report. Await follow-up instructions.**
