<?php
/**
 * Merge-snippet for the linkfield migration module.
 *
 * These keys must be present in the project's config/app.php for the
 * migration module to load. Merge them into the existing return array.
 *
 * Do NOT use this file as a standalone config/app.php.
 */

// Keys to merge into the existing config/app.php return array:
return [
    'modules' => [
        'my-module' => \modules\Module::class,
    ],
    'bootstrap' => ['my-module'],
];
