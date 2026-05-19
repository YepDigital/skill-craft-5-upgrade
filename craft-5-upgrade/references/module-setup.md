# Migration Module Setup

Read this file when executing Block 2.3 (Install the migration module).

---

## Files to copy

Copy the following files from this skill's `module/` directory into the project:

| Source (skill) | Destination (project) |
|---|---|
| `module/Module.php` | `modules/Module.php` |
| `module/console/controllers/MigrateLinkfieldController.php` | `modules/console/controllers/MigrateLinkfieldController.php` |

## Register the module in `config/app.php`

Refer to this skill's `module/app.php` for the exact keys. Merge the following
into the existing `config/app.php` return array. Do not replace the file — only
add the missing `modules` and `bootstrap` entries:

```php
'modules' => [
    'my-module' => \modules\Module::class,
],
'bootstrap' => ['my-module'],
```

## PSR-4 autoload in `composer.json`

Confirm `composer.json` has:

```json
"autoload": {
    "psr-4": {
        "modules\\": "modules/"
    }
}
```

Add the `"modules\\": "modules/"` entry if absent. Do not run `composer update` yet.
