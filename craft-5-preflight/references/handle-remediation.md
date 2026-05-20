# Handle Remediation Reference

Read this file when executing Block P2 (Duplicate-handle remediation on Craft 4).

---

## Why this matters

Craft 5 globally deduplicates field handles. If two Super Table block types both
define a sub-field with handle `navLink`, Craft 5 renames one instance to
`navLink2` during the upgrade — **non-deterministically**. The rename order is
undefined from project config alone.

After the upgrade, the linkfield migration appends `_v2` to every handle:
`navLink` → `navLink_v2`, `navLink2` → `navLink2_v2`. Now there are two
`_v2` handles for what was one template variable. The only way to tell which
belongs to which template loop is the field's human-readable `name`.

This causes silent, invisible failures: if you assign the wrong `_v2` handle
to a template loop, every link in that loop outputs an empty string with no error.

**Renaming duplicate handles while still on Craft 4 — before any upgrade —
eliminates this problem entirely.** After remediation, each handle is unique, the
`_v2` mapping is 1:1, and no disambiguation is needed.

---

## Where duplicate handles are defined

Super Table block types are defined in `config/project/fields/` as YAML files
(one file per Super Table field). Each file contains a `blockTypes` section:

```yaml
# config/project/fields/<uid>.yaml
handle: navigationLinks
name: Navigation Links
type: verbb\supertable\fields\SuperTableField
blockTypes:
  <uid>:
    fields:
      <uid>:
        handle: navLink     # ← this handle
        name: Utility Navigation - Link
        type: lenz\linkfield\fields\LinkField
      ...
  <uid>:
    fields:
      <uid>:
        handle: navLink     # ← duplicate
        name: Main Navigation - Link
        type: lenz\linkfield\fields\LinkField
```

The `handle` inside a block type's `fields` section is the sub-field handle.
Duplicate = the same string appears in two different block types (even in
different Super Table fields).

---

## How to identify which block type is which

Use the `name` field (human-readable) to identify context:
- `name: Utility Navigation - Link` → this is the utility nav link
- `name: Main Navigation - Link` → this is the main nav link

Cross-reference with template loops: find `{% for block in entry.navigationLinks.all() %}` 
(or similar) in templates and see which block type variables are accessed in each loop.

---

## Renaming a handle in project config

Edit the YAML file directly. Change the `handle:` value for the specific
block type field:

```yaml
# Before
      handle: navLink
      name: Utility Navigation - Link

# After
      handle: utilityNavLink
      name: Utility Navigation - Link
```

Only change `handle:`. Do not change the UID keys, the name, or any other
values.

---

## Updating templates

After changing a handle in project config, find every template that accesses
the old handle **in the context of that block type's loop**.

Use `rg` to find candidates:
```bash
rg -n 'navLink' templates/
```

For each result, check the surrounding loop structure:
```twig
{% for block in entry.navigationLinks.all() %}
  {% if block.type == 'utilityNav' %}
    {# ← this loop uses the utility nav block type #}
    {{ block.navLink.url }}  {# → change to block.utilityNavLink.url #}
  {% endif %}
{% endfor %}
```

Only change references inside the relevant block type's conditional. Do not
change references that belong to a different block type's loop.

---

## After each rename

1. `php craft project-config/apply` — applies the config change to the DB
2. Verify the site loads in browser (no Craft errors)
3. Report the diff and wait for confirmation before the next rename

Do one rename pair at a time. Rushing multiple renames without verification
risks leaving the site broken.

---

## Naming conventions for renamed handles

Prefer descriptive, context-specific names over generic suffixes:
- `navLink` (utility) → `utilityNavLink` ✓
- `navLink` (main) → `mainNavLink` ✓
- `navLink` (utility) → `navLink1` ✗ (no better than the auto-suffix)

The rename is permanent. Choose names you'll want in templates for the life
of the project.

---

## Handles that are NOT duplicates (within Super Table scope)

The P1.7a audit reports handles duplicated across Super Table block types.
It does NOT flag handles that appear in the same block type (only one instance
per handle per block type is allowed by Craft).

It also does NOT flag handles that appear in separate, unrelated Super Table
fields — those are independent DB rows and Craft does not deduplicate them.

Check the audit output carefully: each duplicate entry includes the ST field
name and block type name so you can see exactly which pairings need renaming.

---

## Non-ST duplicate linkfield handles (P1.7b)

P1.7b flags linkfield handles that appear in multiple *non-ST* contexts:
top-level fields, Matrix block sub-fields, or both.

**The risk is the same as ST duplicates** — the `craft-5-linkfield` migrator
calls `getAllFields()` which deduplicates by handle. If `linkTo` appears as
both a top-level field and a Matrix block sub-field, only one will be returned,
and one context's data will not be migrated.

**Why P2 does not remediate these:** renaming a top-level linkfield handle
on Craft 4 is safe but requires updating all field layout YAML and templates.
The same pattern as P2.3 applies, but the YAML files are different (top-level
field files rather than ST block type YAML).

If data exists in both contexts: apply the same rename pattern — choose a
unique intentional name, edit the YAML, update templates, apply, and commit.
Document the renaming in `HANDLE_REMEDIATIONS` like ST renames.

If both contexts have zero rows (verify via SQL before deciding): document
in `NON_ST_DUPLICATE_HANDLES` and proceed — the L2 `_v2` count mismatch
will be caught after migration.

Check the audit output carefully: each duplicate entry includes the YAML file path
for each instance.
