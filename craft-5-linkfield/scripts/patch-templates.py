#!/usr/bin/env python3
"""
Craft 4 to 5 template patcher — Block L3
Applies standard Typed Link Field → native Link field API substitutions
and project-specific handle renames to a list of template files.

Modes:
  (default)    Patch files in place.
  --dry-run    Print diffs without writing files.
  --verify     Exit non-zero if any old handle reference remains after patching.
  --lint-only  Flag Twig 2→3 syntax patterns that break under Twig 3 (no writes).

Usage:
  python3 patch-templates.py \\
    --handles '{"primaryLink":"primaryLink_v2","navLink":"navLink_v2"}' \\
    --files templates/_components/buttons.twig templates/_partials/nav.twig

  # Dry run:
  python3 patch-templates.py --handles '{}' --files file.twig --dry-run

  # Null-guard transforms (opt-in):
  python3 patch-templates.py --handles '{"myLink":"myLink_v2"}' \\
    --files templates/*.twig --null-guards --dry-run

  # Twig 3 syntax lint (no writes):
  python3 patch-templates.py --handles '{"myLink":"myLink_v2"}' \\
    --files templates/*.twig --lint-only

  # Verify clean after patching:
  python3 patch-templates.py --handles '{"myLink":"myLink_v2"}' \\
    --files templates/*.twig --verify

Options:
  --handles JSON        JSON object mapping old handle → new handle
  --handles-file PATH   Path to a JSON file with the same mapping
  --files PATH...       Template files to process
  --dry-run             Print diffs without writing
  --null-guards         Also apply null-guard transforms (opt-in)
  --lint-only           Flag Twig 2→3 breaking patterns only (no other changes)
  --verify              After patching, exit 1 if any old handle reference remains
  --linkattributes-mode {inline,macro}
                        How to replace .getLinkAttributes() (default: inline)
"""

import argparse
import json
import os
import re
import sys
import difflib


# ─────────────────────────────────────────────
# Hardcoded API substitutions (same on every project)
# ─────────────────────────────────────────────

API_SUBSTITUTIONS = [
    ('.getUrl()',        '.url'),
    ('.getCustomText()', '.label'),
    ('.getTarget()',     '.target'),
    ('.getType',        '.type'),
    ('.getElement()',    '.element'),
    # getLinkAttributes() is handled separately (see apply_linkattributes)
]

# Inline replacement for .getLinkAttributes() — avoids requiring a macro file.
# Replaces `<expr>.getLinkAttributes()` with the href + target attributes.
_LINKATTR_INLINE_PATTERN = re.compile(
    r'([\w.\[\]\'\"]+)\.getLinkAttributes\(\)'
)


def apply_api_substitutions(content):
    for old, new in API_SUBSTITUTIONS:
        content = content.replace(old, new)
    return content


def apply_linkattributes(content, mode='inline'):
    """Replace .getLinkAttributes() calls."""
    if mode == 'inline':
        def _replace(m):
            expr = m.group(1)
            return (
                f'href="{{{{ {expr}.url }}}}"'
                f'{{% if {expr}.target %}} target="{{{{ {expr}.target }}}}"'
                f' rel="noopener noreferrer"{{% endif %}}'
            )
        return _LINKATTR_INLINE_PATTERN.sub(_replace, content)
    elif mode == 'macro':
        def _replace_macro(m):
            expr = m.group(1)
            return f'{{{{ linkField.attributes({expr}) }}}}'
        content = _LINKATTR_INLINE_PATTERN.sub(_replace_macro, content)
        if 'getLinkAttributes' not in content and 'linkField.attributes(' in content:
            print('  [NOTE] Add {% import "_macros/linkField.twig" as linkField %} where needed.')
        return content
    return content


def apply_handle_renames(content, handles):
    """
    Rename field handle accesses (e.g. entry.primaryLink → entry.primaryLink_v2).
    Requires a preceding dot so local Twig variable names are not renamed.
    Negative lookahead avoids double-suffixing already-renamed handles.
    """
    for old, new in handles.items():
        suffix = new[len(old):]  # e.g. "_v2"
        pattern = r'\.' + re.escape(old) + r'(?!' + re.escape(suffix) + r')(?!\w)'
        content = re.sub(pattern, '.' + new, content)
    return content


def remove_with_calls(content, handles):
    """
    Remove .with(["handle"]) entries for linkfield handles.
    Handles single-handle and multi-handle .with() arrays.
    Only removes entries for handles in the provided mapping.
    """
    for old in handles:
        # Remove entire .with(["handle"]) if it's the only entry
        content = re.sub(
            r'\.with\(\s*\[\s*["\']' + re.escape(old) + r'["\']\s*\]\s*\)',
            '',
            content
        )
        # Remove "handle", or ,"handle" from multi-entry .with([...]) arrays
        content = re.sub(
            r',\s*["\']' + re.escape(old) + r'["\']',
            '',
            content
        )
        content = re.sub(
            r'["\']' + re.escape(old) + r'["\'],\s*',
            '',
            content
        )
    return content


# ─────────────────────────────────────────────
# Null-guard transforms (--null-guards, opt-in)
# ─────────────────────────────────────────────

def apply_null_guards(content, handles):
    """
    Apply four documented null-guard patterns for migrated linkfield handles.
    Runs after handle renames, so targets the _v2 forms.
    These are opt-in (--null-guards) to keep default diffs minimal.
    """
    for old, new in handles.items():
        # Pattern 1: `if X.type == "..."` → `if X and X.type == "..."`
        # Matches `if <new>.type` not already preceded by `and <new>`
        content = re.sub(
            r'\bif\s+(' + re.escape(new) + r')\.type\b(?!\s)',
            lambda m: f'if {m.group(1)} and {m.group(1)}.type',
            content
        )
        content = re.sub(
            r'\bif\s+(' + re.escape(new) + r')\.type\s*==',
            lambda m: f'if {m.group(1)} and {m.group(1)}.type ==',
            content
        )

        # Pattern 2: `href="{{ X.url }}"` inside elseif → `href="{{ X ? X.url : '' }}"`
        content = re.sub(
            r'href="\{\{\s*(' + re.escape(new) + r')\.url\s*\}\}"',
            lambda m: f'href="{{{{ {m.group(1)} ? {m.group(1)}.url : \'#\' }}}}"',
            content
        )

        # Pattern 3: `?? X.element.title ?? null` → `?? (X.element ? X.element.title : null)`
        content = re.sub(
            r'\?\?\s*(' + re.escape(new) + r')\.element\.(\w+)\s*\?\?\s*null',
            lambda m: f'?? ({m.group(1)}.element ? {m.group(1)}.element.{m.group(2)} : null)',
            content
        )

        # Pattern 4: `entry.slug == X.element.slug` → `X.element and (entry.slug == X.element.slug)`
        content = re.sub(
            r'(\w+\.\w+)\s*==\s*(' + re.escape(new) + r')\.element\.(\w+)',
            lambda m: f'{m.group(2)}.element and ({m.group(1)} == {m.group(2)}.element.{m.group(3)}',
            content
        )

    return content


# ─────────────────────────────────────────────
# Twig 3 strict-mode lint (--lint-only)
# ─────────────────────────────────────────────

# Patterns that parse fine in Twig 2 but throw SyntaxError in Twig 3.
# These involve parenthesised expressions on the left side of ??.
_TWIG3_BREAKING = [
    (re.compile(r'\)\s*\?\?\s*null\b'),    '`...) ?? null` — parenthesised LHS of ?? rejected by Twig 3'),
    (re.compile(r'\)\s*\?\?\s*\('),        '`...) ?? (...)` — parenthesised LHS of ?? rejected by Twig 3'),
]


def lint_twig3(path, content):
    """Print lines matching Twig 3 breaking patterns. Returns count of issues found."""
    issues = 0
    for lineno, line in enumerate(content.splitlines(), 1):
        for rx, desc in _TWIG3_BREAKING:
            if rx.search(line):
                print(f'  [TWIG3] {path}:{lineno}: {desc}')
                print(f'          {line.rstrip()}')
                issues += 1
                break
    return issues


# ─────────────────────────────────────────────
# Verify mode: check no old handle remains
# ─────────────────────────────────────────────

def verify_no_old_handles(path, content, handles):
    """Return list of (lineno, handle, line) for any old handle still present."""
    remaining = []
    for old in handles:
        suffix = handles[old][len(old):]  # e.g. "_v2"
        # Match .oldHandle not followed by the suffix (bare old reference)
        pattern = re.compile(r'\.' + re.escape(old) + r'(?!' + re.escape(suffix) + r')(?!\w)')
        for lineno, line in enumerate(content.splitlines(), 1):
            if pattern.search(line):
                remaining.append((lineno, old, line.rstrip()))
    return remaining


# ─────────────────────────────────────────────
# File patching
# ─────────────────────────────────────────────

def patch_file(path, handles, dry_run=False, null_guards=False,
               lint_only=False, verify=False, linkattributes_mode='inline'):
    try:
        original = open(path, encoding='utf-8').read()
    except FileNotFoundError:
        print(f'  [ERROR] File not found: {path}')
        return False, 0

    lint_issues = 0

    if lint_only:
        lint_issues = lint_twig3(path, original)
        if lint_issues == 0:
            print(f'  [clean] {path}')
        return True, lint_issues

    content = original
    content = apply_api_substitutions(content)
    content = apply_linkattributes(content, mode=linkattributes_mode)
    content = apply_handle_renames(content, handles)
    content = remove_with_calls(content, handles)
    if null_guards and handles:
        content = apply_null_guards(content, handles)

    if verify and handles:
        remaining = verify_no_old_handles(path, content, handles)
        if remaining:
            for lineno, handle, line in remaining:
                print(f'  [REMAINING] {path}:{lineno}: .{handle} still present')
                print(f'              {line}')
            return False, 0

    if content == original:
        print(f'  [unchanged] {path}')
        return True, 0

    diff = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        content.splitlines(keepends=True),
        fromfile=f'a/{os.path.basename(path)}',
        tofile=f'b/{os.path.basename(path)}',
        n=2
    ))
    print(f'\n  [patched] {path}')
    for line in diff:
        sys.stdout.write('    ' + line)

    if not dry_run:
        open(path, 'w', encoding='utf-8').write(content)

    return True, 0


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Patch Craft 4 templates for Craft 5 link field migration.'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--handles',      help='JSON object: {"oldHandle":"newHandle",...}')
    group.add_argument('--handles-file', help='Path to JSON file with handle mapping')
    parser.add_argument('--files',    nargs='+', required=True, help='Template files to process')
    parser.add_argument('--dry-run',  action='store_true', help='Print diffs without writing')
    parser.add_argument('--null-guards', action='store_true', help='Also apply null-guard transforms (opt-in)')
    parser.add_argument('--lint-only',   action='store_true', help='Flag Twig 2→3 breaking patterns (no writes)')
    parser.add_argument('--verify',      action='store_true', help='Exit 1 if any old handle reference remains')
    parser.add_argument(
        '--linkattributes-mode',
        choices=['inline', 'macro'], default='inline',
        help='How to replace .getLinkAttributes(): inline (default) or macro'
    )
    args = parser.parse_args()

    if args.handles:
        try:
            handles = json.loads(args.handles)
        except json.JSONDecodeError as e:
            print(f'[ERROR] Invalid JSON in --handles: {e}')
            sys.exit(1)
    else:
        try:
            handles = json.load(open(args.handles_file, encoding='utf-8'))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f'[ERROR] Could not load handles file: {e}')
            sys.exit(1)

    if args.lint_only:
        print('[LINT-ONLY — checking Twig 2→3 syntax patterns, no files written]\n')
    elif args.verify:
        print('[VERIFY — checking for remaining old handle references]\n')
    elif args.dry_run:
        print('[DRY RUN — no files will be written]\n')

    print(f'Handles: {json.dumps(handles)}')
    print(f'Files:   {len(args.files)}')
    print()

    all_ok = True
    total_lint = 0

    for path in args.files:
        ok, lint_count = patch_file(
            path, handles,
            dry_run=args.dry_run,
            null_guards=args.null_guards,
            lint_only=args.lint_only,
            verify=args.verify,
            linkattributes_mode=args.linkattributes_mode,
        )
        if not ok:
            all_ok = False
        total_lint += lint_count

    print()
    if args.lint_only:
        if total_lint:
            print(f'[LINT] {total_lint} Twig 3 syntax issue(s) found. Fix before upgrading templates.')
            sys.exit(1)
        else:
            print('[LINT] No Twig 2→3 breaking patterns found.')
    elif args.verify:
        if not all_ok:
            print('[VERIFY FAILED] Old handle references remain. Re-run patcher on listed files.')
            sys.exit(1)
        else:
            print('[VERIFY OK] No old handle references found.')
    elif args.dry_run:
        print('[DRY RUN complete — no files written]')
    else:
        print('Done.')

    print()
    if not args.lint_only and not args.verify:
        print('Manual steps still required after this script:')
        print('  - Null guards on all link field accesses (or use --null-guards)')
        print('  - field|length → field.url|length')
        print('  - craft.matrixBlocks() → craft.entries()')
        print('  - Super Table .one() patterns')
        print('  - Twig 2→3 syntax (run --lint-only to find these)')
        print('  See references/template-migration.md for patterns.')


if __name__ == '__main__':
    main()
