# Template Migration Reference

Read this file before starting Block L3 (Template updates).

---

## API changes: Typed Link Field to native Link field

| Old | New |
|---|---|
| `field.getUrl()` | `field.url` |
| `field.getCustomText()` | `field.label` |
| `field.getTarget()` | `field.target` |
| `field.getType()` | `field.type` |
| `field.getElement()` | `field.element` |
| `field.getLinkAttributes()` | inline `href`/`target` (see below) or macro |
| `field\|length` | `field.url\|length` *(manual — not automated by patcher script)* |
| `craft.matrixBlocks()` | `craft.entries()` |

---

## Field handle changes

Every linkfield handle gains a `_v2` suffix:
- `entry.primaryLink` becomes `entry.primaryLink_v2`
- `block.ctaButton` becomes `block.ctaButton_v2`
- `nav.promoButton.linkTo` becomes `nav.promoButton.linkTo_v2`

After `craft-5-preflight` Block P2 remediated duplicate handles on Craft 4,
the mapping should be strictly 1:1 — no ambiguous deduplication suffixes
(no `handle2_v2`, `handle3_v2`). Verify this in Block L2.2 before patching.

If any ambiguous `_v2` handles remain (e.g. from a project that skipped
preflight), resolve them by field `name` before patching templates.

(Adjust the `craft_` prefix to match your `CRAFT_DB_TABLE_PREFIX` — empty
prefix means bare `fields`.)

```bash
<MYSQL_CMD> <DB_NAME> -e "SELECT handle, name FROM craft_fields WHERE handle LIKE '%_v2' ORDER BY handle;"
```

A field's `name` (e.g. "Utility Navigation - Link") identifies its template
context. Use that context to determine which `_v2` handle belongs to which
template loop. Assign handles incorrectly and the loop silently outputs empty
strings with no error.

---

## `getLinkAttributes()` replacement

The patcher replaces `<expr>.getLinkAttributes()` with inline attributes by
default (`--linkattributes-mode inline`, the default):

```twig
{# Before #}
<a {{ entry.myLink_v2.getLinkAttributes() }}>

{# After (inline mode) #}
<a href="{{ entry.myLink_v2.url }}"{% if entry.myLink_v2.target %} target="{{ entry.myLink_v2.target }}" rel="noopener noreferrer"{% endif %}>
```

Use `--linkattributes-mode macro` to emit `{{ linkField.attributes(entry.myLink_v2) }}`
instead. You must then import the macro file wherever it is used.

---

## `getLinkAttributes()` macro (if using `--linkattributes-mode macro`)

If `templates/_macros/linkField.twig` does not already exist, create it:

```twig
{#
  attributes(field) — drop-in replacement for getLinkAttributes()
  Usage: <a {{ linkField.attributes(entry.myLink_v2) }}>
#}
{% macro attributes(field) %}
  {%- if field.url is defined and field.url -%}
    href="{{ field.url }}"
    {%- if field.target %} target="{{ field.target }}" rel="noopener noreferrer"{% endif %}
  {%- endif %}
{% endmacro %}

{#
  tag(field, classes, text) — renders a complete <a> tag
  Usage: {{ linkField.tag(entry.myLink_v2, 'btn', 'Click here') }}
#}
{% macro tag(field, classes, text) %}
  {%- if field.url is defined and field.url -%}
    <a href="{{ field.url }}"
      {%- if classes %} class="{{ classes }}"{% endif %}
      {%- if field.target %} target="{{ field.target }}" rel="noopener noreferrer"{% endif %}>
      {{- text ?? field.label -}}
    </a>
  {%- endif %}
{% endmacro %}
```

---

## Null safety

The Craft 5 native Link field returns `null` when empty, unlike Typed Link
Field which returned an empty value object. Every link field access needs a
null guard.

```twig
{# Correct — null-safe #}
{% if linkField and linkField.url|length %}
    <a href="{{ linkField.url }}">{{ linkField.label }}</a>
{% endif %}

{# Also correct for type checks #}
{% if linkField and linkField.type == "entry" %}

{# Wrong — throws "Impossible to access attribute on null variable" #}
{% if linkField.url|length %}
```

**Common miss — `elseif` fallback branches:**
```twig
{% if item.link_v2 and item.link_v2.type == "entry" %}
    {# ... #}
{% elseif item.someTitle|length %}
    <a href="{{ item.link_v2.url }}">  {# ← throws if link_v2 is null #}
```
The `elseif` fires precisely when `link_v2` is null. Use:
```twig
<a href="{{ item.link_v2 ? item.link_v2.url : '' }}">
```

---

## Do not use `.with()` with native Link field handles

In Craft 5, passing a native `craft\fields\Link` field handle to `.with()` on
an element query causes Craft to eager-load the linked element. The field
accessor then returns an `ElementCollection` instead of a `LinkData` object,
and any `.url`, `.label`, `.target`, or `.type` access throws
`BadMethodCallException: Method craft\elements\ElementCollection::url does not exist`.

```twig
{# Wrong — causes ElementCollection error #}
{% set items = craft.entries().section('nav').with(['myLink_v2']).collect() %}

{# Correct — remove .with() for native Link fields, keep .collect() #}
{% set items = craft.entries().section('nav').collect() %}
{% for item in items %}
  {% if item.myLink_v2 and item.myLink_v2.url %}
    {{ item.myLink_v2.url }}
  {% endif %}
{% endfor %}
```

`LinkData` is stored inline and does not benefit from eager loading.
The patcher script removes `.with()` entries for migrated handles automatically.

---

## Super Table fields in Craft 5: always use `.one()`

In Craft 4, single-row Super Table fields returned a block object directly.
In Craft 5, all Super Table fields return an EntryQuery. Accessing `.subField`
on a query returns null.

Always call `.one()` before accessing sub-fields:
```twig
{# Craft 4 — no longer works #}
{% set link = entry.mySupertable.myField %}

{# Craft 5 — correct #}
{% set row = entry.mySupertable.one() %}
{% set link = row ? row.myField ?? null : null %}
```

---

## URL field auto-promotion

Craft 5's `php craft up` silently promotes `craft\fields\Url` fields to
`craft\fields\Link` (URL-only variant). These are **not** linkfields — they are
plain URL fields whose runtime type changes from `string` to `LinkData`.

The promoted `LinkData` object implements `__toString()`, so `{{ entry.x }}`
and `{{ entry.x.url }}` both output the URL. However, `|length` and `in` tests
operate differently on objects vs strings and may produce unexpected results.

Preflight P1.7c lists candidate fields in `URL_PROMOTION_CANDIDATES`.
After `php craft up`, L2.3 queries the DB to confirm which candidates were
actually promoted and writes them to `## URL fields actually promoted` in the
state file. Use that confirmed list when fixing templates in L3.3.

### Breaking patterns and fixes

| Pattern | Problem | Fix |
|---|---|---|
| `{% if entry.x\|length %}` | `\|length` on object may not behave like `\|length` on string | `{% if entry.x.url\|length %}` |
| `{% if 'foo' in entry.x %}` | `in` membership test on object vs string | `{% if 'foo' in entry.x.url %}` |

Patterns that continue to work unchanged:

| Pattern | Why it works |
|---|---|
| `{{ entry.x }}` | `LinkData.__toString()` returns the URL string |
| `{{ entry.x.url }}` | Explicit; preferred for clarity |

### Example

```twig
{# Before (field was craft\fields\Url) #}
{% if entry.mapLink|length %}
  <a href="{{ entry.mapLink }}">View map</a>
{% endif %}

{# After (field promoted to craft\fields\Link) #}
{% if entry.mapLink.url|length %}
  <a href="{{ entry.mapLink.url }}">View map</a>
{% endif %}
```

These fixes are **not** applied by `patch-templates.py` — apply them manually
using the file/line references in `URL_PROMOTION_CANDIDATES`.

---

## Template editing approach

**Use the patcher script first** (`scripts/patch-templates.py`).
It handles API substitutions, handle renames, `.with()` removal, and
`getLinkAttributes()` replacement automatically.

Run the patcher, then apply the following manually (or use the opts listed):
- `--null-guards` — applies the four null-guard patterns (see Null-guard recipes below)
- `field|length` → `field.url|length` *(manual — not automated)*
- `craft.matrixBlocks()` → `craft.entries()` *(manual)*
- Super Table `.one()` patterns *(manual)*
- Twig 2→3 syntax issues — run `--lint-only` first to find them *(manual fix)*

For any manual edits, use Python string replacement rather than the Edit tool's
`old_str` matching. Tab-indented Twig files can cause `old_str` matching to
fail silently:

```python
import re

path = 'templates/path/to/file.twig'
content = open(path).read()

# Replace all occurrences:
content = content.replace('.getUrl()', '.url')

# Rename handles (negative lookahead avoids double-suffixing):
content = re.sub(r'entry\.primaryLink(?!_v2)', 'entry.primaryLink_v2', content)

open(path, 'w').write(content)
```

---

## Templates with multiple loops requiring different handles

After `craft-5-preflight` Block P2, this case should be rare. If it occurs
(a template has two loops that both used the same original handle, mapped to
different `_v2` handles):

Find a unique structural delimiter between the two loops, then split and patch
each half independently:

```python
path = 'templates/_partials/example.twig'
content = open(path).read()

# Use a unique comment or closing tag between the loops as the split point
delimiter = '{# Second Loop Section #}'
top, bottom = content.split(delimiter, 1)

top    = top.replace('item.linkField.', 'item.utilityNavLink_v2.')
bottom = bottom.replace('item.linkField.', 'item.mainNavLink_v2.')

open(path, 'w').write(top + delimiter + bottom)
```

Confirm the delimiter appears exactly once between the two loops before
splitting.

---

## Null-guard recipes (`--null-guards`)

Pass `--null-guards` to the patcher to apply these four transforms automatically.
They run after handle renames so they target the `_v2` forms.

### 1. Type check without null guard

```twig
{# Before — throws if myLink_v2 is null #}
{% if myLink_v2.type == "entry" %}

{# After #}
{% if myLink_v2 and myLink_v2.type == "entry" %}
```

### 2. `href` in `elseif` branch

```twig
{# Before — the elseif fires precisely when myLink_v2 is null #}
{% elseif someTitle|length %}
  <a href="{{ myLink_v2.url }}">

{# After #}
  <a href="{{ myLink_v2 ? myLink_v2.url : '#' }}">
```

### 3. Chained `??` with element attribute

```twig
{# Before — throws if element is null #}
{{ fallback ?? myLink_v2.element.title ?? null }}

{# After #}
{{ fallback ?? (myLink_v2.element ? myLink_v2.element.title : null) }}
```

### 4. Slug comparison through element

```twig
{# Before — throws if element is null #}
{% if entry.slug == myLink_v2.element.slug %}

{# After #}
{% if myLink_v2.element and (entry.slug == myLink_v2.element.slug) %}
```

---

## Twig 2 → 3 syntax tightening

Several Twig patterns that compiled fine under Craft 4 / Twig 2 throw
`Twig\Error\SyntaxError: The "defined" test only works with simple variables`
under Craft 5 / Twig 3.

Run `--lint-only` before patching to find these in your template files.

### Parenthesised LHS of `??`

```twig
{# Twig 2: valid.  Twig 3: SyntaxError #}
{% set isActive = (entry.slug == link.element.slug) ?? null %}
{{ A ?? (B ? C : null) ?? null }}
```

**Fix:** strip the trailing `?? null` (it's redundant — `??` already falls back
to `null`) or rewrite without parenthesised LHS:

```twig
{# Correct #}
{% set isActive = link.element and (entry.slug == link.element.slug) %}
{{ A ?? (B ? C : null) }}
```

The patcher's `--lint-only` mode greps for `) ?? null` and `) ?? (` patterns
so you can find all instances before patching.

### `null.attribute` access

Twig 3 is stricter about attribute access on null — the error surface is the
same as Twig 2, but null guards were often omitted because the old Typed Link
Field returned an empty object (not `null`) on empty fields. After migration,
every link field access that was previously safe needs a null guard.
Use the Null-guard recipes above or `--null-guards` to apply them in bulk.
