---
name: craft5-upgrade
description: "Use this skill when the user wants to upgrade a Craft CMS 4 project to Craft CMS 5. Triggers include: any mention of 'upgrade to Craft 5', 'Craft 4 to 5', 'Craft 5 upgrade', 'Typed Link Field migration', 'sebastianlenz/linkfield', 'linkfield to native Link field', 'Craft 5 migration', or requests to migrate a Craft CMS project to the latest major version. This skill handles the full upgrade process including pre-upgrade preparation, composer changes, the Craft 5 database upgrade, and migration of the sebastianlenz/linkfield (Typed Link Field) plugin to Craft 5's native Link field. Also use when the user asks about migrating Super Table fields to native Matrix in Craft 5. Do NOT use for Craft 3 upgrades, general Craft CMS development, or plugin development unrelated to the upgrade."
---

# Craft 4 to Craft 5 Upgrade

## Overview

This skill upgrades a Craft CMS 4 project to Craft 5. It handles a known blocker:
`sebastianlenz/linkfield` (Typed Link Field) is abandoned with no official Craft 5
release, but a `3.0.0-beta` on Packagist declares `craftcms/cms: ^5.1.3` compatibility.
The strategy is to resolve both Craft 5 and the linkfield beta in a single composer pass,
then migrate linkfield data to the native Craft 5 Link field post-upgrade.

**Work through one block at a time. Stop at the end of each block, report findings,
and wait for explicit confirmation before proceeding to the next block.**

---

## Global rules

- Never run destructive commands (composer changes, database writes, file edits) outside the block they are designated to.
- Never skip a STOP checkpoint. Each block ends with an explicit stop requiring user confirmation before continuing.
- If any command exits non-zero: stop, report the full output, wait for instructions.
- Report all command output. Report all file edits with diffs for non-trivial changes.
- Minimal changes only. Do not refactor, reformat, or improve code beyond what the upgrade strictly requires.
- Never delete database content. The `--cleanup` flag removes field definitions only.

**Rollback:** Restore the database backup, run `git checkout composer.json composer.lock && composer install`, then `git checkout .` to revert file changes.

---

## BLOCK 1 — Audit (read-only, no changes)

### 1.1 Craft and PHP version
Ask the user to provide:
- The current Craft CMS version (e.g. "4.12.2")
- The PHP version in use (e.g. "8.2.1")

Record both. Flag PHP below 8.2 as a blocker. Do not attempt to detect these
automatically; user-provided values are more reliable.

### 1.2 Database engine
Check `.env` and `config/db.php` for `CRAFT_DB_DRIVER`. Record MySQL or PostgreSQL.
Record any existing `CRAFT_DB_CHARSET` / `CRAFT_DB_COLLATION` values.

### 1.3 Plugin inventory
Read `composer.json`. For every package under `require`, check Packagist for a
Craft 5-compatible release. Flag any missing Craft 5 release as a blocker.

If Packagist is unreachable or returns errors, ask the user to confirm Craft 5
compatibility for each plugin manually before proceeding.

Exception: `sebastianlenz/linkfield` has no official Craft 5 release but
`3.0.0-beta` requires `craftcms/cms: ^5.1.3` and is the intended upgrade path.
Do not flag it as a blocker if it is present.

### 1.4 Linkfield presence check
Check whether `sebastianlenz/linkfield` appears in `composer.json` under `require`.
Record the result as **LINKFIELD_PRESENT: yes** or **LINKFIELD_PRESENT: no**.
This determines whether Blocks 2.3, 2.5, 2.5a, and Block 4 are relevant.
Include this prominently in the Block 1 report.

### 1.5 `vlucas/phpdotenv`
Check the constraint in `composer.json`. Flag if below `^5.6.0`.

### 1.6 Queue status
```bash
php craft queue/info
```
Flag any pending or reserved jobs as a blocker.

### 1.7 Linkfield field inventory
Search `config/project/` for fields with `type: lenz\linkfield\fields\LinkField`.
For each field record: handle, name, context (global / Matrix / Super Table),
enabled link types, and any `columnSuffix` value.

### 1.7a Super Table duplicate field handles
If `verbb/super-table` is present, search `config/project/` for field handles that
appear in more than one Super Table block type. List each duplicated handle, the block
type name it belongs to, and the section/field that contains the block type.

This matters because after the Craft 5 upgrade Super Table block types become native
Matrix entry types. Fields sharing a handle across multiple block types get globally
deduplicated by Craft: the first occurrence keeps the original handle, subsequent
occurrences get numeric suffixes (`handle2`, `handle3`, etc.). The exact mapping is
non-deterministic from config alone — you will need to confirm it via the CP or a DB
query after the upgrade. Record all duplicated handles here so Block 5 template work
can reference the correct suffixed handle per template loop.

### 1.8 Template linkfield API usage
Search all files under `templates/` for:
- `.getUrl(`
- `.getCustomText(`
- `.getTarget(`
- `.getType`
- `.getElement(`
- `.getLinkAttributes(`
- `craft.matrixBlocks(`

Also search for `.with([` calls that include any linkfield handle from step 1.7
(e.g. `.with(["navLink"])`, `.with(["primaryLink"])`). These calls must be removed
after migration because native Craft 5 Link fields cannot be eager-loaded — passing
a Link field handle to `.with()` causes Craft to return an `ElementCollection`
instead of a `LinkData` object, breaking all subsequent `.url`, `.label`, and
`.type` access.

List every file and line number found.

### 1.9 Template extension collisions
Search `templates/` for directories containing both a `.twig` and `.html` file
with the same base name. List any found.

### 1.10 `web/index.php` and `craft` executable
Check for any customisations beyond standard Craft boilerplate. Note bootstrap
constants or custom logic.

### 1.11 Temp Uploads Location
Check `config/general.php` or project config for a temp uploads path. Record it.

---

**STOP. Report all findings as a structured summary. Flag blockers clearly.
Wait for confirmation before Block 2.**

---

## BLOCK 2 — Pre-upgrade preparation (Craft 4, no composer changes yet)

### 2.1 Confirm backup and version control
Ask the user to confirm a full database backup has been taken and the project is committed to version control. Do not proceed until both confirmed.

### 2.2 Pre-upgrade Craft commands
```bash
php craft project-config/rebuild
php craft utils/fix-field-layout-uids
```

### 2.3 Install the migration module (linkfield projects only)
**Skip this entire step if LINKFIELD_PRESENT was recorded as "no" in Block 1.**

Check whether `modules/Module.php` already exists in the project.

- If it exists and already registers a console controller namespace, check whether
  `modules/console/controllers/MigrateLinkfieldController.php` already exists.
  If both exist, skip to step 2.4.

- If the module does not exist, copy the following files from this skill's `module/`
  directory into the project:

  | Source (skill) | Destination (project) |
  |---|---|
  | `module/Module.php` | `modules/Module.php` |
  | `module/console/controllers/MigrateLinkfieldController.php` | `modules/console/controllers/MigrateLinkfieldController.php` |

- Ensure `config/app.php` contains the module registration keys. Refer to this
  skill's `module/app.php` for the keys that must be present. Merge them into the
  existing `config/app.php` return array if absent. Do not replace the file; only
  add the missing `modules` and `bootstrap` entries:
  ```php
  'modules' => [
      'my-module' => \modules\Module::class,
  ],
  'bootstrap' => ['my-module'],
  ```

- Confirm `composer.json` has a PSR-4 autoload entry `"modules\\": "modules/"`. Add if absent. Do not run `composer update` yet.

### 2.4 Update `vlucas/phpdotenv` if needed
If below `^5.6.0`, update the constraint in `composer.json` to `^5.6.0`.
Do not run `composer update` yet; constraint edit only.

### 2.5 Update `composer.json` for Craft 5
Ask the user if they have run the Craft 5 Upgrade utility in the CP
(Utilities > Craft 5 Upgrade > Prep `composer.json`) and have output to paste in.

- If yes: apply the user's output to `composer.json`.
- If no: manually update `craftcms/cms` to `^5.0.0` and each plugin to its
  Craft 5-compatible version as identified in Block 1.

If LINKFIELD_PRESENT is "yes", also set:
```json
"sebastianlenz/linkfield": "^3.0.0-beta"
```
If LINKFIELD_PRESENT is "no", do not add or modify any linkfield constraint.

### 2.6 Stability flags (linkfield projects only)
**Skip this entire step if LINKFIELD_PRESENT was recorded as "no" in Block 1.**

Because `sebastianlenz/linkfield: ^3.0.0-beta` is a beta release, `composer.json`
must contain these flags or composer will refuse to install it:
```json
"minimum-stability": "beta",
"prefer-stable": true
```
Add them now if not already present. **These must be removed in Block 6 once
`sebastianlenz/linkfield` has been removed from the project.** Note their presence
in your Block 2 report so Block 6 includes the removal step.

### 2.7 MySQL charset vars (MySQL only, skip for PostgreSQL)
If `CRAFT_DB_CHARSET` is not already set in `.env`, add:
```
CRAFT_DB_CHARSET="utf8mb3"
CRAFT_DB_COLLATION="utf8mb3_general_ci"
```
If already set to something else, leave as-is and note the existing values.

---

**STOP. Report all file changes with diffs. Confirm no `composer update` or `php craft up` has been run yet. Wait for confirmation before Block 3.**

---

## BLOCK 3 — Craft 5 upgrade

### 3.1 Run composer update
```bash
composer update --no-interaction
```
Do not add `--with-all-dependencies` or package-specific flags. If LINKFIELD_PRESENT is "yes", `sebastianlenz/linkfield` and `craftcms/cms ^5.x` must be resolved together in this single pass — this is intentional. Confirm both were updated in the output.

### 3.2 Run the Craft database upgrade
```bash
php craft up
php craft project-config/apply
```

### 3.3 Install any newly added plugins
For each plugin newly added to `composer.json` during this upgrade, run:
```bash
php craft plugin/install <handle>
```
Installing an already-installed plugin is harmless.

### 3.4 MySQL charset conversion (MySQL only)
Remove `CRAFT_DB_CHARSET` and `CRAFT_DB_COLLATION` from `.env` (and from `config/db.php` if present). Then run:
```bash
php craft db/convert-charset
```

### 3.5 Verify Craft 5
```bash
php craft --version
```
Confirm output shows Craft 5.x. Stop if not.

---

**STOP. Report Craft version, all command outputs, current state of `.env` and `composer.json`. Wait for confirmation before Block 4.**

---

## BLOCK 4 — Linkfield data migration

**Skip this block entirely if LINKFIELD_PRESENT was recorded as "no" in Block 1. Proceed directly to Block 5.**

### 4.1 Dry-run
```bash
php craft my-module/migrate-linkfield/run --dry-run
```
Report full output and row counts per field.
Cross-reference fields found against the Block 1 inventory (step 1.7).
Flag any discrepancies: fields in the inventory missing from dry-run output, or
unexpected fields appearing.
Note: `tel` link type will be remapped to `phone` automatically.

---

**STOP. Report dry-run output in full. Wait for explicit confirmation before
running the live migration.**

---

### 4.3 Live migration
```bash
echo "yes" | php craft my-module/migrate-linkfield/run
```
The command prompts "Have you taken a database backup? [yes/no]" and defaults to "no",
so pipe `yes` to pass it non-interactively.

Report full output including the summary table (field | rows migrated | rows skipped | status).
Stop if any field reports ERROR status. Report any skipped rows and reason given.

---

**STOP. Report migration output. Do not proceed to Block 5 until the user confirms
they have manually verified new `*_v2` fields are populated correctly in the Craft CP
on at least 3-5 entries. Wait for confirmation.**

---

## BLOCK 5 — Template updates

Do not proceed if Block 4 was not confirmed complete with CP data verified.

**Before starting this block, read `references/template-migration.md` from this
skill's directory.** It contains the full API mapping table, Twig macro definitions,
null safety patterns, Super Table `.one()` guidance, and the template editing approach.

### 5.1 Update all templates from Block 1 step 1.8
Work through every file flagged in the audit using the Python approach from the
template migration reference. Apply all API substitutions, handle renames, null
guards, and Super Table `.one()` fixes. Replace `craft.matrixBlocks()` with
`craft.entries()`.

Do not refactor, reformat, or change anything beyond what the migration requires.
Minimal diff only.

### 5.2 Report all changes
List every file modified with a summary of changes. Show diffs for non-trivial files.

---

**STOP. Report all template changes. Wait for confirmation before Block 6.**

---

## BLOCK 6 — Cleanup and finalisation

### 6.1 Remove minimum-stability flags (linkfield projects only)
**Skip if LINKFIELD_PRESENT is "no".**

Remove `"minimum-stability": "beta"` and `"prefer-stable": true` from `composer.json`, then:
```bash
composer update --lock --no-interaction
```

### 6.2 CKEditor Redactor conversion (if applicable)
If the project uses Redactor fields, run:
```bash
php craft ckeditor/convert/redactor
```
Skip if no Redactor fields exist.

### 6.3 Linkfield cleanup and removal (linkfield projects only)
**Skip if LINKFIELD_PRESENT is "no".**
```bash
php craft my-module/migrate-linkfield/run --cleanup
composer remove sebastianlenz/linkfield --no-interaction
```

### 6.4 Apply project config
```bash
php craft project-config/apply
```

### 6.5 Run fields/auto-merge
```bash
php craft fields/auto-merge
```
Present each merge batch to the user; do not accept automatically. If any merges are accepted, remind the user to commit the generated migration files and run `php craft up` in all other environments before deploying.

### 6.6 Final report
Produce a structured summary covering:

- Craft version now running
- Plugins removed
- Fields migrated (old handle to new handle, row count per field)
- Templates updated (list of files changed)
- Any items requiring manual follow-up:
  - Template extension collisions found in Block 1
  - Any `columnSuffix` fields identified in Block 1
  - Super Table single-row access patterns that may need `.one()` added
  - Any `user` link type rows that were dropped (no native equivalent)
- Going Live reminder:
  For each remote environment, add MySQL charset vars to `.env`, deploy,
  run `php craft up`, remove charset vars, run `php craft db/convert-charset`.

---

**STOP. Present the final report. This is the end of the main upgrade process.
Await any follow-up instructions.**

---

## BLOCK 7 — Super Table to native Matrix migration (optional)

This block is a separate post-upgrade task. Read `references/supertable-migration.md`
from this skill's directory for the full instructions before starting.
