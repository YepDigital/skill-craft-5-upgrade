# DEPLOY.md Template — Linkfield present (DB-push deployment)

The linkfield data migration has already run in the local database. The local
Craft 5 DB must be pushed to production — do not run migration commands on production.

Content delta: this deployment overwrites the production database with the local
migrated copy. Any content added to production after the initial local DB snapshot
was taken will be lost. Put the site in maintenance mode first.

Fill in all `[placeholders]` from the session's recorded values before writing the file.

```markdown
# Craft 5 Production Deployment — [project name]
Generated [date].

## Upgrade summary
- Craft version: [version from Block 3.5]
- Linkfield fields migrated: [handles from Block 1.7, e.g. linkUrl → linkUrl_v2]
- Templates patched: [list from Block 5]
- fields/auto-merge migration files committed: [yes / no]

## ⚠ Content delta warning
This deployment replaces the production database with the local migrated database.
Any content added to production after [date of original local DB snapshot] will be
overwritten. Put production in maintenance mode before pushing the DB.

## Pre-deployment checklist
- [ ] Local site fully verified — all linkfield entries display correctly in browser
- [ ] All code committed (modules/, config/project/, templates, composer.json/lock)
- [ ] Fresh production DB backup taken and stored safely off-server
- [ ] Maintenance window communicated to content editors

## Deployment steps

### 1. Export local Craft 5 database
```bash
[MYSQL_CMD] [db_name] > ~/Desktop/[project]-craft5-[date].sql
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
- Hosting panel: use DB import tool, select the exported .sql file
- TablePlus / Sequel Pro: connect to production DB and run File > Import]

### 6. Run Craft upgrade
```bash
php craft up
php craft project-config/apply
```

### 7. Verify
- [ ] Log into Craft CP — confirm Craft [version] in footer
- [ ] Open an entry containing field [first _v2 handle] — confirm link renders correctly
- [ ] Load [a URL from a patched template] in browser — confirm no errors
- [ ] Check logs: `tail -n 50 storage/logs/web.log`

### 8. Exit maintenance mode
[Reverse of step 2]

## Rollback
If anything is wrong, restore the production backup from the Pre-deployment checklist:
```bash
[DB import command] < /path/to/craft4-production-backup.sql
git checkout [craft4-branch] && composer install --no-dev && php craft up
```
```
