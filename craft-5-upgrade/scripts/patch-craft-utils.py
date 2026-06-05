#!/usr/bin/env python3
"""
Idempotent patcher for sebastianlenz/craft-utils ForeignFieldQueryListener.

Fixes the PHP fatal that occurs when a project uses both linkfield (craft-utils)
and a non-stringable Formie field (Heading, Html, Section, Summary) and runs
`php craft up`.  ForeignFieldQueryListener.onBeforeQueryPrepare() calls
array_unique(SORT_STRING) over ALL custom field objects in an element type's
field layouts before filtering to ForeignField — Formie cosmetic types have no
__toString(), so PHP throws:
    "Object of class ... could not be converted to string"

The patch: filter to ForeignField first, then dedup by handle (O(n), matches
downstream usage) — never stringifying arbitrary field objects.

Usage (run from the target project root):
    python3 ~/.claude/skills/craft-5-upgrade/scripts/patch-craft-utils.py
    python3 ~/.claude/skills/craft-5-upgrade/scripts/patch-craft-utils.py --dry-run
    python3 ~/.claude/skills/craft-5-upgrade/scripts/patch-craft-utils.py --check

This is a TEMPORARY vendor-file edit.  The patch disappears automatically when
sebastianlenz/linkfield (and craft-utils) is removed in craft-5-linkfield L4.1.
If `composer install` or `composer update` reinstalls craft-utils before then,
re-run this script.

See references/craft-utils-formie-heading.md for root cause, rationale, and
the orphaned-table recovery procedure.
"""

import argparse
import difflib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TARGET_RELPATH = (
    'vendor/sebastianlenz/craft-utils/src/foreignField'
    '/ForeignFieldQueryListener.php'
)

# Sentinel that marks the file as already patched — never changed, so it is
# both the idempotency guard and a human-readable annotation.
SENTINEL = 'Patched (Craft 5 upgrade): dedup ForeignFields by handle'

# The dedup loop to inject immediately after the $fields = array_filter(...)
# statement (after the closing semicolon of that statement).
DEDUP_BLOCK = '''\
        // Patched (Craft 5 upgrade): dedup ForeignFields by handle instead of
        // array_unique() over all field objects, which fatals on non-stringable
        // fields (e.g. Formie Heading). Temporary — reverts when craft-utils is
        // removed with linkfield in craft-5-linkfield L4.
        $unique = [];
        foreach ($fields as $field) {
            $unique[$field->handle] = $field;
        }
        $fields = $unique;
'''


def _balanced_paren_end(text, open_pos):
    """Return the index of the ')' that closes the '(' at open_pos."""
    depth = 0
    for i in range(open_pos, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i
    return -1


def _apply_patch(original):
    """Return (patched_text, changed: bool) or raise ValueError on structure mismatch."""

    # Already patched?
    if SENTINEL in original:
        return original, False

    # Locate the array_unique( that wraps array_reduce inside the
    # $fields = array_filter( ... ) assignment.
    # We look for the specific pattern:
    #   array_unique(array_reduce(
    # which is the fingerprint of the buggy line.
    au_re = re.search(r'array_unique\(', original)
    if not au_re:
        raise ValueError(
            'Expected array_unique() call not found in ForeignFieldQueryListener.php.\n'
            'craft-utils source structure has changed — re-derive the patch from\n'
            'references/craft-utils-formie-heading.md before proceeding.'
        )

    # Confirm the inner call is array_reduce( immediately after array_unique(
    inner_start = au_re.end()
    if not original[inner_start:].lstrip().startswith('array_reduce('):
        raise ValueError(
            'array_unique() found but it does not wrap array_reduce() as expected.\n'
            'craft-utils source structure has changed — re-derive the patch from\n'
            'references/craft-utils-formie-heading.md before proceeding.'
        )

    # Find the extent of the array_unique( ... ) wrapper:
    #   au_open  = position of the '(' in array_unique(
    #   au_close = position of the matching ')'
    au_open = au_re.end() - 1  # the '(' character
    au_close = _balanced_paren_end(original, au_open)
    if au_close < 0:
        raise ValueError(
            'Could not find the closing ) for array_unique() — unbalanced parens?\n'
            'craft-utils source structure has changed — re-derive the patch from\n'
            'references/craft-utils-formie-heading.md before proceeding.'
        )

    # The inner content is everything between the outer ( and its matching )
    inner_content = original[au_open + 1:au_close]

    # Remove the array_unique() wrapper: replace array_unique(<inner>) with <inner>
    patched = original[:au_re.start()] + inner_content + original[au_close + 1:]

    # Now locate the $fields assignment statement end (semicolon after the
    # array_filter(...) that now directly wraps array_reduce(...)).
    # Find the $fields = ... ; statement that contains our just-spliced content.
    # We search for the first ';' that follows the splice point in the patched text.
    splice_pos = original.index('array_unique(')  # position in original → same offset works
    # In patched text the splice happened at the same offset (au_re.start()).
    # Find the ';' that ends the $fields = array_filter(...) statement.
    stmt_end = patched.find(';', au_re.start())
    if stmt_end < 0:
        raise ValueError(
            'Could not locate the semicolon ending the $fields statement after patching.\n'
            'craft-utils source structure has changed — re-derive the patch from\n'
            'references/craft-utils-formie-heading.md before proceeding.'
        )

    # Inject the dedup block after that semicolon (keep the newline already there).
    insert_at = stmt_end + 1
    patched = patched[:insert_at] + '\n' + DEDUP_BLOCK + patched[insert_at:]

    return patched, True


def main():
    parser = argparse.ArgumentParser(
        description='Patch craft-utils ForeignFieldQueryListener to avoid array_unique fatal.'
    )
    parser.add_argument(
        'project_root', nargs='?', default='.',
        help='Path to the Craft project root (default: current directory)'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Show what would change without writing the file.'
    )
    parser.add_argument(
        '--check', action='store_true',
        help='Exit 0 if already patched, 1 if not. No output on success.'
    )
    args = parser.parse_args()

    target = Path(args.project_root).resolve() / TARGET_RELPATH

    if not target.exists():
        if args.check:
            # Not installed = patch not needed — treat as patched for gate purposes.
            sys.exit(0)
        print('craft-utils not installed — nothing to patch.')
        sys.exit(0)

    original = target.read_text(encoding='utf-8')

    if args.check:
        if SENTINEL in original:
            sys.exit(0)
        else:
            print(f'NOT PATCHED: {target}')
            sys.exit(1)

    try:
        patched, changed = _apply_patch(original)
    except ValueError as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        sys.exit(1)

    if not changed:
        print(f'Already patched — sentinel found in {target}')
        sys.exit(0)

    if args.dry_run:
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile=f'a/{TARGET_RELPATH}',
            tofile=f'b/{TARGET_RELPATH}',
        )
        print(''.join(diff), end='')
        sys.exit(0)

    # Write via temp file so the original is intact if php -l fails.
    with tempfile.NamedTemporaryFile(
        mode='w', encoding='utf-8',
        dir=target.parent, suffix='.tmp', delete=False
    ) as tmp:
        tmp.write(patched)
        tmp_path = Path(tmp.name)

    # Lint check before replacing the original.
    lint = subprocess.run(
        ['php', '-l', str(tmp_path)],
        capture_output=True, text=True
    )
    if lint.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        print('[ERROR] php -l failed on the patched file — original not modified.',
              file=sys.stderr)
        print(lint.stdout, file=sys.stderr)
        print(lint.stderr, file=sys.stderr)
        sys.exit(1)

    # Atomic replace.
    shutil.move(str(tmp_path), str(target))
    print(f'Patched: {target}')
    print('  array_unique() wrapper removed; handle-dedup loop injected.')
    print(f'  Lint: {lint.stdout.strip()}')


if __name__ == '__main__':
    main()
