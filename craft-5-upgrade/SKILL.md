---
name: craft-5-upgrade
description: "Use this skill to upgrade a Craft CMS 4 project to Craft CMS 5 — the actual destructive upgrade (Composer, php craft up, database migrations). Requires craft-5-preflight to have already run (look for .craft5-upgrade.md with PHASE: preflight-done in the project root). Triggers: 'run the Craft 5 upgrade', 'upgrade Craft to 5', 'Craft 4 to 5 upgrade', 'do the Craft 5 upgrade', 'composer update for Craft 5', 'upgrade to Craft 5'. Do NOT use for the pre-upgrade audit — that is craft-5-preflight. Do NOT use for linkfield data migration — that is craft-5-linkfield."
disable-model-invocation: true
---

# Craft 5 Upgrade

## Overview

Runs the destructive Craft 4 → 5 upgrade: Composer changes, `php craft up`,
database migrations, and charset conversion.

**Requires:** `.craft5-upgrade.md` in the project root with
`PHASE: preflight-done` (written by `craft-5-preflight`).

Subsequent skill: `craft-5-linkfield` (only if `LINKFIELD_PRESENT: yes`).

**Work through one block at a time. Stop at the end of each block, report
findings, and wait for explicit confirmation before proceeding.**

---

## Global rules

- **First action:** read `.craft5-upgrade.md`. If absent or `PHASE` is not
  `preflight-done`, stop immediately and report:
  > "State file not found / preflight not complete.
  > Run craft-5-preflight first, then return here."
- Never run destructive commands (Composer changes, database writes, file
  edits) outside the block they are designated to.
- If any command exits non-zero: stop, report full output, wait for
  instructions.
- Report all command output and all file edits with diffs.
- Minimal changes only.
- MySQL only. Do not add Postgres paths.

**Rollback:** restore DB backup, run
`git checkout composer.json composer.lock && composer install`,
then `git checkout .` to revert file changes.

---

## BLOCK U1 — Pre-upgrade preparation (Craft 4, no composer changes yet)

### U1.0 Read state file
Read `.craft5-upgrade.md`. Record:
- `LINKFIELD_PRESENT` (yes/no)
- `MYSQL_CMD` (working mysql command)
- `DB_NAME`
- `DB_CHARSET_EXISTING`
- `PLUGINS_TO_DISABLE_FOR_UPGRADE` (may be empty)
- `FIELD_PLUGINS_KEEP_ENABLED` (may be empty — field/content plugins that must
  stay enabled throughout the upgrade)
- `PLUGINS_FOR_MANUAL_REVIEW` (may be empty)
- `COMPOSER_POST_UPDATE_HOOK` (yes/no)
- Plugin target versions from PLUGIN_TARGETS table
- Any blockers (must be none)

Confirm `PHASE: preflight-done`. If not, stop and instruct as above.

**If `COMPOSER_POST_UPDATE_HOOK: yes`:** note this now. In U2.1, `composer update`
will automatically run `php craft up` via the `post-update-cmd` hook. U2.2 will
be a no-op (or will confirm "already up to date"). Do not be surprised by this.

### U1.1 Confirm backup and version control
Ask the user to confirm:
- A fresh full database backup has been taken (separate from the preflight
  backup — this is the rollback point for the destructive upgrade).
  Recommended: `php craft db/backup` — native, transactional, and config-aware.
- All code is committed to version control.

Do not proceed without both confirmed.

### U1.2 Pre-upgrade Craft commands
```bash
php craft project-config/rebuild
```
This normalises all project YAML files. Expect a large diff — 80+ files
is normal. Do not review file-by-file; commit with a descriptive message.

```bash
php craft utils/fix-field-layout-uids
```

### U1.2.5 Disable deploy-side plugins
**Skip this step if `PLUGINS_TO_DISABLE_FOR_UPGRADE` in the state file is empty.**

> **CRITICAL — never disable field/content plugins.** Only disable plugins listed
> in `PLUGINS_TO_DISABLE_FOR_UPGRADE` (deploy/notification hooks). **Do NOT disable
> any plugin in `FIELD_PLUGINS_KEEP_ENABLED`** (Hyper, Super Table, CKEditor,
> Redactor, Formie, linkfield, or anything that provides a field/block/element
> type). Those plugins run content migrations during `php craft up` against the
> still-present Craft 4 content tables. Disabling one serializes its fields as
> `craft\fields\MissingField` into project config **and** skips its migration —
> **irreversible** once Craft drops the Craft 4 source tables (`matrixcontent_*`,
> `stc_*`). The damage cannot be undone by re-enabling the plugin afterward; the
> only recovery is a full DB + code rollback and a clean re-run. Leave every field
> plugin enabled throughout `fix-field-layout-uids`, `composer update`, and
> `php craft up`.

`fix-field-layout-uids` (and `php craft up` in U2) trigger many element saves.
Deploy/notification plugins that register `afterSaveElement` with environment-specific
paths (cache busters, deploy notifiers, search reindex hooks, Slack webhooks) will
throw `InvalidArgumentException` on dev and abort the command mid-run. **These** are
safe and correct to disable.

The preflight audit resolves vendor libraries to their host plugin and records
plugin handles (not package names) directly in `PLUGINS_TO_DISABLE_FOR_UPGRADE`.
For each entry:
```bash
php craft plugin/disable <handle>
```

If an entry shows `# no plugin handle resolved`, the preflight could not map
the vendor library to a host plugin — derive the handle from
`php craft plugin/list` and disable manually.

If `PLUGINS_FOR_MANUAL_REVIEW` is non-empty, do **not** disable those plugins by
default. Inspect each `afterSave*` handler and disable only the ones that clearly
reference env-specific filesystem paths, external HTTP endpoints, or deploy tooling.
When in doubt, leave the plugin enabled.

Record the handles disabled here; they must be re-enabled on production
(added to DEPLOY.md in U3/L5).

### U1.3 Install the migration module (linkfield projects only)
**Skip this entire step if `LINKFIELD_PRESENT` is "no".**

Check whether `modules/Module.php` already exists in the project.

- If it exists and already registers a console controller namespace, check
  whether `modules/console/controllers/MigrateLinkfieldController.php` exists.
  If both exist, skip to U1.4.
- If not: follow `references/module-setup.md` in this skill's directory to
  copy the module files from `~/.claude/skills/craft-5-upgrade/module/`,
  register the module in `config/app.php`, and confirm the PSR-4 autoload
  entry in `composer.json`. Do not run `composer update` yet.

### U1.4 Update `vlucas/phpdotenv` if needed
If the state file shows phpdotenv below `^5.6.0`, update the constraint in
`composer.json` to `^5.6.0`. Do not run `composer update` yet.

### U1.5 Update `composer.json` for Craft 5

Ask the user if they have run the Craft 5 Upgrade utility in the CP
(Utilities > Craft 5 Upgrade > Prep `composer.json`) and have output to paste.

- If yes: apply the user's output to `composer.json`.
- If no: manually update `craftcms/cms` to `^5.0.0` and each plugin to the
  Craft 5-compatible version from the state file's PLUGIN_TARGETS table.

If `LINKFIELD_PRESENT` is "yes", also set:
```json
"sebastianlenz/linkfield": "^3.0.0-beta"
```
If `LINKFIELD_PRESENT` is "no", do not add or modify any linkfield constraint.

### U1.5.5 Configure composer audit (conditional)
Craft 5.9.x+ requires `twig/twig ~3.21.0` or newer. Some twig versions in that
range carry active PKSA security advisories; Composer 2.9.x with default
settings refuses to resolve them ("requirements could not be resolved").

**Check first** — many runs need no override:
```bash
composer audit --no-dev
```

- If the output ends with `0 advisories` (or `No security vulnerability
  advisories found`), no override is required. Skip the rest of this step
  and record `COMPOSER_AUDIT_OVERRIDES: (none — composer audit clean)` in the
  state file.

- If advisories are reported, add (or amend) the `config` section in
  `composer.json`:
  ```json
  "config": {
      "audit": {
          "abandoned": "report",
          "block-insecure": false
      }
  }
  ```
  **The `audit` key must be inside `config`, not at the JSON root.**

  Record the actual advisory IDs from the audit output in the state file:
  ```
  COMPOSER_AUDIT_OVERRIDES: PKSA-xxxx, PKSA-yyyy
  ```
  Revisit after the upgrade is deployed to check if newer Twig versions
  resolve the advisories.

### U1.6 Stability flags (linkfield projects only)
**Skip this entire step if `LINKFIELD_PRESENT` is "no".**

Add to `composer.json` if not already present:
```json
"minimum-stability": "beta",
"prefer-stable": true
```

If `LINKFIELD_PRESENT` is "yes": these flags are removed in `craft-5-linkfield`
Block L4.3 (after the plugin itself is removed in L4.1). Note their addition in
the U1 report.

If `LINKFIELD_PRESENT` is "no" but stability flags were added anyway
(unlikely): remove them in Block U3.

### U1.7 MySQL charset vars
If `DB_CHARSET_EXISTING` in the state file is "(none)", add to `.env`:
```
CRAFT_DB_CHARSET="utf8mb3"
CRAFT_DB_COLLATION="utf8mb3_general_ci"
```
If already set, leave as-is and note the existing values.

---

**STOP. Report all file changes with diffs. Confirm no `composer update`
or `php craft up` has been run yet. Wait for confirmation before Block U2.**

---

## BLOCK U2 — Craft 5 upgrade

### U2.1 Run composer update
```bash
composer update --no-interaction
```
Do not add `--with-all-dependencies` or package-specific flags.
If `LINKFIELD_PRESENT` is "yes": confirm both `craftcms/cms` (^5.x) and
`sebastianlenz/linkfield` (3.0.0-beta) appear in the output.

**If `COMPOSER_POST_UPDATE_HOOK: yes` (from state file):** `composer update`
will automatically run `php craft up` via the `post-update-cmd` hook. U2.2
below will likely be a no-op that confirms "already up to date." This is expected.

### U2.2 Run the Craft database upgrade
```bash
php craft up
php craft project-config/apply
```
If `COMPOSER_POST_UPDATE_HOOK: yes`, this command will likely output "already
up to date" — that is correct behaviour, not a failure.

**Note:** `php craft --version` is not a valid Craft CLI command and will exit
with code 1. Do not treat that as a failure. Use `composer show craftcms/cms`
(U2.5) to confirm the installed Craft 5 version.

### U2.3 Install any newly added plugins
`php craft up` typically installs all plugins. Run `php craft plugin/list` to
confirm every required plugin shows as installed.

If any plugin is missing:
```bash
php craft plugin/install <handle>
```
Always derive plugin handles from `php craft plugin/list`, not from package
names — they often differ.

### U2.4 MySQL charset conversion
Remove `CRAFT_DB_CHARSET` and `CRAFT_DB_COLLATION` from `.env` (and from
`config/db.php` if present). Then:
```bash
php craft db/convert-charset
```

### U2.5 Verify Craft 5
```bash
composer show craftcms/cms | grep -E "^versions"
```
Confirm a 5.x version is shown. Stop if not.

### U2.6 Field/content render gate (before committing)
`php craft up` runs each field plugin's content migration in place against the
Craft 4 source tables — and then Craft drops those tables. If a field plugin's
content did not migrate correctly, the only fix is a full rollback (restore the
DB + code to the pre-upgrade snapshot taken in U1.1). **Catch it now, before
anything is committed.**

For every plugin in `FIELD_PLUGINS_KEEP_ENABLED` (and any field plugin you know
the site uses — Hyper, Super Table, CKEditor, Redactor, Formie), load a front-end
page or CP entry that renders one of its fields and confirm the content is intact:

- **Hyper / linkfield:** a link renders with its real link text **and** a non-empty
  `href`, including anchor-only links (e.g. `href="#apply"`). An empty `<a href="">`
  or missing text means the migration was skipped (plugin was disabled, or source
  tables were already gone) — **stop and roll back to the U1.1 snapshot**.
- **Super Table / Matrix:** blocks render with their field values populated.
- **CKEditor / Redactor:** rich-text body renders with formatting intact.

Also check field definitions did not corrupt:
```bash
php craft project-config/diff
```
Confirm no field that should belong to a field plugin is serialized as
`craft\fields\MissingField`. If any is, the plugin was disabled during the
upgrade — **stop and roll back to the U1.1 snapshot**; do not "fix" it by re-enabling, as the
content migration has already been skipped against now-dropped source tables.

If anything renders empty or as `MissingField`, do not commit. Report and roll back.

---

**STOP. Report Craft version, all command outputs, the U2.6 render-gate results,
and current state of `.env` and `composer.json`. Wait for confirmation before
Block U3.**

---

## BLOCK U3 — Finalise and hand off

### U3.1 Update state file
Append to `.craft5-upgrade.md`:
```
## Upgrade result
PHASE: upgrade-done
CRAFT_TO: <installed Craft 5 version>
```

### U3.2 If LINKFIELD_PRESENT = "yes"
Instruct the user:
> "Upgrade to Craft 5 complete. Run `craft-5-linkfield` next to migrate link
> field data and update templates."

Done for this skill. Do not proceed further.

### U3.3 If LINKFIELD_PRESENT = "no"

#### Re-enable plugins disabled locally
If `PLUGINS_TO_DISABLE_FOR_UPGRADE` in the state file is non-empty, re-enable
each handle locally now — they were disabled in U1.2.5 only to get past the
element-save phase of `php craft up`. Leaving them disabled silently breaks
dev (SEO previews, search indexing, cache busting, etc.) for the rest of the
smoke-test phase.

Skip any handle whose plugin was removed by this upgrade (compare against
plugins listed for removal in U1.5 / state file).
```bash
php craft plugin/enable <handle>
```

The corresponding production re-enable belongs in the deploy notes (see below).

#### Remove stability flags (if added in U1.6)
Check `composer.json` for `"minimum-stability"` and `"prefer-stable"`.
If present, remove them, then:
```bash
composer update --lock --no-interaction
```

#### CKEditor Redactor conversion (if applicable)
If the project uses Redactor fields:
```bash
php craft plugin/install ckeditor
php craft ckeditor/convert/redactor
```
`plugin/install ckeditor` is required — composer alone does not enable the
plugin, and the convert command will not exist without it. Skip both if no
Redactor fields exist.

#### Run fields/auto-merge (optional — skip unless you want field-count cleanup)

**Duplicate fields after upgrade are an acceptable outcome** — `auto-merge` only
reduces field count (an optimization, not a stability gain). It also carries known
relation-merge bugs for max-relations=1 fields
([#15869](https://github.com/craftcms/cms/issues/15869),
[#16198](https://github.com/craftcms/cms/issues/16198),
[#16444](https://github.com/craftcms/cms/discussions/16444)). **Recommended: skip.**
Only proceed if you specifically want to collapse post-upgrade field proliferation,
and only on fields that are genuinely identical in type and config.

If you choose to proceed: `php craft fields/auto-merge` requires an interactive
terminal and cannot be run by Claude — it exits with code 1 non-interactively.
Ask the user to run it themselves:
```bash
php craft fields/auto-merge
```
Instruct them to review each proposed merge batch carefully and only accept
where the fields are genuinely the same type and config. If any merges are
accepted, commit the generated migration files and run `php craft up` in all
other environments before deploying.

#### Optional: post-upgrade verification with craft-mcp
`stimmt/craft-mcp` is a Craft 5-only MCP plugin that lets Claude inspect runtime
deprecations, logs, and CP entry state — a useful smoke-test supplement. It is
dev-only; install transiently and remove after sign-off. For setup and the read-only
tool subset to use, see `craft-5-linkfield/references/post-upgrade-verification.md`.

#### Generate upgrade-deploy notes (optional)
Assume the user already has a deploy process for this project. Do not produce
a generic deploy runbook by default — most developers will find it duplicates
their existing workflow and bury the upgrade-specific bits they actually need.

Ask: **Do you want upgrade-specific deploy notes generated, or do you already
have a deploy process you'll integrate these changes into?** Default to the
latter — only generate notes if the user opts in (e.g. new project, handoff,
or unfamiliar deploy path).

If notes are wanted, write to `CRAFT-5-UPGRADE-NOTES.md` (not `DEPLOY.md`) and
include *only* the upgrade-specific deltas — not generic deploy steps. The
template below is a starting point; trim ruthlessly to what is genuinely
upgrade-specific.

```markdown
# Craft 5 Upgrade Notes — [project name]
Generated [date]. Integrate these deltas into your existing deploy process.

## Upgrade summary
- Craft: [from version] → [version from U2.5]
- Plugins updated: [list from U2.3 with version bumps]
- Plugins removed: [list, or "none"]
- Templates patched: [list, or "none"]
- fields/auto-merge migration files committed: [yes / no]
- Matching pre-upgrade code commit (rollback target): `[short SHA]`
- Matching pre-upgrade DB backup (rollback target): `[path/filename]` — take with `php craft db/backup` before step U2.1

## Production re-enable
These plugins were disabled locally during the upgrade and must be re-enabled
on production after `project-config/apply` completes. Skip any that were also
removed by this upgrade.
```bash
[for each handle in PLUGINS_TO_DISABLE_FOR_UPGRADE that was NOT removed:]
php craft plugin/enable <handle>
```

## Post-deploy manual follow-up
- [ ] Confirm Craft [version] in CP footer
- [ ] Spot-check patched templates: [list 2–3 highest-traffic files]
- [ ] Template extension collisions from preflight P1.9: [list, or "none"]
- [ ] CKEditor visual diff if Redactor was converted: [yes/no]

## Rollback for this upgrade
This upgrade migrates the DB schema. Restore code and DB to matching snapshots:
```bash
# 1. Restore DB from the pre-upgrade backup listed above
[DB import command] < [path to pre-upgrade backup]
# 2. Restore code to the matching pre-upgrade commit
git checkout [pre-upgrade SHA]
composer install --no-dev
```
```

---

**STOP. Present final report and upgrade notes (if generated).
Await confirmation or corrections.**

---
