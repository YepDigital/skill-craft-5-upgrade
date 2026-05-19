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
Ask the user to provide:
- The current Craft CMS version (e.g. "4.12.2")
- The PHP version in use (e.g. "8.2.1")

Record both. Flag PHP below 8.2 as a blocker.

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

### P1.7 / P1.7a / P1.8 Audit script
Run from the project root:
```bash
bash ~/.claude/skills/craft-5-preflight/scripts/audit.sh
```

This covers three areas in one pass:
- **P1.7** — Linkfield field inventory (handle, name, enabled types, columnSuffix)
- **P1.7a** — Super Table duplicate field handles
- **P1.8** — Deprecated API calls and `.with([` calls in templates

Read the output and record all findings. Do not grep files manually unless the
script fails to run.

**After running — P1.7a note:**
List every duplicate Super Table sub-field handle found. These are remediated
in Block P2.

**Data loss risk from duplicate handles + linkfield data:**
`getAllFields()` surfaces only one field instance per handle. If two Super Table
block types share a handle and both carry linkfield data, only one field's data
will be migrated in `craft-5-linkfield`. Flag this explicitly.
Craft-4-side remediation (Block P2) eliminates this risk entirely.

**After running — columnSuffix note:**
List any linkfield fields with a `columnSuffix` value. Record these in the
state file for explicit verification in `craft-5-linkfield` Block L1.

**After running — P1.8 note:**
Cross-reference `.with([` matches against linkfield handles from P1.7.
Any `.with()` call on a migrated handle must be removed in `craft-5-linkfield`
Block L3.

### P1.9 Template extension collisions
Search `templates/` for directories containing both a `.twig` and `.html` file
with the same base name. List any found.

### P1.10 `web/index.php` and `craft` executable
Check for any customisations beyond standard Craft boilerplate.
Note bootstrap constants or custom logic.

### P1.11 Temp Uploads Location
Check `config/general.php` or project config for a temp uploads path.
Record it.

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
Ask the user to confirm a full database backup has been taken and all changes
are committed to version control. Do not proceed without both confirmed.

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

After the user approves proposals, for each rename:

1. Edit the relevant YAML file(s) in `config/project/` to change the
   `handle:` value.
2. Search `templates/` for every reference to the old handle within the
   context of the relevant Super Table loop (use the surrounding template
   structure to scope the search). Update all references.
3. Run: `php craft project-config/apply`
4. Ask the user to confirm the Craft 4 site still loads correctly in browser.

Process one rename at a time. Stop and report diffs between each rename.
Record each in the state file:
```
HANDLE_REMEDIATIONS: <oldHandle> (blockType: <type>) → <newHandle>
```

### P2.4 Commit
```bash
git add -p
git commit -m "refactor: rename duplicate Super Table handles before Craft 5 upgrade"
```
Confirm `git status` is clean before proceeding.

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

## Linkfield inventory
<!-- One row per linkfield field. Empty section if LINKFIELD_PRESENT=no. -->
| handle | name | enabled types | columnSuffix | rows (approx) |
|--------|------|---------------|--------------|---------------|
| ...    | ...  | ...           | none / <val> | ...           |

## Handle remediations (renamed on Craft 4)
<!-- Empty table if P1.7a found no duplicates. -->
| old handle | Super Table block type | new handle |
|------------|------------------------|------------|
| ...        | ...                    | ...        |

## Template audit
<!-- Files to patch in craft-5-linkfield Block L3. -->
DEPRECATED_API_FILES:
  - <file path>

WITH_CALL_FILES:
  - <file path>

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
