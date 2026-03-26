# Template Migration Reference

Read this file before starting Block 5 (Template updates).

---

## API changes: Typed Link Field to native Link field

| Old | New |
|---|---|
| `field.getUrl()` | `field.url` |
| `field.getCustomText()` | `field.label` |
| `field.getTarget()` | `field.target` |
| `field.getType` | `field.type` |
| `field.getElement()` | `field.element` |
| `field.getLinkAttributes()` | macro (see below) |
| `field|length` | `field.url|length` |
| `craft.matrixBlocks()` | `craft.entries()` |

## Field handle changes

Every linkfield handle gains a `_v2` suffix:
- `entry.primaryLink` becomes `entry.primaryLink_v2`
- `block.ctaButton` becomes `block.ctaButton_v2`
- `nav.promoButton.linkTo` becomes `nav.promoButton.linkTo_v2`
- Apply to all handles from Block 1 step 1.6.

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

## Null safety

The Craft 5 native Link field returns `null` when empty, unlike Typed Link Field
which returned an empty value object. All link field accesses must include a null guard.

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

Apply null guards to every link field access in every template updated in Block 5.

## Unmigrable link types

The following Typed Link Field types have no native Craft 5 Link field equivalent:

| Type | Behaviour during migration | Manual resolution |
|---|---|---|
| `tel` | Stored as `phone` in source table after first migration pass; throws `[ERROR] Invalid link type: phone` on cleanup | Re-enter as a URL link using `tel:+...` prefix |
| `asset` | Skipped as `unmappable type 'asset'` | Re-enter manually; there is no asset link type in the native Link field |
| `user` | Skipped as unmappable | No equivalent — omit or replace with another link type |

These rows are never written to the `_v2` field. They will be blank in the CP after migration.

---

## Do not use `.with()` with native Link field handles

In Craft 5, passing a native `craft\fields\Link` field handle to `.with()` on an element
query causes Craft to eager-load the *linked element*. The field accessor then returns
an `ElementCollection` instead of a `LinkData` object, and any `.url`, `.label`,
`.target`, or `.type` access will throw `BadMethodCallException: Method
craft\elements\ElementCollection::url does not exist`.

```twig
{# Wrong — causes ElementCollection error #}
{% set items = craft.entries().section('nav').with(['myLink_v2']).collect() %}
{% for item in items %}
  {{ item.myLink_v2.url }}  {# throws BadMethodCallException #}
{% endfor %}

{# Correct — remove .with() for native Link fields, keep .collect() #}
{% set items = craft.entries().section('nav').collect() %}
{% for item in items %}
  {% if item.myLink_v2 and item.myLink_v2.url %}
    {{ item.myLink_v2.url }}
  {% endif %}
{% endfor %}
```

`LinkData` is stored inline in the element and does not benefit from eager loading.
Remove all `.with(["handle_v2"])` calls for linkfield-migrated handles. Keep `.collect()`
on the query itself where needed for Matrix/Super Table fields.

## Super Table fields in Craft 5: always use .one()

In Craft 4, single-row Super Table fields returned a block object directly, allowing
`entry.superTableField.subField`. In Craft 5, all Super Table fields return an
EntryQuery. Accessing `.subField` on a query returns null.

Always call `.one()` before accessing sub-fields:
```twig
{# Craft 4 — no longer works #}
{% set link = entry.mySupertable.myField %}

{# Craft 5 — correct #}
{% set row = entry.mySupertable.one() %}
{% set link = row ? row.myField ?? null : null %}
```

Apply this pattern to every Super Table field access in updated templates.

## Template editing approach

Always use Python string replacement for template edits. Do not use the Edit tool's
`old_str` matching. Tab-indented files cause `old_str` matching to fail silently or
produce incorrect replacements.

Use this pattern for every template file:
```python
import re

path = 'templates/path/to/file.twig'
content = open(path).read()

# For single, unique replacements:
content = content.replace(old_str, new_str, 1)

# For replacing ALL occurrences of a pattern (e.g. all .getUrl() calls):
content = content.replace('.getUrl()', '.url')

# For pattern-based replacements (e.g. renaming field handles):
content = re.sub(r'entry\.primaryLink(?!_v2)', 'entry.primaryLink_v2', content)

# For complex multi-pattern replacements, chain them:
replacements = {
    '.getUrl()': '.url',
    '.getCustomText()': '.label',
    '.getTarget()': '.target',
}
for old, new in replacements.items():
    content = content.replace(old, new)

open(path, 'w').write(content)
```

When replacing field handles, use `re.sub` with a negative lookahead to avoid
double-suffixing handles that already have `_v2`. When replacing API methods like
`.getUrl()`, use `str.replace()` without a count argument to replace all occurrences
in the file. Review the diff after each file to confirm only intended changes were made.

### Templates with multiple loops requiring different handles

If a template contains two or more `{% for %}` loops that both use `item.navLink.*`
patterns but correspond to different Super Table block types (and therefore different
deduplicated `_v2` handles), split the file content at a unique structural delimiter
between the loops before applying substitutions:

```python
path = 'templates/_partials/navigation/_desktop.twig'
content = open(path).read()

# Find a unique delimiter that sits between the two loops
delimiter = '{# Utility Nav Items #}'  # or a comment, closing tag, etc.
top, bottom = content.split(delimiter, 1)

# Apply different handles to each half
top = top.replace('item.navLink.', 'item.navLink3_v2.')
bottom = bottom.replace('item.navLink.', 'item.navLink_v2.')

open(path, 'w').write(top + delimiter + bottom)
```

Use a comment or structural marker that appears exactly once between the two loops as
the split point. Confirm the delimiter is unique before splitting.
