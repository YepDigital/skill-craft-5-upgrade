#!/usr/bin/env bash
# Craft 4 to 5 upgrade audit script
# Run from the project root: bash path/to/skill/scripts/audit.sh
# Covers SKILL.md steps 1.7, 1.7a, and 1.8
# If grep is unavailable or the script fails, perform each section manually per SKILL.md.

set -euo pipefail

PROJECT_ROOT="${1:-.}"
CONFIG_DIR="$PROJECT_ROOT/config/project"
TEMPLATES_DIR="$PROJECT_ROOT/templates"

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
section() { echo; echo "════════════════════════════════════════"; echo "  $1"; echo "════════════════════════════════════════"; }
found()   { echo "  [FOUND] $*"; }
none()    { echo "  (none)"; }

# ─────────────────────────────────────────────
# 1.7 Linkfield field inventory
# ─────────────────────────────────────────────
section "1.7 LINKFIELD FIELDS (lenz\\linkfield\\fields\\LinkField)"

if [ ! -d "$CONFIG_DIR" ]; then
  echo "  [WARN] $CONFIG_DIR not found — skipping"
else
  LINKFIELD_FILES=$(grep -rl 'lenz\\linkfield\\fields\\LinkField' "$CONFIG_DIR" 2>/dev/null || true)
  if [ -z "$LINKFIELD_FILES" ]; then
    none
  else
    for f in $LINKFIELD_FILES; do
      echo
      echo "  File: $f"
      # handle
      handle=$(grep -m1 'handle:' "$f" | awk '{print $2}' || true)
      name=$(grep -m1 '^name:' "$f" | sed 's/^name: *//' || true)
      echo "    handle: $handle"
      echo "    name:   $name"
      # enabled link types
      echo "    enabledLinkTypes:"
      grep 'enabledLinkTypes\|linkType' "$f" | sed 's/^/      /' || true
      # columnSuffix
      suffix=$(grep 'columnSuffix' "$f" | awk '{print $2}' || true)
      [ -n "$suffix" ] && echo "    columnSuffix: $suffix" || echo "    columnSuffix: (none)"
    done
  fi
fi

# ─────────────────────────────────────────────
# 1.7a Super Table duplicate field handles
# ─────────────────────────────────────────────
section "1.7a SUPER TABLE DUPLICATE FIELD HANDLES"

if [ ! -d "$CONFIG_DIR" ]; then
  echo "  [WARN] $CONFIG_DIR not found — skipping"
else
  ST_FILES=$(grep -rl 'verbb\\supertable\\fields\\SuperTableField' "$CONFIG_DIR" 2>/dev/null || true)
  if [ -z "$ST_FILES" ]; then
    echo "  verbb/super-table not found in project config — skipping"
  else
    # Collect all block-type field handles and detect duplicates
    echo "  Scanning Super Table block type field handles..."
    TMPFILE=$(mktemp)
    for f in $ST_FILES; do
      # Extract field handles from block type definitions (indented handle: lines)
      grep -n '^\s\+handle:' "$f" | awk -v file="$f" '{print $2 "\t" file}' >> "$TMPFILE" || true
    done
    # Find handles appearing more than once
    DUPES=$(awk '{print $1}' "$TMPFILE" | sort | uniq -d || true)
    if [ -z "$DUPES" ]; then
      echo "  No duplicate handles found."
    else
      echo
      for dupe in $DUPES; do
        found "Duplicate handle: '$dupe'"
        grep -P "^$dupe\t" "$TMPFILE" | while IFS=$'\t' read -r h file; do
          echo "    → $file"
        done
      done
      echo
      echo "  [WARN] Duplicate handles will be deduplicated after upgrade (handle, handle2, handle3...)."
      echo "  [WARN] If any duplicate handle also has linkfield data, only one copy will be migrated."
    fi
    rm -f "$TMPFILE"
  fi
fi

# ─────────────────────────────────────────────
# 1.8 Template deprecated API usage
# ─────────────────────────────────────────────
section "1.8 TEMPLATE DEPRECATED API CALLS"

if [ ! -d "$TEMPLATES_DIR" ]; then
  echo "  [WARN] $TEMPLATES_DIR not found — skipping"
else
  PATTERNS=(
    ".getUrl("
    ".getCustomText("
    ".getTarget("
    ".getType"
    ".getElement("
    ".getLinkAttributes("
    "craft.matrixBlocks("
  )

  any_found=0
  for pattern in "${PATTERNS[@]}"; do
    results=$(grep -rn --include="*.twig" --include="*.html" -F "$pattern" "$TEMPLATES_DIR" 2>/dev/null || true)
    if [ -n "$results" ]; then
      any_found=1
      echo
      echo "  Pattern: $pattern"
      echo "$results" | sed 's/^/    /'
    fi
  done
  [ $any_found -eq 0 ] && none
fi

# ─────────────────────────────────────────────
# 1.8 Template .with() calls (check for linkfield handles)
# ─────────────────────────────────────────────
section "1.8 TEMPLATE .with() CALLS (check for linkfield handles)"

if [ ! -d "$TEMPLATES_DIR" ]; then
  echo "  [WARN] $TEMPLATES_DIR not found — skipping"
else
  results=$(grep -rn --include="*.twig" --include="*.html" -F ".with([" "$TEMPLATES_DIR" 2>/dev/null || true)
  if [ -n "$results" ]; then
    echo "  Cross-reference these against the linkfield handles from step 1.7."
    echo "  Any .with() call that includes a linkfield handle must be removed after migration."
    echo
    echo "$results" | sed 's/^/  /'
  else
    none
  fi
fi

echo
echo "════════════════════════════════════════"
echo "  Audit complete."
echo "════════════════════════════════════════"
echo
