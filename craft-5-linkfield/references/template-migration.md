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
| `field.getLinkAttributes()` | macro (see below) |
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
preflight), resolve them by field `name` before patching templates:

```bash
<MYSQL_CMD> <DB_NAME> -e "SELECT handle, name FROM craft_fields WHERE handle LIKE '%_v2' ORDER BY handle;"
```

A field's `name` (e.g. "Utility Navigation - Link") identifies its template
context. Use that context to determine which `_v2` handle belongs to which
template loop. Assign handles incorrectly and the loop silently outputs empty
strings with no error.

---

## `getLinkAttributes()` replacement macro

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

## Template editing approach

**Use the patcher script first** (`scripts/patch-templates.py`).
It handles API substitutions, handle renames, and `.with()` removal automatically.

Apply the following manually after the script (the patcher cannot handle these):
- Null guards on all link field accesses
- `field|length` → `field.url|length` checks
- `craft.matrixBlocks()` → `craft.entries()` replacements
- Super Table `.one()` patterns

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
