#!/usr/bin/env python3
"""
Craft 4 to 5 template patcher — Block 5
Applies standard Typed Link Field → native Link field API substitutions
and project-specific handle renames to a list of template files.

Usage:
  python3 path/to/skill/scripts/patch-templates.py \\
    --handles '{"primaryLink":"primaryLink_v2","navLink":"navLink_v2"}' \\
    --files templates/_components/buttons/single.twig templates/_partials/ctas.twig

  # Or load handles from a JSON file:
  python3 path/to/skill/scripts/patch-templates.py \\
    --handles-file handles.json \\
    --files templates/_components/buttons/single.twig

  # Dry run (print diffs, no writes):
  python3 patch-templates.py --handles '{}' --files file.twig --dry-run

Options:
  --handles JSON     JSON object mapping old handle → new handle
  --handles-file     Path to a JSON file with the same mapping
  --files            One or more template file paths to patch
  --dry-run          Print diffs without writing files

Notes:
- Handle renames use a negative lookahead to avoid double-suffixing.
- .with() removal only removes entries for handles listed in --handles.
- Templates with multiple loops needing different per-loop handles must
  be patched manually after running this script (see template-migration.md).
"""

import argparse
import json
import re
import sys
import difflib
import os

# ─────────────────────────────────────────────
# Hardcoded API substitutions (same on every project)
# ─────────────────────────────────────────────
API_SUBSTITUTIONS = [
    ('.getUrl()',        '.url'),
    ('.getCustomText()', '.label'),
    ('.getTarget()',     '.target'),
    ('.getType',        '.type'),
    ('.getElement()',    '.element'),
]


def apply_api_substitutions(content):
    for old, new in API_SUBSTITUTIONS:
        content = content.replace(old, new)
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


def patch_file(path, handles, dry_run=False):
    try:
        original = open(path).read()
    except FileNotFoundError:
        print(f'  [ERROR] File not found: {path}')
        return False

    content = original
    content = apply_api_substitutions(content)
    content = apply_handle_renames(content, handles)
    content = remove_with_calls(content, handles)

    if content == original:
        print(f'  [unchanged] {path}')
        return True

    # Show diff
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
        open(path, 'w').write(content)

    return True


def main():
    parser = argparse.ArgumentParser(description='Patch Craft 4 templates for Craft 5 link field migration.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--handles',      help='JSON object: {"oldHandle":"newHandle",...}')
    group.add_argument('--handles-file', help='Path to JSON file with handle mapping')
    parser.add_argument('--files',    nargs='+', required=True, help='Template files to patch')
    parser.add_argument('--dry-run',  action='store_true', help='Print diffs without writing')
    args = parser.parse_args()

    if args.handles:
        try:
            handles = json.loads(args.handles)
        except json.JSONDecodeError as e:
            print(f'[ERROR] Invalid JSON in --handles: {e}')
            sys.exit(1)
    else:
        try:
            handles = json.load(open(args.handles_file))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f'[ERROR] Could not load handles file: {e}')
            sys.exit(1)

    if args.dry_run:
        print('[DRY RUN — no files will be written]\n')

    print(f'Handles: {json.dumps(handles)}')
    print(f'Files:   {len(args.files)}')
    print()

    for path in args.files:
        patch_file(path, handles, dry_run=args.dry_run)

    print()
    if args.dry_run:
        print('[DRY RUN complete — no files written]')
    else:
        print('Done.')
    print()
    print('NOTE: Templates with multiple loops needing different per-loop handles')
    print('must be patched manually. See references/template-migration.md.')


if __name__ == '__main__':
    main()
