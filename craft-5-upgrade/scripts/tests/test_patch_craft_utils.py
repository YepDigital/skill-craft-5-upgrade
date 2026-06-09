"""Regression tests for craft-5-upgrade/scripts/patch-craft-utils.py.

Run either way (no third-party deps — works with or without pytest):
    python3 craft-5-upgrade/scripts/tests/test_patch_craft_utils.py
    python3 -m pytest craft-5-upgrade/scripts/tests/

The fixture mirrors the real ForeignFieldQueryListener structure documented in
references/craft-utils-formie-heading.md (array_unique wrapping array_reduce
inside the $fields = array_filter(...) assignment).
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(HERE)

_spec = importlib.util.spec_from_file_location(
    'patch_craft_utils', os.path.join(SCRIPTS_DIR, 'patch-craft-utils.py')
)
pcu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pcu)

FIXTURE_PHP = '''<?php
namespace lenz\\craft\\utils\\foreignField;

class ForeignFieldQueryListener
{
    public function onBeforeQueryPrepare($event) {
        $fields = array_filter(
        array_unique(array_reduce(
            $fieldLayouts,
            fn($fields, $fieldLayout) => array_merge($fields, $fieldLayout->getCustomFields()),
            []
        )),
        fn($field) => $field instanceof ForeignField
        );

        foreach ($fields as $field) {
            $handle = $field->handle;
        }
    }
}
'''


def test_patch_applies():
    patched, changed = pcu._apply_patch(FIXTURE_PHP)
    assert changed is True
    assert pcu.SENTINEL in patched
    # The wrapper call is gone (the explanatory comment still names it).
    assert 'array_unique(array_reduce(' not in patched
    assert 'array_unique(' not in patched.replace('array_unique() over', '')
    # The dedup loop lands after the $fields statement and before the consumer.
    assert patched.index('$unique = [];') < patched.index('foreach ($fields as $field) {\n            $handle')
    assert '$unique[$field->handle] = $field;' in patched


def test_patch_is_idempotent():
    patched, _ = pcu._apply_patch(FIXTURE_PHP)
    again, changed = pcu._apply_patch(patched)
    assert changed is False
    assert again == patched


def test_patch_rejects_missing_array_unique():
    src = FIXTURE_PHP.replace('array_unique(', 'array_values(')
    try:
        pcu._apply_patch(src)
    except ValueError as exc:
        assert 'array_unique' in str(exc)
    else:
        raise AssertionError('expected ValueError for missing array_unique')


def test_patch_rejects_unexpected_inner_call():
    src = FIXTURE_PHP.replace('array_unique(array_reduce(',
                              'array_unique(array_map(')
    # Keep parens balanced: array_map takes the same arg shape here.
    try:
        pcu._apply_patch(src)
    except ValueError as exc:
        assert 'array_reduce' in str(exc)
    else:
        raise AssertionError('expected ValueError for non-array_reduce inner call')


# ── Standalone runner (no pytest required) ────────────────────────────────────

if __name__ == '__main__':
    tests = sorted(
        (name, obj) for name, obj in globals().items()
        if name.startswith('test_') and callable(obj)
    )
    passed, failed = 0, 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f'FAIL  {name}: {exc}')
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f'ERROR {name}: {type(exc).__name__}: {exc}')
        else:
            passed += 1
            print(f'ok    {name}')
    print(f'\n{passed} passed, {failed} failed')
    sys.exit(1 if failed else 0)
