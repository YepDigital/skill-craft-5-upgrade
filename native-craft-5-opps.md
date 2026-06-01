# Native Craft 5 Tooling Opportunities

Grounded against current Craft 5 docs and package pages (some of this is newer
than what the skill suite currently assumes).

## Native tooling worth pulling in

**1. `fields/merge`, `fields/auto-merge`, `entry-types/merge` (Craft 5.3.0+)** —
**investigated and rejected.** See "Spike findings" below. Short version: these
commands solve the *inverse* of P2 (they collapse proliferated fields into one),
they cannot replace P2's pre-upgrade rename for distinct-but-colliding handles,
and their only upside is reducing field count — which is an optimization, not a
stability gain. Project priority is **stability over optimization**, and
duplicate fields are an acceptable outcome, so we are not adopting the merge
family.

**2. `php craft db/backup`** — native, transactional, config-aware backup. If the
upgrade/linkfield skills shell out to `MYSQL_CMD` for safety dumps, the native
command removes the `MYSQL_CMD` dependency in the state file (and the MySQL-only
constraint pain) for the *backup* step at least.

**3. `php craft resave/entries --field …`** — Craft's native element re-save.
Several field-type conversions only "take" once elements are re-saved and
re-normalized. Anywhere a script manually rewrites normalized values, a targeted
`resave` may do it natively (and idempotently, which the suite already values).

**4. Project-config commands** — `project-config/rebuild`, `pc/apply`,
`utils/fix-field-layout-uids`. These are the official pre-upgrade hygiene steps.
`fix-field-layout-uids` in particular addresses a known class of upgrade failures
and is a natural addition to the preflight audit's recommendations.

**5. `craftcms/rector`** — automated PHP refactoring for deprecated API calls /
signature changes. **Caveat:** it targets **PHP** (the `module/` code, and any
plugins/modules in the target), **not Twig**. So it would *not* replace
`patch-templates.py` (which patches templates), but it *could* automate the
`audit.py` deprecated-API findings for any PHP in the target project.

## Reframing custom scripts as native constructs

**6. Content migrations (`php craft migrate/create`)** — the
`MigrateLinkfieldController` `run-direct` path is essentially a one-shot data
migration. Craft's migration system gives ordering, applied/unapplied tracking,
and re-run safety for free. Trade-off: the current console-command approach gives
the explicit dry-run-then-live + `echo "yes" |` safety ritual that CLAUDE.md
calls deliberate. A migration is "run once, tracked" rather than "dry-run,
inspect, commit." For a *destructive* op against a live DB, the current explicit
gating is arguably safer, so don't move this without thought.

**7. Super Table** — Verbb ships `super-table/migrate`, and Craft 5 auto-converts
Matrix blocks to entry types during `php craft up` with no interaction. The
`craft-5-supertable` skill may be re-implementing what `super-table/migrate` +
native conversion already do. Worth checking whether the skill can become a thin
orchestrator over `super-table/migrate` rather than its own migration logic.

## Where custom genuinely stays

**The linkfield data migration is the irreducible core.** Its entire reason to
exist is that the linkfield 3.0.0-beta *can't instantiate Craft 4-era field
settings* (the documented "No Typed Link Fields found" failure), so it bypasses
the plugin and reads `lenz_linkfield` / `craft_fields` directly. No native
command does that — that's the hard-won value of `run-direct`, and it should stay
custom.

## Spike findings: `fields/merge` family vs. P2 remediation

**Decision: do not adopt the merge family. Keep P2 as-is.**

Project priority is **stability over optimization**. Reducing excess field count
is explicitly not a goal — duplicate fields after upgrade are an acceptable
outcome. The merge family's only benefit is field-count reduction, so it does
not earn its risk here.

### Merge solves the *inverse* problem of P2

The 4→5 upgrade **proliferates** fields: every Matrix (and, via
`super-table/migrate`, every Super Table) block-type sub-field becomes its own
globally-accessible field, named `{Matrix Field Name} - {Block Type Name} -
{Field Name}`. The `fields/merge` family exists to *collapse that proliferation
back down* — it **combines N fields into one survivor**, merging their content
relations into the survivor.

P2 needs the opposite. P2's canonical case is `navLink` (utility) vs `navLink`
(main) — two **semantically distinct** fields that collide on a handle and must
**stay separate** with distinct, intentional handles. Merging them is not a
no-op cleanup; it is destructive:

- Content relations from both get combined into one field **per element**. For a
  link/asset field with max-relations = 1, the survivor ends up holding both
  values → validation errors. Live, reported bug class:
  [#15869](https://github.com/craftcms/cms/issues/15869),
  [#16198](https://github.com/craftcms/cms/issues/16198),
  [#16444](https://github.com/craftcms/cms/discussions/16444).

So `fields/merge` **cannot replace P2** for distinct-but-colliding handles. For
that case it is actively wrong.

### Where it *could* have helped (but we're declining)

Not every duplicate P2 flags is semantically distinct. Two buckets:

| Bucket | Example | Tool |
|---|---|---|
| **Distinct semantics, shared handle** | utility `navLink` vs main `navLink` | **P2** — pre-upgrade rename to distinct handles. Merge would corrupt data. |
| **Identical field reused** | same `linkTo` picker, identical settings, copy-pasted across block types | Native `fields/auto-merge` *could* unify these post-upgrade — but unifying is an optimization we don't want. P2 rename (or just accepting the duplicates) is fine. |

`auto-merge` acts only on identical-settings fields, then prompts `y` + pick the
survivor. Even for the "identical" bucket we accept the duplicates rather than
introduce a post-upgrade merge step with known bugs.

### The ordering trap (recorded for posterity)

If the merge family were ever reconsidered: `auto-merge` and the linkfield `_v2`
migration both run post-upgrade and both operate per-field, so they interact.
The `run-direct` migrator reads `lenz_linkfield` keyed by **fieldId**; merging
linkfields *before* the migration collapses fieldIds and the migrator's direct
table reads can miss data. The only safe order would be **upgrade → linkfield
`_v2` migration → `fields/auto-merge` on the resulting native Link fields**.
Since we're not adopting merge, this is moot — but noted so the constraint isn't
rediscovered the hard way.

### Open question (only matters if P2 itself is ever reworked)

Whether Craft actually collides *handles* (the non-deterministic
`navLink`/`navLink2` rename P2's doc asserts) or whether the namespaced **names**
keep handles unique enough that P2's premise is narrower than stated — the
upgrade guide describes name namespacing, not handle behaviour, and Super
Table's path (Verbb's `super-table/migrate`) may differ from native Matrix.
Validate against a real upgraded dataset before changing P2. Does not affect the
merge decision above.

## Optional post-upgrade verification: `stimmt/craft-mcp`

[`stimmtdigital/craft-mcp`](https://github.com/stimmtdigital/craft-mcp) is a
Craft **5-only** MCP plugin (PHP 8.2+, `composer require stimmt/craft-mcp` →
`php craft plugin/install mcp`) that exposes ~50 tools letting Claude introspect
a running Craft install directly. **Craft 4 is unsupported**, so it has zero
value until the target reaches `upgrade-done` — it is purely a post-upgrade aid.

### Why it fits: it verifies *resolved output*, not just row counts

The suite's scariest failure mode is **silent** — a mis-mapped `_v2` handle makes
a link resolve to `""` with no error (the exact risk `handle-remediation.md` and
linkfield L2 guard against). Today that can only be checked indirectly via
`_v2` row counts. This MCP lets Claude verify the actual rendered value:

| Verification need | MCP tool | Replaces / improves |
|---|---|---|
| Migrated link field returns a real URL, not `""` | `Get Entry`, `Execute GraphQL` | Nothing today does this — direct attack on the silent-empty-link failure |
| L2 `_v2`-count reconciliation | `Run Query`, `Get Table Counts` | Removes the `MYSQL_CMD` / MySQL-only coupling for *checks* |
| Confirm remediation applied, no duplicate handles survived | `List Fields`, `Get Project Config Diff` | Manual YAML/DB inspection |
| Runtime deprecated-API surfacing | `Get Deprecations` | Runtime counterpart to `audit.py` static detection |
| Catch Twig errors from `patch-templates.py` | `Read Logs`, `Get Last Error` | Manual browser check |
| Pre-verification safety dump | `Create Backup` | Native `db/backup` (see item #2) |

Net gain: during the verification blocks, Claude gets **live introspection** into
the running Craft 5 install instead of shelling out and parsing text — an upgrade
for exactly the blocks where the suite is weakest.

### Where it does NOT help

- **Not a migrator.** It runs *inside* Craft, so it inherits the same Craft-4-era
  field-settings instantiation limits that forced `run-direct` to read tables
  directly. It verifies *after* migration; it cannot replace the direct-table
  approach.
- **Preflight/upgrade phases get nothing** — Craft 4 unsupported.

### Caveats (stability-first ethos)

- New dependency with **write + arbitrary-exec surface**: `Run Query`, `Tinker`
  (arbitrary PHP), `Create/Update Entry`, `Create Backup`. Treat as
  **dev/local-only, installed transiently for verification, removed after
  sign-off** — never shipped to production. Verification needs only the read
  subset.
- **Complementary to the skills, not part of them.** Keep it out of the SKILL.md
  mechanics — an optional, operator-installed aid for the post-upgrade
  verification blocks. Do not couple the destructive, sequential skill suite to
  an external plugin's availability.

### Recommendation

Document as an **optional** post-upgrade verification aid, scoped to read-only
verification of resolved link output and `_v2` reconciliation, dev-only, removed
after sign-off. Not a dependency of any skill.

## Sources

- [stimmtdigital/craft-mcp — GitHub](https://github.com/stimmtdigital/craft-mcp)
- [Upgrading from Craft 4 | Craft CMS 5.x docs](https://craftcms.com/docs/5.x/upgrade.html)
- [Updating Plugins for Craft 5 | Craft CMS 5.x docs](https://craftcms.com/docs/5.x/extend/updating-plugins.html)
- [craftcms/rector — GitHub](https://github.com/craftcms/rector)
- [Super Table changelog / migrate command — Verbb](https://verbb.io/craft-plugins/super-table/changelog)
- [Craft 5: What It Means For Super Table Page Builders — Viget](https://www.viget.com/articles/craft-5-what-it-means-for-super-table-page-builders)
