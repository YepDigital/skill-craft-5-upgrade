"""Regression tests for craft-5-linkfield/scripts/patch-templates.py.

Run either way (no third-party deps — works with or without pytest):
    python3 craft-5-linkfield/scripts/tests/test_patch_templates.py
    python3 -m pytest craft-5-linkfield/scripts/tests/

The transforms here are all regex/substring rewrites of live templates — the
highest-risk code in the suite — so every documented transform has a test,
including the cases the patterns must NOT touch.
"""

import contextlib
import importlib.util
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(HERE)

_spec = importlib.util.spec_from_file_location(
    'patch_templates', os.path.join(SCRIPTS_DIR, 'patch-templates.py')
)
pt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pt)

HANDLES = {'primaryLink': 'primaryLink_v2', 'navLink': 'navLink_v2'}


# ── API substitutions ─────────────────────────────────────────────────────────

def test_api_substitutions():
    src = '{{ x.getUrl() }} {{ x.getCustomText() }} {{ x.getTarget() }} {{ x.getElement() }}'
    out = pt.apply_api_substitutions(src)
    assert out == '{{ x.url }} {{ x.label }} {{ x.target }} {{ x.element }}'


def test_gettype_call_and_property_forms():
    assert pt.apply_api_substitutions('{{ x.getType() }}') == '{{ x.type }}'
    assert pt.apply_api_substitutions('{% if x.getType == "url" %}') == '{% if x.type == "url" %}'


def test_gettype_does_not_corrupt_longer_identifiers():
    # .getTypeId() and .getTypes() must NOT become .typeId()/.types().
    src = '{{ entry.getTypeId() }} {{ entry.getTypes() }} {{ x.getType(arg) }}'
    assert pt.apply_api_substitutions(src) == src


# ── getLinkAttributes() ───────────────────────────────────────────────────────

def test_linkattributes_inline_consumes_twig_delimiters():
    src = '<a {{ entry.myLink.getLinkAttributes() }}>'
    out = pt.apply_linkattributes(src, mode='inline')
    assert out == (
        '<a href="{{ entry.myLink.url }}"'
        '{% if entry.myLink.target %} target="{{ entry.myLink.target }}"'
        ' rel="noopener noreferrer"{% endif %}>'
    )


def test_linkattributes_macro_mode():
    src = '<a {{ entry.myLink.getLinkAttributes() }}>'
    out = pt.apply_linkattributes(src, mode='macro')
    assert '{{ linkField.attributes(entry.myLink) }}' in out


# ── Handle renames ────────────────────────────────────────────────────────────

def test_handle_rename_field_access_only():
    src = '{{ entry.primaryLink.url }} {% set primaryLink = 1 %}'
    out = pt.apply_handle_renames(src, HANDLES)
    # Field access renamed; bare local variable (no leading dot) untouched.
    assert '{{ entry.primaryLink_v2.url }}' in out
    assert '{% set primaryLink = 1 %}' in out


def test_handle_rename_is_idempotent():
    src = '{{ entry.primaryLink_v2.url }}'
    assert pt.apply_handle_renames(src, HANDLES) == src


def test_validate_handles_rejects_non_suffix_mappings():
    assert pt.validate_handles(HANDLES) == {}
    bad = pt.validate_handles({'navLink': 'mainNavLink', 'a': 'a'})
    assert set(bad) == {'navLink', 'a'}


# ── .with() removal ───────────────────────────────────────────────────────────

def test_with_removal_single_entry():
    src = "craft.entries().section('nav').with(['primaryLink']).collect()"
    out = pt.remove_with_calls(src, HANDLES)
    assert out == "craft.entries().section('nav').collect()"


def test_with_removal_multi_entry_keeps_others():
    src = '.with(["primaryLink", "heroImage"])'
    out = pt.remove_with_calls(src, HANDLES)
    assert 'primaryLink' not in out
    assert 'heroImage' in out
    src2 = '.with(["heroImage", "primaryLink"])'
    out2 = pt.remove_with_calls(src2, HANDLES)
    assert 'primaryLink' not in out2
    assert 'heroImage' in out2


# ── Null guards ───────────────────────────────────────────────────────────────

def test_null_guard_type_check():
    src = '{% if item.navLink_v2.type == "entry" %}'
    out = pt.apply_null_guards(src, HANDLES)
    assert out == '{% if item.navLink_v2 and item.navLink_v2.type == "entry" %}'


def test_null_guard_href():
    src = 'href="{{ navLink_v2.url }}"'
    out = pt.apply_null_guards(src, HANDLES)
    assert out == 'href="{{ navLink_v2 ? navLink_v2.url : \'#\' }}"'


def test_null_guard_chained_null_coalesce():
    src = '{{ fallback ?? navLink_v2.element.title ?? null }}'
    out = pt.apply_null_guards(src, HANDLES)
    assert out == '{{ fallback ?? (navLink_v2.element ? navLink_v2.element.title : null) }}'


def test_null_guard_slug_comparison():
    src = '{% if entry.slug == navLink_v2.element.slug %}'
    out = pt.apply_null_guards(src, HANDLES)
    assert out == '{% if navLink_v2.element and (entry.slug == navLink_v2.element.slug) %}'


# ── Twig 3 lint ───────────────────────────────────────────────────────────────

def test_lint_twig3_flags_parenthesised_lhs():
    content = '{% set a = (x == y) ?? null %}\n{{ A ?? (B ? C : null) ?? (D) }}\n{{ ok ?? null }}'
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        issues = pt.lint_twig3('f.twig', content)
    assert issues == 2


# ── Verify mode ───────────────────────────────────────────────────────────────

def test_verify_no_old_handles():
    remaining = pt.verify_no_old_handles('f.twig', '{{ entry.primaryLink.url }}', HANDLES)
    assert [(h) for _, h, _ in remaining] == ['primaryLink']
    assert pt.verify_no_old_handles('f.twig', '{{ entry.primaryLink_v2.url }}', HANDLES) == []


def test_verify_mode_is_read_only_and_flags_unpatched_file():
    src = '{{ entry.primaryLink.getUrl() }}\n'
    with tempfile.NamedTemporaryFile('w', suffix='.twig', delete=False,
                                     encoding='utf-8') as tmp:
        tmp.write(src)
        path = tmp.name
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok, _ = pt.patch_file(path, HANDLES, verify=True)
        assert ok is False                                # old handle flagged
        assert open(path, encoding='utf-8').read() == src  # nothing written
    finally:
        os.unlink(path)


def test_verify_mode_passes_on_patched_file():
    src = '{{ entry.primaryLink_v2.url }}\n'
    with tempfile.NamedTemporaryFile('w', suffix='.twig', delete=False,
                                     encoding='utf-8') as tmp:
        tmp.write(src)
        path = tmp.name
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok, _ = pt.patch_file(path, HANDLES, verify=True)
        assert ok is True
        assert open(path, encoding='utf-8').read() == src
    finally:
        os.unlink(path)


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
