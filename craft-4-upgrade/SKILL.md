---
name: craft-4-upgrade
description: "Use this skill to upgrade a Craft CMS 3 project to Craft CMS 4 — audit, dependency updates, the destructive upgrade (Composer, php craft migrate/all, project-config/apply), template/config remediation, and deploy notes. Triggers: 'upgrade to Craft 4', 'Craft 3 to 4 upgrade', 'do the Craft 4 upgrade', 'prepare for Craft 4', 'audit Craft 3 site for Craft 4', 'is my site ready for Craft 4', 'run the Craft 4 upgrade'. Do NOT use for Craft 4 → 5 — that is craft-5-preflight / craft-5-upgrade. Do NOT use for in-place patch updates within Craft 3.x — use `composer update` and the Craft updater directly."
disable-model-invocation: true
---

# Craft 4 Upgrade — Craft 3 → 4

## Overview

Audits a Craft 3 project, prepares it on Craft 3, then performs the destructive
Craft 4 upgrade: Composer changes, `php craft migrate/all`,
`project-config/apply`, template/config remediation, and (optionally) MySQL
charset conversion.

Writes a `.craft4-upgrade.md` state file in the project root that tracks phase,
plugin targets, blockers and remediations.

**Work through one block at a time. Stop at the end of each block, report
findings, and wait for explicit confirmation before proceeding.**

---

## Global rules

- **First action:** check for `.craft4-upgrade.md` in the project root. If
  present, read it and resume at the next un-completed block. If absent,
  start at Block A1.
- Block A is **entirely read-only**. No changes.
- Block B edits the Craft 3 site only (pre-upgrade prep). Site must remain
  fully working on Craft 3 after Block B.
- Block C is the destructive upgrade. Do not run any command in Block C
  until A and B are complete and the user has confirmed a fresh DB backup.
- Never run destructive commands (Composer changes, DB writes, file edits)
  outside the block they are designated to.
- If any command exits non-zero: stop, report full output, wait for
  instructions.
- Report all command output and all file edits with diffs.
- Minimal changes only. Do not refactor beyond stated scope.
- MySQL only. Do not add Postgres paths.
- `php craft --version` is not a valid Craft CLI command. Use
  `composer show craftcms/cms` to confirm versions.

**Rollback for Block C:** restore DB backup, run
`git checkout composer.json composer.lock && composer install`,
then `git checkout .` to revert file changes.

---

## BLOCK A — Audit (read-only)

### A.1 Craft and PHP version
Record:
- Current Craft CMS version — from `composer.lock` (search for
  `"name": "craftcms/cms"` and read the adjacent `version` field) or
  `composer show craftcms/cms`.
- Current PHP version (`php --version`).
- Target Craft version (latest 4.x — record as **CRAFT_TARGET**).

**Flag as blocker:** Craft below 3.7.39 (Craft 4 requires migration paths
present in late 3.x — earlier than 3.7.39 should be patched up to latest
3.x first via `composer update craftcms/cms --with-dependencies` and
`php craft migrate/all` *before* running this skill).

**Flag as blocker:** PHP below 8.0.2 in any environment that will run
Craft 4 (local, staging, production). Note that Craft 3.7+ runs on PHP 8.0,
so PHP can be upgraded to 8.0.x on Craft 3 ahead of the upgrade. Do not
jump to PHP 8.1 or 8.2 while still on Craft 3 — those versions surface
additional deprecations that Craft 3 does not fully silence.

### A.2 Required PHP extensions
Confirm these extensions are installed (`php -m | grep -i <name>`):
- `bcmath` — newly required in Craft 4
- `intl` — newly required in Craft 4
- `dom`, `mbstring`, `openssl`, `pdo`, `pdo_mysql`, `gd` or `imagick`,
  `json`, `curl`, `zip`, `fileinfo` — already required in Craft 3

Flag any missing extension as a blocker (especially `bcmath` and `intl` —
these are the common ones Craft 3 sites lack).

### A.3 Database engine and connection
Check `.env` and `config/db.php` for `CRAFT_DB_DRIVER` / `DB_DRIVER`.
Confirm MySQL. Record:
- Server version (`mysql --version` or `SELECT VERSION()`).
- Existing `CRAFT_DB_CHARSET` / `CRAFT_DB_COLLATION` values, or `(none)`.
- Working mysql command as **MYSQL_CMD**:
  ```bash
  mysql -u root -e "SELECT 1"          # or
  mysql -h 127.0.0.1 -u root -e "SELECT 1"
  ```
- Database name as **DB_NAME**.

**Flag as blocker:** MySQL < 5.7.8 or MariaDB < 10.2.7. Flag a failed
connection as a blocker.

### A.4 Plugin inventory and Craft 4 targets
Read `composer.json`. For every Craft plugin under `require`, look up the
Craft 4-compatible release on Packagist (or the plugin's repo).
Record the target version for each. Common patterns to expect:

| Craft 3 plugin family       | Craft 4 notes |
|-----------------------------|---------------|
| `craftcms/aws-s3` 1.x       | → `^2.0` (volume → filesystem split, see B.4) |
| `craftcms/redactor` 2.x     | → `^3.0` (still maintained) |
| `verbb/super-table` 2.x     | → `^3.0` |
| `verbb/navigation` 1.x      | → `^2.0` |
| `verbb/bugsnag` 3.x         | → `^4.0` |
| `nystudio107/craft-seomatic` 3.x | → `^4.0` |
| `nystudio107/craft-minify`  | check Packagist — may be archived |
| `solspace/craft-freeform` 3.x | → `^4.0` (major API/template changes; review Solspace's own upgrade guide separately) |
| `barrelstrength/sprout-fields` 3.x | **Often a blocker** — Sprout was substantially restructured. The Craft 4 successor is `sprout/sprout` (which bundles several former separate packages). Map the Sprout modules you use to the new package before proceeding. |
| `vaersaagod/dospaces`       | check for Craft 4 release; may need replacing with `craftcms/aws-s3` v2 + DO Spaces endpoint |
| `born05/craft-assetusage`   | check Packagist for Craft 4 release |
| `craftplugins/carbon`       | check; small wrappers often need a fork |
| `misterbk/mix`              | check; small Twig helper, low risk |

Skip `php`, `ext-*`, and non-Craft PHP libraries.

For each plugin record one of:
- `OK: <version constraint>` — Craft 4 release exists, target version known
- `REPLACE: <reason>` — needs a replacement plugin
- `REMOVE: <reason>` — plugin is no longer needed / abandoned
- `BLOCKER: no Craft 4 release` — stop here

If Packagist is unreachable, ask the user to confirm Craft 4 compatibility
for each plugin manually before proceeding.

**REPLACE candidates require a written data-migration plan before Block C.**
Swapping a plugin package often means migrating field data to a different
schema — stop and plan this explicitly; do not assume `migrate/all` handles
it automatically.

### A.5 `vlucas/phpdotenv`
Check the constraint in `composer.json`. Craft 4's starter project uses
`^5.4.1`. Flag if below `^5.4.0` (constraint should be bumped in B).

### A.6 Queue status
```bash
php craft queue/info
```
**Flag as blocker:** any pending or reserved jobs. The user must drain or
release them on Craft 3 first.

### A.7 Legacy draft/revision tables
```bash
php craft project-config/get dateModified   # confirms Craft can boot
[MYSQL_CMD] [DB_NAME] -e "SHOW TABLES LIKE 'entrydrafts'; SHOW TABLES LIKE 'entryversions';"
```
If `entrydrafts` or `entryversions` exist, they will be **dropped** by the
Craft 4 install process. Craft 3.2+ stopped using them. Check for meaningful
data:
```bash
[MYSQL_CMD] [DB_NAME] -e "SELECT COUNT(*) FROM entrydrafts; SELECT COUNT(*) FROM entryversions;"
```
Record non-zero counts in the state file and confirm with the user that
the data is expendable before continuing.

### A.8 Deprecation warnings
The Craft 3 control panel surfaces deprecation warnings at
**Utilities → Deprecation Warnings**. Ask the user to confirm the list is
empty (or to share screenshots / export). Record the count.

Any deprecated API in use on Craft 3 may be **removed** in Craft 4.
Resolving these on Craft 3 is the single most effective way to avoid
post-upgrade breakage. Flag a non-empty list as **strongly recommended to
clear before Block C**, but not a hard blocker.

### A.9 `config/general.php` removed settings
Search `config/general.php` for any of these keys — they are **removed**
in Craft 4 and leaving them in place throws an error on boot:

- `customAsciiCharMappings`
- `siteName`           (move to control panel, optionally via env var)
- `siteUrl`            (move to control panel, optionally via env var)
- `suppressTemplateErrors`
- `useCompressedJs`
- `useProjectConfigFile`

Record each match for removal in Block B.

### A.10 PHP constants in `bootstrap.php` / `web/index.php` / `craft`
Inspect the three entrypoint files for:

1. **`CRAFT_SITE_URL`** — deprecated; use env-var-driven site URLs in CP
   instead. Record any use.
2. **`CRAFT_LOCALE`** — replaced by `CRAFT_SITE`. Record any use.
3. **Environment determination.** Craft 3's bootstrap typically reads
   `getenv('ENVIRONMENT')` and assigns to `CRAFT_ENVIRONMENT`. The Craft 4
   starter project requires `CRAFT_ENVIRONMENT` to be set directly in
   `.env`. Record whether the current bootstrap uses the legacy
   `ENVIRONMENT` → `CRAFT_ENVIRONMENT` pattern (it almost certainly does).
4. Any other custom constants (cache dir overrides, alias setup) — note
   them; they need to be preserved through any entry-script update in B.

### A.11 Custom modules / `modules/` directory
List files under `modules/`. For each PHP class, note:
- Namespace (commonly `modules\`).
- Any Yii event handlers (`Event::on(...)`) targeting elements, fields or
  services that change between Craft 3 and 4.
- Any direct use of removed APIs (see A.13).

This is a project-level review — record findings, do not modify yet.

### A.12 Template audit — Craft 4 breaking patterns
Grep `templates/` (and any module-owned templates) for the following
patterns. Record file:line for each match. These are addressed in Block D.

Removed query methods:
```bash
grep -rnE "\.(find|first|last|total)\(\)" templates/
```
Removed Twig tags (`{% spaceless %}`, `{% filter %}`):
```bash
grep -rnE "\{%\s*(spaceless|filter)(\s|%)" templates/
```
Removed `if` param inside `{% for %}`:
```bash
grep -rnE "\{%\s*for\s.+\sif\s" templates/
```
Removed `craft` variable shortcuts (replace with `craft.app.*`):
```bash
grep -rnE "craft\.(categoryGroups|config|deprecator|elementIndexes|emailMessages|feeds|fields|globals|i18n|isLocalized|locale|request|sections|session|systemSettings|userGroups|userPermissions)\b" templates/
```
Removed template functions:
```bash
grep -rnE "\b(getCsrfInput|getFootHtml|getHeadHtml|round|atom|cookie|iso8601|rfc822|rfc850|rfc1036|rfc1123|rfc2822|rfc3339|rss|w3c|w3cDate|mySqlDateTime|localeDate|localeTime|year|month|day|nice|uiTimestamp)\(" templates/
```
Removed user query default — Craft 4 returns **all** users by default
(Craft 3 returned only active). Flag any:
```bash
grep -rnE "craft\.users\(\)" templates/
```
…that does **not** chain `.status(...)` or `.id(...)` — these likely need
`.status('active')` added to preserve behaviour.

Removed Asset query params `source` / `sourceId`:
```bash
grep -rnE "\.(source|sourceId)\(" templates/
```
Element-query special-case: implicit count on `craft.entries()...`
without `.all()` / `.collect()` may break — only flag if the audit script
finds suspicious patterns; do not bulk-rewrite.

### A.13 PHP / module audit — Craft 4 breaking patterns
Grep `modules/` and any custom `src/` for:

```bash
grep -rnE "\\\\craft\\\\log\\\\(FileTarget|StreamLogTarget)" modules/
grep -rnE "App::(getDefaultLogTargets|logConfig)" modules/
grep -rnE "->(find|first|last|total)\(\)" modules/
grep -rnE "\\\\craft\\\\services\\\\Feeds" modules/
```

Record matches; remediate in Block D.

### A.14 Reserved field handles
List all custom field handles from `config/project/fields/` (parse the
`handle:` key from each YAML file). Flag any matching:

- `isNewForSite`, `isProvisionalDraft`, `newSiteIds` — reserved on all
  elements
- `active`, `addresses`, `admin`, `email`, `friendlyName`, `locked`,
  `name`, `password`, `pending`, `suspended`, `username` — reserved on
  **User** field layouts only (Craft 4.5+)
- `alt` — reserved on **Asset** field layouts only

These must be renamed on Craft 3 (in Block B) before the upgrade. The
collision is silent and will break field layouts post-upgrade.

### A.15 Volumes inventory (filesystem split)
List all volumes from `config/project/volumes/`. For each, record:
- Handle, name, type (`craft\awss3\Volume`, `craft\helpers\App::env(...)`,
  local, etc.).
- Whether it has a public URL (`hasUrls: true`) and what the URL is.
- Whether it uses environment variables for credentials/paths.

Craft 4 splits volumes into **Volume** (field layout + association) +
**Filesystem** (storage + URLs). `php craft migrate/all` creates a
filesystem per volume automatically. Two cases need attention post-upgrade:

1. Any `config/volumes.php` file — **no longer supported** in Craft 4.
   Record its existence as a blocker requiring conversion to
   per-environment filesystem env vars.
2. Volumes without public URLs need a designated **transform filesystem**
   for CP thumbnails.

### A.16 Composer post-update hook
Check `composer.json` for a `scripts.post-update-cmd` that runs Craft
commands (e.g. `@craft-update`, `craft migrate/all`). Record:
**COMPOSER_POST_UPDATE_HOOK: yes|no**. If yes, `composer update` in C.4
will automatically run migrations via the hook, and C.5 will then be a
confirmation no-op — note this so it does not surprise the operator.

### A.17 Project structure overview
Briefly note any project-specific files that diverge from the standard
Craft 3 starter:
- Custom files in `web/` (e.g. `OurHelpers.php` required from `index.php`).
- Custom `bootstrap.php` logic beyond loading Composer + Dotenv + setting
  constants.
- Non-standard `config/` files (e.g. `volumes.php`, `app.web.php`,
  `app.console.php`).
- Any deploy hooks in `composer.json` (`pre-install-cmd` etc.).

These must be preserved through any entry-script update.

---

**STOP. Produce a structured A-block report. Flag blockers clearly with
the word BLOCKER. Wait for confirmation before Block B.**

---

## BLOCK B — Craft 3 preparation (site stays on Craft 3)

Everything in this block edits the Craft 3 site and must leave it fully
working on Craft 3. Do **not** change Craft or plugin major versions here.

### B.1 Confirm backup and version control
Ask the user to confirm:
- A fresh full database backup exists.
- All code is committed and pushed.

Do not proceed without both confirmed.

### B.2 Patch Craft 3 to latest 3.x
If A.1 recorded a Craft version below the latest 3.x patch:
```bash
composer update craftcms/cms --with-dependencies
php craft migrate/all
php craft project-config/apply
```
Confirm site loads. Commit `composer.json`, `composer.lock`, any new
project-config files.

### B.3 Remove deprecated `config/general.php` keys
For each key recorded in A.9, remove it from `config/general.php`. For
`siteName` / `siteUrl`, move the value into the control panel (Settings →
Sites), optionally referencing the same env vars.

Show the diff. Confirm site still loads.

### B.4 Rename reserved field handles (if A.14 flagged any)

**Skip if A.14 found no reserved handles.**

For each flagged handle:

1. Identify the field context (top-level, matrix, super-table, user
   layout, asset volume) from the `config/project/` YAML.
2. Propose an unambiguous rename (e.g. `name` on Users → `displayName`;
   `alt` on Assets → `altText`).
3. Present proposals and wait for user approval.
4. Edit the YAML files in `config/project/fields/` (and any matrix /
   super-table block-type YAML referencing the handle) to change `handle:`.
5. Grep `templates/`, `modules/`, and any custom code for every reference to
   the old handle — including raw SQL queries against `content` table columns —
   and update all occurrences.
6. Run `php craft project-config/apply` and confirm site loads.

Stop and report after each rename. Commit each rename as its own commit
with a descriptive message.

### B.5 Bump `vlucas/phpdotenv` constraint (if A.5 flagged)
Update `composer.json` constraint to `^5.4.1` (do not bump to ^5.6 yet —
that is a Craft 5 prerequisite). Run:
```bash
composer update vlucas/phpdotenv
```
Confirm site loads.

### B.6 Drain the queue (if A.6 flagged jobs)
Either let jobs complete (`php craft queue/run`) or release them
(`php craft queue/release all` — destructive, confirm with user). Re-run
`php craft queue/info` until empty.

### B.7 Clear deprecation warnings (recommended)
If A.8 recorded non-zero warnings, fix them on Craft 3 now — most relate
directly to APIs removed in Craft 4. After fixing, clear the log:
```bash
php craft clear-caches/all
```
and ask the user to re-check the CP Deprecation Warnings utility.

### B.8 Deploy Craft 3 prep changes to live
The official Craft guide requires that Block B changes are deployed to the
live site **before** Block C runs locally. Ask the user to:

1. Merge / deploy the B-block commits to the live site.
2. Run `composer install && php craft project-config/apply` on live.
3. Confirm the live site is healthy.
4. Capture a fresh DB backup from **live** and import it locally — this
   is the snapshot Block C will run against.

Do not start Block C until live is on the same B-state as local and a
fresh live DB backup is imported.

---

**STOP. Report all B-block diffs, deploy status, and local DB refresh
status. Wait for confirmation before Block C.**

---

## BLOCK C — The Craft 4 upgrade (destructive)

### C.0 Write initial state file
If `.craft4-upgrade.md` does not exist, write it now using the template at
the bottom of this skill (`PHASE: prep-done`). Add `.craft4-upgrade.md` to
`.gitignore` — it contains a local `MYSQL_CMD` value.

### C.1 Pre-upgrade rebuilds (still on Craft 3)
```bash
php craft project-config/rebuild
```
Expect a large diff in `config/project/`. Do not review file-by-file;
commit with a descriptive message.

### C.2 Disable deploy-side plugins (if any)
If any installed plugin registers `afterSave*` element hooks that hit
environment-specific paths (cache busters, deploy notifiers, search
reindex webhooks), `migrate/all` will hit them during element resaves and
may abort. Examples to watch for: `nystudio107/craft-minify` (minifies on
element save), deploy webhook plugins, search-indexer plugins. If any are
present:
```bash
php craft plugin/disable <handle>
```
Record disabled handles — they must be re-enabled locally in C.8 and on
production in the deploy notes (C.9).

### C.3 Edit `composer.json` for Craft 4
Apply all of the following in **one edit**, then run **one**
`composer update`:

1. `craftcms/cms` → `^4.0.0` (or pinned `^4.x` of your choice).
2. Each plugin → the Craft 4 target version recorded in A.4.
3. Plugins marked `REMOVE` in A.4 → delete from `require`.
4. Plugins marked `REPLACE` → swap to the replacement package.
5. Add platform requirement if not already present:
   ```json
   "config": {
       "platform": { "php": "8.0.2" }
   }
   ```
6. If any required plugin only has a Craft 4 **beta** release, add:
   ```json
   "minimum-stability": "beta",
   "prefer-stable": true
   ```
   (Remove these in C.9 once all packages have stable releases.)

Show the full diff. Do not yet run `composer update`.

### C.4 Run composer update
```bash
composer update --no-interaction
```
- Do not add `--with-all-dependencies` or package-specific flags.
- If `COMPOSER_POST_UPDATE_HOOK: yes`, this command will automatically run
  the Craft migrations via the hook — C.5 will then be a confirmation
  no-op.
- Confirm `craftcms/cms` resolves to a 4.x version in the output. Stop
  if it does not.

If composer reports any unresolved conflict, **stop** and report the full
output verbatim. Do not attempt resolution by guessing constraints.

### C.5 Run Craft migrations
```bash
php craft migrate/all
php craft project-config/apply
```
If C.4 already ran the hook, the first command will report "no new
migrations" — that is expected.

If `migrate/all` errors:
- Read the trace. The most common cause is a plugin still pinned to
  Craft 3 internals (check `composer.lock`).
- Second most common: a removed `config/general.php` key that was missed
  in B.3.
- Third: a reserved field handle missed in B.4.

Do not retry blindly — diagnose, report, fix, then retry.

### C.6 Verify plugin install state
```bash
php craft plugin/list
```
If any required plugin is missing (sometimes occurs when `migrate/all` is
interrupted):
```bash
php craft plugin/install <handle>
```
Derive handles from `plugin/list`, not from package names.

### C.7 Confirm Craft 4
```bash
composer show craftcms/cms | grep -E "^versions"
```
Confirm a 4.x version is reported. Stop if not.

### C.8 Re-enable plugins disabled in C.2
For each handle recorded in C.2 (skipping any removed in C.3):
```bash
php craft plugin/enable <handle>
```

### C.9 Smoke test locally
Ask the user to:
- Load the front-end and exercise a few key templates.
- Load the CP and confirm sections, fields, assets, users.
- Check **Utilities → System Report** shows Craft 4.x.
- Check **Utilities → Deprecation Warnings** — many will now appear; this
  is normal and addressed in Block D.

---

**STOP. Report Craft version, `composer show` output, plugin list, smoke
test status. Wait for confirmation before Block D.**

---

## BLOCK D — Post-upgrade remediation

### D.1 Update Twig templates for removed APIs

Work through the audit findings from A.12 systematically. For each
match, apply the documented replacement:

| Craft 3                         | Craft 4 replacement |
|---------------------------------|---------------------|
| `.find()`                       | `.all()` |
| `.first()`                      | `.one()` |
| `.last()`                       | `.inReverse().one()` |
| `.total()`                      | `.count()` |
| `{% spaceless %}…{% endspaceless %}` | `{% apply spaceless %}…{% endapply %}` |
| `{% filter X %}…{% endfilter %}` | `{% apply X %}…{% endapply %}` |
| `{% for x in xs if cond %}`     | `{% for x in xs\|filter(x => cond) %}` |
| `craft.categoryGroups`          | `craft.app.categories` |
| `craft.fields`                  | `craft.app.fields` |
| `craft.sections`                | `craft.app.sections` |
| `craft.config`                  | `craft.app.config` |
| `craft.session`                 | `craft.app.session` |
| `craft.request`                 | `craft.app.request` |
| `craft.globals`                 | `craft.app.globals` |
| `craft.locale`                  | `craft.app.locale` |
| `craft.isLocalized`             | `craft.app.isMultiSite` |
| `craft.userGroups`              | `craft.app.userGroups` |
| `craft.userPermissions`         | `craft.app.userPermissions` |
| `craft.systemSettings`          | `craft.app.projectConfig.get('...')` |
| `craft.app.feeds.getFeed(url)`  | install `dodecastudio/craft-feedreader`, then `craft.feedreader.getFeed(url)` |
| `getCsrfInput()` / `getHeadHtml()` / `getFootHtml()` | `csrfInput()` / `head()` / `endBody()` |
| `round(x)` (function)           | `x\|round` (filter) |
| `nice(d)` / `localeDate(d)` etc. | `d\|date('short')` (see full table in upgrade docs) |
| `craft.users().all()` (intending active users) | `craft.users().status('active').all()` |
| `.source(x)` / `.sourceId(x)` on assets | `.volume(x)` / `.volumeId(x)` |

Edit one logical group at a time (e.g. all `.find()` → `.all()` in one
commit). Show diffs after each group. Do not bulk-rewrite without showing
diffs.

**Twig 3 stricter comparisons:** review any template comparing strings
with `==`, `!=`, `in`, `<`, `>` against numbers. Add explicit casts where
needed.

**Additional Twig 3 breakages to check manually:**
- `craft.session.isLoggedIn` has no equivalent on `craft.app.session` —
  replace with `currentUser is not null`.
- `loop.parent.loop` inside macros no longer works in Twig 3 (macros do not
  inherit the outer loop context). Pass the value explicitly as a macro argument.
- The `date` filter applied to a `null` value now returns the current
  date/time rather than an empty string. Guard with
  `{% if value %}{{ value|date(...) }}{% endif %}`.

### D.2 Update modules / custom PHP

Apply the matches from A.13:

- `craft\log\FileTarget` / `StreamLogTarget` → move to Monolog targets
  under `components.log.monologTargetConfig` in `config/app.php`.
- `App::getDefaultLogTargets()` / `App::logConfig` → use
  `components.log.targets` instead.
- Element-query `find/first/last/total` → as in D.1.
- `craft\services\Feeds` → no longer exists; use the feedreader plugin or
  inline `SimpleXMLElement`.

Show each diff. Do not "modernise" code beyond what is needed to make it
run on Craft 4.

### D.3 Filesystem / volume cleanup (if A.15 flagged)

`migrate/all` will have created one filesystem per volume automatically.
Check the result:

1. CP → **Settings → Filesystems** — confirm one per volume.
2. CP → **Settings → Volumes** — each should have a filesystem assigned.
3. For any volume without a public URL, set a **Transform filesystem** in
   its settings so CP thumbnails work.
4. If A.15 flagged a `config/volumes.php` file: it is no longer honoured.
   Move per-environment storage settings into the new filesystem entities
   using env vars on filesystem fields. Remove `config/volumes.php`.

Confirm assets still load on the front-end.

### D.4 Update entry scripts (optional but recommended)

The Craft 4 starter project (https://github.com/craftcms/craft) changed
`bootstrap.php`, `web/index.php` and `craft`. Most projects can keep
their existing scripts working on Craft 4, but the starter pattern is
worth adopting if A.10 flagged the legacy `ENVIRONMENT` → `CRAFT_ENVIRONMENT`
indirection (it almost always does).

If updating:
1. The Craft 4 starter project inlines bootstrap logic into `web/index.php`
   and `craft` — there is no standalone project-root `bootstrap.php`. Delete
   `bootstrap.php` and merge any custom constants or requires it contained
   (from A.10/A.17) into the two entry scripts before removing it.
2. Replace `web/index.php` and `craft` with the Craft 4 starter versions
   (https://github.com/craftcms/craft), preserving any local requires
   (e.g. `OurHelpers.php`) and custom constants.
3. Set `CRAFT_ENVIRONMENT` directly in `.env` for each environment
   (replacing the legacy `ENVIRONMENT` variable).

If not updating: leave the existing scripts and skip. They will continue
to work — this is housekeeping only.

### D.5 Logging configuration (only if D.2 changed log targets)
If custom log targets were used on Craft 3, port them to the Craft 4
Monolog config under `components.log.monologTargetConfig` in
`config/app.php`. Refer to `craft\log\MonologTarget` for defaults.

If you want 404s logged again (Craft 4 silences them by default), set
`components.log.monologTargetConfig.except` to **not** include
`yii\web\HttpException::class . ':404'`.

### D.6 MySQL charset conversion (optional, recommended)

Only run this if the user wants to align with Craft 4's recommended
`utf8mb4` charset defaults.

1. Take a fresh DB backup.
2. If charset env vars were added during the upgrade (rare for 3→4), set the
   appropriate collation for your server in `.env`:
   ```
   CRAFT_DB_CHARSET="utf8mb4"
   CRAFT_DB_COLLATION="utf8mb4_0900_ai_ci"   # MySQL 8
   # CRAFT_DB_COLLATION="utf8mb4_unicode_ci"  # MariaDB / MySQL 5.7
   ```
3. Run:
   ```bash
   php craft db/convert-charset
   ```
4. After completion, remove the temporary env vars (Craft uses the
   database's now-current values).

Skip entirely if the user has no charset issues — `migrate/all` does not
mandate conversion.

### D.7 Optional housekeeping
- Run `php craft up` periodically through the rest of D to apply any
  schema changes from plugins added/updated mid-flow.
- Clear caches: `php craft clear-caches/all`.
- Re-check CP Deprecation Warnings — anything still showing belongs in
  D.1 / D.2.

### D.8 Final commit
Confirm `git status` shows only intended changes. Commit:
- `composer.json`, `composer.lock`
- `config/project/` updates from rebuild + apply
- Template / module edits from D.1 / D.2
- Entry-script updates from D.4 (if done)

### D.9 Update state file
Update `PHASE:` at the top of `.craft4-upgrade.md` to `upgrade-done`, then
append a new `## Upgrade result` section:
```
## Upgrade result
CRAFT_TO: <installed Craft 4 version>
PLUGINS_DISABLED_FOR_UPGRADE: <list, or "(none)">
ENTRY_SCRIPTS_UPDATED: yes|no
CHARSET_CONVERTED: yes|no
```

### D.10 Deploy notes (ask first)

Ask: **Do you want upgrade-specific deploy notes generated, or do you
already have a deploy process you'll integrate these changes into?**
Default to the latter — only generate notes if the user opts in.

If notes are wanted, write to `CRAFT-4-UPGRADE-NOTES.md` (not `DEPLOY.md`)
and include *only* the upgrade-specific deltas — not generic deploy
steps. Template:

```markdown
# Craft 4 Upgrade Notes — [project name]
Generated [date]. Integrate these deltas into your existing deploy process.

## Upgrade summary
- Craft: [from] → [installed 4.x version]
- PHP requirement bumped to 8.0.2+ (confirm production)
- Plugins updated: [list with version bumps]
- Plugins removed: [list, or "none"]
- Plugins replaced: [list, or "none"]
- Templates patched: [count, with high-traffic file list]
- Entry scripts updated: [yes/no — if yes, note CRAFT_ENVIRONMENT must be in .env]
- Matching pre-upgrade code commit (rollback target): `[short SHA]`
- Matching pre-upgrade DB backup (rollback target): `[path/filename]`

## Production prerequisites (do before deploying)
- [ ] PHP 8.0.2+ on production
- [ ] PHP extensions `bcmath` and `intl` installed
- [ ] MySQL ≥ 5.7.8 / MariaDB ≥ 10.2.7
- [ ] Production .env has `CRAFT_ENVIRONMENT=production` (if entry scripts updated)

## Production re-enable
These plugins were disabled locally during the upgrade and must be re-enabled
on production after `project-config/apply` completes:
```bash
[for each handle in PLUGINS_DISABLED_FOR_UPGRADE that was NOT removed:]
php craft plugin/enable <handle>
```

## Post-deploy manual follow-up
- [ ] Confirm Craft [version] in CP footer
- [ ] Spot-check patched templates: [list 2–3 highest-traffic files]
- [ ] Filesystems → Volumes mapping intact (CP → Settings)
- [ ] Asset thumbnails render in CP
- [ ] Queue processing healthy
- [ ] CP Deprecation Warnings clear (or known-residual list documented)

## Rollback for this upgrade
This upgrade migrates the DB schema and drops `entrydrafts` / `entryversions`
if present. Restore code and DB to matching snapshots:
```bash
# 1. Restore DB from the pre-upgrade backup
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

## State file template

`.craft4-upgrade.md`:

```markdown
# Craft 4 Upgrade State
<!-- Generated by craft-4-upgrade. -->
<!-- Do not edit PHASE manually. -->

## Phase
PHASE: <audit-done | prep-done | upgrade-done>

## Environment
CRAFT_FROM: <version>
CRAFT_TARGET: <4.x version>
PHP: <version>
MYSQL_CMD: <e.g. "mysql -h 127.0.0.1 -u root">
DB_NAME: <database name>
DB_CHARSET_EXISTING: <existing CRAFT_DB_CHARSET value, or "(none)">

## Plugin targets
| package | Craft 3 version | Craft 4 target | status (OK/REPLACE/REMOVE/BLOCKER) | notes |
|---------|-----------------|----------------|-------------------------------------|-------|
| ...     | ...             | ...            | ...                                 | ...   |

## Reserved field handle remediations (renamed on Craft 3)
<!-- Empty table if A.14 found none. -->
| old handle | context (entry / matrix / ST / user / asset) | new handle |
|------------|---------------------------------------------|------------|

## Removed general.php keys
REMOVED_GENERAL_KEYS:
  - <key>

## Entry script status
LEGACY_ENVIRONMENT_INDIRECTION: yes|no
CUSTOM_BOOTSTRAP_NOTES:
  - <description or "(none)">

## Template audit (from A.12)
TEMPLATES_REMOVED_QUERY_METHODS:
  - <file:line>
TEMPLATES_REMOVED_TWIG_TAGS:
  - <file:line>
TEMPLATES_REMOVED_CRAFT_VARS:
  - <file:line>
TEMPLATES_REMOVED_FUNCTIONS:
  - <file:line>
TEMPLATES_USER_QUERY_DEFAULT:
  - <file:line>

## Module audit (from A.13)
MODULE_BREAKING_REFS:
  - <file:line: pattern>

## Volumes / filesystems
HAS_VOLUMES_PHP: yes|no
VOLUMES:
  - handle: <h>, type: <t>, hasUrls: <bool>, transformFs: <h or "(needs setting)">

## Queue
QUEUE_PENDING_PRE_UPGRADE: <count>

## Legacy tables
LEGACY_DRAFT_TABLES: yes|no  (rows: drafts=<n>, versions=<n>)

## Deprecation warnings (Craft 3 CP)
DEPRECATION_WARNINGS_PRE_UPGRADE: <count>

## Composer hook
COMPOSER_POST_UPDATE_HOOK: yes|no

## Plugins disabled for upgrade
PLUGINS_DISABLED_FOR_UPGRADE:
  - <handle>

## Blockers
BLOCKERS: none | <list>

## Notes
<any additional audit notes>
```
