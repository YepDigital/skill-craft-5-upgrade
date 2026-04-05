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

If MySQL, test the connection now and record the working form as **MYSQL_CMD**:
```bash
mysql -u root -e "SELECT 1"
```
If that fails with a socket error, retry with:
```bash
mysql -h 127.0.0.1 -u root -e "SELECT 1"
```
Record whichever works (e.g. `MYSQL_CMD: mysql -h 127.0.0.1 -u root`). Flag a
failed connection as a blocker. This is used for diagnostic queries in Blocks 4 and 5.

### 1.3 Plugin inventory
Read `composer.json`. For every Craft plugin under `require`, check Packagist for a
Craft 5-compatible release. Flag any missing Craft 5 release as a blocker.

Skip `php`, `ext-*`, and general PHP libraries (e.g. `nesbot/carbon`,
`guzzlehttp/guzzle`) — these are not Craft plugins and need no Craft 5
compatibility check.

If Packagist is unreachable or returns errors, ask the user to confirm Craft 5
compatibility for each plugin manually before proceeding.

Exception: `sebastianlenz/linkfield` has no official Craft 5 release but
`3.0.0-beta` requires `craftcms/cms: ^5.1.3` and is the intended upgrade path.
Do not flag it as a blocker if it is present.

### 1.4 Linkfield presence check
Check whether `sebastianlenz/linkfield` appears in `composer.json` under `require`.
Record the result as **LINKFIELD_PRESENT: yes** or **LINKFIELD_PRESENT: no**.
This determines whether Blocks 2.3, 2.5, 2.6, and Block 4 are relevant.
Include this prominently in the Block 1 report.

### 1.5 `vlucas/phpdotenv`
Check the constraint in `composer.json`. Flag if below `^5.6.0`.

### 1.6 Queue status
```bash
php craft queue/info
```
Flag any pending or reserved jobs as a blocker.

### 1.7 / 1.7a / 1.8 Audit script
Run the audit script from the project root:
```bash
bash ~/.claude/skills/craft-5-upgrade/scripts/audit.sh
```
This covers all three steps in one pass:
- **1.7** — linkfield field inventory (handle, name, enabled types, columnSuffix)
- **1.7a** — Super Table duplicate field handles
- **1.8** — deprecated API calls and `.with([` calls in templates

Read the output and record findings. Do not grep files manually unless the script
fails to run.

**After running, note for step 1.7a:**
Duplicate handles will be globally deduplicated after upgrade (handle → handle2,
handle3...). The exact mapping is non-deterministic from config alone — confirm via
the CP or a DB query after the upgrade.

**Data loss risk — duplicated handle with linkfield data:** `getAllFields()` surfaces
only one field instance per handle, so if two Super Table block types share a handle
and both carry linkfield data, only one field's data will be migrated. Flag this and
warn the user that affected entries need manual re-entry; there is no automated fix.

**After running, note for step 1.8:**
Cross-reference `.with([` matches against the linkfield handles from 1.7. Any `.with()` call
on a migrated handle must be removed — see `references/template-migration.md` for why.

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

- If not, follow `references/module-setup.md` from this skill's directory to copy
  the module files, register the module in `config/app.php`, and confirm the
  PSR-4 autoload entry in `composer.json`. Do not run `composer update` yet.

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
Note: `php craft --version` is not a valid Craft CLI command and will exit non-zero.
Use `composer show craftcms/cms | grep -E "^versions"` to confirm the installed version (step 3.5).

### 3.3 Install any newly added plugins
`php craft up` (step 3.2) typically installs all plugins automatically. Run
`php craft plugin/list` to confirm every required plugin shows as installed.

If any plugin is missing, install it:
```bash
php craft plugin/install <handle>
```

Note: plugin handles often differ from package names — always derive the handle
from `php craft plugin/list` rather than guessing.

### 3.4 MySQL charset conversion (MySQL only)
Remove `CRAFT_DB_CHARSET` and `CRAFT_DB_COLLATION` from `.env` (and from `config/db.php` if present). Then run:
```bash
php craft db/convert-charset
```

### 3.5 Verify Craft 5
```bash
composer show craftcms/cms | grep -E "^versions"
```
Confirm output shows a 5.x version. Stop if not.

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

**Unmigrable link types — flag before proceeding:**
The following link types have no native Craft 5 equivalent and will not be migrated:

| Typed Link Field type | Outcome |
|---|---|
| `tel` | Skipped with `[ERROR] Invalid link type: phone`. Re-enter manually as a URL link using a `tel:+...` prefix. |
| `asset` | Skipped — migration script does not implement asset mapping. Re-enter manually in the CP; native Craft 5 Link fields do support asset links. |
| `user` | Skipped as unmappable. No native equivalent. |

Count rows of each type per field in the dry-run output. Include these counts in
the Block 4 report and add the affected fields to the manual follow-up list in
Block 6.6. Do not proceed to the live migration until the user acknowledges the
data loss for these rows.

---

**STOP. Report dry-run output in full. Wait for explicit confirmation before
running the live migration.**

---

### 4.2 Live migration
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

If LINKFIELD_PRESENT = "yes": do not proceed until Block 4 is confirmed complete with CP data verified.
If LINKFIELD_PRESENT = "no": Block 4 was skipped — proceed directly.

**If LINKFIELD_PRESENT = "yes": read `references/template-migration.md` from this
skill's directory before starting.** It contains the full API mapping table, Twig
macro definitions, null safety patterns, and the template editing approach.

If LINKFIELD_PRESENT = "no": skip the DB query, handle mapping, and patcher script
in step 5.1 below. Apply only the general fixes from Block 1 step 1.8 (e.g.
`craft.matrixBlocks()` → `craft.entries()`). Then proceed to step 5.2.

### 5.1 Update all templates from Block 1 step 1.8

**Before building the handle mapping, verify each `_v2` field's name against its
template context.** Deduplication order is non-deterministic — the field name is
the only reliable indicator of which handle belongs to which context.

**MySQL only (skip for PostgreSQL):** Run using **MYSQL_CMD** recorded in Block 1.2:

```bash
MYSQL_CMD <db_name> -e "SELECT handle, name FROM craft_fields WHERE handle LIKE '%_v2' ORDER BY handle;"
```

**PostgreSQL:** Skip this query. Derive the handle mapping from the Block 1 audit
output (step 1.7) and confirm field names via the Craft CP field settings.

Cross-reference each handle's name against the template loops from step 1.8.
For example, if two loops both used `navLink` originally:
- `navLink_v2` → "Utility Navigation - Link" → use in utility nav loops
- `navLink3_v2` → "Main Navigation - Link" → use in main nav loops

Record the confirmed mapping before proceeding. Assigning the wrong handle to the
wrong loop will silently produce empty URLs with no error.

Build a handle mapping JSON — every linkfield handle mapped to its confirmed `_v2`
counterpart:
```json
{"primaryLink": "primaryLink_v2", "navLink": "navLink_v2"}
```

Run the template patcher in dry-run mode first, review the diffs, then apply:
```bash
python3 ~/.claude/skills/craft-5-upgrade/scripts/patch-templates.py \
  --handles '{"primaryLink":"primaryLink_v2","navLink":"navLink_v2"}' \
  --files templates/_components/buttons/single.twig templates/_partials/ctas.twig \
  --dry-run
python3 ~/.claude/skills/craft-5-upgrade/scripts/patch-templates.py \
  --handles '{"primaryLink":"primaryLink_v2","navLink":"navLink_v2"}' \
  --files templates/_components/buttons/single.twig templates/_partials/ctas.twig
```

The script applies API method substitutions (`.getUrl()` → `.url` etc.), handle
renames (field accesses only, not local variable names), and removes `.with()`
calls for migrated handles.

**Apply manually after the script:**
- Null guards on all link field accesses (see `references/template-migration.md`)
- `field|length` → `field.url|length` checks (patcher does not handle these)
- Templates with multiple loops needing different per-loop handles (script cannot
  distinguish which loop uses which deduplicated handle — split and patch manually)
- Super Table `.one()` patterns
- `craft.matrixBlocks()` → `craft.entries()` replacements

Do not refactor, reformat, or change anything beyond what the migration requires. Minimal diff only.

### 5.2 Report all changes
List every file modified with a summary of changes; show diffs for non-trivial files.

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
echo "yes" | php craft my-module/migrate-linkfield/run --cleanup
composer remove sebastianlenz/linkfield --no-interaction
```
If `run --cleanup` reports "No Typed Link Fields found", the 3.0.0-beta cannot
instantiate the old field types in this environment. Use the direct fallback instead:
```bash
echo "yes" | php craft my-module/migrate-linkfield/run-direct --cleanup
composer remove sebastianlenz/linkfield --no-interaction
```

After removal, rebuild project config from the current DB state. **This step is
critical** — without it, the committed YAML files will not include the `_v2` fields
in field layouts, and production's `project-config/apply` will not add them:
```bash
php craft project-config/rebuild
```

### 6.4 Apply project config
```bash
php craft project-config/apply
```

### 6.5 Run fields/auto-merge
`php craft fields/auto-merge` requires an interactive terminal and cannot be run
by Claude — it exits with code 1 non-interactively. Ask the user to run it
themselves:

```bash
php craft fields/auto-merge
```

Instruct them to review each proposed merge batch carefully and only accept where
the fields are genuinely the same type and config. If any merges are accepted,
remind the user to commit the generated migration files and run `php craft up`
in all other environments before deploying.

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
  - Any `user` link type rows that were skipped (no native equivalent)
  - Any `tel` link type rows that were skipped — re-enter as URL links using `tel:+...` prefix
  - Any `asset` link type rows that were skipped (no native equivalent)
  - Any fields where duplicate Super Table handles caused the second field's data to be unmigratable (manual re-entry required)
- Going Live: proceed to Block 7 to generate a production deployment guide.

---

**STOP. Present the final report. Ask the user if they are ready to generate
the production deployment guide (Block 7) before proceeding.**

---

## BLOCK 7 — Production Deployment Guide

This block generates a project-specific `DEPLOY.md` in the project root.
Do not attempt to deploy; only generate the guide.

### 7.1 Confirm readiness

Confirm with the user:
- The local site is fully verified (loads without errors, all upgraded content
  renders correctly in browser).
- All code is committed to git, including `modules/`, `config/project/`, and
  any template changes from Block 5.

### 7.2 Ask for deployment details

Ask: **How is code deployed to production?** (examples: `git push` to remote + SSH,
Laravel Forge, Ploi, Deployer, rsync, FTP, hosting panel). If unsure, default to
generic SSH steps.

If LINKFIELD_PRESENT = "yes": use the DB name and MYSQL_CMD from Block 1.2 when
filling in the DB export command — no need to ask the user again.

### 7.3 Generate DEPLOY.md

- If LINKFIELD_PRESENT = "no": read `references/deploy-guide-a.md` from this skill's directory.
- If LINKFIELD_PRESENT = "yes": read `references/deploy-guide-b.md` from this skill's directory.

Fill in all placeholders from the session's recorded values, then write the
result to `DEPLOY.md` in the project root.

### 7.4 Checkpoint

Show the generated DEPLOY.md to the user. Ask them to confirm the steps match their
hosting environment and apply any corrections before finalising.

**STOP. Present DEPLOY.md for review. Await confirmation or corrections.**

---

## BLOCK 8 — Super Table to native Matrix migration (optional)

This block is a separate post-upgrade task. Read `references/supertable-migration.md`
from this skill's directory for the full instructions before starting.
