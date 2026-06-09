# craft-utils `array_unique` / Formie `Heading` fatal — reference

> Audience: maintainers of the craft-5-upgrade skill suite.
> This doc is the permanent skill reference for this failure mode. The detection
> (P1.15) lives in `craft-5-preflight/scripts/audit.py`; the fix (U2.1.5) lives in
> `craft-5-upgrade/SKILL.md` and `craft-5-upgrade/scripts/patch-craft-utils.py`.

---

## TL;DR

On a Craft 4 → 5 upgrade of a project that uses **both**:
- `sebastianlenz/linkfield` (Typed Link Field; pulls in `sebastianlenz/craft-utils`), **and**
- `verbb/formie` with at least one **`Heading`** field (or any other Formie field
  whose class is **not stringable** — see below) in a form,

`php craft up` **fatals partway through migrations** with:

```
Exception: Object of class verbb\formie\fields\Heading could not be converted to string
  (vendor/sebastianlenz/craft-utils/src/foreignField/ForeignFieldQueryListener.php:54)
#0 ... array_unique(Array)
#1 lenz\craft\utils\foreignField\ForeignFieldQueryListener::onBeforeQueryPrepare(...)
... triggered from a Formie migration that runs Form::find()->all()
   (e.g. verbb/formie/src/migrations/m240130_000000_permissions.php)
```

Craft auto-rolls-back the DB on the failed migration, leaving you on Craft 4
**schema** but with Craft 5 **vendor** code installed (a split state). See the
Recovery section for the second gotcha (orphaned tables) this produces.

**Confirmed versions (real incident):** Craft `5.10.5`,
`sebastianlenz/linkfield 3.0.0-beta`, `sebastianlenz/craft-utils 4.0.8`,
`verbb/formie 3.1.27`, PHP 8.4. `3.0.0-beta` is currently the only Craft 5
release of linkfield, so there is no "upgrade the plugin" escape hatch.

---

## Root cause

`craft-utils` registers a global `ElementQuery::EVENT_BEFORE_PREPARE` listener
(`ForeignFieldQueryListener::onBeforeQueryPrepare`). For any element query with
`withCustomFields`, it collects every custom field across **all field layouts of
that element type**, de-duplicates them, then filters down to its own `ForeignField`
(linkfield) instances.

The de-dup uses `array_unique()` **with the default `SORT_STRING` flag**, over an
array of **field objects**:

```php
// vendor/sebastianlenz/craft-utils/src/foreignField/ForeignFieldQueryListener.php (~line 53)
$fields = array_filter(
  array_unique(array_reduce(                       // <-- SORT_STRING casts each field to string
    $fieldLayouts,
    fn($fields, $fieldLayout) => array_merge($fields, $fieldLayout->getCustomFields()),
    []
  )),
  fn($field) => $field instanceof ForeignField
);
```

`SORT_STRING` casts every element to a string. Most Craft field classes tolerate
this, but Formie's `Heading` (and other cosmetic/no-value Formie fields) has
**no `__toString()`**, so PHP throws
*"Object of class … could not be converted to string"*. Because the
`array_unique()` runs over **all** fields **before** the `instanceof ForeignField`
filter, a single non-stringable field anywhere in the queried element type's
layouts is enough to fatal.

During `php craft up`, Formie's own migrations call `Form::find()->all()`, which
triggers the listener against `Form` element layouts (which contain the `Heading`),
so it blows up mid-upgrade.

The non-stringable class is **not limited to `Heading`** — any Formie cosmetic
field without `__toString()` triggers it. The preflight check covers:
`Heading`, `Html`, `Section`, `Summary`. The vendor patch fixes the whole class.

**Runtime risk (not just upgrade):** this same fatal hits the **front-end** any
time a non-stringable custom field shares an element type's field layouts with a
query that has `withCustomFields` (e.g. the live Formie contact form). The vendor
patch must stay in place until `linkfield`/`craft-utils` is removed.

---

## The fix (U2.1.5): `scripts/patch-craft-utils.py`

The skill patches `ForeignFieldQueryListener` so it **filters to `ForeignField`
first, then de-dups by handle** — never stringifying arbitrary field objects. This
matches how the downstream loop already keys everything by `$field->handle`.

```php
// BEFORE (buggy)
$fields = array_filter(
  array_unique(array_reduce(
    $fieldLayouts,
    fn($fields, $fieldLayout) => array_merge($fields, $fieldLayout->getCustomFields()),
    []
  )),
  fn($field) => $field instanceof ForeignField
);

// AFTER (patched)
$fields = array_filter(
  array_reduce(
    $fieldLayouts,
    fn($fields, $fieldLayout) => array_merge($fields, $fieldLayout->getCustomFields()),
    []
  ),
  fn($field) => $field instanceof ForeignField
);
// Patched (Craft 5 upgrade): dedup ForeignFields by handle instead of
// array_unique() over all field objects, which fatals on non-stringable
// fields (e.g. Formie Heading). Temporary — reverts when craft-utils is
// removed with linkfield in craft-5-linkfield L4.
$unique = [];
foreach ($fields as $field) {
    $unique[$field->handle] = $field;
}
$fields = $unique;
```

### Why "by handle" and not `array_unique(..., SORT_REGULAR)`
`SORT_REGULAR` avoids the string cast but falls back to **deep object comparison**
(`==`) over Craft field objects, which can be slow and may recurse on internal
references. Keying by `$field->handle` is O(n), matches the downstream usage
(`$handle = $field->handle; $filter = $fieldAttributes->$handle`), and is the
safest minimal change.

### Durability — important
This edits **`vendor/`**, which is git-ignored and **will be reverted by any
`composer install`/`composer update` that touches `craft-utils`.** It must survive
only until `linkfield` + `craft-utils` are removed in `craft-5-linkfield` Block L4.1.

- **Skill behaviour:** `patch-craft-utils.py` is idempotent (sentinel-guarded),
  so it is safe to run again after any composer reinstall of `craft-utils`.
- **If composer reinstalls craft-utils before L4:** re-run the patcher
  (`scripts/patch-craft-utils.py` in the craft-5-upgrade skill directory):
  `python3 <skill_dir>/scripts/patch-craft-utils.py`
- **Removal:** when `composer remove sebastianlenz/linkfield` runs in L4.1,
  `craft-utils` is also removed and the patched vendor file disappears with it.
  No separate cleanup needed.

---

## Recovery: orphaned tables after a failed `php craft up`

When `php craft up` fails mid-migration, Craft **auto-restores the backup it took
at the start of that run** — but its restore **only drops/recreates tables that
exist in the dump**. Any **new** tables created by migrations that ran *before*
the failure are **not in the Craft 4 dump**, so they are **left behind**
(orphaned). On the next `php craft up`, an early migration like
`craftcms/ckeditor … m260427_230945_references` fails with:

```
SQLSTATE[42S01]: Base table or view already exists: 1050 Table 'ckeditor_references' already exists
```

Each failed run takes a *fresh* start-of-run backup (now containing the previous
run's orphans), so the orphan set can **grow** across attempts.

### Do not chase orphans one-by-one

The set is non-deterministic — drop counts depend on how far into the migration
sequence each run got. Instead, restore a **known-clean pre-`php craft up`
snapshot** and re-run.

**Identify the right backup deterministically:**

```bash
# Tables currently in DB
mysql ... -sN -e "SELECT table_name FROM information_schema.tables
                  WHERE table_schema='DB' ORDER BY table_name;" > /tmp/current.txt
# Tables defined in a candidate backup
grep -oE 'CREATE TABLE `[^`]+`' backup.sql | sed 's/CREATE TABLE `//;s/`//' | sort -u > /tmp/clean.txt
# Orphans = present now but not in the clean backup
comm -23 /tmp/current.txt /tmp/clean.txt
```

The right backup to restore is the **auto-backup taken at the start of the
*first* `php craft up` attempt** — it is post-preflight-prep
(`project-config/rebuild`, `fix-field-layout-uids`, handle remediations) but
pre-Craft-5-tables. Verify a candidate is clean by confirming it has **no**
`CREATE TABLE \`ckeditor_references\`` (or `auth_oauth_tokens`) and still contains
your expected state (e.g. renamed field handles).

**Restore cleanly** — raw `mysql < dump` does **not** drop tables absent from the
dump, so drop/recreate the schema first:

```bash
mysql ... -e "DROP DATABASE db; CREATE DATABASE db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
mysql ... db < clean-start-of-first-up.sql
```

Recreate the database with its **original default** charset/collation — capture it
beforehand from `information_schema.SCHEMATA`. The Craft 4-era tables are typically
`utf8mb3` per-table; the `db/convert-charset` step (U2.4) moves everything to
`utf8mb4` after the upgrade succeeds.

A dropped/recreated DB is a destructive action and may be blocked by tooling
guardrails — expect to ask the operator to authorise it (or run it themselves).

> Prevention beats recovery: if the skill pre-patches `craft-utils` (U2.1.5) and
> neutralises the `post-update-cmd` auto-`up` so the patch lands first, the first
> `php craft up` succeeds and **no orphaned tables are ever created**.

---

## Appendix — exact error site

```
File:    vendor/sebastianlenz/craft-utils/src/foreignField/ForeignFieldQueryListener.php
Method:  ForeignFieldQueryListener::onBeforeQueryPrepare(CancelableEvent $event)
Line:    ~54 (the array_unique() call)
Trigger: any ElementQuery with withCustomFields whose elementType has a
         non-stringable custom field in its field layouts
         (Formie Heading is the canonical case).
Upgrade trigger: verbb/formie migration running Form::find()->all() during
         `php craft up`, e.g. m240130_000000_permissions.
Runtime trigger: rendering a Formie form that contains a Heading field.
```
