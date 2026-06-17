"""Regression tests for craft-5-preflight/scripts/audit.py.

Run either way (no third-party deps — works with or without pytest):
    python3 craft-5-preflight/scripts/tests/test_audit.py
    python3 -m pytest craft-5-preflight/scripts/tests/

The fixture project under
fixtures/sample-project/ contains exactly the structures the mid-project bug
report proved the auditor was missing:
  - a Matrix field with EXTERNAL block types (matrixBlockTypes/),
  - a Super Table field NESTED inside a Matrix block (its blocks external too),
  - a Redactor field and a URL field INSIDE block types (not top-level),
  - a handle ('linkTo') duplicated across a top-level field and a Matrix sub-field,
  - a native handle ('heading') duplicated top-level + block-type (informational).
"""

import contextlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS_DIR)

import audit  # noqa: E402


@contextlib.contextmanager
def patched_run_mysql(fn):
    """Temporarily replace audit._run_mysql (no live MySQL needed)."""
    original = audit._run_mysql
    audit._run_mysql = fn
    try:
        yield
    finally:
        audit._run_mysql = original

FIXTURE = os.path.join(HERE, 'fixtures', 'sample-project')
CONFIG_DIR = audit.Path(FIXTURE) / 'config' / 'project'
TEMPLATES_DIR = audit.Path(FIXTURE) / 'templates'

LF = r'lenz\linkfield\fields\LinkField'
URL = r'craft\fields\Url'
REDACTOR = r'craft\redactor\Field'
ST = r'verbb\supertable\fields\SuperTableField'
PLAIN = r'craft\fields\PlainText'


# ── Config-parser path (offline) ──────────────────────────────────────────────

def _collect():
    return audit.collect_all_fields(CONFIG_DIR)


def test_matrix_external_blocks_are_loaded():
    """Fields inside an EXTERNAL matrix block type must be discovered."""
    _, _, _, all_fields = _collect()
    matrix_subs = {(f['handle'], f['context']) for f in all_fields
                   if f['context'] == 'matrix'}
    assert ('bodyText', 'matrix') in matrix_subs   # redactor in block type
    assert ('heading', 'matrix') in matrix_subs    # native in block type
    assert ('linkTo', 'matrix') in matrix_subs     # linkfield in block type
    assert ('buttons', 'matrix') in matrix_subs    # nested ST field


def test_supertable_nested_in_matrix_is_resolved():
    """A Super Table nested inside a Matrix block — and its sub-fields — resolve."""
    lf_records, st_sub_handles, st_count, all_fields = _collect()
    assert st_count == 1, 'the nested ST field must be counted'
    st_handles = {r['handle'] for r in st_sub_handles}
    assert {'button', 'profileUrl'} <= st_handles
    # The nested linkfield must appear in the linkfield inventory.
    button = [r for r in lf_records if r['handle'] == 'button']
    assert button and button[0]['context'] == 'supertable'
    assert button[0]['parent_handle'] == 'buttons'


def test_linkfield_inventory_is_complete():
    lf_records, _, _, _ = _collect()
    by_ctx = sorted((r['handle'], r['context']) for r in lf_records)
    assert by_ctx == [
        ('button', 'supertable'),
        ('linkTo', 'matrix'),
        ('linkTo', 'top-level'),
    ]


def test_url_collector_descends_into_block_types():
    _, _, _, all_fields = _collect()
    handles = {f['handle'] for f in audit._collect_url_fields(all_fields)}
    assert handles == {'siteUrl', 'profileUrl'}   # top-level AND ST sub-field


def test_redactor_collector_descends_into_block_types():
    _, _, _, all_fields = _collect()
    handles = {f['handle'] for f in audit._collect_redactor_fields(all_fields)}
    assert handles == {'bodyText'}   # only exists inside a matrix block type


def test_global_duplicate_handles():
    _, _, _, all_fields = _collect()
    result = audit.run_p17d(all_fields)
    # linkTo collides across top-level + matrix, both linkfields -> risky.
    assert 'linkTo' in result['risky']
    # heading collides across top-level + matrix, native only -> informational.
    assert 'heading' in result['informational']
    assert 'linkTo' not in result['informational']


# ── Template cache (P1.7c / P1.8 / P1.8b / P1.9) ──────────────────────────────

def test_load_templates_and_p19_collision():
    cache = audit.load_templates(TEMPLATES_DIR)
    names = {os.path.basename(p) for p in cache}
    assert {'index.twig', 'index.html'} <= names
    collisions = audit.run_p19(cache)
    assert len(collisions) == 1
    assert collisions[0].endswith('index')


def test_grep_cache_single_pass():
    cache = audit.load_templates(TEMPLATES_DIR)
    hits = audit._grep_cache(cache, ['.getUrl(', '.with(['])
    assert any(f.endswith('index.twig') for f, _, _ in hits['.getUrl('])
    assert hits['.with(['] == []


def test_url_breaking_patterns_from_cache():
    cache = audit.load_templates(TEMPLATES_DIR)
    breaking, ref_files = audit._find_url_breaking_patterns(cache, 'siteUrl')
    assert any(f.endswith('index.twig') for f in ref_files)
    assert [pat for _, _, _, pat in breaking] == ['|length']


def test_run_p18b_uses_cache():
    lf_records, _, _, _ = _collect()
    cache = audit.load_templates(TEMPLATES_DIR)
    files = audit.run_p18b(TEMPLATES_DIR, cache, lf_records, set(), set())
    assert any(f.endswith('index.twig') for f in files)   # references linkTo


# ── DB-authoritative path (no live MySQL — _run_mysql is monkeypatched) ────────

FORMIE_HEADING = r'verbb\formie\fields\Heading'
FORMIE2_HEADING = r'verbb\formie\fields\formfields\Heading'

# Real Craft 4 references block types by UID in fields.context
# (e.g. matrixBlockType:<uid>), NOT integer id — keying the lookup by id made
# every sub-field resolve to '?'. Fixtures use UID contexts to lock that path.
MBT_UID = 'btm-3c489301-ecd6-4968-bbfb-a25d28f4364a'
SBT_UID = 'bts-7f221044-aa10-4c0b-9e1a-2b3c4d5e6f70'

_DB_FIELDS = [
    ['1',  'u1',  'linkTo',       'Hero Link',    'global',                          LF,             '{"columnSuffix":null}'],
    ['2',  'u2',  'siteUrl',      'Site URL',     'global',                          URL,            '{}'],
    ['3',  'u3',  'linkTo',       'Link To',      f'matrixBlockType:{MBT_UID}',      LF,             '{}'],
    ['4',  'u4',  'bodyText',     'Body Text',    f'matrixBlockType:{MBT_UID}',      REDACTOR,       '{}'],
    ['5',  'u5',  'button',       'Button',       f'superTableBlockType:{SBT_UID}',  LF,             '{}'],
    ['6',  'u6',  'profileUrl',   'Profile URL',  f'superTableBlockType:{SBT_UID}',  URL,            '{}'],
    ['7',  'u7',  'heading',      'Heading',      'global',                          PLAIN,          '{}'],
    ['8',  'u8',  'heading',      'Heading',      f'matrixBlockType:{MBT_UID}',      PLAIN,          '{}'],
    ['9',  'u9',  'buttons',      'Buttons',      f'matrixBlockType:{MBT_UID}',      ST,             '{}'],
    ['10', 'u10', 'formieHead',   'Form Heading', 'global',                          FORMIE_HEADING, '{}'],
    ['11', 'u11', 'formieHead2',  'Form Heading (Formie 2)', 'formie:abc',           FORMIE2_HEADING, '{}'],
]
# Block-type rows: (id, uid, name, parent field handle). ST has no name column.
_DB_MATRIX_BT = [['10', MBT_UID, 'Text Block', 'contentMatrix']]
_DB_ST_BT = [['20', SBT_UID, '', 'buttons']]


def _fake_run_mysql(mysql_cmd, db_name, sql):
    if 'FROM fields' in sql and 'blocktypes' not in sql:
        return list(_DB_FIELDS)
    if 'matrixblocktypes' in sql:
        return list(_DB_MATRIX_BT)
    if 'supertableblocktypes' in sql:
        return list(_DB_ST_BT)
    return []


def _db_inventory():
    with patched_run_mysql(_fake_run_mysql):
        return audit.build_db_inventory('mysql -u root', 'testdb')


def test_db_inventory_is_authoritative():
    inv = _db_inventory()
    assert inv is not None
    lf = {r['handle'] for r in inv['lf_records']}
    assert lf == {'linkTo', 'button'}
    assert len(inv['lf_records']) == 3   # linkTo x2 + button
    assert inv['st_field_count'] == 1
    st = {r['handle'] for r in inv['st_sub_handles']}
    assert st == {'button', 'profileUrl'}


def test_db_context_resolution():
    inv = _db_inventory()
    by_handle = {(f['handle'], f['context']): f for f in inv['all_fields']}
    assert by_handle[('linkTo', 'matrix')]['parent_handle'] == 'contentMatrix'
    assert by_handle[('button', 'supertable')]['parent_handle'] == 'buttons'


def test_db_uid_context_resolves_parent_not_question_mark():
    """Regression: fields.context references the block type by UID on Craft 4.
    The parent field handle (and ST sub-field parent) must resolve, never '?'."""
    inv = _db_inventory()
    st_subs = {r['handle']: r for r in inv['st_sub_handles']}
    assert st_subs['button']['parent_st_handle'] == 'buttons'
    assert st_subs['button']['parent_st_handle'] != '?'
    matrix_lf = [f for f in inv['all_fields']
                 if f['handle'] == 'linkTo' and f['context'] == 'matrix']
    assert matrix_lf and matrix_lf[0]['parent_handle'] == 'contentMatrix'
    # The matrix block type's name is carried through for P2 ownership context.
    assert matrix_lf[0]['block_type_name'] == 'Text Block'


def test_db_block_type_parents_keys_both_id_and_uid():
    """_db_block_type_parents must resolve whether context carries id or uid
    (older Craft used the integer id), so the dict is keyed by both."""
    with patched_run_mysql(_fake_run_mysql):
        mbt = audit._db_block_type_parents('mysql -u root', 'testdb', 'matrixblocktypes')
    assert mbt[MBT_UID] == ('contentMatrix', 'Text Block')   # uid form (Craft 4)
    assert mbt['10'] == ('contentMatrix', 'Text Block')      # id form (legacy)


def test_db_collectors_and_dupes():
    inv = _db_inventory()
    urls = {f['handle'] for f in audit._collect_url_fields(inv['all_fields'])}
    reds = {f['handle'] for f in audit._collect_redactor_fields(inv['all_fields'])}
    assert urls == {'siteUrl', 'profileUrl'}
    assert reds == {'bodyText'}
    dupes = audit.run_p17d(inv['all_fields'])
    assert 'linkTo' in dupes['risky']
    assert 'heading' in dupes['informational']


def test_cross_check_separates_formie_from_genuine_mismatch():
    """Formie fields missing from project config are expected (they live outside
    it) and must not be reported under the alarming CONFIG/DB MISMATCH WARN."""
    import io
    config_fields = [{'handle': 'siteUrl', 'context': 'top-level', 'type': URL}]
    db_fields = [
        {'handle': 'siteUrl',    'context': 'top-level', 'type': URL},
        {'handle': 'realMiss',   'context': 'matrix',    'type': LF},
        {'handle': 'formieHead', 'context': 'formie:abc','type': FORMIE_HEADING},
    ]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        audit.report_db_config_discrepancy(config_fields, db_fields)
    out = buf.getvalue()
    assert 'CONFIG/DB MISMATCH' in out          # genuine miss still warned
    assert 'realMiss' in out
    # Formie field reported under the "expected" note, not the MISMATCH warning.
    mismatch_block = out.split('CONFIG/DB MISMATCH', 1)[1].split('expected', 1)[0]
    assert 'formieHead' not in mismatch_block
    assert 'expected' in out and 'formieHead' in out


def test_db_query_failure_returns_none():
    with patched_run_mysql(lambda *a, **k: None):
        assert audit.build_db_inventory('mysql -u root', 'testdb') is None


def test_mysql_unescape():
    assert audit._mysql_unescape(r'a\tb\nc') == 'a\tb\nc'
    assert audit._mysql_unescape(r'back\\slash') == 'back\\slash'
    assert audit._mysql_unescape('plain') == 'plain'


# ── P1.15 — non-stringable Formie field detection ────────────────────────────

def test_collect_nonstringable_formie_fields_config_path():
    """Synthetic all_fields: Formie Heading found; native/LF fields not returned."""
    fields = [
        {'handle': 'heading', 'type': r'craft\fields\PlainText', 'context': 'top-level', 'parent_handle': ''},
        {'handle': 'linkTo', 'type': r'lenz\linkfield\fields\LinkField', 'context': 'top-level', 'parent_handle': ''},
        {'handle': 'formieHead', 'type': r'verbb\formie\fields\Heading', 'context': 'top-level', 'parent_handle': ''},
        {'handle': 'formieSection', 'type': r'verbb\formie\fields\Section', 'context': 'matrix', 'parent_handle': 'form'},
        # field with no handle — must be excluded
        {'handle': '', 'type': r'verbb\formie\fields\Heading', 'context': 'top-level', 'parent_handle': ''},
    ]
    result = audit._collect_nonstringable_formie_fields(fields)
    handles = {f['handle'] for f in result}
    # Formie non-stringable fields with handles are returned
    assert handles == {'formieHead', 'formieSection'}
    # Native and linkfield types are excluded
    assert 'heading' not in handles
    assert 'linkTo' not in handles
    # Empty-handle entry is excluded
    assert '' not in handles


def test_collect_nonstringable_formie_fields_all_types():
    """All four non-stringable Formie types are captured, in BOTH the Formie 3
    namespace and the Formie 2 (Craft 4) `formfields` namespace — the preflight
    audit runs on Craft 4, where the DB contains the Formie 2 class names."""
    fields = [
        {'handle': 'h', 'type': r'verbb\formie\fields\Heading',  'context': 'top-level', 'parent_handle': ''},
        {'handle': 'ht', 'type': r'verbb\formie\fields\Html',    'context': 'top-level', 'parent_handle': ''},
        {'handle': 's', 'type': r'verbb\formie\fields\Section',  'context': 'top-level', 'parent_handle': ''},
        {'handle': 'sm', 'type': r'verbb\formie\fields\Summary', 'context': 'top-level', 'parent_handle': ''},
        {'handle': 'h2', 'type': r'verbb\formie\fields\formfields\Heading',  'context': 'top-level', 'parent_handle': ''},
        {'handle': 'ht2', 'type': r'verbb\formie\fields\formfields\Html',    'context': 'top-level', 'parent_handle': ''},
        {'handle': 's2', 'type': r'verbb\formie\fields\formfields\Section',  'context': 'top-level', 'parent_handle': ''},
        {'handle': 'sm2', 'type': r'verbb\formie\fields\formfields\Summary', 'context': 'top-level', 'parent_handle': ''},
    ]
    result = audit._collect_nonstringable_formie_fields(fields)
    assert {f['handle'] for f in result} == {'h', 'ht', 's', 'sm', 'h2', 'ht2', 's2', 'sm2'}


def test_db_inventory_includes_formie_heading():
    """build_db_inventory returns Formie Heading (both namespaces) in all_fields."""
    inv = _db_inventory()
    assert inv is not None
    all_types = {f['type'] for f in inv['all_fields']}
    assert FORMIE_HEADING in all_types
    assert FORMIE2_HEADING in all_types
    formie_fields = audit._collect_nonstringable_formie_fields(inv['all_fields'])
    handles = {f['handle'] for f in formie_fields}
    assert {'formieHead', 'formieHead2'} <= handles
    # Existing LF/URL/ST counts are unchanged
    lf = {r['handle'] for r in inv['lf_records']}
    assert lf == {'linkTo', 'button'}
    assert inv['st_field_count'] == 1


# ── Table-prefix support (CRAFT_DB_TABLE_PREFIX) ──────────────────────────────

def _fake_run_mysql_prefixed(mysql_cmd, db_name, sql):
    """Simulates a DB where every Craft table has the 'craft_' prefix."""
    if 'blocktypes' in sql:
        if 'craft_matrixblocktypes' in sql:
            return list(_DB_MATRIX_BT)
        if 'craft_supertableblocktypes' in sql:
            return list(_DB_ST_BT)
        return None
    if 'FROM craft_fields' in sql:
        return list(_DB_FIELDS)
    if 'FROM fields' in sql:
        return None  # bare table does not exist
    if "SHOW TABLES LIKE '%fields'" in sql:
        return [['craft_fields']]
    if "SHOW TABLES LIKE 'craft_elements'" in sql:
        return [['craft_elements']]
    return []


def test_db_inventory_with_table_prefix():
    with patched_run_mysql(_fake_run_mysql_prefixed):
        assert audit.build_db_inventory('mysql -u root', 'testdb') is None
        inv = audit.build_db_inventory('mysql -u root', 'testdb',
                                       table_prefix='craft_')
    assert inv is not None
    lf = {r['handle'] for r in inv['lf_records']}
    assert lf == {'linkTo', 'button'}
    by_handle = {(f['handle'], f['context']): f for f in inv['all_fields']}
    assert by_handle[('linkTo', 'matrix')]['parent_handle'] == 'contentMatrix'


def test_detect_table_prefix():
    with patched_run_mysql(_fake_run_mysql_prefixed):
        assert audit._detect_table_prefix('mysql -u root', 'testdb') == 'craft_'
    with patched_run_mysql(_fake_run_mysql):
        # Unprefixed DB: SHOW TABLES fake returns [] → no prefix detected.
        assert audit._detect_table_prefix('mysql -u root', 'testdb') is None


# ── Standalone runner (no pytest required) ────────────────────────────────────

if __name__ == '__main__':
    import io

    tests = sorted(
        (name, obj) for name, obj in globals().items()
        if name.startswith('test_') and callable(obj)
    )
    passed, failed = 0, 0
    for name, fn in tests:
        # Silence section() output from functions under test.
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
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
