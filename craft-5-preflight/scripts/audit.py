#!/usr/bin/env python3
"""
Craft 5 preflight audit script — replaces audit.sh
Run from the project root (path is this skill's scripts/ directory):
    python3 <skill_dir>/scripts/audit.py [project_root]
Covers SKILL.md blocks P1.7, P1.7a, P1.7b, P1.7c, P1.7d, P1.8, P1.8b, P1.9, P1.10b, P1.12, P1.13, P1.14, P1.15

Field inventory source: the `fields` DB table is authoritative when --mysql-cmd
and --db-name are supplied (it is cross-checked against project config and any
discrepancy is flagged). Without them, the (recursive) project-config parser is
used as an offline fallback.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# ── YAML loading ──────────────────────────────────────────────────────────────

try:
    import yaml as _yaml

    def _load_yaml(text):
        try:
            return _yaml.safe_load(text) or {}
        except _yaml.YAMLError:
            return {}

    _YAML_BACKEND = 'PyYAML'

except ImportError:
    _YAML_BACKEND = 'fallback'

    def _load_yaml(text):
        return _yaml_fallback(text)


def _yaml_fallback(text):
    """
    Minimal YAML parser sufficient for Craft project config YAML.
    Handles: mappings, block sequences, scalars, single/double-quoted strings.
    Silently skips YAML block scalars (| and >) — their content is not needed.
    """
    lines = []
    for raw in text.splitlines():
        stripped = raw.rstrip()
        if not stripped or stripped.lstrip().startswith('#'):
            continue
        indent = len(stripped) - len(stripped.lstrip())
        lines.append((indent, stripped.lstrip()))

    BLOCK_SCALAR_RE = re.compile(r'^[|>][-+]?\s*$')

    def scalar(s):
        s = s.strip()
        if (s.startswith('"') and s.endswith('"')) or \
           (s.startswith("'") and s.endswith("'")):
            s = s[1:-1]
        if s in ('true', 'True'): return True
        if s in ('false', 'False'): return False
        if s in ('null', '~', ''): return None
        try: return int(s)
        except ValueError: pass
        try: return float(s)
        except ValueError: pass
        return s

    def parse(pos, min_indent):
        result = None
        i = pos
        while i < len(lines):
            indent, content = lines[i]
            if indent < min_indent:
                break
            if content.startswith('- '):
                if result is None: result = []
                val_str = content[2:].strip()
                if val_str:
                    result.append(scalar(val_str))
                    i += 1
                else:
                    ni = i + 1
                    if ni < len(lines) and lines[ni][0] > indent:
                        sub, i = parse(ni, lines[ni][0])
                        if sub is not None: result.append(sub)
                    else:
                        i += 1
            elif ': ' in content:
                if result is None: result = {}
                k, v = content.split(': ', 1)
                k = k.strip()
                v = v.strip()
                if BLOCK_SCALAR_RE.match(v):
                    # Block scalar — skip all deeper-indented continuation lines
                    result[k] = ''
                    while i + 1 < len(lines) and lines[i + 1][0] > indent:
                        i += 1
                else:
                    result[k] = scalar(v)
                i += 1
            elif content.endswith(':'):
                if result is None: result = {}
                k = content[:-1].strip()
                ni = i + 1
                if ni < len(lines) and lines[ni][0] > indent:
                    sub, i = parse(ni, lines[ni][0])
                    result[k] = sub
                else:
                    result[k] = None
                    i += 1
            else:
                i += 1
        return result, i

    result, _ = parse(0, 0)
    return result or {}


# ── Output helpers ────────────────────────────────────────────────────────────

SEP = '════════════════════════════════════════'


def section(title):
    print(f'\n{SEP}\n  {title}\n{SEP}')


def found(msg): print(f'  [FOUND] {msg}')
def warn(msg):  print(f'  [WARN] {msg}')
def info(msg):  print(f'  {msg}')
def none_found(): print('  (none)')


def ctx_label(rec):
    """Human-readable location label for a field record (any collector shape)."""
    ctx = rec.get('context', 'top-level') or 'top-level'
    if ctx == 'top-level':
        return '[top-level field]'
    parent = rec.get('parent_handle') or '?'
    bt = rec.get('block_type_name') or '?'
    return f'[{ctx} sub-field: {parent} / block type: {bt}]'


# ── Field type constants ──────────────────────────────────────────────────────

LF_TYPES = (
    r'lenz\linkfield\fields\LinkField',         # sebastianlenz/linkfield 2.x+
    r'typedlinkfield\fields\LinkField',         # legacy pre-rename (Craft 3 era)
)
ST_TYPE = r'verbb\supertable\fields\SuperTableField'
MT_TYPE = r'craft\fields\Matrix'
URL_TYPE = r'craft\fields\Url'
REDACTOR_TYPE = r'craft\redactor\Field'
NONSTRINGABLE_FORMIE_TYPES = frozenset({
    # Formie 3 (Craft 5) namespace
    r'verbb\formie\fields\Heading',
    r'verbb\formie\fields\Html',
    r'verbb\formie\fields\Section',
    r'verbb\formie\fields\Summary',
    # Formie 2 (Craft 4) namespace — what the preflight DB/config actually
    # contains, since the audit runs before the upgrade.
    r'verbb\formie\fields\formfields\Heading',
    r'verbb\formie\fields\formfields\Html',
    r'verbb\formie\fields\formfields\Section',
    r'verbb\formie\fields\formfields\Summary',
})


# ── YAML file discovery and field collection ──────────────────────────────────

def iter_config_yamls(config_dir):
    for root, _, files in os.walk(str(config_dir)):
        for fname in sorted(files):
            if not fname.endswith(('.yaml', '.yml')):
                continue
            fpath = os.path.join(root, fname)
            try:
                text = open(fpath, encoding='utf-8', errors='replace').read()
                data = _load_yaml(text)
                if isinstance(data, dict):
                    yield fpath, data
            except (OSError, IOError):
                pass


def _get_settings(data):
    """Extract settings dict, handling JSON-serialised settings."""
    s = data.get('settings', {})
    if isinstance(s, str):
        try: s = json.loads(s)
        except (json.JSONDecodeError, ValueError): s = {}
    return s if isinstance(s, dict) else {}


def _parse_link_names(value):
    """Return list of enabled link type names; handles list or JSON string."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value.strip().startswith('['):
        try: return json.loads(value)
        except (json.JSONDecodeError, ValueError): pass
    return []


def _lf_record(handle, name, settings, filepath, context, parent_handle='', block_type_name='', field_type=''):
    return {
        'handle': handle,
        'name': name,
        'column_suffix': settings.get('columnSuffix'),
        'allowed_link_names': _parse_link_names(settings.get('allowedLinkNames')),
        'filepath': filepath,
        'context': context,
        'parent_handle': parent_handle,
        'block_type_name': block_type_name,
        'field_type': field_type,
    }


def _field_uid_from_path(filepath):
    """Field YAMLs are named {handle}--{uuid}.yaml; return the bare UUID."""
    return Path(filepath).stem.split('--')[-1]


def _load_external_blocks(config_dir, subdir):
    """
    Load externally-stored block types from config/project/<subdir>/.

    Newer Super Table and modern Matrix releases store block types in per-file
    YAMLs here rather than inline under the parent field's blockTypes: key. Each
    file references its parent field UID via a 'field' (or 'fieldId') key.
    Returns {parent_field_uid: {bt_uid: bt_data}}.
    """
    bt_dir = config_dir / subdir
    result = defaultdict(dict)
    if not bt_dir.is_dir():
        return result
    for filepath, data in iter_config_yamls(bt_dir):
        parent_uid = (
            data.get('field') or
            data.get('fieldId') or
            data.get('superTableFieldId')
        )
        if not parent_uid:
            continue
        bt_uid = Path(filepath).stem
        # Remember the block type's own source file so nested sub-fields are
        # reported against the file the operator must actually edit in P2, not
        # the parent field's YAML.
        if isinstance(data, dict):
            data['__src__'] = filepath
        result[str(parent_uid)][bt_uid] = data
    return result


def _resolve_block_types(field_data, field_uid, field_type, st_external, mt_external):
    """Return the merged block-type dict for an ST/Matrix field.

    Combines the inline blockTypes: key (older storage) with any externally
    stored block types (newer storage), keyed by the field's bare UUID.
    """
    merged = dict(field_data.get('blockTypes') or {})
    if not field_uid:
        return merged
    if field_type == ST_TYPE:
        merged.update(st_external.get(field_uid, {}))
    elif field_type == MT_TYPE:
        merged.update(mt_external.get(field_uid, {}))
    return merged


def collect_all_fields(config_dir):
    """
    Walk all project config YAML files, recursing into block types.

    Returns (lf_records, st_sub_handles, st_field_count, all_fields):
      lf_records:     every linkfield definition found (all contexts)
      st_sub_handles: every ST sub-field handle (for P1.7a dup detection)
      st_field_count: number of ST-typed fields found (top-level + nested);
                      distinct from whether sub-handles were collected — used to
                      tell "ST not installed" from "ST installed, scan failed"
      all_fields:     EVERY field (top-level + every block-type context), used
                      for the global duplicate-handle report and type collectors

    Both Super Table AND Matrix external block types are merged, and nested
    block types (e.g. a Super Table field inside a Matrix block) are resolved
    recursively — so a field is never missed just because its parent field does
    not appear as a top-level YAML.
    """
    lf_records = []
    st_sub_handles = []
    all_fields = []
    st_counter = {'n': 0}
    st_external = _load_external_blocks(config_dir, 'superTableBlockTypes')
    mt_external = _load_external_blocks(config_dir, 'matrixBlockTypes')

    def record(handle, name, ftype, settings, filepath, context,
               parent_handle, block_type_name):
        all_fields.append({
            'handle': handle, 'name': name, 'type': ftype,
            'context': context, 'parent_handle': parent_handle,
            'block_type_name': block_type_name, 'filepath': filepath,
        })
        if ftype == ST_TYPE:
            st_counter['n'] += 1
        if ftype in LF_TYPES:
            lf_records.append(_lf_record(
                handle, name, settings, filepath, context,
                parent_handle, block_type_name, ftype,
            ))

    def walk(parent_type, parent_handle, block_types, filepath, seen_uids):
        ctx = 'supertable' if parent_type == ST_TYPE else 'matrix'
        if not isinstance(block_types, dict):
            return
        for bt_uid, bt_data in block_types.items():
            if not isinstance(bt_data, dict):
                continue
            bt_name = bt_data.get('name', '') or bt_uid
            # Externally-stored blocks carry their own source path; inline blocks
            # live in the parent field's YAML (filepath).
            bt_file = bt_data.get('__src__', filepath)
            fields_in_bt = bt_data.get('fields', {}) or {}
            if not isinstance(fields_in_bt, dict):
                continue
            for f_uid, f_data in fields_in_bt.items():
                if not isinstance(f_data, dict):
                    continue
                f_handle = f_data.get('handle', '') or ''
                f_type = f_data.get('type', '') or ''
                f_name = f_data.get('name', '') or ''
                f_settings = _get_settings(f_data)

                if parent_type == ST_TYPE and f_handle:
                    st_sub_handles.append({
                        'handle': f_handle, 'name': f_name, 'type': f_type,
                        'filepath': bt_file, 'parent_st_handle': parent_handle,
                        'block_type_name': bt_name,
                    })

                record(f_handle, f_name, f_type, f_settings, bt_file, ctx,
                       parent_handle, bt_name)

                # Recurse when the sub-field is itself an ST/Matrix field, so
                # ST-inside-Matrix (and any depth) resolves. Guard UID cycles.
                if f_type in (ST_TYPE, MT_TYPE):
                    key = f_uid or f_handle
                    if key and key not in seen_uids:
                        seen_uids.add(key)
                        nested = _resolve_block_types(
                            f_data, f_uid, f_type, st_external, mt_external
                        )
                        walk(f_type, f_handle, nested, filepath, seen_uids)

    field_sep = os.sep + 'fields' + os.sep
    for filepath, data in iter_config_yamls(config_dir):
        field_type = data.get('type', '') or ''
        if not field_type:
            continue
        handle = data.get('handle', '') or ''
        name = data.get('name', '') or ''
        settings = _get_settings(data)
        field_uid = _field_uid_from_path(filepath)

        # Only YAMLs under config/project/fields/ are top-level field definitions.
        # Other config (entry types, sites, …) can also carry a `type` key — they
        # must not pollute the global field inventory. Linkfield/ST/Matrix matches
        # below are namespace-specific so this filter only affects native types.
        if field_sep in filepath:
            record(handle, name, field_type, settings, filepath, 'top-level', '', '')

        if field_type in (ST_TYPE, MT_TYPE):
            block_types = _resolve_block_types(
                data, field_uid, field_type, st_external, mt_external
            )
            walk(field_type, handle, block_types, filepath, {field_uid})

    return lf_records, st_sub_handles, st_counter['n'], all_fields


# ── DB-authoritative field inventory ──────────────────────────────────────────
#
# The `fields` table is the source of truth: it lists every field in every
# context with its type and settings, immune to project-config structural drift
# across Craft/plugin versions. When MYSQL_CMD/DB_NAME are supplied (established
# in SKILL.md P1.2, which runs before P1.7), it drives every inventory and the
# global duplicate-handle report, and is diffed against the config parser to
# flag any discrepancy. MySQL only.

_MYSQL_ESCAPES = {'\\t': '\t', '\\n': '\n', '\\0': '\0', '\\\\': '\\'}


def _mysql_unescape(s):
    """Reverse mysql --batch output escaping (\\t \\n \\0 \\\\)."""
    return re.sub(r'\\.', lambda m: _MYSQL_ESCAPES.get(m.group(0), m.group(0)[1]), s)


def _run_mysql(mysql_cmd, db_name, sql):
    """Run a read-only SELECT. Returns a list of column-lists, or None on failure."""
    try:
        argv = shlex.split(mysql_cmd) + ['-N', '-B', '-e', sql, db_name]
    except ValueError:
        return None
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    rows = []
    for line in proc.stdout.split('\n'):
        if line == '':
            continue
        rows.append([_mysql_unescape(c) for c in line.split('\t')])
    return rows


def _db_block_type_parents(mysql_cmd, db_name, table, prefix=''):
    """Map block-type identifier → (parent field handle, block type name).

    The `fields.context` column references a block type by its **UID** on
    Craft 4 (e.g. `superTableBlockType:3c489301-…`), but older Craft versions
    used the integer id. Key the result by BOTH id and uid so the lookup in
    build_db_inventory resolves whichever form the context carries — keying by
    id alone made every ST/matrix sub-field resolve to '?' on real Craft 4 DBs.

    matrixblocktypes has a name column; supertableblocktypes does not (ST block
    types are auto-named), so its name is reported empty.
    """
    has_name = (table == 'matrixblocktypes')
    cols = 'bt.id, bt.uid, ' + ('bt.name' if has_name else "''") + ', f.handle'
    rows = _run_mysql(
        mysql_cmd, db_name,
        f'SELECT {cols} FROM {prefix}{table} bt JOIN {prefix}fields f ON f.id = bt.fieldId'
    )
    result = {}
    for row in (rows or []):
        if len(row) >= 4:
            bt_id, bt_uid, bt_name, handle = row[0], row[1], row[2], row[3]
            value = (handle, bt_name)
            if bt_id:
                result[bt_id] = value
            if bt_uid:
                result[bt_uid] = value
    return result


def _detect_table_prefix(mysql_cmd, db_name):
    """Detect a CRAFT_DB_TABLE_PREFIX (e.g. 'craft_') by probing table names.

    Returns the prefix string, or None if no prefixed fields table is found.
    Candidates are validated by checking that '{prefix}elements' also exists.
    """
    rows = _run_mysql(mysql_cmd, db_name, "SHOW TABLES LIKE '%fields'")
    candidates = sorted(
        {r[0][:-len('fields')] for r in (rows or []) if r and r[0].endswith('fields')},
        key=len,
    )
    for prefix in candidates:
        if not prefix:
            continue  # bare `fields` — the unprefixed query already failed
        if _run_mysql(mysql_cmd, db_name, f"SHOW TABLES LIKE '{prefix}elements'"):
            return prefix
    return None


def build_db_inventory(mysql_cmd, db_name, config_index=None, table_prefix=''):
    """Build the authoritative field inventory from the DB.

    Returns a dict with the same record shapes collect_all_fields produces
    (lf_records, st_sub_handles, st_field_count, all_fields), or None if the
    DB is unreachable / the query fails. config_index (optional) maps
    (handle, context, parent_handle) → filepath for best-effort enrichment.
    table_prefix is the CRAFT_DB_TABLE_PREFIX value ('' on most Craft 4 sites,
    'craft_' on Craft 3 carry-overs).
    """
    rows = _run_mysql(
        mysql_cmd, db_name,
        "SELECT id, COALESCE(uid,''), COALESCE(handle,''), COALESCE(name,''), "
        "COALESCE(context,''), COALESCE(type,''), COALESCE(settings,'') "
        f"FROM {table_prefix}fields"
    )
    if rows is None:
        return None

    mbt = _db_block_type_parents(mysql_cmd, db_name, 'matrixblocktypes', table_prefix)
    sbt = _db_block_type_parents(mysql_cmd, db_name, 'supertableblocktypes', table_prefix)
    config_index = config_index or {}

    lf_records, st_sub_handles, all_fields = [], [], []
    st_field_count = 0

    for row in rows:
        if len(row) < 7:
            continue
        _id, _uid, handle, name, context, ftype, settings_raw = row[:7]
        settings = _get_settings({'settings': settings_raw})

        if context in ('', 'global'):
            ctx_label_name, parent_handle, bt_name = 'top-level', '', ''
        elif context.startswith('matrixBlockType:'):
            parent_handle, bt_name = mbt.get(context.split(':', 1)[1], ('?', ''))
            ctx_label_name = 'matrix'
        elif context.startswith('superTableBlockType:'):
            parent_handle, _ = sbt.get(context.split(':', 1)[1], ('?', ''))
            ctx_label_name, bt_name = 'supertable', ''
        else:
            ctx_label_name, parent_handle, bt_name = context, '', ''

        filepath = config_index.get((handle, ctx_label_name, parent_handle), '')

        all_fields.append({
            'handle': handle, 'name': name, 'type': ftype,
            'context': ctx_label_name, 'parent_handle': parent_handle,
            'block_type_name': bt_name, 'filepath': filepath,
        })
        if ftype == ST_TYPE:
            st_field_count += 1
        if ctx_label_name == 'supertable' and handle:
            st_sub_handles.append({
                'handle': handle, 'name': name, 'type': ftype,
                'filepath': filepath, 'parent_st_handle': parent_handle,
                'block_type_name': bt_name,
            })
        if ftype in LF_TYPES:
            lf_records.append(_lf_record(
                handle, name, settings, filepath, ctx_label_name,
                parent_handle, bt_name, ftype,
            ))

    return {
        'lf_records': lf_records,
        'st_sub_handles': st_sub_handles,
        'st_field_count': st_field_count,
        'all_fields': all_fields,
    }


def _config_filepath_index(config_all_fields):
    """Index config-parsed fields by (handle, context, parent_handle) → filepath."""
    index = {}
    for f in config_all_fields:
        key = (f.get('handle', ''), f.get('context', ''), f.get('parent_handle', ''))
        if f.get('filepath') and key not in index:
            index[key] = f['filepath']
    return index


def report_db_config_discrepancy(config_all_fields, db_all_fields):
    """Diff config-parsed vs DB field sets by (handle, context, type).

    A clean diff is the trust signal that the config parser is complete; a dirty
    diff tells the operator the config-only path is unreliable on this project.
    """
    section('P1.7 CONFIG/DB FIELD INVENTORY CROSS-CHECK')

    def keyset(fields):
        return {(f.get('handle', ''), f.get('context', ''), f.get('type', ''))
                for f in fields if f.get('handle')}

    cfg, db = keyset(config_all_fields), keyset(db_all_fields)
    missed_by_config = db - cfg
    only_in_config = cfg - db

    if not missed_by_config and not only_in_config:
        info('Config parser matches the database exactly — inventory is complete.')
        return

    if missed_by_config:
        def _is_formie(ctx, ftype):
            return (ctx or '').startswith('formie:') or 'verbb\\formie' in (ftype or '')

        genuine = sorted(e for e in missed_by_config if not _is_formie(e[1], e[2]))
        formie = sorted(e for e in missed_by_config if _is_formie(e[1], e[2]))

        if genuine:
            warn('CONFIG/DB MISMATCH — fields in the DB the config parser MISSED:')
            warn('(The DB figures above are authoritative; config-only runs would')
            warn(' under-report these.)')
            for handle, ctx, ftype in genuine:
                tname = (ftype or '?').rsplit('\\', 1)[-1]
                info(f'    → {handle}  [{ctx}]  type: {tname}')
            print()

        if formie:
            info('Formie fields not in project config '
                 '(expected — Formie fields live outside project config, not a mismatch):')
            for handle, ctx, ftype in formie:
                tname = (ftype or '?').rsplit('\\', 1)[-1]
                info(f'    → {handle}  [{ctx}]  type: {tname}')
            print()

    if only_in_config:
        warn('Fields in config NOT present in the DB (stale config / pending apply):')
        for handle, ctx, ftype in sorted(only_in_config):
            tname = (ftype or '?').rsplit('\\', 1)[-1]
            info(f'    → {handle}  [{ctx}]  type: {tname}')
        print()


# ── P1.7 – Linkfield inventory ────────────────────────────────────────────────

def run_p17(lf_records):
    section(r'P1.7 LINKFIELD FIELDS (lenz\linkfield or typedlinkfield)')
    if not lf_records:
        none_found()
        return

    legacy_ns = r'typedlinkfield\fields\LinkField'
    has_legacy = any(rec.get('field_type') == legacy_ns for rec in lf_records)
    if has_legacy:
        warn('Legacy typedlinkfield namespace detected in project config.')
        info(f'  One or more fields are still stored as {legacy_ns}.')
        info('  Likely a Craft 3 → 4 carry-over: the plugin renamed to')
        info(r'  lenz\linkfield\fields\LinkField but the YAML was never re-saved.')
        info('  No action needed pre-upgrade — the craft-5-upgrade composer bump')
        info('  to ^3.0.0-beta + `php craft up` rewrite the field-type string.')

    for rec in lf_records:
        print()
        ctx, parent, bt = rec['context'], rec['parent_handle'], rec['block_type_name']
        if ctx == 'top-level':
            loc = '[top-level field]'
        else:
            loc = f'[{ctx} sub-field: {parent} / block type: {bt}]'
        info(f"handle: {rec['handle']}  {loc}")
        info(f"  name:         {rec['name']}")
        suffix = rec['column_suffix']
        info(f"  columnSuffix: {suffix if suffix else '(none)'}")
        links = rec['allowed_link_names']
        info(f"  enabledTypes: {', '.join(links) if links else '(all / not restricted)'}")
        if rec.get('field_type') == legacy_ns:
            info('  namespace:    typedlinkfield (legacy)')
        info(f"  file: {rec['filepath']}")


# ── P1.7a – Super Table duplicate handles ─────────────────────────────────────

def run_p17a(st_sub_handles, st_field_count):
    section('P1.7a SUPER TABLE DUPLICATE FIELD HANDLES')
    if not st_field_count:
        info('No Super Table fields found in project config — skipping')
        return
    if not st_sub_handles:
        warn('Super Table fields found but no sub-fields collected.')
        warn('Check config/project/superTableBlockTypes/ — YAMLs may have an unexpected structure.')
        return

    info('Scanning Super Table block type field handles...')
    by_handle = defaultdict(list)
    for rec in st_sub_handles:
        by_handle[rec['handle']].append(rec)

    dupes = {h: recs for h, recs in by_handle.items() if len(recs) > 1}
    if not dupes:
        info('No duplicate handles found.')
        return

    print()
    for handle, recs in sorted(dupes.items()):
        found(f"Duplicate handle: '{handle}'")
        for rec in recs:
            info(f"    → ST field '{rec['parent_st_handle']}' / block type '{rec['block_type_name']}'")
            info(f"      ({rec['filepath']})")
    print()
    warn('Duplicate handles will be deduplicated post-upgrade (handle → handle2, handle3...).')
    warn('If any duplicate also has linkfield data, only one copy will be migrated.')
    warn('Remediate ALL duplicates in Block P2 before proceeding.')

    return dupes


# ── P1.7b – Non-ST duplicate linkfield handles ────────────────────────────────

def run_p17b(lf_records):
    section('P1.7b NON-SUPERTABLE DUPLICATE LINKFIELD HANDLES')
    non_st = [r for r in lf_records if r['context'] != 'supertable']
    by_handle = defaultdict(list)
    for rec in non_st:
        by_handle[rec['handle']].append(rec)

    dupes = {h: recs for h, recs in by_handle.items() if len(recs) > 1}
    if not dupes:
        info('No duplicate handles found across top-level / matrix contexts.')
        return

    print()
    warn('These linkfield handles appear in multiple non-ST contexts.')
    warn("craft-5-linkfield's getAllFields() may return only one instance per handle.")
    warn('Consider renaming before upgrade using the P2 remediation pattern.')
    print()
    for handle, recs in sorted(dupes.items()):
        found(f"Handle '{handle}' appears in {len(recs)} contexts:")
        for rec in recs:
            if rec['context'] == 'top-level':
                info(f"    → top-level field  ({rec['filepath']})")
            else:
                info(f"    → {rec['context']}: {rec['parent_handle']} / block '{rec['block_type_name']}'")
                info(f"      ({rec['filepath']})")

    return dupes


# ── P1.7d – Global duplicate handles ──────────────────────────────────────────

def run_p17d(all_fields):
    """Report handles that collide across ALL fields and contexts.

    Craft 5 deduplicates handles globally across every field, so this is the
    superset of P1.7a (ST-only) and P1.7b (linkfield-only). Groups are split:
      risky         — contains a linkfield: real getAllFields() data-loss risk,
                      must be remediated in Block P2.
      informational — native-type duplicates only: Craft 5 auto-suffixes them
                      (handle → handle2), content-safe.
    """
    section('P1.7d GLOBAL DUPLICATE HANDLES (all fields, all contexts)')
    if not all_fields:
        info('No fields collected — skipping.')
        return {'risky': {}, 'informational': {}}

    by_handle = defaultdict(list)
    for f in all_fields:
        if f.get('handle'):
            by_handle[f['handle']].append(f)
    dupes = {h: recs for h, recs in by_handle.items() if len(recs) > 1}
    if not dupes:
        info('No duplicate handles found across all fields and contexts.')
        return {'risky': {}, 'informational': {}}

    risky, informational = {}, {}
    for handle, recs in dupes.items():
        if any(r.get('type') in LF_TYPES for r in recs):
            risky[handle] = recs
        else:
            informational[handle] = recs

    def _dump(groups):
        for handle, recs in sorted(groups.items()):
            found(f"Duplicate handle: '{handle}'  ({len(recs)} instances)")
            for r in recs:
                tname = (r.get('type') or '?').rsplit('\\', 1)[-1]
                info(f"    → {ctx_label(r)}  type: {tname}")
                if r.get('filepath'):
                    info(f"      ({r['filepath']})")

    if risky:
        print()
        warn('RISKY duplicates — a linkfield shares this handle across contexts.')
        warn("craft-5-linkfield's getAllFields() surfaces only one instance per")
        warn('handle, so duplicate linkfield data can be lost. Remediate in Block P2.')
        print()
        _dump(risky)

    if informational:
        print()
        info('Informational duplicates — native-type handles only (no linkfield).')
        info('Craft 5 consolidates/auto-suffixes these (handle → handle2); content-safe.')
        info('Listed for completeness; no pre-upgrade action required.')
        print()
        _dump(informational)

    return {'risky': risky, 'informational': informational}


# ── P1.7c – URL field promotion candidates ────────────────────────────────────

def _collect_url_fields(all_fields):
    """Collect all craft\\fields\\Url fields from the full field inventory.

    Operates on the recursively-collected field list (or DB rows), so URL fields
    nested inside Matrix/Super Table block types are included — not just
    top-level fields.
    """
    url_fields = []
    for f in all_fields:
        if f.get('type') == URL_TYPE and f.get('handle'):
            url_fields.append({
                'handle': f['handle'],
                'name': f.get('name', '') or '',
                'filepath': f.get('filepath', '') or '',
                'context': f.get('context', 'top-level'),
                'parent_handle': f.get('parent_handle', ''),
                'block_type_name': f.get('block_type_name', ''),
                'breaking_refs': [],
                'all_ref_files': set(),
            })
    return url_fields


def load_templates(templates_dir):
    """Read every .twig/.html file under templates_dir ONCE.

    Returns {filepath: text}. All template scanners (P1.7c, P1.8, P1.8b, P1.9)
    consume this cache so the template tree is walked and read a single time
    per audit run instead of once per pattern/handle.
    """
    cache = {}
    if not templates_dir.is_dir():
        return cache
    for root, _, files in os.walk(str(templates_dir)):
        for fname in sorted(files):
            if not (fname.endswith('.twig') or fname.endswith('.html')):
                continue
            fpath = os.path.join(root, fname)
            try:
                cache[fpath] = open(fpath, encoding='utf-8', errors='replace').read()
            except (OSError, IOError):
                pass
    return cache


def _find_url_breaking_patterns(tpl_cache, handle):
    """
    Scan templates for uses of a URL field handle that break when Craft 5
    auto-promotes it from craft\\fields\\Url to craft\\fields\\Link.

    Returns (breaking_hits, all_ref_files):
      breaking_hits: list of (fpath, lineno, line, pattern_type)
      all_ref_files: set of all template files that reference the handle at all
    """
    breaking_hits = []
    all_ref_files = set()

    length_re = re.compile(re.escape(handle) + r'\s*\|length')
    in_test_re = re.compile(r'\bin\s+\S*' + re.escape(handle) + r'\b')

    for fpath in sorted(tpl_cache):
        for lineno, line in enumerate(tpl_cache[fpath].splitlines(), 1):
            if handle not in line:
                continue
            stripped = line.rstrip()
            all_ref_files.add(fpath)
            if length_re.search(line):
                breaking_hits.append((fpath, lineno, stripped, '|length'))
            elif in_test_re.search(line):
                breaking_hits.append((fpath, lineno, stripped, 'in-test'))

    return breaking_hits, all_ref_files


def run_p17c(url_fields, tpl_cache):
    section(r'P1.7c URL FIELDS — CANDIDATES FOR Craft 5 AUTO-PROMOTION TO craft\fields\Link')
    if not url_fields:
        info(r'No craft\fields\Url fields found in project config.')
        return url_fields

    info(r'Craft 5 auto-promotes craft\fields\Url to craft\fields\Link (URL-only variant).')
    info('These are NOT linkfield fields — they are plain URL fields that change runtime type.')
    print()

    any_breaking = False
    for field in url_fields:
        handle = field['handle']
        if not handle:
            continue
        breaking, ref_files = _find_url_breaking_patterns(tpl_cache, handle)
        field['breaking_refs'] = breaking
        field['all_ref_files'] = ref_files

        print()
        found(f"handle: '{handle}'  [name: {field['name']!r}]  {ctx_label(field)}")
        if field.get('filepath'):
            info(f"  file: {field['filepath']}")

        if breaking:
            any_breaking = True
            warn('  Breaking template patterns:')
            for fpath, lineno, line, pat_type in breaking:
                info(f'    [{pat_type}] {fpath}:{lineno}: {line.strip()}')
        elif ref_files:
            info(f'  No breaking patterns detected (handle referenced in {len(ref_files)} file(s)).')
            for rf in sorted(ref_files)[:3]:
                info(f'    {rf}')
            if len(ref_files) > 3:
                info(f'    ... and {len(ref_files) - 3} more')
        else:
            info('  No template references found.')

    print()
    if any_breaking:
        warn('Breaking patterns above must be fixed manually after `php craft up`.')
    warn('After promotion, bare access still works via __toString(), but use .url for clarity:')
    warn(r"  {{ entry.x }}              — still works (LinkData __toString returns URL)")
    warn(r"  {{ entry.x.url }}          — explicit, preferred")
    warn(r"  {% if entry.x|length %}    → {% if entry.x.url|length %}")
    warn(r"  {% if 'foo' in entry.x %}  → {% if 'foo' in entry.x.url %}")
    warn('See craft-5-linkfield references/template-migration.md — URL field auto-promotion.')

    return url_fields


# ── P1.14 – Redactor fields (CKEditor conversion candidates) ─────────────────

def _collect_redactor_fields(all_fields):
    """Collect all craft\\redactor\\Field fields from the full field inventory.

    Operates on the recursively-collected field list (or DB rows), so Redactor
    fields nested inside Matrix/Super Table block types are included.
    """
    redactor_fields = []
    for f in all_fields:
        if f.get('type') == REDACTOR_TYPE and f.get('handle'):
            redactor_fields.append({
                'handle': f['handle'],
                'name': f.get('name', '') or '',
                'filepath': f.get('filepath', '') or '',
                'context': f.get('context', 'top-level'),
                'parent_handle': f.get('parent_handle', ''),
                'block_type_name': f.get('block_type_name', ''),
            })
    return redactor_fields


def _composer_has(project_root, package):
    """Return True if `package` is in composer.json require/require-dev."""
    composer_json = project_root / 'composer.json'
    if not composer_json.exists():
        return False
    try:
        data = json.loads(composer_json.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return False
    requires = {
        **((data.get('require') or {})),
        **((data.get('require-dev') or {})),
    }
    return package in requires


def _composer_has_redactor(project_root):
    return _composer_has(project_root, 'craftcms/redactor')


def _composer_has_ckeditor(project_root):
    return _composer_has(project_root, 'craftcms/ckeditor')


def run_p114(redactor_fields, project_root):
    section('P1.14 REDACTOR FIELDS — CKEditor CONVERSION CANDIDATES')
    has_pkg = _composer_has_redactor(project_root)
    has_ckeditor = _composer_has_ckeditor(project_root)
    if not redactor_fields and not has_pkg:
        info('No craftcms/redactor package or Redactor fields detected — skipping.')
        return []

    if has_pkg:
        info('composer.json requires craftcms/redactor (abandoned — superseded by craftcms/ckeditor).')
    if not redactor_fields:
        info(r'No craft\redactor\Field fields found in project config.')
        info('You may still need to remove the abandoned package after upgrade.')
        return []

    print()
    info(f'Found {len(redactor_fields)} Redactor field(s):')
    for f in redactor_fields:
        print()
        found(f"handle: '{f['handle']}'  [name: {f['name']!r}]  {ctx_label(f)}")
        if f.get('filepath'):
            info(f"  file: {f['filepath']}")

    print()
    if has_ckeditor:
        # CKEditor already in use — skip the install/require steps and just
        # surface the convert command for the remaining Redactor fields.
        info('craftcms/ckeditor is already in composer.json — install/require steps not needed.')
        warn('Convert the remaining Redactor fields with:')
        warn('    php craft ckeditor/convert/redactor')
        warn('Then `composer remove craftcms/redactor` once no Redactor fields remain.')
    else:
        warn('craftcms/redactor is abandoned. Replacement: craftcms/ckeditor, which')
        warn('supports BOTH Craft 4 and Craft 5 and ships a conversion command:')
        warn('    php craft ckeditor/convert/redactor')
        warn('')
        warn('RECOMMENDED: do the Redactor→CKEditor swap on Craft 4 BEFORE the Craft 5')
        warn('upgrade, so the two migrations are isolated and easier to debug:')
        warn('  1. composer require craftcms/ckeditor  (Craft 4 — installs the 3.x line)')
        warn('  2. php craft plugin/install ckeditor   (composer alone does not enable it)')
        warn('  3. php craft ckeditor/convert/redactor')
        warn('  4. Visual-diff a sample of converted entries.')
        warn('  5. composer remove craftcms/redactor')
        warn('  6. Commit, then proceed with the Craft 5 upgrade as normal.')
        warn('')
        warn('Fallback: defer the swap to post-upgrade (U3.3 or L4.4). Works, but')
        warn('mixes two migrations and is harder to bisect if something looks off.')

    return redactor_fields


# ── P1.15 – craft-utils non-stringable Formie field risk ──────────────────────

def _collect_nonstringable_formie_fields(all_fields):
    """Collect Formie field types that have no __toString().

    ForeignFieldQueryListener.onBeforeQueryPrepare() (craft-utils) calls
    array_unique(..., SORT_STRING) over ALL custom field objects in every queried
    element type's field layouts — before filtering to its own ForeignField
    instances. Formie Heading/Html/Section/Summary have no __toString(), so PHP
    fatals when any of them share an element type layout with a linkfield.

    Operates on the same all_fields shape both DB and config paths produce.
    """
    return [
        f for f in all_fields
        if f.get('type') in NONSTRINGABLE_FORMIE_TYPES and f.get('handle')
    ]


def run_p115(all_fields, project_root):
    section('P1.15 LINKFIELD + craft-utils — non-stringable Formie field risk')
    has_linkfield = _composer_has(project_root, 'sebastianlenz/linkfield')
    has_formie = _composer_has(project_root, 'verbb/formie')
    fields = _collect_nonstringable_formie_fields(all_fields)
    risk = has_linkfield and has_formie and bool(fields)

    if not has_linkfield:
        info('sebastianlenz/linkfield not in composer.json — not applicable.')
        return {'risk': False, 'fields': fields, 'has_linkfield': False, 'has_formie': has_formie}
    if not has_formie:
        info('verbb/formie not in composer.json — not applicable.')
        return {'risk': False, 'fields': fields, 'has_linkfield': True, 'has_formie': False}
    if not fields:
        info('No non-stringable Formie fields found (Heading, Html, Section, Summary).')
        info('LINKFIELD_CRAFTUTILS_FORMIE_HEADING_RISK: no')
        return {'risk': False, 'fields': fields, 'has_linkfield': True, 'has_formie': True}

    warn('LINKFIELD_CRAFTUTILS_FORMIE_HEADING_RISK: yes')
    print()
    warn('ForeignFieldQueryListener.onBeforeQueryPrepare() (craft-utils) calls')
    warn('array_unique(..., SORT_STRING) over ALL custom field objects in every')
    warn("queried element type's field layouts — before filtering to ForeignField.")
    warn('Formie Heading/Html/Section/Summary have no __toString(), so PHP fatals:')
    warn('  "Object of class ... could not be converted to string"')
    warn('Formie migrations call Form::find()->all() during `php craft up`, triggering')
    warn('this listener against Form layouts that contain the offending field.')
    print()
    warn('The craft-5-upgrade skill pre-patches craft-utils (U2.1.5) before running')
    warn('`php craft up`, preventing this fatal unconditionally for linkfield projects.')
    warn('This detection is predictive only — the patch runs regardless.')
    print()
    info('Offending fields:')
    for f in fields:
        tname = (f.get('type') or '?').rsplit('\\', 1)[-1]
        ctx = f.get('context', 'top-level') or 'top-level'
        parent = f.get('parent_handle', '') or ''
        loc = '[top-level field]' if ctx == 'top-level' else f'[{ctx} sub-field: {parent}]'
        found(f"handle: '{f['handle']}'  type: {tname}  {loc}")

    return {'risk': risk, 'fields': fields, 'has_linkfield': True, 'has_formie': True}


# ── P1.8 – Deprecated API calls and .with() ───────────────────────────────────

DEPRECATED_PATTERNS = [
    '.getUrl(',
    '.getCustomText(',
    '.getTarget(',
    '.getType',
    '.getElement(',
    '.getLinkAttributes(',
    'craft.matrixBlocks(',
]


def _grep_cache(tpl_cache, patterns):
    """One pass over the template cache for a list of fixed-string patterns.

    Returns {pattern: [(fpath, lineno, line), ...]}.
    """
    results = {p: [] for p in patterns}
    for fpath in sorted(tpl_cache):
        for lineno, line in enumerate(tpl_cache[fpath].splitlines(), 1):
            for pattern in patterns:
                if pattern in line:
                    results[pattern].append((fpath, lineno, line.rstrip()))
    return results


def run_p18(templates_dir, tpl_cache):
    section('P1.8 TEMPLATE DEPRECATED API CALLS')
    if not templates_dir.is_dir():
        warn(f'{templates_dir} not found — skipping')
        return set(), set()

    hits_by_pattern = _grep_cache(tpl_cache, DEPRECATED_PATTERNS + ['.with(['])

    deprecated_files = set()
    any_found = False
    for pattern in DEPRECATED_PATTERNS:
        hits = hits_by_pattern[pattern]
        if hits:
            any_found = True
            print()
            info(f'Pattern: {pattern}')
            for fpath, lineno, line in hits:
                info(f'  {fpath}:{lineno}: {line}')
                deprecated_files.add(fpath)
    if not any_found:
        none_found()

    section('P1.8 TEMPLATE .with() CALLS (check for linkfield handles)')
    with_files = set()
    hits = hits_by_pattern['.with([']
    if hits:
        info('Cross-reference these against linkfield handles from P1.7.')
        info('Any .with() call on a migrated handle must be removed in craft-5-linkfield Block L3.')
        print()
        for fpath, lineno, line in hits:
            info(f'  {fpath}:{lineno}: {line}')
            with_files.add(fpath)
    else:
        none_found()

    return deprecated_files, with_files


# ── P1.8b – Handle reference files ───────────────────────────────────────────

def run_p18b(templates_dir, tpl_cache, lf_records, deprecated_files, with_files):
    section('P1.8b HANDLE REFERENCE FILES (for L3 patcher file list)')
    if not templates_dir.is_dir() or not lf_records:
        none_found()
        return set()

    handles = sorted({r['handle'] for r in lf_records if r['handle']})
    if not handles:
        none_found()
        return set()

    info('All template files referencing any linkfield handle (bare, method call, argument dict, or include target bound to a handle).')
    info('Use this list as the --files argument to patch-templates.py in Block L3.')
    print()

    pat = re.compile(r'\b(' + '|'.join(re.escape(h) for h in handles) + r')\b')
    # Twig include(...) calls with an argument dict. Captures path + dict body.
    # The dict body match is intentionally permissive — we only inspect its
    # contents for handle tokens, so nested braces/multi-line dicts are fine
    # in practice (the regex tolerates one level of nesting).
    # Twig has two include forms — function `include("path", { ... })` and
    # tag `{% include "path" with { ... } %}`. Match both.
    include_pat = re.compile(
        r'(?:\binclude\s*\(\s*|\{%-?\s*include\s+)'
        r'["\']([^"\']+)["\']'
        r'(?:\s*,\s*|\s+with\s+)'
        r'(\{(?:[^{}]|\{[^{}]*\})*\})',
        re.DOTALL,
    )
    handle_ref_files = defaultdict(set)

    def add_include_target(src_dir, target_str, handles_found):
        """Resolve a Twig include path and mark the target file as needing patching.

        Twig templates that receive a linkfield via include argument reference
        the bound *variable name* (e.g. `linkField.url()`), not the handle —
        so a plain handle-token scan misses them. The include's caller binds
        the handle, so we propagate the handle association to the target.
        """
        # Strip leading '@namespace/' if present (e.g. @app/foo) — namespace
        # roots can't be resolved generically; fall back to templates_dir-relative.
        rel = re.sub(r'^@[^/]+/', '', target_str)
        candidates = []
        if rel.endswith('.twig') or rel.endswith('.html'):
            candidates.append(rel)
        else:
            candidates.extend([rel + '.twig', rel + '.html', rel + '/index.twig'])
        for cand in candidates:
            # Try templates_dir-relative first, then source-file-relative.
            for base in (templates_dir, Path(src_dir)):
                p = (base / cand).resolve()
                if p.is_file() and str(p).startswith(str(templates_dir.resolve())):
                    for h in handles_found:
                        handle_ref_files[str(p)].add(h)
                    return

    for fpath in sorted(tpl_cache):
        text = tpl_cache[fpath]
        for m in pat.finditer(text):
            handle_ref_files[fpath].add(m.group(1))
        # Cross-file: if this file binds a handle into an include's
        # argument dict, the included target also needs L3 patching.
        for im in include_pat.finditer(text):
            target, arg_dict = im.group(1), im.group(2)
            handles_in_args = {hm.group(1) for hm in pat.finditer(arg_dict)}
            if handles_in_args:
                add_include_target(os.path.dirname(fpath), target, handles_in_args)

    all_files = set(handle_ref_files) | deprecated_files | with_files

    previously_listed = deprecated_files | with_files
    new_files = all_files - previously_listed

    if new_files:
        warn('Files below reference linkfield handles but have NO deprecated API calls.')
        warn('They would be missed by P1.8 alone — include them in the L3 patcher file list.')
        print()
        for fpath in sorted(new_files):
            handles_in = ', '.join(sorted(handle_ref_files.get(fpath, set())))
            found(f'{fpath}')
            info(f'    ↳ references: {handles_in}')
        print()

    if not all_files:
        none_found()

    return all_files


# ── P1.9 – Template extension collisions ─────────────────────────────────────

def run_p19(tpl_cache):
    """Report base names that exist as BOTH .twig and .html in templates/.

    Only one of the pair is served (per Craft's template-extension resolution
    order) — the other is dead weight and a post-upgrade confusion source.
    """
    section('P1.9 TEMPLATE EXTENSION COLLISIONS (.twig + .html, same base name)')
    exts_by_base = defaultdict(set)
    for fpath in tpl_cache:
        base, ext = os.path.splitext(fpath)
        exts_by_base[base].add(ext)

    collisions = sorted(
        base for base, exts in exts_by_base.items() if {'.twig', '.html'} <= exts
    )
    if not collisions:
        info('No .twig/.html base-name collisions found.')
        return collisions

    for base in collisions:
        found(f'{base}.twig  +  {base}.html')
    print()
    warn('Only one file of each pair is served — confirm which is live and')
    warn('remove or rename the other. Record collisions in the state file Notes.')
    return collisions


# ── P1.10b – Bootstrap / entrypoint customisations ───────────────────────────

def run_p1_bootstrap(project_root):
    section('P1.10b BOOTSTRAP / ENTRYPOINT CUSTOMISATIONS')
    # Webroot is conventionally 'public' on these projects (never the Craft
    # default 'web'). Check 'public' first, fall back to 'web' for robustness.
    files_to_check = [
        project_root / 'bootstrap.php',
        project_root / 'public' / 'index.php',
        project_root / 'web' / 'index.php',
    ]
    patterns = [
        ('error_reporting',     re.compile(r'\berror_reporting\s*\(')),
        ('ini_set',             re.compile(r'\bini_set\s*\(')),
        ('Custom define()',     re.compile(r'\bdefine\s*\(')),
        ('Non-standard require', re.compile(
            r'\b(?:require|include)(?:_once)?\s+(?!["\'].*vendor)', re.IGNORECASE
        )),
    ]

    any_found = False
    for fpath in files_to_check:
        if not fpath.exists():
            continue
        try:
            lines = open(fpath, encoding='utf-8', errors='replace').readlines()
        except (OSError, IOError):
            continue
        file_hits = []
        for lineno, line in enumerate(lines, 1):
            for label, rx in patterns:
                if rx.search(line):
                    file_hits.append((lineno, label, line.rstrip()))
                    break
        if file_hits:
            any_found = True
            print()
            info(f'File: {fpath}')
            for lineno, label, line in file_hits:
                found(f'[{label}] line {lineno}: {line.strip()}')

    if not any_found:
        info('No non-standard customisations detected in bootstrap.php / public/index.php.')
    else:
        print()
        warn('Record these in BOOTSTRAP_CUSTOMISATIONS in the state file.')
        warn('They may affect behaviour during and after the upgrade (e.g. error suppression).')


# ── P1.12 – Plugins with afterSave* event hooks ───────────────────────────────

_SKIP_VENDORS = frozenset({
    'craftcms', 'yiisoft', 'symfony', 'twig', 'composer', 'doctrine',
    'guzzlehttp', 'psr', 'monolog', 'paragonie', 'vlucas', 'bacon',
    'php-http', 'ralouphie', 'myclabs', 'sebastian', 'phpunit',
})
_AFTERSAVE_PATTERNS = [
    'EVENT_AFTER_SAVE_ELEMENT',
    'EVENT_AFTER_SAVE_ENTRY',
    'afterSaveElement',
]

# Field / content plugins must NOT be disabled for the upgrade. Their afterSave*
# hooks maintain their own field data, and they ship content migrations that run
# during `php craft up` against the still-present Craft 4 content tables.
# Disabling them serializes their fields as MissingField and skips the migration
# irreversibly (the Craft 4 source tables are dropped). See the Hyper postmortem.
#
# Detected two ways: (a) a hard-coded known list of handles/package fragments,
# and (b) source signals showing the package registers a field/element/block type.
_FIELD_PLUGIN_HANDLES = frozenset({
    'hyper', 'super-table', 'supertable', 'ckeditor', 'redactor', 'formie',
    'linkfield', 'typedlinkfield', 'typed-link-field',
})
_FIELD_PLUGIN_PKG_FRAGMENTS = (
    'verbb/', 'sebastianlenz/linkfield', 'craftcms/ckeditor', 'craftcms/redactor',
)
_FIELD_SIGNAL_PATTERNS = (
    'EVENT_REGISTER_FIELD_TYPES',
    'registerFieldTypes',
    'EVENT_REGISTER_ELEMENT_TYPES',
    'extends Field',
    'extends \\craft\\base\\Field',
    'craft\\base\\FieldInterface',
)
# Signals that an afterSave* hook is a deploy/notification side effect (env-specific
# paths, external HTTP, cache busting, deploy tooling) — these ARE safe to disable.
_DEPLOY_SIGNAL_PATTERNS = (
    'GuzzleHttp',
    'file_put_contents',
    'file_get_contents',
    'curl_',
    'webhook',
    'Webhook',
    'Slack',
    '->purge',
    'invalidateCaches',
    'getResponse()->redirect',
    'shell_exec',
    'proc_open',
)


def _classify_pkg(pkg_key, handle, signals):
    """Return 'field', 'deploy', or 'unknown' for an afterSave* package.

    'field'   → field/content plugin; never disable (would skip its migration).
    'deploy'  → env-specific deploy/notification hook; safe to disable for upgrade.
    'unknown' → can't confirm; default to leaving enabled and flag for review.
    """
    h = (handle or '').lower()
    if h in _FIELD_PLUGIN_HANDLES:
        return 'field'
    if any(frag in pkg_key for frag in _FIELD_PLUGIN_PKG_FRAGMENTS):
        return 'field'
    if signals.get('field'):
        return 'field'
    if signals.get('deploy'):
        return 'deploy'
    return 'unknown'


def _build_composer_map(vendor_dir):
    """Build {package_name → composer.json data} for every vendor package."""
    result = {}
    try:
        vendor_names = os.listdir(str(vendor_dir))
    except OSError:
        return result

    for vendor_name in vendor_names:
        if vendor_name.startswith('.'):
            continue
        vp = vendor_dir / vendor_name
        if not vp.is_dir():
            continue
        try:
            pkg_names = os.listdir(str(vp))
        except OSError:
            continue
        for pkg_name in pkg_names:
            composer_json = vp / pkg_name / 'composer.json'
            if not composer_json.exists():
                continue
            try:
                result[f'{vendor_name}/{pkg_name}'] = json.loads(
                    composer_json.read_text(encoding='utf-8', errors='replace')
                )
            except (json.JSONDecodeError, OSError):
                pass
    return result


def _resolve_plugin_handle(pkg_key, composer_map):
    """Resolve a vendor package to its Craft plugin handle.

    Returns (host_pkg, handle) where host_pkg is the package containing the
    Craft plugin (may equal pkg_key) and handle is the plugin's handle from
    composer.json `extra.handle`. Returns (None, None) when no host plugin
    can be found — caller falls back to the package name.

    Craft 4 plugin convention: composer.json has `"type": "craft-plugin"` and
    `"extra": {"handle": "<handle>"}`. Vendor libraries bundled with plugins
    (e.g. sebastianlenz/craft-utils inside sebastianlenz/linkfield) register
    their own afterSave* hooks but disabling them means disabling the host
    plugin — `php craft plugin/disable <package-name>` won't work.
    """
    own = composer_map.get(pkg_key, {}) or {}
    if own.get('type') == 'craft-plugin':
        return pkg_key, ((own.get('extra') or {}).get('handle'))

    for other_pkg, other_data in composer_map.items():
        if other_pkg == pkg_key or (other_data or {}).get('type') != 'craft-plugin':
            continue
        requires = {
            **((other_data.get('require') or {})),
            **((other_data.get('require-dev') or {})),
        }
        if pkg_key in requires:
            return other_pkg, ((other_data.get('extra') or {}).get('handle'))

    return None, None


def run_p112(project_root):
    section('P1.12 PLUGINS WITH afterSave* EVENT HOOKS')
    vendor_dir = project_root / 'vendor'
    empty = {'disable': [], 'field': [], 'review': []}
    if not vendor_dir.is_dir():
        warn(f'{vendor_dir} not found — skipping')
        return empty

    info('Scanning vendor plugins for afterSave* event registrations...')
    info('(May take a moment on large vendor directories.)')

    results = {}

    try:
        vendor_names = sorted(os.listdir(str(vendor_dir)))
    except OSError:
        warn('Could not read vendor/ directory.')
        return empty

    for vendor_name in vendor_names:
        if vendor_name.startswith('.') or vendor_name in _SKIP_VENDORS:
            continue
        vendor_path = vendor_dir / vendor_name
        if not vendor_path.is_dir():
            continue

        try:
            pkg_names = sorted(os.listdir(str(vendor_path)))
        except OSError:
            continue

        for pkg_name in pkg_names:
            pkg_path = vendor_path / pkg_name
            if not pkg_path.is_dir():
                continue
            pkg_key = f'{vendor_name}/{pkg_name}'

            src_path = pkg_path / 'src'
            search_root = str(src_path) if src_path.is_dir() else str(pkg_path)

            # Accumulate signals across every PHP file in the package. Field-type
            # registration usually lives in a different file (Plugin.php, a Field
            # class) than the afterSave* hook, so signals are scanned for the whole
            # package regardless of walk order. Packages with no afterSave* hook are
            # dropped after the walk.
            entry = {'patterns': [], 'field': False, 'deploy': False}
            for dirpath, dirnames, filenames in os.walk(search_root):
                dirnames[:] = [d for d in dirnames if d not in ('vendor', 'node_modules')]
                for fname in filenames:
                    if not fname.endswith('.php'):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    try:
                        content = open(fpath, encoding='utf-8', errors='replace').read()
                    except (OSError, IOError):
                        continue
                    for pat in _AFTERSAVE_PATTERNS:
                        if pat in content and pat not in entry['patterns']:
                            entry['patterns'].append(pat)
                    if any(s in content for s in _FIELD_SIGNAL_PATTERNS):
                        entry['field'] = True
                    if any(s in content for s in _DEPLOY_SIGNAL_PATTERNS):
                        entry['deploy'] = True
            if entry['patterns']:
                results[pkg_key] = entry

    print()
    if not results:
        info('No plugins with afterSave* event hooks detected.')
        info('(If a deploy-side plugin is not listed, disable it manually before U1.2.)')
        return {'disable': [], 'field': [], 'review': []}

    composer_map = _build_composer_map(vendor_dir)
    by_category = {'field': [], 'deploy': [], 'unknown': []}
    for pkg, signals in sorted(results.items()):
        host_pkg, handle = _resolve_plugin_handle(pkg, composer_map)
        category = _classify_pkg(pkg, handle, signals)
        by_category[category].append({
            'pkg': pkg,
            'host_pkg': host_pkg,
            'handle': handle,
            'patterns': signals['patterns'],
        })

    def _label(entry):
        pkg, host_pkg, handle = entry['pkg'], entry['host_pkg'], entry['handle']
        if host_pkg and host_pkg != pkg:
            return f'{pkg}  (host plugin: {host_pkg}, handle: {handle or "?"})'
        if handle:
            return f'{pkg}  (handle: {handle})'
        return f'{pkg}  (no Craft plugin handle resolved)'

    # Field/content plugins — NEVER disable. Disabling skips their content
    # migration during `php craft up`, which is irreversible (source tables drop).
    if by_category['field']:
        warn('FIELD/CONTENT PLUGINS — DO NOT DISABLE for the upgrade.')
        warn('These run content migrations during `php craft up` that require the')
        warn('plugin enabled and the Craft 4 source tables intact. Disabling them')
        warn('serializes their fields as MissingField and skips the migration')
        warn('irreversibly. Leave them enabled throughout fix-field-layout-uids,')
        warn('composer update, and php craft up. (See the Hyper postmortem.)')
        print()
        for entry in by_category['field']:
            found(f'[KEEP ENABLED] {_label(entry)}')
            for pat in entry['patterns']:
                info(f'    ↳ {pat}')
        print()

    # Deploy/notification plugins — safe and correct to disable.
    if by_category['deploy']:
        warn('Deploy/notification plugins to disable before U1.2 (env-specific paths,')
        warn('external HTTP, or cache busting in their afterSave* hooks will fail in dev).')
        warn('Add them to PLUGINS_TO_DISABLE_FOR_UPGRADE. Re-enable on production (DEPLOY.md).')
        print()
        for entry in by_category['deploy']:
            found(f'[DISABLE] {_label(entry)}')
            for pat in entry['patterns']:
                info(f'    ↳ {pat}')
        print()

    # Unknown — can't confirm. Default to LEAVING ENABLED; flag for manual review.
    if by_category['unknown']:
        warn('UNCONFIRMED afterSave* plugins — default to LEAVING ENABLED.')
        warn('Could not confirm these are purely deploy/notification hooks. Inspect each')
        warn('afterSave* handler: only disable if it references env-specific filesystem')
        warn('paths, external HTTP endpoints, or deploy tooling. If it touches its own')
        warn('field/content data, leave it enabled (disabling it may skip a migration).')
        print()
        for entry in by_category['unknown']:
            found(f'[REVIEW] {_label(entry)}')
            for pat in entry['patterns']:
                info(f'    ↳ {pat}')
        print()

    return {
        'disable': by_category['deploy'],
        'field': by_category['field'],
        'review': by_category['unknown'],
    }


# ── P1.13 – composer.json post-update-cmd ────────────────────────────────────

def run_p113(project_root):
    section('P1.13 COMPOSER POST-UPDATE-CMD')
    composer_json = project_root / 'composer.json'
    if not composer_json.exists():
        warn(f'{composer_json} not found — skipping')
        return False

    try:
        data = json.loads(composer_json.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        warn('Could not parse composer.json — skipping')
        return False

    scripts = data.get('scripts', {}) or {}
    post_cmd = scripts.get('post-update-cmd', [])
    if isinstance(post_cmd, str):
        post_cmd = [post_cmd]

    craft_hooks = [str(c) for c in (post_cmd or []) if '@craft-update' in str(c)]

    if craft_hooks:
        found('@craft-update is registered in post-update-cmd:')
        for hook in craft_hooks:
            info(f'    {hook}')
        print()
        warn('COMPOSER_POST_UPDATE_HOOK: yes')
        warn('U2.1 (composer update) will automatically trigger php craft up via this hook.')
        warn('The craft-5-upgrade skill will account for this; U2.2 will likely be a no-op.')
        return True
    else:
        info('post-update-cmd does not include @craft-update.')
        info('COMPOSER_POST_UPDATE_HOOK: no')
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Craft 5 preflight audit. Run from the project root.'
    )
    parser.add_argument(
        'project_root', nargs='?', default='.',
        help='Path to the Craft project root (default: current directory)'
    )
    parser.add_argument(
        '--mysql-cmd', default=None,
        help='MySQL client invocation from P1.2, e.g. "mysql -h 127.0.0.1 -u root". '
             'When given with --db-name, the fields table is the authoritative '
             'inventory source and is cross-checked against project config.'
    )
    parser.add_argument(
        '--db-name', default=None,
        help='Database name (DB_NAME from P1.2). Required for the DB inventory path.'
    )
    parser.add_argument(
        '--table-prefix', default=None,
        help="CRAFT_DB_TABLE_PREFIX value (e.g. 'craft_'). Auto-detected when "
             'omitted and the bare `fields` table is not found.'
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    config_dir = project_root / 'config' / 'project'
    templates_dir = project_root / 'templates'

    if _YAML_BACKEND == 'fallback':
        print('[INFO] PyYAML not available — using built-in YAML parser.')
        print('[INFO] For broader YAML compatibility: pip install pyyaml')

    # Collect field data from project config (always — it is the offline fallback
    # and supplies filepaths the DB lacks).
    if config_dir.is_dir():
        cfg_lf, cfg_st, cfg_stc, cfg_all = collect_all_fields(config_dir)
    else:
        cfg_lf, cfg_st, cfg_stc, cfg_all = [], [], 0, []
        print(f'\n[WARN] {config_dir} not found — P1.7/P1.7a/P1.7b/P1.7c/P1.14 sections skipped.')

    # DB is authoritative when reachable. Fall back to config on absence/failure.
    inventory_source = 'config'
    db_inv = None
    if args.mysql_cmd and args.db_name:
        cfg_index = _config_filepath_index(cfg_all)
        db_inv = build_db_inventory(
            args.mysql_cmd, args.db_name, cfg_index, args.table_prefix or ''
        )
        if db_inv is None and args.table_prefix is None:
            # The bare `fields` query failed — the project may use a
            # CRAFT_DB_TABLE_PREFIX (e.g. 'craft_'). Probe for it before
            # giving up on the authoritative DB path.
            detected = _detect_table_prefix(args.mysql_cmd, args.db_name)
            if detected:
                print(f"\n[INFO] Bare `fields` table not found — detected table "
                      f"prefix '{detected}'. Using it for the DB inventory.")
                db_inv = build_db_inventory(
                    args.mysql_cmd, args.db_name, cfg_index, detected
                )
        if db_inv is None:
            print('\n[WARN] --mysql-cmd/--db-name supplied but the fields query failed '
                  '(unreachable DB, auth error, or unrecognised table prefix — '
                  'try --table-prefix). Falling back to project config.')

    if db_inv is not None:
        inventory_source = 'db'
        lf_records = db_inv['lf_records']
        st_sub_handles = db_inv['st_sub_handles']
        st_field_count = db_inv['st_field_count']
        all_fields = db_inv['all_fields']
    else:
        lf_records, st_sub_handles, st_field_count, all_fields = \
            cfg_lf, cfg_st, cfg_stc, cfg_all

    url_fields = _collect_url_fields(all_fields)
    redactor_fields = _collect_redactor_fields(all_fields)
    tpl_cache = load_templates(templates_dir)

    # ── Run all sections ──────────────────────────────────────────────────────
    if db_inv is not None:
        report_db_config_discrepancy(cfg_all, all_fields)
    run_p17(lf_records)
    run_p17a(st_sub_handles, st_field_count)
    run_p17b(lf_records)
    p17d = run_p17d(all_fields)
    url_fields = run_p17c(url_fields, tpl_cache) or url_fields
    deprecated_files, with_files = run_p18(templates_dir, tpl_cache)
    all_template_files = run_p18b(templates_dir, tpl_cache, lf_records, deprecated_files, with_files)
    extension_collisions = run_p19(tpl_cache)
    run_p1_bootstrap(project_root)
    p112 = run_p112(project_root)
    plugins_to_disable = p112['disable']
    field_plugins_keep = p112['field']
    plugins_to_review = p112['review']
    has_post_update_hook = run_p113(project_root)
    has_redactor_pkg = _composer_has_redactor(project_root)
    has_ckeditor_pkg = _composer_has_ckeditor(project_root)
    redactor_fields = run_p114(redactor_fields, project_root) or redactor_fields
    p115 = run_p115(all_fields, project_root)

    # ── State file summary ────────────────────────────────────────────────────
    print(f'\n{SEP}\n  STATE FILE SUMMARY — copy into .craft5-upgrade.md (Block P3)\n{SEP}')

    print()
    if inventory_source == 'db':
        print('FIELD_INVENTORY_SOURCE: db  # authoritative — fields table, cross-checked vs config')
    elif config_dir.is_dir():
        print('FIELD_INVENTORY_SOURCE: config  # DB not provided/unreachable — pass --mysql-cmd/--db-name for authoritative counts')
    else:
        print('FIELD_INVENTORY_SOURCE: none  # no config/project dir and no DB')

    if lf_records:
        print()
        print('## Linkfield inventory')
        print('| handle | name | context | enabled types | columnSuffix |')
        print('|--------|------|---------|---------------|--------------|')
        for rec in lf_records:
            ctx = rec['context']
            if rec['block_type_name']:
                ctx += f" / {rec['block_type_name']}"
            types = ', '.join(rec['allowed_link_names']) if rec['allowed_link_names'] else '(all)'
            suffix = rec['column_suffix'] or 'none'
            print(f"| {rec['handle']} | {rec['name']} | {ctx} | {types} | {suffix} |")

    print()
    print('## URL field promotion candidates')
    print('<!-- craft\\fields\\Url fields that Craft 5 auto-promotes to craft\\fields\\Link. -->')
    print('<!-- Review breaking patterns; fix manually in L3 (see template-migration.md). -->')
    print('URL_PROMOTION_CANDIDATES:')
    active_url_fields = [f for f in url_fields if f.get('handle')]
    if active_url_fields:
        for f in active_url_fields:
            print(f"  - handle: {f['handle']}")
            print(f"    name: {f['name']!r}")
            print(f"    file: {f['filepath']}")
            brk = f.get('breaking_refs', [])
            if brk:
                print('    breaking_refs:')
                for fpath, lineno, line, pat_type in brk:
                    print(f'      - {fpath}:{lineno}: [{pat_type}] {line.strip()[:80]}')
            else:
                print('    breaking_refs: (none detected)')
    else:
        print('  (none)')

    print()
    print('## Global duplicate handles')
    print('<!-- Craft 5 deduplicates handles globally. Risky = a linkfield shares the -->')
    print('<!-- handle (getAllFields data-loss risk; remediate in P2). Informational = -->')
    print('<!-- native-type duplicates Craft 5 auto-suffixes (content-safe). -->')
    print('GLOBAL_DUPLICATE_HANDLES:')
    risky = (p17d or {}).get('risky', {})
    informational = (p17d or {}).get('informational', {})
    if not risky and not informational:
        print('  (none)')
    else:
        for handle in sorted(risky):
            ctxs = ', '.join(sorted({ctx_label(r) for r in risky[handle]}))
            print(f'  - handle: {handle}  # RISKY (linkfield) — {ctxs}')
        for handle in sorted(informational):
            print(f'  - handle: {handle}  # informational (native, content-safe)')

    print()
    print('DEPRECATED_API_FILES:')
    for f in sorted(deprecated_files): print(f'  - {f}')
    if not deprecated_files: print('  (none)')

    print()
    print('WITH_CALL_FILES:')
    for f in sorted(with_files): print(f'  - {f}')
    if not with_files: print('  (none)')

    print()
    print('HANDLE_REFERENCE_FILES:')
    for f in sorted(all_template_files): print(f'  - {f}')
    if not all_template_files: print('  (none)')

    print()
    print('TEMPLATE_EXTENSION_COLLISIONS:')
    for base in extension_collisions: print(f'  - {base} (.twig + .html)')
    if not extension_collisions: print('  (none)')

    print()
    print('PLUGINS_TO_DISABLE_FOR_UPGRADE:')
    print('<!-- Deploy/notification plugins only. Field/content plugins are NEVER -->')
    print('<!-- listed here — see FIELD_PLUGINS_KEEP_ENABLED below. -->')
    if plugins_to_disable:
        for entry in plugins_to_disable:
            handle = entry['handle']
            host = entry['host_pkg']
            pkg = entry['pkg']
            if handle and host and host != pkg:
                print(f'  - {handle}  # afterSave* registered in {pkg} (host plugin: {host})')
            elif handle:
                print(f'  - {handle}  # afterSave* registered in {pkg}')
            else:
                print(f'  - {pkg}  # no plugin handle resolved — derive from `php craft plugin/list` and disable manually')
    else:
        print('  (none)')

    print()
    print('FIELD_PLUGINS_KEEP_ENABLED:')
    print('<!-- Field/content plugins that register afterSave* hooks. DO NOT disable -->')
    print('<!-- these for the upgrade: they run content migrations during `php craft -->')
    print('<!-- up` that require the plugin enabled and the Craft 4 source tables -->')
    print('<!-- intact. Disabling them is irreversible once those tables drop. -->')
    if field_plugins_keep:
        for entry in field_plugins_keep:
            handle = entry['handle'] or entry['pkg']
            print(f'  - {handle}  # field/content plugin — {entry["pkg"]}')
    else:
        print('  (none)')

    print()
    print('PLUGINS_FOR_MANUAL_REVIEW:')
    print('<!-- afterSave* plugins that could not be confirmed as deploy/notification -->')
    print('<!-- hooks. Default to LEAVING ENABLED. Only disable if the handler uses -->')
    print('<!-- env-specific paths, external HTTP, or deploy tooling. -->')
    if plugins_to_review:
        for entry in plugins_to_review:
            handle = entry['handle'] or entry['pkg']
            print(f'  - {handle}  # review afterSave* handler — {entry["pkg"]}')
    else:
        print('  (none)')

    print()
    print(f'COMPOSER_POST_UPDATE_HOOK: {"yes" if has_post_update_hook else "no"}')

    print()
    print('## craft-utils Formie-Heading risk (P1.15)')
    print('<!-- linkfield + verbb/formie + non-stringable Formie field (Heading/Html/Section/Summary). -->')
    print('<!-- craft-utils ForeignFieldQueryListener.onBeforeQueryPrepare() calls array_unique() -->')
    print('<!-- (SORT_STRING) over ALL field objects before filtering — fatals on non-stringable types. -->')
    print('<!-- craft-5-upgrade pre-patches craft-utils unconditionally for linkfield projects (U2.1.5). -->')
    print(f'LINKFIELD_CRAFTUTILS_FORMIE_HEADING_RISK: {"yes" if p115.get("risk") else "no"}')
    print('NONSTRINGABLE_FORMIE_FIELDS:')
    if p115.get('fields'):
        for f in p115['fields']:
            tname = (f.get('type') or '?').rsplit('\\', 1)[-1]
            print(f"  - {f['handle']} ({tname})")
    else:
        print('  (none)')

    print()
    print('## Redactor → CKEditor conversion')
    print('<!-- craftcms/redactor is abandoned. Convert to craftcms/ckeditor post-upgrade. -->')
    print(f'REDACTOR_PACKAGE_PRESENT: {"yes" if has_redactor_pkg else "no"}')
    print(f'CKEDITOR_PACKAGE_PRESENT: {"yes" if has_ckeditor_pkg else "no"}')
    print('REDACTOR_FIELDS:')
    if redactor_fields:
        for f in redactor_fields:
            print(f"  - handle: {f['handle']}")
            print(f"    name: {f['name']!r}")
            print(f"    file: {f['filepath']}")
    else:
        print('  (none)')
    print()
    print(SEP)
    print('  Audit complete.')
    print(SEP)


if __name__ == '__main__':
    main()
