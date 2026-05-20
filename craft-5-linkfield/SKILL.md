---
name: craft-5-linkfield
description: "Use this skill to migrate sebastianlenz/linkfield (Typed Link Field) data to the native Craft 5 Link field, and update templates after a Craft 5 upgrade. Requires craft-5-upgrade to have run first (look for .craft5-upgrade.md with PHASE: upgrade-done and LINKFIELD_PRESENT: yes). Triggers: 'migrate linkfield to Craft 5', 'linkfield migration', 'Typed Link Field migration', 'migrate link field data', 'update templates for Craft 5 link field', 'run linkfield migration', 'sebastianlenz linkfield migration'. Do NOT use if the project has no sebastianlenz/linkfield — check LINKFIELD_PRESENT in state file first."
disable-model-invocation: true
---

# Craft 5 Linkfield Migration

## Overview

Migrates `sebastianlenz/linkfield` (Typed Link Field) data to Craft 5's native
Link field, patches templates, and removes the old plugin.

**Requires:** `.craft5-upgrade.md` in the project root with
`PHASE: upgrade-done` and `LINKFIELD_PRESENT: yes`
(written by `craft-5-upgrade`).

**Work through one block at a time. Stop at the end of each block, report
findings, and wait for explicit confirmation before proceeding.**

---

## Global rules

- **First action:** read `.craft5-upgrade.md`. If absent, `PHASE` ≠
  `upgrade-done`, or `LINKFIELD_PRESENT` ≠ `yes`, stop and report:
  > "State file missing or prerequisites not met. Run craft-5-upgrade first
  > (with LINKFIELD_PRESENT=yes)."
- Never run destructive commands outside their designated block.
- If any command exits non-zero: stop, report full output, wait for
  instructions.
- Report all command output and all file edits with diffs.
- Minimal template changes only. Do not refactor beyond migration requirements.
- Never delete database content. `--cleanup` removes field definitions only.

**Rollback:** restore DB backup, `git checkout .`, `composer install`.

---

## BLOCK L1 — Data migration — dry-run

### L1.0 Read state file
Read `.craft5-upgrade.md`. Record:
- `MYSQL_CMD`, `DB_NAME`
- `LINKFIELD_INVENTORY` table (handles, columnSuffix, enabled types, row counts)
- `HANDLE_REMEDIATIONS` table (any handles renamed on Craft 4 in preflight)

Confirm `PHASE: upgrade-done` and `LINKFIELD_PRESENT: yes`.

### L1.1 Dry-run — primary path

**`run-direct` is the primary path.** It discovers old fields and target fields
via direct DB queries, bypassing plugin field instantiation entirely. This works
reliably with `sebastianlenz/linkfield 3.0.0-beta` in Craft 5 environments
where the beta cannot instantiate Craft 4-era field settings.

`run-direct` will auto-create any missing `_v2` native Link fields before
reporting, so the dry-run shows a complete picture:

```bash
php craft my-module/migrate-linkfield/run-direct --dry-run
```

**Fallback:** If `run-direct --dry-run` reports no fields at all (fields table
has no rows with type `lenz\linkfield\fields\LinkField`), try the standard path:
```bash
php craft my-module/migrate-linkfield/run --dry-run
```
If both report nothing, investigate: check whether the `lenz_linkfield` table
is empty, or whether fields have already been removed. Report and stop.

### L1.2 Verify dry-run output

Cross-reference the fields listed by the dry-run against the
`LINKFIELD_INVENTORY` in the state file.

**Every handle in the inventory must appear in the dry-run with a non-zero
row count.** Discrepancies:
- Handle in inventory but missing from dry-run → potential data-loss risk.
  Investigate before proceeding.
- Handle in dry-run not in inventory → unexpected but not blocking; note it.

**columnSuffix fields — explicit check:**
If any field in the inventory has a `columnSuffix` value, confirm it appears
in the dry-run with the expected row count. The `lenz_linkfield` table stores
rows by `fieldId` regardless of columnSuffix, so `run-direct` should query them
correctly. If a suffixed field shows zero rows unexpectedly, flag as requiring
manual investigation before proceeding.

### L1.3 Unmigrable link types

The following Typed Link Field types are skipped by the migrator (`run-direct`
and `run`):

| Typed Link Field type | Outcome |
|---|---|
| `tel` | Skipped. Re-enter manually as a URL link using a `tel:+...` prefix. |
| `user` | Skipped. No native Craft 5 equivalent. |

**`asset` rows are fully migrated by `run-direct`.** The asset element ID is
stored in `linkedId` and written as `{"type": "asset", "value": "{asset:ID@1:url}"}`.
Do not flag asset rows as a data loss risk.

Count rows of each **skipped** type per field in the dry-run output. Include
these counts in the L1 report and record them in the manual follow-up list for
Block L5.

**Do not proceed to the live migration until the user acknowledges the data
loss for the skipped rows.**

---

**STOP. Report dry-run output in full. Wait for explicit confirmation before
running the live migration.**

---

## BLOCK L2 — Data migration — live

### L2.1 Live migration

**Primary path (`run-direct`):**
```bash
echo "yes" | php craft my-module/migrate-linkfield/run-direct
```

**Fallback:** if the dry-run in L1 required `run` instead:
```bash
echo "yes" | php craft my-module/migrate-linkfield/run
```

`run-direct` is safe to re-run: if a `_v2` field already has a value for an
element, the save overwrites it (idempotent per element).

Report the full output including the summary table
(field | rows migrated | rows skipped | status).
Stop if any field reports ERROR status. Report any skipped rows and their reason.

### L2.2 Handle mapping confirmation

Because duplicate handles were remediated on Craft 4 in `craft-5-preflight`
Block P2, the `_v2` mapping should be strictly 1:1.

Confirm via:
```bash
<MYSQL_CMD> <DB_NAME> -e "SELECT handle, name FROM craft_fields WHERE handle LIKE '%_v2' ORDER BY handle;"
```
(Substitute `MYSQL_CMD` and `DB_NAME` from the state file.)

Each `_v2` field should correspond unambiguously to one entry in the inventory.
If any `_v2` handle is still ambiguous (e.g. `handle2_v2`, `handle3_v2` from
post-upgrade dedup), cross-reference by field `name` to determine the correct
template mapping, and record the resolved mapping in the state file before
proceeding to templates.

If the `NON_ST_DUPLICATE_HANDLES` list in the state file is non-empty: verify
that the `_v2` field count matches the source field count. If it doesn't,
map by field `name` before proceeding.

### L2.2b Verify migrated data by layout element UID

`run-direct` prints layout element UIDs for each `_v2` field at the end of its
output. `elements_sites.content` is keyed by **field layout element UID**, not
field UID — direct queries against field UIDs will return 0 rows.

Use the printed UIDs to spot-check migrated content:
```sql
SELECT content->>'$."<element_uid>"' AS link_value
FROM craft_elements_sites
WHERE content->>'$."<element_uid>"' IS NOT NULL
LIMIT 5;
```

If `run-direct` did not print UIDs (older run), use this query to build the map:
```sql
SELECT f.handle, je.element_uid
FROM craft_fields f
CROSS JOIN craft_fieldlayouts fl
JOIN JSON_TABLE(fl.config, '$.tabs[*].elements[*]' COLUMNS (
  element_uid VARCHAR(36) PATH '$.uid',
  field_uid   VARCHAR(36) PATH '$.fieldUid'
)) AS je ON je.field_uid = f.uid
WHERE f.handle LIKE '%_v2';
```

---

**STOP. The frontend is broken between L2 and L3** — templates that access
migrated handles via the old Typed Link Field API throw
`BadMethodCallException: Method ElementCollection::getType does not exist`
on every page that includes those partials. The Craft CP works normally.
Do not share frontend previews of the site during this window.

**Hard stop — CP verification required.** Open the Craft CP and check at
least 3 entries using each migrated field. For every entry, confirm:
1. The link URL is present and correct.
2. If the source had a label (`customText`), the label field is populated.
3. The link type (URL / entry / asset) is correct.

**Type "verified" to continue to Block L3.** Do not proceed on partial checks.

---

## BLOCK L3 — Template updates

Read `references/template-migration.md` in this skill's directory before
starting.

### L3.1 Build handle map

From the state file's LINKFIELD_INVENTORY and the L2.2 query result, build a
JSON handle map — every old handle to its `_v2` counterpart:
```json
{"primaryLink": "primaryLink_v2", "navLink": "navLink_v2"}
```

After Craft-4-side remediation there should be no ambiguous mappings.
If any remain (see L2.2), resolve them first.

### L3.2 Patch templates — automated

Run the patcher in dry-run mode first, review the diffs, then apply:
```bash
python3 ~/.claude/skills/craft-5-linkfield/scripts/patch-templates.py \
  --handles '{"primaryLink":"primaryLink_v2","navLink":"navLink_v2"}' \
  --files <DEPRECATED_API_FILES and WITH_CALL_FILES from state file> \
  --dry-run

python3 ~/.claude/skills/craft-5-linkfield/scripts/patch-templates.py \
  --handles '{"primaryLink":"primaryLink_v2","navLink":"navLink_v2"}' \
  --files <same files>
```

The script applies:
- API method substitutions (`.getUrl()` → `.url`, `.getCustomText()` → `.label`,
  `.getTarget()` → `.target`, `.getType` → `.type`, `.getElement()` → `.element`)
- Handle renames (field accesses only — does not rename local Twig variables)
- `.with()` removal for migrated handles (prevents ElementCollection error)

### L3.3 Manual template fixes

After the patcher, apply manually (the patcher cannot handle these):

- **Null guards** on all link field accesses — see `references/template-migration.md`
  Null safety section. The native Link field returns `null` when empty; the old
  plugin returned an empty object. Every access needs a null guard.
- **`field|length`** → `field.url|length` (patcher does not handle)
- **`craft.matrixBlocks()`** → `craft.entries()` replacements
- **Super Table `.one()` patterns** — in Craft 5, Super Table fields return an
  EntryQuery; call `.one()` before accessing sub-fields
- Templates with multiple loops needing different per-loop handles (after
  Craft-4 remediation this should be rare; if it occurs, use the Python split
  approach in `references/template-migration.md`)

Minimal diff only. Do not refactor, reformat, or change anything beyond what
the migration requires.

### L3.4 Report all template changes
List every file modified with a summary of changes; show diffs for non-trivial
files.

### L3.5 Post-patch bare-reference sweep
After patching, run the patcher in `--verify` mode to confirm no old handles
remain in templates:
```bash
python3 ~/.claude/skills/craft-5-linkfield/scripts/patch-templates.py \
  --handles '{"primaryLink":"primaryLink_v2",...}' \
  --files <all HANDLE_REFERENCE_FILES from state file> \
  --verify
```

If `--verify` exits non-zero: the output lists files still containing bare
old-handle references. Re-run the patcher on those files, then sweep again.
**Do not proceed to L4 until the sweep is clean.**

This step catches files that were in `HANDLE_REFERENCE_FILES` but absent from
`DEPRECATED_API_FILES` (passed arguments to includes rather than direct method
calls) — these would otherwise silently call methods that no longer exist.

---

**STOP. Report all template changes and verify output. Wait for confirmation before Block L4.**

---

## BLOCK L4 — Cleanup and finalisation

**Steps run in this order:** L4.1 (cleanup + remove plugin) → L4.2 (apply) →
L4.3 (remove stability flags + lock) → L4.4 (CKEditor) → L4.5 (auto-merge).

This order matters: removing stability flags before removing the beta plugin
(`sebastianlenz/linkfield: ^3.0.0-beta`) causes `composer update --lock` to
fail because the constraint can no longer resolve without beta stability.

### L4.1 Linkfield cleanup and removal

**Primary path (`run-direct`):**
```bash
echo "yes" | php craft my-module/migrate-linkfield/run-direct --cleanup
composer remove sebastianlenz/linkfield --no-interaction
```

If `run-direct --cleanup` reports errors or fails to find old fields, try the
fallback:
```bash
echo "yes" | php craft my-module/migrate-linkfield/run --cleanup
composer remove sebastianlenz/linkfield --no-interaction
```

After removal, rebuild project config from the current DB state.
**This step is critical** — without it, the committed YAML will not include the
`_v2` fields in field layouts, and production's `project-config/apply` will not
add them:
```bash
php craft project-config/rebuild
```

### L4.2 Apply project config
```bash
php craft project-config/apply
```

### L4.3 Remove minimum-stability flags
Now that `sebastianlenz/linkfield` is removed, remove the stability flags:
```json
"minimum-stability": "beta",
"prefer-stable": true
```
Then lock without re-resolving:
```bash
composer update --lock --no-interaction
```

### L4.4 CKEditor Redactor conversion (if applicable)
If the project uses Redactor fields:
```bash
php craft ckeditor/convert/redactor
```
Skip if no Redactor fields exist.

### L4.5 Run fields/auto-merge
`php craft fields/auto-merge` requires an interactive terminal and cannot be
run by Claude. Ask the user to run it themselves:
```bash
php craft fields/auto-merge
```

Instruct them to review each proposed merge batch carefully and only accept
where the fields are genuinely the same type and config. If any merges are
accepted, commit the generated migration files and run `php craft up` in all
other environments before deploying.

---

**STOP. Report all cleanup outputs. Wait for confirmation before Block L5.**

---

## BLOCK L5 — Final report and DEPLOY.md

### L5.1 Final report

Produce a structured summary:
- Craft version now running
- Plugins removed
- Fields migrated (old handle → new handle, row count per field)
- Templates updated (list of files changed)
- Manual follow-up items:
  - Template extension collisions from P1.9 (check state file Notes)
  - Any `columnSuffix` fields — confirm data verified in CP
  - Super Table single-row access patterns needing `.one()`
  - `user` link type rows skipped (no native equivalent; re-enter manually)
  - `tel` link type rows skipped (re-enter as URL links using `tel:+...` prefix)
  - (`asset` rows are migrated automatically by `run-direct` — no manual action)
  - Any `_v2` fields not yet visible in entry type layouts — add via CP
    (if `run-direct` was used and layout insertion was not possible)
  - Any fields where pre-existing duplicate handles caused data to be
    unmigratable (only if not remediated in preflight — manual re-entry required)
  - Re-enable any plugins listed in `PLUGINS_TO_DISABLE_FOR_UPGRADE` on production

### L5.2 Generate DEPLOY.md

Ask: **How is code deployed to production?** (examples: git push + SSH, Laravel
Forge, Ploi, Deployer, rsync, FTP, hosting panel). Ask about the deployment
method before filling in the template.

Fill in the template below using values from the state file and session,
then write it to the project root as `DEPLOY.md`.

```markdown
# Craft 5 Production Deployment — [project name]
Generated [date].

## Upgrade summary
- Craft version: [version]
- Linkfield fields migrated: [e.g. linkUrl → linkUrl_v2, primaryLink → primaryLink_v2]
- Templates patched: [list of files, or "none"]
- fields/auto-merge migration files committed: [yes / no]

## ⚠ Content delta warning
This deployment replaces the production database with the local migrated
database. Any content added to production after [date of original DB snapshot]
will be overwritten. Put production in maintenance mode before pushing the DB.

## Pre-deployment checklist
- [ ] Local site fully verified — all link field entries display correctly in browser
- [ ] All code committed (modules/, config/project/, templates, composer.json/lock)
- [ ] Fresh production DB backup taken and stored safely off-server
- [ ] Maintenance window communicated to content editors

## Deployment steps

### 1. Export local Craft 5 database
```bash
[MYSQL_CMD] [DB_NAME] > ~/Desktop/[project]-craft5-[date].sql
```

### 2. Enable maintenance mode on production
[Step based on their deployment method, e.g.:
- Forge / Ploi: enable maintenance toggle in hosting panel
- Generic: create a `storage/maintenance.html` file or return 503 via server config]

### 3. Deploy code to production
[Deployment steps based on their method]

### 4. Install dependencies
```bash
composer install --no-dev
```

### 5. Import migrated database to production
[DB import steps based on their hosting environment, e.g.:
- SSH + mysql: `mysql -u user -p db_name < craft5-migrated.sql`
- Hosting panel: use DB import tool
- TablePlus / Sequel Pro: connect to production DB, run File > Import]

### 6. Run Craft upgrade
```bash
php craft up
php craft project-config/apply
```

### 7. Re-enable plugins disabled for the upgrade
[If any plugins were listed in PLUGINS_TO_DISABLE_FOR_UPGRADE:]
```bash
php craft plugin/enable <handle>
```

### 8. Verify
- [ ] Log into Craft CP — confirm Craft [version] in footer
- [ ] Open an entry using field [first _v2 handle] — confirm link renders correctly
- [ ] Load a URL from a patched template — confirm no errors
- [ ] Check logs: `tail -n 50 storage/logs/web.log`

### 9. Exit maintenance mode
[Reverse of step 2]

## Rollback
Restore the production backup from the pre-deployment checklist:
```bash
[DB import command] < /path/to/craft4-production-backup.sql
git checkout [craft4-branch] && composer install --no-dev && php craft up
```
```

### L5.3 Update state file
Append to `.craft5-upgrade.md`:
```
## Linkfield migration result
PHASE: linkfield-done
```

---

**STOP. Present final report and DEPLOY.md. Await confirmation or corrections.**

---
