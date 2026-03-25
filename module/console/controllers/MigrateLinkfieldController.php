<?php

namespace modules\console\controllers;

use Craft;
use craft\fieldlayoutelements\CustomField;
use craft\fields\Link as NativeLinkField;
use craft\helpers\Json;
use yii\console\Controller;
use yii\console\ExitCode;
use yii\helpers\Console;

/**
 * Migrates sebastianlenz/linkfield (Typed Link Field) data to Craft 5's native Link field.
 *
 * Usage:
 *   php craft my-module/migrate-linkfield/run [--dry-run] [--cleanup] [--field=handle] [--suffix=_v2]
 */
class MigrateLinkfieldController extends Controller
{
    // -------------------------------------------------------------------------
    // Options
    // -------------------------------------------------------------------------

    /** Preview what would be migrated without writing anything. */
    public bool $dryRun = false;

    /** After migrating, delete old fields. */
    public bool $cleanup = false;

    /** Migrate only the field with this handle. */
    public ?string $field = null;

    /** Suffix appended to old handle to produce the new handle. Default: _v2 */
    public string $suffix = '_v2';

    // -------------------------------------------------------------------------
    // Yii option wiring
    // -------------------------------------------------------------------------

    public function options($actionID): array
    {
        return array_merge(parent::options($actionID), ['dryRun', 'cleanup', 'field', 'suffix']);
    }

    public function optionAliases(): array
    {
        return array_merge(parent::optionAliases(), [
            'd' => 'dryRun',
            'c' => 'cleanup',
            'f' => 'field',
            's' => 'suffix',
        ]);
    }

    // -------------------------------------------------------------------------
    // Actions
    // -------------------------------------------------------------------------

    /**
     * Audit, then migrate Typed Link Field data to native Craft 5 Link fields.
     */
    public function actionRun(): int
    {
        $this->stdout("\n");
        $this->stdout("=== Typed Link Field → Native Link Migration ===\n", Console::FG_CYAN, Console::BOLD);
        $this->stdout("\n");

        $sourceFields = $this->discoverLinkFields();

        if (empty($sourceFields)) {
            $this->stdout("No Typed Link Fields found. Nothing to do.\n", Console::FG_GREEN);
            return ExitCode::OK;
        }

        $this->printAudit($sourceFields);

        if ($this->dryRun) {
            $this->stdout("\n[Dry-run mode] No changes written.\n", Console::FG_YELLOW);
            return ExitCode::OK;
        }

        $this->stdout("\n");
        $confirm = $this->prompt(
            'This will modify live element data. Have you taken a database backup? [yes/no]',
            ['default' => 'no']
        );
        if (strtolower(trim($confirm)) !== 'yes') {
            $this->stdout("Aborted. Please take a backup first.\n", Console::FG_RED);
            return ExitCode::OK;
        }

        $summary = [];

        foreach ($sourceFields as $oldField) {
            $oldHandle = $oldField->handle;
            $newHandle = $oldHandle . $this->suffix;

            $this->stdout("\n--- Migrating field: {$oldHandle} → {$newHandle} ---\n", Console::FG_CYAN);

            $newField = $this->ensureNativeLinkField($oldField, $newHandle);
            if ($newField === null) {
                $this->stderr("  [ERROR] Could not create native Link field for {$oldHandle}. Skipping.\n", Console::FG_RED);
                $summary[$oldHandle] = ['migrated' => 0, 'skipped' => 0, 'status' => 'ERROR'];
                continue;
            }

            $this->addFieldToLayouts($oldField, $newField);

            [$migrated, $skipped] = $this->migrateFieldData($oldField, $newField);

            $summary[$oldHandle] = ['migrated' => $migrated, 'skipped' => $skipped, 'status' => 'OK'];
            $this->stdout("  Migrated: {$migrated}  Skipped: {$skipped}\n", Console::FG_GREEN);

            if ($this->cleanup) {
                $this->cleanupOldField($oldField);
            }
        }

        $this->printSummary($summary);

        if ($this->cleanup) {
            $this->stdout("\n");
            $this->stdout("[Cleanup] Old fields removed. Now run:\n", Console::FG_YELLOW);
            $this->stdout("  composer remove sebastianlenz/linkfield\n", Console::FG_YELLOW);
            $this->stdout("  php craft project-config/apply\n", Console::FG_YELLOW);
        }

        $this->stdout("\nDone.\n", Console::FG_GREEN, Console::BOLD);
        return ExitCode::OK;
    }

    // -------------------------------------------------------------------------
    // Discovery
    // -------------------------------------------------------------------------

    /** @return \lenz\linkfield\fields\LinkField[] */
    private function discoverLinkFields(): array
    {
        $found = [];
        foreach (Craft::$app->getFields()->getAllFields() as $field) {
            if (!($field instanceof \lenz\linkfield\fields\LinkField)) {
                continue;
            }
            if ($this->field !== null && $field->handle !== $this->field) {
                continue;
            }
            $found[] = $field;
        }
        return $found;
    }

    // -------------------------------------------------------------------------
    // Audit
    // -------------------------------------------------------------------------

    private function printAudit(array $sourceFields): void
    {
        $this->stdout("Fields found:\n", Console::BOLD);
        foreach ($sourceFields as $field) {
            $count = $this->countPopulatedElements($field);
            $this->stdout(sprintf(
                "  %-28s → %-28s  rows: %s\n",
                $field->handle,
                $field->handle . $this->suffix,
                $count
            ));
        }
    }

    /**
     * Count rows in the lenz_linkfield table for this field.
     * Direct DB query — avoids :notempty: element query compatibility issues
     * with sebastianlenz/craft-utils's ForeignFieldQueryExtension.
     */
    private function countPopulatedElements(\lenz\linkfield\fields\LinkField $field): int
    {
        return (int) Craft::$app->getDb()->createCommand(
            'SELECT COUNT(DISTINCT [[elementId]]) FROM {{%lenz_linkfield}} WHERE [[fieldId]] = :fieldId',
            [':fieldId' => $field->id]
        )->queryScalar();
    }

    // -------------------------------------------------------------------------
    // Native field creation
    // -------------------------------------------------------------------------

    private function ensureNativeLinkField(
        \lenz\linkfield\fields\LinkField $oldField,
        string $newHandle
    ): ?NativeLinkField {
        $fieldsService = Craft::$app->getFields();

        $existing = $fieldsService->getFieldByHandle($newHandle);
        if ($existing instanceof NativeLinkField) {
            // Ensure target support is enabled on already-created fields
            if (!in_array('target', $existing->advancedFields ?? [], true)) {
                $existing->advancedFields = array_merge($existing->advancedFields ?? [], ['target']);
                $fieldsService->saveField($existing);
                $this->stdout("  Updated '{$newHandle}' to enable target support.\n");
            }
            $this->stdout("  Native field '{$newHandle}' already exists. Reusing.\n");
            return $existing;
        }

        $newField = new NativeLinkField([
            'name'              => $oldField->name,
            'handle'            => $newHandle,
            'instructions'      => $oldField->instructions ?? '',
            'translationMethod' => $oldField->translationMethod,
            // 'types' is the correct Craft 5 property name (not 'allowedLinkTypes')
            'types'             => $this->resolveEnabledTypes($oldField),
            // 'advancedFields' enables target (_blank) support for migrated values
            'advancedFields'    => ['target'],
            // Note: 'groupId' is intentionally omitted — field groups were removed in Craft 5
        ]);

        if (!$fieldsService->saveField($newField)) {
            $this->stderr("  [ERROR] Save failed: " . implode(', ', $newField->getFirstErrors()) . "\n", Console::FG_RED);
            return null;
        }

        $this->stdout("  Created native Link field '{$newHandle}' (id: {$newField->id}).\n");
        return $newField;
    }

    /**
     * Resolve the enabled link types from the old field's settings.
     * Maps Typed Link Field type names to Craft 5 native Link field type names.
     */
    private function resolveEnabledTypes(\lenz\linkfield\fields\LinkField $oldField): array
    {
        $typeMap = [
            'url'      => 'url',
            'entry'    => 'entry',
            'asset'    => 'asset',
            'category' => 'category',
            'email'    => 'email',
            'tel'      => 'phone',
            'phone'    => 'phone',
            'custom'   => 'url',
            'site'     => 'site',
        ];

        $enabled = [];
        try {
            $allowedNames = $oldField->getSettings()['allowedLinkNames'] ?? null;
            if (is_array($allowedNames)) {
                foreach ($allowedNames as $name) {
                    $mapped = $typeMap[$name] ?? null;
                    if ($mapped && !in_array($mapped, $enabled, true)) {
                        $enabled[] = $mapped;
                    }
                }
            }
        } catch (\Throwable) {
            // Fall back to a sensible default
        }

        return $enabled ?: ['url', 'entry', 'asset', 'email'];
    }

    // -------------------------------------------------------------------------
    // Field layout insertion — Craft 5 OO API
    // -------------------------------------------------------------------------

    /**
     * Insert the new native Link field adjacent to the old field in every
     * field layout that contains the old field.
     *
     * Uses Craft 5's FieldLayout OO API. The fieldlayoutfields table was
     * removed in Craft 5 — do not query it directly.
     */
    private function addFieldToLayouts(
        \lenz\linkfield\fields\LinkField $oldField,
        NativeLinkField $newField
    ): void {
        $fieldsService = Craft::$app->getFields();
        $modified = 0;

        foreach ($fieldsService->getAllLayouts() as $layout) {
            $layoutModified = false;

            foreach ($layout->getTabs() as $tab) {
                $elements = $tab->getElements();
                $hasOld = $hasNew = false;

                foreach ($elements as $el) {
                    if (!($el instanceof CustomField)) continue;
                    $f = $el->getField();
                    if ($f?->id === $oldField->id) $hasOld = true;
                    if ($f?->id === $newField->id) $hasNew = true;
                }

                if (!$hasOld || $hasNew) continue;

                $newElements = [];
                foreach ($elements as $el) {
                    $newElements[] = $el;
                    // Insert new field immediately after old field
                    if ($el instanceof CustomField && $el->getField()?->id === $oldField->id) {
                        // Correct Craft 5 constructor: new CustomField($fieldInstance)
                        $newElements[] = new CustomField($newField);
                    }
                }

                $tab->setElements($newElements);
                $layoutModified = true;
            }

            if ($layoutModified) {
                $fieldsService->saveLayout($layout);
                $modified++;
            }
        }

        $this->stdout("  Added '{$newField->handle}' to {$modified} layout(s).\n");
    }

    // -------------------------------------------------------------------------
    // Data migration — direct DB query against lenz_linkfield table
    // -------------------------------------------------------------------------

    /**
     * Migrate all rows for this field from the lenz_linkfield table.
     *
     * IMPORTANT: Do NOT use Entry::find()->{$handle}(':notempty:')->all() here.
     * sebastianlenz/craft-utils's ForeignFieldQueryExtension throws
     * "The query value for the field must be an array" for :notempty: shorthand,
     * and the exception is caught silently — resulting in zero rows migrated
     * with no visible error.
     *
     * @return array{int, int} [migrated, skipped]
     */
    private function migrateFieldData(
        \lenz\linkfield\fields\LinkField $oldField,
        NativeLinkField $newField
    ): array {
        $migrated = 0;
        $skipped  = 0;

        $rows = Craft::$app->getDb()->createCommand(
            'SELECT [[elementId]], [[siteId]], [[type]], [[linkedUrl]], [[linkedId]], [[payload]]
             FROM {{%lenz_linkfield}}
             WHERE [[fieldId]] = :fieldId',
            [':fieldId' => $oldField->id]
        )->queryAll();

        foreach ($rows as $row) {
            try {
                $element = Craft::$app->getElements()->getElementById(
                    (int)$row['elementId'],
                    null,
                    (int)$row['siteId']
                );

                if (!$element) {
                    $skipped++;
                    $this->stdout(
                        "  [Skip] Element #{$row['elementId']} site #{$row['siteId']} — not found.\n",
                        Console::FG_YELLOW
                    );
                    continue;
                }

                $mapped = $this->mapDbRow($row);

                if ($mapped === null) {
                    $skipped++;
                    $this->stdout(
                        "  [Skip] Element #{$row['elementId']} — unmappable type '{$row['type']}'.\n",
                        Console::FG_YELLOW
                    );
                    continue;
                }

                $element->setFieldValue($newField->handle, $mapped);

                if (!Craft::$app->getElements()->saveElement($element, false)) {
                    $skipped++;
                    $this->stderr(
                        "  [ERROR] Element #{$element->id} save failed: " .
                        implode(', ', $element->getFirstErrors()) . "\n",
                        Console::FG_RED
                    );
                    continue;
                }

                $migrated++;

            } catch (\Throwable $e) {
                $skipped++;
                $this->stderr(
                    "  [ERROR] Element #{$row['elementId']}: " . $e->getMessage() . "\n",
                    Console::FG_RED
                );
            }
        }

        return [$migrated, $skipped];
    }

    /**
     * Map a row from the lenz_linkfield DB table to the array format
     * expected by craft\fields\Link.
     *
     * lenz_linkfield columns used:
     *   type      — 'url', 'entry', 'asset', 'category', 'email', 'tel', 'site', 'custom', 'user'
     *   linkedUrl — populated for URL-based types
     *   linkedId  — element ID for element-based types
     *   payload   — JSON blob containing customText, target, and other metadata
     */
    private function mapDbRow(array $row): ?array
    {
        $type = $row['type'] ?? null;
        if (!$type) return null;

        $mappedType = $this->mapTypeName($type);
        if ($mappedType === null) return null; // 'user' and unknown types are skipped

        // Element-based types use linkedId; URL-based types use linkedUrl
        if (in_array($mappedType, ['entry', 'asset', 'category', 'site'], true)) {
            $value = $row['linkedId'] ? (int)$row['linkedId'] : null;
        } else {
            $value = $row['linkedUrl'] ?? null;
        }

        if (!$value) return null;

        $result = ['type' => $mappedType, 'value' => $value];

        // Extract label and target from the payload JSON blob
        if (!empty($row['payload'])) {
            $payload = Json::decodeIfJson($row['payload']);
            if (is_array($payload)) {
                $label = $payload['customText'] ?? $payload['label'] ?? null;
                if ($label !== null && $label !== '') {
                    $result['label'] = $label;
                }
                if (!empty($payload['target'])) {
                    $result['target'] = $payload['target'];
                }
            }
        }

        return $result;
    }

    /**
     * Map Typed Link Field type → Craft 5 native Link field type.
     * Returns null for types with no native equivalent (e.g. 'user').
     */
    private function mapTypeName(string $type): ?string
    {
        return match ($type) {
            'tel'    => 'phone',
            'custom' => 'url',
            'user'   => null,
            default  => $type,
        };
    }

    // -------------------------------------------------------------------------
    // Cleanup
    // -------------------------------------------------------------------------

    private function cleanupOldField(\lenz\linkfield\fields\LinkField $field): void
    {
        $this->stdout("  [Cleanup] Deleting old field '{$field->handle}'...\n", Console::FG_YELLOW);
        if (!Craft::$app->getFields()->deleteField($field)) {
            $this->stderr("  [ERROR] Could not delete field '{$field->handle}'.\n", Console::FG_RED);
        }
    }

    // -------------------------------------------------------------------------
    // Summary
    // -------------------------------------------------------------------------

    private function printSummary(array $summary): void
    {
        $this->stdout("\n");
        $this->stdout("=== Summary ===\n", Console::FG_CYAN, Console::BOLD);
        $this->stdout(sprintf("%-28s  %-10s  %-10s  %s\n", 'Field', 'Migrated', 'Skipped', 'Status'));
        $this->stdout(str_repeat('-', 62) . "\n");

        foreach ($summary as $handle => $row) {
            $statusColor = $row['status'] === 'OK' ? Console::FG_GREEN : Console::FG_RED;
            $this->stdout(sprintf("%-28s  %-10s  %-10s  ", $handle, $row['migrated'], $row['skipped']));
            $this->stdout($row['status'] . "\n", $statusColor);
        }
    }
}
