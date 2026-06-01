# Optional: post-upgrade verification with `stimmt/craft-mcp`

This file is an optional reference. `stimmt/craft-mcp` is **not a skill dependency** —
it is an operator-installed, dev-only aid for post-upgrade verification. Install
transiently, use only the read subset, and remove after sign-off. Never ship to
production.

**Craft 5 only.** The plugin runs inside Craft, so it inherits the same
Craft-4-era instantiation limits that forced `run-direct` to read tables directly.
It has zero value until the target reaches `PHASE: upgrade-done` — it is purely a
post-upgrade smoke-test aid.

---

## Installation

```bash
composer require stimmt/craft-mcp
php craft plugin/install mcp
```

`plugin/install` is required — `composer require` alone does not enable the plugin.

Remove after sign-off:
```bash
php craft plugin/uninstall mcp
composer remove stimmt/craft-mcp
```

---

## Why it helps: resolved output, not just row counts

The suite's scariest failure mode is **silent** — a mis-mapped `_v2` handle makes a
link resolve to `""` with no error, even when the CP shows "1 row migrated." Today
that can only be checked indirectly via `_v2` row counts. craft-mcp lets Claude
verify the actual rendered value.

| Verification need | MCP tool | Replaces / improves |
|---|---|---|
| Migrated link field returns a real URL, not `""` | `Get Entry`, `Execute GraphQL` | Nothing today does this — direct attack on the silent-empty-link failure |
| L2 `_v2`-count reconciliation | `Run Query`, `Get Table Counts` | Removes the `MYSQL_CMD` / MySQL-only coupling for *checks* |
| Confirm no duplicate handles survived | `List Fields`, `Get Project Config Diff` | Manual YAML/DB inspection |
| Runtime deprecated-API surfacing | `Get Deprecations` | Runtime counterpart to `audit.py` static detection |
| Catch Twig errors from `patch-templates.py` | `Read Logs`, `Get Last Error` | Manual browser check |

---

## Use the read subset only

craft-mcp exposes write and arbitrary-exec tools (`Run Query`, `Tinker`, `Create/Update
Entry`, `Create Backup`). For post-upgrade verification, only the **read-only** subset
is needed:

- `Get Entry` — verify link field resolves to a real URL
- `Execute GraphQL` — spot-check multiple entries at once
- `List Fields` — confirm `_v2` fields present with correct type
- `Get Project Config Diff` — confirm no unexpected YAML drift
- `Get Deprecations` — surface runtime deprecated-API hits
- `Read Logs`, `Get Last Error` — catch Twig errors from template patching
- `Get Table Counts` — cross-check migrated row counts

Avoid `Run Query` (raw SQL write risk), `Tinker` (arbitrary PHP), and `Create/Update
Entry` during verification — they are not needed and carry unnecessary write surface.

---

## Where craft-mcp does NOT help

- **Not a migrator.** It runs inside Craft, so it cannot replace the direct-table
  approach in `run-direct`. It verifies *after* migration; it does not perform it.
- **Preflight and upgrade phases get nothing** — Craft 4 is unsupported.

---

## Source

- [stimmtdigital/craft-mcp — GitHub](https://github.com/stimmtdigital/craft-mcp)
