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
- Plugin target versions from PLUGIN_TARGETS table
- Any blockers (must be none)

Confirm `PHASE: preflight-done`. If not, stop and instruct as above.

### U1.1 Confirm backup and version control
Ask the user to confirm:
- A fresh full database backup has been taken (separate from the preflight
  backup — this is the rollback point for the destructive upgrade).
- All code is committed to version control.

Do not proceed without both confirmed.

### U1.2 Pre-upgrade Craft commands
```bash
php craft project-config/rebuild
php craft utils/fix-field-layout-uids
```

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

### U1.6 Stability flags (linkfield projects only)
**Skip this entire step if `LINKFIELD_PRESENT` is "no".**

Add to `composer.json` if not already present:
```json
"minimum-stability": "beta",
"prefer-stable": true
```

If `LINKFIELD_PRESENT` is "yes": these flags are removed in `craft-5-linkfield`
Block L4.1 once the plugin is gone. Note their addition in the U1 report.

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

### U2.2 Run the Craft database upgrade
```bash
php craft up
php craft project-config/apply
```
Note: `php craft --version` is not a valid Craft CLI command and will exit
non-zero. Use the command in U2.5 to confirm the installed version.

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

---

**STOP. Report Craft version, all command outputs, current state of `.env`
and `composer.json`. Wait for confirmation before Block U3.**

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

#### Remove stability flags (if added in U1.6)
Check `composer.json` for `"minimum-stability"` and `"prefer-stable"`.
If present, remove them, then:
```bash
composer update --lock --no-interaction
```

#### CKEditor Redactor conversion (if applicable)
If the project uses Redactor fields:
```bash
php craft ckeditor/convert/redactor
```
Skip if no Redactor fields exist.

#### Run fields/auto-merge
`php craft fields/auto-merge` requires an interactive terminal and cannot be
run by Claude — it exits with code 1 non-interactively. Ask the user to run it
themselves:
```bash
php craft fields/auto-merge
```
Instruct them to review each proposed merge batch carefully and only accept
where the fields are genuinely the same type and config. If any merges are
accepted, commit the generated migration files and run `php craft up` in all
other environments before deploying.

#### Generate DEPLOY.md
Ask: **How is code deployed to production?** (examples: git push + SSH, Laravel
Forge, Ploi, Deployer, rsync, FTP, hosting panel). If unsure, default to generic
SSH steps.

Fill in the template below using values from the session and state file,
then write it to the project root as `DEPLOY.md`.

```markdown
# Craft 5 Production Deployment — [project name]
Generated [date].

## Upgrade summary
- Craft version: [version from U2.5]
- Plugins updated: [list from U2.3]
- Templates patched: [list, or "none"]
- fields/auto-merge migration files committed: [yes / no]

## Deployment steps

### 1. Deploy code
[Deployment command/steps based on their method, e.g.:
- Forge: trigger deploy via dashboard or `forge deploy <site-id>`
- Git + SSH: `git push origin main` then `ssh user@host "cd /path && git pull"`
- Generic SSH: `cd /path/to/site && git pull origin main`]

### 2. Install dependencies
```bash
composer install --no-dev
```

### 3. Run Craft upgrade
```bash
php craft up
php craft project-config/apply
```

### 4. Verify
- [ ] Log into Craft CP — confirm Craft [version] in footer
- [ ] Browse key page types in browser — confirm no errors
- [ ] Check logs: `tail -n 50 storage/logs/web.log`

## Rollback
```bash
git checkout [craft4-branch]
composer install --no-dev
php craft up
```
```

---

**STOP. Present final report and DEPLOY.md (if generated).
Await confirmation or corrections.**

---
