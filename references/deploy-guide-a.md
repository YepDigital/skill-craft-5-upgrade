# DEPLOY.md Template — No linkfield (standard code deployment)

No DB push needed. Craft's migrations and project config carry all changes.
Fill in all `[placeholders]` from the session's recorded values before writing the file.

```markdown
# Craft 5 Production Deployment — [project name]
Generated [date].

## Upgrade summary
- Craft version: [version from Block 3.5]
- Plugins updated: [list from Block 3.3]
- Templates patched: [list from Block 5, or "none"]
- fields/auto-merge migration files committed: [yes / no]

## Deployment steps

### 1. Deploy code
[Deployment command or steps based on their method, e.g.:
- Forge: trigger deploy via dashboard or `forge deploy <site-id>`
- Git + SSH: `git push origin main` then `ssh user@host "cd /path && git pull"`
- Generic SSH: log into server, `cd /path/to/site && git pull origin main`]

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
