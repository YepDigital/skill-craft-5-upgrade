---
name: craft-5-preflight
description: "Use this skill to audit and prepare a Craft CMS 4 project for upgrade to Craft 5. Run this BEFORE craft-5-upgrade. Triggers include: 'prepare for Craft 5', 'Craft 5 preflight', 'audit Craft 4 site for Craft 5', 'check Craft 5 compatibility', 'Craft 5 readiness check', 'pre-upgrade audit', 'what do I need to do before upgrading to Craft 5', 'is my site ready for Craft 5'. Do NOT use for the actual upgrade — that is craft-5-upgrade."
disable-model-invocation: true
---

# Craft 5 Preflight — Audit and Craft 4 Preparation

## Overview

Read-only audit followed by Craft-4-side remediation of duplicate field handles.
Outputs a `.craft5-upgrade.md` state file in the target project root.
The site remains fully working on Craft 4 after this skill completes.

Subsequent skills in this suite:
- `craft-5-upgrade` — runs the actual Craft 5 upgrade (requires preflight-done)
- `craft-5-linkfield` — migrates linkfield data and patches templates (requires upgrade-done)
- `craft-5-supertable` — optional Super Table → native Matrix migration

**Work through one block at a time. Stop at the end of each block, report
findings, and wait for explicit confirmation before proceeding.**

---

## Global rules

- Block P1 is entirely read-only. No changes.
- Block P2 edits Craft 4 project config and templates only. Minimal diffs.
- If any command exits non-zero: stop, report full output, wait for instructions.
- Report all command output and all file edits with diffs.
- Minimal changes only. Do not refactor beyond stated scope.
- MySQL only. The suite does not support Postgres.

---

## BLOCK P1 — Audit (read-only)

### P1.1 Craft and PHP version
Record:
- The current Craft CMS version. Source it from `composer.lock` (search for
  `"name": "craftcms/cms"` and read the adjacent `version` field) or
  `composer show craftcms/cms`. **Do not use `php craft --version`** — that
  is not a valid Craft CLI command and exits with code 1.
- The PHP version in use (`php --version`).

Flag PHP below 8.2 as a blocker.

### P1.2 Database engine and connection
Check `.env` and `config/db.php` for `CRAFT_DB_DRIVER`. Confirm MySQL.
Record any existing `CRAFT_DB_CHARSET` and `CRAFT_DB_COLLATION` values.

Test the MySQL connection and record the working form as **MYSQL_CMD**:
```bash
mysql -u root -e "SELECT 1"
```
If that fails with a socket error, retry:
```bash
mysql -h 127.0.0.1 -u root -e "SELECT 1"
```
Record whichever works (e.g. `MYSQL_CMD: mysql -h 127.0.0.1 -u root`).
Also record the database name as **DB_NAME** (from `.env` or `config/db.php`).
Flag a failed connection as a blocker.

### P1.3 Plugin inventory
Read `composer.json`. For every Craft plugin under `require`, check Packagist
for a Craft 5-compatible release. Record the target version for each.
Flag any missing Craft 5 release as a blocker.

Skip `php`, `ext-*`, and general PHP libraries — not Craft plugins.

If Packagist is unreachable, ask the user to confirm Craft 5 compatibility for
each plugin manually before proceeding.

Exception: `sebastianlenz/linkfield` — `3.0.0-beta` declares
`craftcms/cms: ^5.1.3` compatibility and is the intended upgrade path.
Do not flag it as a blocker if present.

### P1.4 Linkfield presence check
Check whether `sebastianlenz/linkfield` appears in `composer.json` under
`require`. Record as **LINKFIELD_PRESENT: yes** or **LINKFIELD_PRESENT: no**.
Include this prominently in the P1 report.
This value drives many conditional steps in `craft-5-upgrade` and
`craft-5-linkfield`.

### P1.5 `vlucas/phpdotenv`
Check the constraint in `composer.json`. Flag if below `^5.6.0`.

### P1.6 Queue status
```bash
php craft queue/info
```
Flag any pending or reserved jobs as a blocker.

### P1.7 / P1.7a / P1.7b / P1.7c / P1.7d / P1.8 / P1.8b / P1.10b / P1.12 / P1.13 / P1.14 Audit script
Run from the project root, passing the `MYSQL_CMD` and `DB_NAME` recorded in P1.2:
```bash
python3 ~/.claude/skills/craft-5-preflight/scripts/audit.py \
    --mysql-cmd "$MYSQL_CMD" --db-name "$DB_NAME"
```

**Always pass the DB args.** With them, the `fields` table is the **authoritative**
source for the field inventory and duplicate-handle checks (immune to project-config
structural drift across Craft/plugin versions), and the audit cross-checks it
against project config and flags any discrepancy. The bare no-arg form still runs
offline (config-only) as a fallback — but its counts are not authoritative; use it
only when the DB is unreachable.

This covers all areas in one pass:
- **P1.7** — Linkfield field inventory (handle, name, enabled types, columnSuffix). Includes a CONFIG/DB cross-check when DB args are supplied.
- **P1.7a** — Super Table duplicate field handles (reads both inline `blockTypes:` and `config/project/superTableBlockTypes/`)
- **P1.7b** — Duplicate linkfield handles across non-ST contexts (top-level, matrix)
- **P1.7c** — `craft\fields\Url` fields that Craft 5 will auto-promote to `craft\fields\Link`
- **P1.7d** — **Global** duplicate handles across ALL fields and contexts (the superset of P1.7a/P1.7b — what Craft 5 actually deduplicates on)
- **P1.8** — Deprecated API calls and `.with([` calls in templates
- **P1.8b** — All template files referencing any linkfield handle (for the L3 patcher file list)
- **P1.10b** — Non-standard customisations in `bootstrap.php` / `web/index.php`
- **P1.12** — Vendor plugins with `afterSave*` event hooks, classified into field/content plugins (keep enabled), deploy/notification plugins (disable), and unconfirmed (review)
- **P1.13** — `composer.json` `post-update-cmd` running `@craft-update`
- **P1.14** — `craftcms/redactor` package + `craft\redactor\Field` field inventory (CKEditor conversion candidates)

Read the output and record all findings. The script prints a state file summary at the end — use it directly in Block P3.

**After running — P1.7a note:**
List every duplicate Super Table sub-field handle found. These are remediated
in Block P2.

The config-parser path reads inline `blockTypes:` keys **and** the external
`config/project/superTableBlockTypes/` **and** `config/project/matrixBlockTypes/`
directories, and recurses into nested block types (e.g. a Super Table field
inside a Matrix block) so sub-fields are resolved at any depth. When DB args are
supplied, the `fields` table supersedes all of this and is authoritative. The two
guard states are distinct:

- **"No Super Table fields found"** — no YAML in `config/project/fields/` has
  `type: verbb\supertable\fields\SuperTableField`. ST is not installed or not
  configured. Fully authoritative skip.
- **"Super Table fields found but no sub-fields collected"** — ST fields exist
  but block-type scanning yielded nothing. This is an unexpected structure
  warning, not a clean skip. Investigate `config/project/superTableBlockTypes/`.

A "no duplicates found" result after the scan runs is authoritative.

**Data loss risk from duplicate handles + linkfield data:**
`getAllFields()` in the `craft-5-linkfield` migrator surfaces only one field
instance per handle. If two Super Table block types share a handle and both
carry linkfield data, only one field's data will be migrated. This is a
migrator-layer risk (not a Craft core dedup). Craft-4-side remediation (Block P2)
eliminates this risk entirely.

**After running — P1.7b note:**
Duplicate linkfield handles across non-ST contexts (e.g. `linkTo` in a
top-level field AND in a Matrix block sub-field) also trigger the same
`getAllFields()` collision. These cannot be remediated by P2 (which targets
ST sub-fields only) — document them in `NON_ST_DUPLICATE_HANDLES` and warn
the user to verify the L2 `_v2` field count after migration.

**After running — P1.7d note (global duplicate handles):**
P1.7d is the **superset** of P1.7a and P1.7b — it groups every field across all
contexts, which is what Craft 5 actually deduplicates on. It splits results:

- **RISKY** — a linkfield shares the handle across contexts. Real
  `getAllFields()` data-loss risk; remediate in Block P2 (ST sub-fields) or
  record under `NON_ST_DUPLICATE_HANDLES` (top-level/matrix). Record all of these
  under `GLOBAL_DUPLICATE_HANDLES` in the state file.
- **Informational** — native-type duplicates only (e.g. `heading`×8 PlainText).
  Craft 5 auto-suffixes these (`handle` → `handle2`); content-safe, no
  pre-upgrade action required. Note them so post-upgrade renames are expected.

**After running — CONFIG/DB cross-check:**
When DB args were supplied, `FIELD_INVENTORY_SOURCE: db` and a
`P1.7 CONFIG/DB FIELD INVENTORY CROSS-CHECK` section appears. If it reports
`CONFIG/DB MISMATCH`, the DB figures are authoritative — the listed fields are
ones a config-only run would under-report. An empty cross-check confirms the
inventory is complete. If you see `FIELD_INVENTORY_SOURCE: config`, the DB was
not reachable; the counts are best-effort — fix the connection (P1.2) and re-run
before trusting any "none found".

**After running — P1.7c note:**
`URL_PROMOTION_CANDIDATES` lists every `craft\fields\Url` field in the project.
Craft 5's `php craft up` silently promotes these to `craft\fields\Link`
(URL-only variant). The runtime type changes from `string` to `LinkData`, which
breaks templates that use:

- `entry.x|length` — `|length` on the raw field (should become `entry.x.url|length`)
- `'foo' in entry.x` — `in` membership test (should become `'foo' in entry.x.url`)

Note: `{{ entry.x }}` still works because `LinkData.__toString()` returns the
URL string — but `|length` and `in` tests behave differently against an object.
Bare access is therefore not flagged as breaking.

These fields are **not** linkfields and do not go through the `craft-5-linkfield`
migration. Fixes must be applied manually in `craft-5-linkfield` Block L3.3,
guided by the `URL_PROMOTION_CANDIDATES` and `## URL fields actually promoted`
sections that L2.3 writes into the state file.

**After running — columnSuffix note:**
List any linkfield fields with a `columnSuffix` value. Record these in the
state file for explicit verification in `craft-5-linkfield` Block L1.

**After running — P1.8b note:**
`HANDLE_REFERENCE_FILES` contains ALL template files that reference any
linkfield handle. Use this list (not just `DEPRECATED_API_FILES`) as the
`--files` argument to `patch-templates.py` in `craft-5-linkfield` Block L3.

**After running — P1.12 note:**
The audit classifies every plugin that registers an `afterSave*` event hook into
three buckets. **The `afterSave*` heuristic alone cannot tell field plugins from
deploy plugins**, so the audit also scans each package for field-type / element-type
registration (keep enabled) and for env-specific deploy signals (safe to disable):

- **`PLUGINS_TO_DISABLE_FOR_UPGRADE`** — deploy/notification plugins only (cache
  busters, webhook/Slack notifiers, external-service reindexers). Their `afterSave*`
  hooks use env-specific paths or external HTTP and genuinely fail in dev during
  `fix-field-layout-uids`. Disable these before U1.2; re-enable locally at the end
  of the upgrade (U3.3 / L4.6) and in production deploy notes.
- **`FIELD_PLUGINS_KEEP_ENABLED`** — field/content plugins (Hyper, Super Table,
  CKEditor, Redactor, Formie, linkfield, anything that registers a field/block/
  element type). **NEVER disable these for the upgrade.** They ship content
  migrations that run during `php craft up` against the still-present Craft 4
  content tables. Disabling one serializes its fields as `craft\fields\MissingField`
  into project config and skips its migration — **irreversible** once Craft drops
  the Craft 4 source tables (`matrixcontent_*`, `stc_*`). Leave them enabled
  throughout `fix-field-layout-uids`, `composer update`, and `php craft up`.
- **`PLUGINS_FOR_MANUAL_REVIEW`** — `afterSave*` plugins the audit could not confirm
  as pure deploy/notification hooks. **Default to leaving these enabled.** Inspect
  each handler: only move a plugin into `PLUGINS_TO_DISABLE_FOR_UPGRADE` if its
  `afterSave*` references env-specific filesystem paths, external HTTP endpoints, or
  deploy tooling. If it touches its own field/content data, leave it enabled.

The audit resolves vendor libraries to their host plugin's handle via `composer.json`
under `vendor/`, so handles can be passed directly to `php craft plugin/disable`.

**After running — P1.14 note:**
`REDACTOR_PACKAGE_PRESENT` and `REDACTOR_FIELDS` flag use of the abandoned
`craftcms/redactor` plugin. Replacement is `craftcms/ckeditor`, which supports
**both Craft 4 and Craft 5** and ships a conversion command
(`php craft ckeditor/convert/redactor`).

**Recommended order — convert on Craft 4 before the Craft 5 upgrade:**
1. `composer require craftcms/ckeditor` (Craft 4 installs the 3.x line)
2. `php craft plugin/install ckeditor` (composer alone does not enable it — the convert command will not be available otherwise)
3. `php craft ckeditor/convert/redactor`
4. Visual-diff a sample of converted entries.
5. `composer remove craftcms/redactor`
6. Commit, then proceed with the Craft 5 upgrade as normal.

Isolating the Redactor→CKEditor migration from the Craft 4→5 upgrade makes
either failure easier to bisect. The existing post-upgrade conversion steps
(upgrade U3.3 / linkfield L4.4) remain as a fallback if the user prefers to
defer the swap; either path is valid.

**MUST surface to the user verbatim — but only when CKEditor is not already
in use.** When `REDACTOR_FIELDS` is non-empty AND `CKEDITOR_PACKAGE_PRESENT=no`,
reproduce the full six-step recommended order above (or the equivalent
`audit.py` P1.14 warning block) in your Block P1 findings report. Do not
collapse it to "Redactor detected" — the user needs the explicit steps and
the install-plugin caveat, otherwise the convert command will not exist when
they try to run it.

When `CKEDITOR_PACKAGE_PRESENT=yes`, skip the require/install/recommended-order
block — those steps are already done. Just report the remaining Redactor
fields and the short follow-up: `php craft ckeditor/convert/redactor`, then
`composer remove craftcms/redactor` once no Redactor fields remain.

### P1.9 Template extension collisions
Search `templates/` for directories containing both a `.twig` and `.html` file
with the same base name. List any found.

### P1.10 `web/index.php` and `craft` executable
Check for any customisations beyond standard Craft boilerplate.
Note bootstrap constants or custom logic.

### P1.11 Temp Uploads Location
Check `config/general.php` or project config for a temp uploads path.
Record it.

### P1 Heads-up — upgrade hygiene commands (informational, no action required)
The upgrade skill (`craft-5-upgrade` Block U1.2) runs three official pre-upgrade
hygiene steps before touching Composer: `project-config/rebuild`, then
`utils/fix-field-layout-uids`, then `project-config/apply`. `fix-field-layout-uids`
in particular addresses a known class of upgrade failures (field layout UID
mismatches). No action needed in preflight — noting here so the large YAML diff
it produces in U1.2 is not a surprise.

---

**STOP. Report all findings as a structured summary. Flag blockers clearly.
Wait for confirmation before Block P2.**

---

## BLOCK P2 — Duplicate-handle remediation (Craft 4 only)

**Skip this block entirely if P1.7a found no duplicate Super Table sub-field
handles. Proceed to Block P3.**

If duplicates were found: read `references/handle-remediation.md` in this
skill's directory before starting.

**Purpose:** rename each duplicate Sub Table sub-field handle to a unique,
intentional name while still on Craft 4. This eliminates the non-deterministic
post-upgrade deduplication (Craft 5 renames `handle` → `handle2`, `handle3`...)
entirely, making the `_v2` mapping in `craft-5-linkfield` strictly 1:1 and
deterministic — removing the main class of silent empty-URL failures.

### P2.1 Confirm backup and version control
Ask the user to confirm a full database backup has been taken (`php craft db/backup`
is the recommended native, config-aware option) and all changes are committed to
version control. Do not proceed without both confirmed.

### P2.2 Identify and propose renames

For each duplicated Sub Table sub-field handle (e.g. `navLink` appears in two
block types):

1. Identify which Super Table block type each instance belongs to, from the
   field `name` and context in `config/project/` YAML files.
2. Propose a unique intentional rename for each instance:
   - e.g. `navLink` (in "Utility Navigation" block) → `utilityNavLink`
   - e.g. `navLink` (in "Main Navigation" block) → `mainNavLink`
3. Present proposals and wait for user approval before making any changes.

### P2.3 Apply each rename

After the user approves proposals, apply one logical group at a time:

**One rename operation = all sub-fields within a single ST block type,
renamed together, with one `project-config/apply` between groups.**

For each group:

1. Edit the relevant YAML file(s) in `config/project/` to change the
   `handle:` value for every sub-field in that block type.
2. Search `templates/` for every reference to the old handles within the
   context of that block type's loop (use the surrounding template
   structure to scope the search). Update all references.
3. Run: `php craft project-config/apply`
4. Ask the user to confirm the Craft 4 site still loads correctly in browser.

Stop and report diffs after each group. Do not apply the next group until
confirmed. Record each rename in the state file:
```
HANDLE_REMEDIATIONS: <oldHandle> (blockType: <type>) → <newHandle>
```

### P2.4 Commit
```bash
git add -p
git commit -m "refactor: rename duplicate Super Table handles before Craft 5 upgrade"
```
Confirm `git status` is clean before proceeding.

### P2.5 Non-ST duplicate linkfield handles (if any)

**Skip this step if P1.7b found no non-ST duplicate linkfield handles.**

If `NON_ST_DUPLICATE_HANDLES` is non-empty: document each duplicate clearly
in the state file. Unlike ST sub-field handles, these cannot be renamed
on Craft 4 without risk (they may be shared across entry types / matrix blocks).

For each non-ST duplicate:
1. Record which contexts share the handle (top-level, matrix block type).
2. Inform the user that after migration the `_v2` field count may not be 1:1.
3. After `craft-5-linkfield` Block L2, verify that the actual `_v2` field
   count matches the source count — if not, map by field `name` manually.

---

**STOP. Report all handle renames with diffs. Confirm site loads on Craft 4.
Wait for confirmation before Block P3.**

---

## BLOCK P3 — Write state file

Write `.craft5-upgrade.md` to the target project root.

Instruct the user to add `.craft5-upgrade.md` to their `.gitignore` —
it contains `MYSQL_CMD` (a local value) and should not be committed.

```markdown
# Craft 5 Upgrade State
<!-- Generated by craft-5-preflight. Read by craft-5-upgrade and craft-5-linkfield. -->
<!-- Do not edit PHASE manually. -->

## Phase
PHASE: preflight-done

## Environment
CRAFT_FROM: <version>
PHP: <version>
LINKFIELD_PRESENT: yes|no
MYSQL_CMD: <e.g. "mysql -h 127.0.0.1 -u root">
DB_NAME: <database name>
DB_CHARSET_EXISTING: <existing CRAFT_DB_CHARSET value, or "(none)">
FIELD_INVENTORY_SOURCE: db|config
<!-- "db" = fields table, authoritative (DB args passed). "config" = offline -->
<!-- fallback, NOT authoritative — re-run with --mysql-cmd/--db-name. -->

## Linkfield inventory
<!-- One row per linkfield field. Empty section if LINKFIELD_PRESENT=no. -->
| handle | name | context | enabled types | columnSuffix |
|--------|------|---------|---------------|--------------|
| ...    | ...  | ...     | ...           | none / <val> |

## Handle remediations (renamed on Craft 4)
<!-- Empty table if P1.7a found no duplicates. -->
| old handle | Super Table block type | new handle |
|------------|------------------------|------------|
| ...        | ...                    | ...        |

## Non-ST duplicate linkfield handles
<!-- Empty if P1.7b found none. These cannot be renamed on Craft 4. -->
<!-- Verify _v2 field count matches source count in craft-5-linkfield Block L2. -->
NON_ST_DUPLICATE_HANDLES:
  - handle: <name>, contexts: [<top-level / matrix:BlockType, ...>]

## Global duplicate handles (P1.7d)
<!-- Superset of the two above. RISKY = a linkfield shares the handle (data-loss -->
<!-- risk; remediate in P2 / NON_ST_DUPLICATE_HANDLES). Informational = native -->
<!-- types Craft 5 auto-suffixes (content-safe). Empty if none. -->
GLOBAL_DUPLICATE_HANDLES:
  - handle: <name>  # RISKY (linkfield) — <contexts>
  - handle: <name>  # informational (native, content-safe)

## URL field promotion candidates
<!-- craft\fields\Url fields Craft 5 auto-promotes to craft\fields\Link on php craft up. -->
<!-- These are NOT linkfields. Fix breaking patterns manually in L3.3. -->
<!-- L2.3 (craft-5-linkfield) writes a "URL fields actually promoted" block from the DB. -->
URL_PROMOTION_CANDIDATES:
  - handle: <handle>
    name: '<field name>'
    file: <config/project/fields/uid.yaml>
    breaking_refs:
      - <templates/path.twig:line: [pattern-type] line content>

## Template audit
<!-- Use HANDLE_REFERENCE_FILES as the --files list for patch-templates.py in L3. -->
DEPRECATED_API_FILES:
  - <file path>

WITH_CALL_FILES:
  - <file path>

HANDLE_REFERENCE_FILES:
  - <file path>

## Bootstrap customisations
<!-- From P1.10b. Note anything that suppresses errors or changes PHP behaviour. -->
BOOTSTRAP_CUSTOMISATIONS:
  - <description or "(none)">

## Plugins to disable for upgrade
<!-- From P1.12: DEPLOY/NOTIFICATION plugins only — afterSave* hooks with -->
<!-- env-specific paths / external HTTP that fail in dev during U1.2. -->
<!-- The audit resolves vendor libraries to their host plugin handle -->
<!-- automatically. Disable before U1.2; re-enable in DEPLOY.md for production. -->
<!-- NEVER list field/content plugins here (see FIELD_PLUGINS_KEEP_ENABLED). -->
PLUGINS_TO_DISABLE_FOR_UPGRADE:
  - <plugin-handle>  # afterSave* registered in <package-name>

## Field/content plugins to KEEP ENABLED
<!-- From P1.12: field/content plugins (Hyper, Super Table, CKEditor, Redactor, -->
<!-- Formie, linkfield, etc.) that register afterSave* hooks. DO NOT disable -->
<!-- these for the upgrade — they run content migrations during `php craft up` -->
<!-- that require the plugin enabled and the Craft 4 source tables intact. -->
<!-- Disabling one is irreversible once those tables drop. -->
FIELD_PLUGINS_KEEP_ENABLED:
  - <plugin-handle>  # field/content plugin — <package-name>

## Plugins for manual review
<!-- From P1.12: afterSave* plugins not confirmed as deploy/notification hooks. -->
<!-- Default to LEAVING ENABLED. Only move to PLUGINS_TO_DISABLE_FOR_UPGRADE if -->
<!-- the handler uses env-specific paths, external HTTP, or deploy tooling. -->
PLUGINS_FOR_MANUAL_REVIEW:
  - <plugin-handle>  # review afterSave* handler — <package-name>

## Composer hook
COMPOSER_POST_UPDATE_HOOK: yes|no
<!-- If yes: U2.1 (composer update) automatically runs php craft up; U2.2 is a no-op. -->

## Composer audit overrides
<!-- Populated in craft-5-upgrade U1.5.5 after adding block-insecure: false. -->
COMPOSER_AUDIT_OVERRIDES: (none)

## Plugin targets (Craft 5 versions)
| package | Craft 5 target version |
|---------|------------------------|
| ...     | ...                    |

## Blockers
BLOCKERS: none

## Notes
<any additional audit notes>
```

Confirm the file is written and the `.gitignore` entry is added.

---

**STOP. Show the complete state file. Confirm no blockers remain.
Instruct the user to run `craft-5-upgrade` next.**

---
