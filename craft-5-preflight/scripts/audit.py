#!/usr/bin/env python3
"""
Craft 5 preflight audit script — replaces audit.sh
Run from the project root:
    python3 ~/.claude/skills/craft-5-preflight/scripts/audit.py [project_root]
Covers SKILL.md blocks P1.7, P1.7a, P1.7b, P1.8, P1.8b, P1.10b, P1.12, P1.13
"""

import argparse
import json
import os
import re
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


# ── Field type constants ──────────────────────────────────────────────────────

LF_TYPE = r'lenz\linkfield\fields\LinkField'
ST_TYPE = r'verbb\supertable\fields\SuperTableField'
MT_TYPE = r'craft\fields\Matrix'


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


def _lf_record(handle, name, settings, filepath, context, parent_handle='', block_type_name=''):
    return {
        'handle': handle,
        'name': name,
        'column_suffix': settings.get('columnSuffix'),
        'allowed_link_names': _parse_link_names(settings.get('allowedLinkNames')),
        'filepath': filepath,
        'context': context,
        'parent_handle': parent_handle,
        'block_type_name': block_type_name,
    }


def _walk_block_types(data, filepath, is_st, parent_handle):
    """
    Walk blockTypes (Super Table or Matrix) and return (lf_fields, st_sub_handles).
    st_sub_handles: ALL sub-field handles when is_st=True (for P1.7a dup detection).
    """
    lf_fields = []
    st_sub_handles = []
    ctx = 'supertable' if is_st else 'matrix'

    block_types = data.get('blockTypes', {}) or {}
    if not isinstance(block_types, dict):
        return lf_fields, st_sub_handles

    for bt_uid, bt_data in block_types.items():
        if not isinstance(bt_data, dict):
            continue
        bt_name = bt_data.get('name', '') or bt_uid
        fields_in_bt = bt_data.get('fields', {}) or {}
        if not isinstance(fields_in_bt, dict):
            continue

        for f_uid, f_data in fields_in_bt.items():
            if not isinstance(f_data, dict):
                continue
            f_handle = f_data.get('handle', '') or ''
            f_type = f_data.get('type', '') or ''

            if is_st and f_handle:
                st_sub_handles.append({
                    'handle': f_handle,
                    'name': f_data.get('name', '') or '',
                    'type': f_type,
                    'filepath': filepath,
                    'parent_st_handle': parent_handle,
                    'block_type_name': bt_name,
                })

            if f_type == LF_TYPE:
                lf_fields.append(_lf_record(
                    f_handle, f_data.get('name', '') or '',
                    _get_settings(f_data), filepath, ctx,
                    parent_handle, bt_name,
                ))

    return lf_fields, st_sub_handles


def collect_all_fields(config_dir):
    """
    Walk all project config YAML files.
    Returns (lf_records, st_sub_handles):
      lf_records: every linkfield definition found (all contexts)
      st_sub_handles: every ST sub-field handle (for P1.7a dup detection)
    """
    lf_records = []
    st_sub_handles = []

    for filepath, data in iter_config_yamls(config_dir):
        field_type = data.get('type', '') or ''
        parent_handle = data.get('handle', '?') or '?'

        if field_type == LF_TYPE:
            lf_records.append(_lf_record(
                data.get('handle', ''), data.get('name', ''),
                _get_settings(data), filepath, 'top-level',
            ))
        elif field_type in (ST_TYPE, MT_TYPE):
            sub_lf, sub_st = _walk_block_types(
                data, filepath, is_st=(field_type == ST_TYPE), parent_handle=parent_handle
            )
            lf_records.extend(sub_lf)
            st_sub_handles.extend(sub_st)

    return lf_records, st_sub_handles


# ── P1.7 – Linkfield inventory ────────────────────────────────────────────────

def run_p17(lf_records):
    section(r'P1.7 LINKFIELD FIELDS (lenz\linkfield\fields\LinkField)')
    if not lf_records:
        none_found()
        return

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
        info(f"  file: {rec['filepath']}")


# ── P1.7a – Super Table duplicate handles ─────────────────────────────────────

def run_p17a(st_sub_handles):
    section('P1.7a SUPER TABLE DUPLICATE FIELD HANDLES')
    if not st_sub_handles:
        info('verbb/super-table not found in project config — skipping')
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


def _grep_templates(templates_dir, pattern, fixed=True):
    results = []
    for root, _, files in os.walk(str(templates_dir)):
        for fname in sorted(files):
            if not (fname.endswith('.twig') or fname.endswith('.html')):
                continue
            fpath = os.path.join(root, fname)
            try:
                for lineno, line in enumerate(
                    open(fpath, encoding='utf-8', errors='replace'), 1
                ):
                    hit = (pattern in line) if fixed else bool(re.search(pattern, line))
                    if hit:
                        results.append((fpath, lineno, line.rstrip()))
            except (OSError, IOError):
                pass
    return results


def run_p18(templates_dir):
    section('P1.8 TEMPLATE DEPRECATED API CALLS')
    if not templates_dir.is_dir():
        warn(f'{templates_dir} not found — skipping')
        return set(), set()

    deprecated_files = set()
    any_found = False
    for pattern in DEPRECATED_PATTERNS:
        hits = _grep_templates(templates_dir, pattern)
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
    hits = _grep_templates(templates_dir, '.with([')
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

def run_p18b(templates_dir, lf_records, deprecated_files, with_files):
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

    for root, _, files in os.walk(str(templates_dir)):
        for fname in sorted(files):
            if not (fname.endswith('.twig') or fname.endswith('.html')):
                continue
            fpath = os.path.join(root, fname)
            try:
                text = open(fpath, encoding='utf-8', errors='replace').read()
                for m in pat.finditer(text):
                    handle_ref_files[fpath].add(m.group(1))
                # Cross-file: if this file binds a handle into an include's
                # argument dict, the included target also needs L3 patching.
                for im in include_pat.finditer(text):
                    target, arg_dict = im.group(1), im.group(2)
                    handles_in_args = {hm.group(1) for hm in pat.finditer(arg_dict)}
                    if handles_in_args:
                        add_include_target(root, target, handles_in_args)
            except (OSError, IOError):
                pass

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


# ── P1.10b – Bootstrap / entrypoint customisations ───────────────────────────

def run_p1_bootstrap(project_root):
    section('P1.10b BOOTSTRAP / ENTRYPOINT CUSTOMISATIONS')
    files_to_check = [
        project_root / 'bootstrap.php',
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
        info('No non-standard customisations detected in bootstrap.php / web/index.php.')
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
    if not vendor_dir.is_dir():
        warn(f'{vendor_dir} not found — skipping')
        return []

    info('Scanning vendor plugins for afterSave* event registrations...')
    info('(May take a moment on large vendor directories.)')

    results = {}

    try:
        vendor_names = sorted(os.listdir(str(vendor_dir)))
    except OSError:
        warn('Could not read vendor/ directory.')
        return []

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

            for dirpath, dirnames, filenames in os.walk(search_root):
                dirnames[:] = [d for d in dirnames if d not in ('vendor', 'node_modules')]
                for fname in filenames:
                    if not fname.endswith('.php'):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    try:
                        content = open(fpath, encoding='utf-8', errors='replace').read()
                        for pat in _AFTERSAVE_PATTERNS:
                            if pat in content:
                                if pkg_key not in results:
                                    results[pkg_key] = []
                                if pat not in results[pkg_key]:
                                    results[pkg_key].append(pat)
                    except (OSError, IOError):
                        pass

    print()
    if not results:
        info('No plugins with afterSave* event hooks detected.')
        info('(If a deploy-side plugin is not listed, disable it manually before U1.2.)')
        return []

    composer_map = _build_composer_map(vendor_dir)
    resolved = []  # list of dicts: pkg, host_pkg, handle, patterns
    for pkg, patterns in sorted(results.items()):
        host_pkg, handle = _resolve_plugin_handle(pkg, composer_map)
        resolved.append({
            'pkg': pkg,
            'host_pkg': host_pkg,
            'handle': handle,
            'patterns': patterns,
        })

    warn('These plugins should be disabled before U1.2 (fix-field-layout-uids triggers')
    warn('many element saves; deploy-side hooks with env-specific paths will fail).')
    warn('Add them to PLUGINS_TO_DISABLE_FOR_UPGRADE in the state file.')
    warn('Re-enable on production after deployment (add to DEPLOY.md).')
    print()
    for entry in resolved:
        pkg, host_pkg, handle, patterns = (
            entry['pkg'], entry['host_pkg'], entry['handle'], entry['patterns']
        )
        if host_pkg and host_pkg != pkg:
            found(f'{pkg}  (host plugin: {host_pkg}, handle: {handle or "?"})')
        elif handle:
            found(f'{pkg}  (handle: {handle})')
        else:
            found(f'{pkg}  (no Craft plugin handle resolved — disable manually)')
        for pat in patterns:
            info(f'    ↳ {pat}')

    return resolved


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
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    config_dir = project_root / 'config' / 'project'
    templates_dir = project_root / 'templates'

    if _YAML_BACKEND == 'fallback':
        print('[INFO] PyYAML not available — using built-in YAML parser.')
        print('[INFO] For broader YAML compatibility: pip install pyyaml')

    # Collect field data from project config
    if config_dir.is_dir():
        lf_records, st_sub_handles = collect_all_fields(config_dir)
    else:
        lf_records, st_sub_handles = [], []
        print(f'\n[WARN] {config_dir} not found — P1.7/P1.7a/P1.7b sections skipped.')

    # ── Run all sections ──────────────────────────────────────────────────────
    run_p17(lf_records)
    run_p17a(st_sub_handles)
    run_p17b(lf_records)
    deprecated_files, with_files = run_p18(templates_dir)
    all_template_files = run_p18b(templates_dir, lf_records, deprecated_files, with_files)
    run_p1_bootstrap(project_root)
    plugins_to_disable = run_p112(project_root)
    has_post_update_hook = run_p113(project_root)

    # ── State file summary ────────────────────────────────────────────────────
    print(f'\n{SEP}\n  STATE FILE SUMMARY — copy into .craft5-upgrade.md (Block P3)\n{SEP}')

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
    print('PLUGINS_TO_DISABLE_FOR_UPGRADE:')
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
    print(f'COMPOSER_POST_UPDATE_HOOK: {"yes" if has_post_update_hook else "no"}')
    print()
    print(SEP)
    print('  Audit complete.')
    print(SEP)


if __name__ == '__main__':
    main()
