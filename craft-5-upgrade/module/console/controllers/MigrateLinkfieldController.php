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
 *   php craft my-module/migrate-linkfield/run-direct [--dry-run] [--cleanup] [--field=handle] [--suffix=_v2]
 *
 * Recommended path: run-direct
 *   Bypasses plugin field instantiation entirely — works when sebastianlenz/linkfield
 *   3.0.0-beta cannot instantiate Craft 4-era field settings. Discovers old fields via
 *   direct DB query, auto-creates missing _v2 native Link fields from raw settings JSON,
 *   then migrates all element data. Safe to re-run (idempotent per element).
 *
 * Fallback path: run
 *   Uses the plugin's own field instantiation to discover fields, create _v2 fields,
 *   and migrate data. Use if run-direct reports no fields in the DB.
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
     * Fallback path — use run-direct instead if this reports "No Typed Link Fields found."
     */
    public function actionRun(): int
    {
        $this->stdout("\n");
        $this->stdout("=== Typed Link Field → Native Link Migration ===\n", Console::FG_CYAN, Console::BOLD);
        $this->stdout("\n");

        $sourceFields = $this->discoverLinkFields();

        if (empty($sourceFields)) {
            $this->stdout("No Typed Link Fields found. Nothing to do.\n", Console::FG_GREEN);
            $this->stdout("(If fields exist but are not found, the beta plugin may not be able\n");
            $this->stdout("to instantiate Craft 4 field settings. Try: run-direct instead.)\n", Console::FG_YELLOW);
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

            [$migrated, $skipReasons] = $this->migrateFieldData($oldField, $newField);
            $skipped = array_sum($skipReasons);

            $summary[$oldHandle] = [
                'migrated' => $migrated,
                'skipped' => $skipped,
                'skipReasons' => $skipReasons,
                'status' => 'OK',
            ];
            $breakdown = $this->formatSkipBreakdown($skipReasons);
            $detail = $breakdown ? " ({$breakdown})" : '';
            $this->stdout("  Migrated: {$migrated}  Skipped: {$skipped}{$detail}\n", Console::FG_GREEN);

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

    /**
     * Recommended path. Discovers old fields and auto-creates _v2 native Link fields
     * via direct DB queries — bypasses plugin field instantiation entirely.
     *
     * Works when sebastianlenz/linkfield 3.0.0-beta cannot instantiate Craft 4-era
     * field settings (causing `run` to report "No Typed Link Fields found").
     *
     * Auto-creates _v2 native fields from the raw settings JSON if they do not
     * already exist. Safe to re-run: existing _v2 field values are overwritten
     * (idempotent per element).
     *
     * Use --cleanup to delete old zombie field records after migration.
     *
     * Note: field layout insertion is attempted but may silently skip if the old
     * field type cannot be instantiated. After migration, verify that _v2 fields
     * appear in entry type layouts in the CP; add manually if missing.
     */
    public function actionRunDirect(): int
    {
        $this->stdout("\n=== Typed Link Field → Native Link Migration (direct DB mode) ===\n", Console::FG_CYAN, Console::BOLD);
        $this->stdout("Discovering fields and creating targets via DB (bypasses plugin instantiation).\n\n");

        $oldFields = Craft::$app->getDb()->createCommand(
            'SELECT [[id]], [[handle]], [[name]], [[settings]] FROM {{%fields}} WHERE [[type]] = :type',
            [':type' => 'lenz\linkfield\fields\LinkField']
        )->queryAll();

        if (empty($oldFields)) {
            $this->stdout("No Typed Link Field entries found in fields table. Nothing to do.\n", Console::FG_GREEN);
            $this->stdout("(If you expected fields, check that sebastianlenz/linkfield was\n");
            $this->stdout("installed before the upgrade. Try: run instead.)\n", Console::FG_YELLOW);
            return ExitCode::OK;
        }

        $plan = [];
        foreach ($oldFields as $row) {
            if ($this->field !== null && $row['handle'] !== $this->field) {
                continue;
            }

            $newHandle = $row['handle'] . $this->suffix;

            // Auto-create _v2 native field if it does not already exist.
            $newField = $this->ensureNativeLinkFieldFromSettings(
                (int)$row['id'],
                $row['handle'],
                $row['name'],
                $row['settings']
            );

            $count = (int) Craft::$app->getDb()->createCommand(
                'SELECT COUNT(DISTINCT [[elementId]]) FROM {{%lenz_linkfield}} WHERE [[fieldId]] = :fieldId',
                [':fieldId' => $row['id']]
            )->queryScalar();

            if ($newField instanceof NativeLinkField) {
                $this->stdout(sprintf(
                    "  ID %-5s %-28s → %-28s  rows: %-6s  [OK]\n",
                    $row['id'], $row['handle'], $newHandle, $count
                ));
                $plan[(int)$row['id']] = ['handle' => $row['handle'], 'newField' => $newField];
            } else {
                $this->stdout(sprintf(
                    "  ID %-5s %-28s → %-28s  rows: %-6s  [ERROR — could not create target]\n",
                    $row['id'], $row['handle'], $newHandle, $count
                ), Console::FG_RED);
            }
        }

        if ($this->dryRun) {
            $this->stdout("\n[Dry-run mode] No changes written.\n", Console::FG_YELLOW);
            return ExitCode::OK;
        }

        if (empty($plan)) {
            $this->stderr("\nNo target fields could be created. See errors above.\n", Console::FG_RED);
            return ExitCode::UNSPECIFIED_ERROR;
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

        foreach ($plan as $oldId => $info) {
            $this->stdout("\n--- {$info['handle']} → {$info['newField']->handle} ---\n", Console::FG_CYAN);

            $rows = Craft::$app->getDb()->createCommand(
                'SELECT [[elementId]], [[siteId]], [[type]], [[linkedUrl]], [[linkedId]], [[payload]]
                 FROM {{%lenz_linkfield}} WHERE [[fieldId]] = :fieldId',
                [':fieldId' => $oldId]
            )->queryAll();

            [$migrated, $skipReasons] = $this->migrateRowsDirect($rows, $info['newField']->handle);
            $skipped = array_sum($skipReasons);

            $summary[$info['handle']] = [
                'migrated' => $migrated,
                'skipped' => $skipped,
                'skipReasons' => $skipReasons,
                'status' => 'OK',
            ];
            $breakdown = $this->formatSkipBreakdown($skipReasons);
            $detail = $breakdown ? " ({$breakdown})" : '';
            $this->stdout("  Migrated: {$migrated}  Skipped: {$skipped}{$detail}\n", Console::FG_GREEN);

            if ($this->cleanup) {
                $this->stdout("  [Cleanup] Deleting zombie field '{$info['handle']}' (ID: {$oldId})...\n", Console::FG_YELLOW);
                $this->deleteFieldById($oldId);
            }
        }

        $this->printSummary($summary);
        $this->printLayoutElementUids($plan);

        if ($this->cleanup) {
            $this->stdout("\n[Cleanup] Zombie fields removed. Run `php craft project-config/apply` to sync.\n", Console::FG_YELLOW);
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
    // Native field creation — plugin-instantiation path (actionRun)
    // -------------------------------------------------------------------------

    private function ensureNativeLinkField(
        \lenz\linkfield\fields\LinkField $oldField,
        string $newHandle
    ): ?NativeLinkField {
        $fieldsService = Craft::$app->getFields();
        $hasCustomText = $this->sourceFieldHasCustomText($oldField->id);

        $existing = $fieldsService->getFieldByHandle($newHandle);
        if ($existing instanceof NativeLinkField) {
            $changed = false;
            if (!in_array('target', $existing->advancedFields ?? [], true)) {
                $existing->advancedFields = array_merge($existing->advancedFields ?? [], ['target']);
                $changed = true;
            }
            if ($hasCustomText && !($existing->showLabelField ?? false)) {
                $existing->showLabelField = true;
                $changed = true;
            }
            if ($changed) {
                $fieldsService->saveField($existing);
                $this->stdout("  Updated '{$newHandle}' settings (showLabelField / target).\n");
            }
            $this->stdout("  Native field '{$newHandle}' already exists. Reusing.\n");
            return $existing;
        }

        $newField = new NativeLinkField([
            'name'              => $oldField->name,
            'handle'            => $newHandle,
            'instructions'      => $oldField->instructions ?? '',
            'translationMethod' => $oldField->translationMethod,
            'types'             => $this->resolveEnabledTypes($oldField),
            'advancedFields'    => ['target'],
            'showLabelField'    => $hasCustomText,
        ]);

        if ($hasCustomText) {
            $labelRowCount = $this->countCustomTextRows($oldField->id);
            $this->stdout("  Enabled showLabelField on '{$newHandle}' ({$labelRowCount} source rows with customText).\n", Console::FG_CYAN);
        }

        if (!$fieldsService->saveField($newField)) {
            $this->stderr("  [ERROR] Save failed: " . implode(', ', $newField->getFirstErrors()) . "\n", Console::FG_RED);
            return null;
        }

        $this->stdout("  Created native Link field '{$newHandle}' (id: {$newField->id}).\n");
        return $newField;
    }

    /**
     * Resolve enabled link types from the typed field object's settings.
     * Used by actionRun (plugin-instantiation path).
     */
    private function resolveEnabledTypes(\lenz\linkfield\fields\LinkField $oldField): array
    {
        $settings = [];
        try {
            $settings = $oldField->getSettings();
        } catch (\Throwable) {
        }
        return $this->resolveEnabledTypesFromSettings(is_array($settings) ? $settings : []);
    }

    // -------------------------------------------------------------------------
    // Native field creation — direct DB path (actionRunDirect)
    // -------------------------------------------------------------------------

    /**
     * Find or create the _v2 native Link field using raw DB data.
     * Does not require the old field type to be instantiable.
     */
    private function ensureNativeLinkFieldFromSettings(
        int $oldId,
        string $oldHandle,
        string $name,
        ?string $settingsJson
    ): ?NativeLinkField {
        $newHandle    = $oldHandle . $this->suffix;
        $fieldsService = Craft::$app->getFields();

        $hasCustomText = $this->sourceFieldHasCustomText($oldId);

        $existing = $fieldsService->getFieldByHandle($newHandle);
        if ($existing instanceof NativeLinkField) {
            $changed = false;
            if (!in_array('target', $existing->advancedFields ?? [], true)) {
                $existing->advancedFields = array_merge($existing->advancedFields ?? [], ['target']);
                $changed = true;
            }
            // Re-enable showLabelField if it was disabled but source has labels.
            if ($hasCustomText && !($existing->showLabelField ?? false)) {
                $existing->showLabelField = true;
                $changed = true;
            }
            if ($changed) {
                $fieldsService->saveField($existing);
                $this->stdout("  Updated '{$newHandle}' settings (showLabelField / target).\n");
            }
            $this->stdout("  Native field '{$newHandle}' already exists. Reusing.\n");
            // Still add the existing _v2 field to THIS source field's layouts.
            // Without this, second-and-subsequent source fields sharing a target
            // handle silently no-op every saveElement (target not in source's layout).
            $this->addFieldToLayoutsById($oldId, $existing);
            return $existing;
        }

        $settings = $settingsJson ? Json::decodeIfJson($settingsJson) : [];
        $newField = new NativeLinkField([
            'name'           => $name,
            'handle'         => $newHandle,
            'types'          => $this->resolveEnabledTypesFromSettings(is_array($settings) ? $settings : []),
            'advancedFields' => ['target'],
            'showLabelField' => $hasCustomText,
        ]);

        if ($hasCustomText) {
            $labelRowCount = $this->countCustomTextRows($oldId);
            $this->stdout("  Enabled showLabelField on '{$newHandle}' ({$labelRowCount} source rows with customText).\n", Console::FG_CYAN);
        }

        if (!$fieldsService->saveField($newField)) {
            $this->stderr(
                "  [ERROR] Could not create '{$newHandle}': " .
                implode(', ', $newField->getFirstErrors()) . "\n",
                Console::FG_RED
            );
            return null;
        }

        $this->stdout("  Created native Link field '{$newHandle}' (id: {$newField->id}).\n");

        // Attempt layout insertion. This may silently skip if the old field
        // type cannot be instantiated (getField() returns null for unregistered
        // types). If _v2 fields are not visible in CP layouts after migration,
        // add them manually via the entry type editor.
        $this->addFieldToLayoutsById($oldId, $newField);

        return $newField;
    }

    /**
     * Return true if the source field has any non-empty customText in its payload.
     * Used to decide whether to enable showLabelField on the destination _v2 field.
     */
    private function sourceFieldHasCustomText(int $fieldId): bool
    {
        $result = Craft::$app->getDb()->createCommand(
            'SELECT 1 FROM {{%lenz_linkfield}}
             WHERE [[fieldId]] = :fieldId
               AND JSON_EXTRACT([[payload]], :path) IS NOT NULL
               AND JSON_UNQUOTE(JSON_EXTRACT([[payload]], :path)) <> \'\'
             LIMIT 1',
            [':fieldId' => $fieldId, ':path' => '$.customText']
        )->queryScalar();
        return (bool)$result;
    }

    private function countCustomTextRows(int $fieldId): int
    {
        return (int) Craft::$app->getDb()->createCommand(
            'SELECT COUNT(*) FROM {{%lenz_linkfield}}
             WHERE [[fieldId]] = :fieldId
               AND JSON_EXTRACT([[payload]], :path) IS NOT NULL
               AND JSON_UNQUOTE(JSON_EXTRACT([[payload]], :path)) <> \'\'',
            [':fieldId' => $fieldId, ':path' => '$.customText']
        )->queryScalar();
    }

    /**
     * Resolve enabled link types from raw settings JSON.
     * Used by both ensureNativeLinkField (via resolveEnabledTypes) and
     * ensureNativeLinkFieldFromSettings.
     */
    private function resolveEnabledTypesFromSettings(?array $settings): array
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

        $allowedNames = $settings['allowedLinkNames'] ?? null;
        if (!is_array($allowedNames)) {
            return ['url', 'entry', 'asset', 'email'];
        }

        $enabled = [];
        foreach ($allowedNames as $name) {
            $mapped = $typeMap[$name] ?? null;
            if ($mapped && !in_array($mapped, $enabled, true)) {
                $enabled[] = $mapped;
            }
        }
        return $enabled ?: ['url', 'entry', 'asset', 'email'];
    }

    // -------------------------------------------------------------------------
    // Field layout insertion — Craft 5 OO API
    // -------------------------------------------------------------------------

    /**
     * Insert the new native Link field adjacent to the old field in every
     * field layout that contains the old field (plugin-instantiation path).
     *
     * Uses Craft 5's FieldLayout OO API. The fieldlayoutfields table was
     * removed in Craft 5 — do not query it directly.
     */
    private function addFieldToLayouts(
        \lenz\linkfield\fields\LinkField $oldField,
        NativeLinkField $newField
    ): void {
        $this->addFieldToLayoutsById($oldField->id, $newField);
    }

    /**
     * Insert the new native Link field adjacent to the old field in every
     * layout that contains the old field's ID. Used by the direct DB path
     * where the old field object cannot be instantiated.
     *
     * If the old field type is unregistered, getField() returns null for
     * its layout elements, so insertion silently skips. The _v2 field will
     * need to be added to entry type layouts manually in the CP.
     */
    private function addFieldToLayoutsById(int $oldFieldId, NativeLinkField $newField): void
    {
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
                    if ($f?->id === $oldFieldId)   $hasOld = true;
                    if ($f?->id === $newField->id) $hasNew = true;
                }

                if (!$hasOld || $hasNew) continue;

                $newElements = [];
                foreach ($elements as $el) {
                    $newElements[] = $el;
                    if ($el instanceof CustomField && $el->getField()?->id === $oldFieldId) {
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
     * @return array{int, array<string,int>} [migrated, skipReasons]
     */
    private function migrateFieldData(
        \lenz\linkfield\fields\LinkField $oldField,
        NativeLinkField $newField
    ): array {
        $migrated = 0;
        $skipReasons = $this->emptySkipReasons();

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
                    $reason = $this->elementSkipReason((int)$row['elementId']);
                    $skipReasons[$reason]++;
                    continue;
                }

                $mapped = $this->mapDbRow($row);

                if ($mapped === null) {
                    $skipReasons['unmappable_type']++;
                    continue;
                }

                $element->setFieldValue($newField->handle, $mapped);

                if (!Craft::$app->getElements()->saveElement($element, false)) {
                    $skipReasons['save_failed']++;
                    $this->stderr(
                        "  [ERROR] Element #{$element->id} save failed: " .
                        implode(', ', $element->getFirstErrors()) . "\n",
                        Console::FG_RED
                    );
                    continue;
                }

                $migrated++;

            } catch (\Throwable $e) {
                $skipReasons['error']++;
                $this->stderr(
                    "  [ERROR] Element #{$row['elementId']}: " . $e->getMessage() . "\n",
                    Console::FG_RED
                );
            }
        }

        return [$migrated, $skipReasons];
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

    /**
     * Delete a field by ID, falling back to direct DB delete if the field
     * type cannot be instantiated (zombie field after plugin removal).
     */
    private function deleteFieldById(int $fieldId): void
    {
        $field = Craft::$app->getFields()->getFieldById($fieldId);
        if ($field && Craft::$app->getFields()->deleteField($field)) {
            return;
        }
        // Field uninstantiable or deleteField failed — remove DB row directly.
        Craft::$app->getDb()->createCommand()
            ->delete('{{%fields}}', ['id' => $fieldId])
            ->execute();
    }

    /**
     * Migrate rows from lenz_linkfield to a target field handle, without needing
     * the old field as a typed object. Used by actionRunDirect().
     *
     * @return array{int, array<string,int>} [migrated, skipReasons]
     */
    private function migrateRowsDirect(array $rows, string $newHandle): array
    {
        $migrated = 0;
        $skipReasons = $this->emptySkipReasons();

        foreach ($rows as $row) {
            try {
                $mapped = $this->mapDbRow($row);
                if ($mapped === null) {
                    $skipReasons['unmappable_type']++;
                    continue;
                }

                $element = Craft::$app->getElements()->getElementById(
                    (int)$row['elementId'], null, (int)$row['siteId']
                );
                if (!$element) {
                    $reason = $this->elementSkipReason((int)$row['elementId']);
                    $skipReasons[$reason]++;
                    continue;
                }

                $element->setFieldValue($newHandle, $mapped);
                if (!Craft::$app->getElements()->saveElement($element, false)) {
                    $skipReasons['save_failed']++;
                    $this->stderr(
                        "  [ERROR] Element #{$element->id}: " . implode(', ', $element->getFirstErrors()) . "\n",
                        Console::FG_RED
                    );
                    continue;
                }
                $migrated++;
            } catch (\Throwable $e) {
                $skipReasons['error']++;
                $this->stderr(
                    "  [ERROR] Element #{$row['elementId']}: " . $e->getMessage() . "\n",
                    Console::FG_RED
                );
            }
        }

        return [$migrated, $skipReasons];
    }

    /**
     * Empty skip-reason tally — categories tracked per field.
     *
     * @return array<string,int>
     */
    private function emptySkipReasons(): array
    {
        return [
            'softdeleted'     => 0,
            'no_element'      => 0,
            'unmappable_type' => 0,
            'save_failed'     => 0,
            'error'           => 0,
        ];
    }

    /**
     * Distinguish "element soft-deleted" from "element does not exist".
     * getElementById returns null in both cases; the postmortem flagged the
     * silent conflation as a class of false-positive failure.
     */
    private function elementSkipReason(int $elementId): string
    {
        // queryScalar returns: the dateDeleted value if the row exists, NULL if
        // the row exists but isn't soft-deleted, false if no row at all.
        $dateDeleted = Craft::$app->getDb()->createCommand(
            'SELECT [[dateDeleted]] FROM {{%elements}} WHERE [[id]] = :id',
            [':id' => $elementId]
        )->queryScalar();
        return ($dateDeleted !== false && $dateDeleted !== null) ? 'softdeleted' : 'no_element';
    }

    /**
     * Render non-zero skip categories as a compact breakdown string.
     * Example: "softdeleted: 144, no_element: 30"
     */
    private function formatSkipBreakdown(array $skipReasons): string
    {
        $parts = [];
        foreach ($skipReasons as $reason => $count) {
            if ($count > 0) {
                $parts[] = "{$reason}: {$count}";
            }
        }
        return implode(', ', $parts);
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
            if (!empty($row['skipReasons'])) {
                $breakdown = $this->formatSkipBreakdown($row['skipReasons']);
                if ($breakdown) {
                    $this->stdout("    ↳ skipped: {$breakdown}\n", Console::FG_YELLOW);
                }
            }
        }
    }

    /**
     * Return field layout element UIDs for a given field ID.
     *
     * Craft 5 stores element data in elements_sites.content keyed by the
     * field layout element UID — NOT the field UID. Use these UIDs to verify
     * migrated data: SELECT content->>'$."<element_uid>"' FROM elements_sites.
     *
     * @return array<string, string>  elementUid => layoutUid
     */
    private function layoutElementUidsForFieldId(int $fieldId): array
    {
        $field = Craft::$app->getFields()->getFieldById($fieldId);
        if (!$field) {
            return [];
        }

        $result = [];
        try {
            $layouts = Craft::$app->getDb()->createCommand(
                'SELECT [[uid]], [[config]] FROM {{%fieldlayouts}} WHERE [[dateDeleted]] IS NULL'
            )->queryAll();

            foreach ($layouts as $layoutRow) {
                if (empty($layoutRow['config'])) {
                    continue;
                }
                $config = Json::decodeIfJson($layoutRow['config']);
                if (!is_array($config)) {
                    continue;
                }
                foreach ($config['tabs'] ?? [] as $tab) {
                    foreach ($tab['elements'] ?? [] as $element) {
                        if (($element['fieldUid'] ?? null) === $field->uid) {
                            $result[$element['uid']] = $layoutRow['uid'];
                        }
                    }
                }
            }
        } catch (\Throwable) {
        }

        return $result;
    }

    /**
     * Print layout element UIDs for _v2 fields so users can verify migrated data.
     * elements_sites.content is keyed by field layout element UID, not field UID.
     * Call this after the migration summary to give the user the verification SQL.
     */
    private function printLayoutElementUids(array $plan): void
    {
        $this->stdout("\n=== Layout element UIDs for data verification ===\n", Console::FG_CYAN, Console::BOLD);
        $this->stdout("elements_sites.content is keyed by layout element UID, not field UID.\n");
        $this->stdout("Use the UIDs below to verify migrated data in Block L2.2b.\n\n");

        foreach ($plan as $oldId => $info) {
            $newField = $info['newField'];
            $uids = $this->layoutElementUidsForFieldId($newField->id);
            $this->stdout(sprintf("  %s_v2 (field id: %d)\n", $info['handle'], $newField->id));
            if (empty($uids)) {
                $this->stdout("    (no layout element UIDs found — field may not be in any layout yet)\n", Console::FG_YELLOW);
            } else {
                foreach ($uids as $elementUid => $layoutUid) {
                    $this->stdout("    element uid: {$elementUid}\n");
                }
            }
        }
    }
}
