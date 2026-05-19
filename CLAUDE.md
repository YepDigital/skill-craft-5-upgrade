# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This repo is **not an application** — it is a single Claude Code skill (`craft-5-upgrade`)
that orchestrates upgrading a Craft CMS 4 project to Craft CMS 5. There is no build,
lint, or test step. The "product" is the procedure in `SKILL.md` plus the support
files it invokes. Changes here change how Claude runs the upgrade against a *separate*
target project — they do not run against this repo.

When editing the skill itself, the `skill-creator` skill is the tool for creating,
editing, evaluating, and optimizing skills (including the `description` frontmatter
that controls trigger accuracy).

## Architecture

`SKILL.md` is the orchestrator: a strict 8-block sequential procedure. Each block
ends with a hard **STOP** — report findings and wait for explicit user confirmation
before the next block. This stop-and-confirm gating is the core design contract;
preserve it in any edit. Blocks 1–7 are the linear upgrade; Block 8 (Super Table →
Matrix) is an optional separate post-upgrade task.

The central conditional is **LINKFIELD_PRESENT** (recorded in Block 1.4). Many steps
(2.3, 2.5, 2.6, Block 4, parts of Block 5/6/7) are skipped entirely when the project
has no `sebastianlenz/linkfield`. Any edit touching those steps must keep both the
"yes" and "no" paths correct.

Support files, loaded on demand by `SKILL.md` (never all at once):

- `scripts/audit.sh` — read-only Block 1 audit (steps 1.7, 1.7a, 1.8): linkfield
  field inventory, Super Table duplicate handles, deprecated template API calls,
  `.with([` calls. Run from the target project root with the project root as `$1`.
- `scripts/patch-templates.py` — Block 5 template patcher. Hardcoded API
  substitutions (`.getUrl()` → `.url`, etc.) plus project-specific handle renames
  passed via `--handles` JSON. `--dry-run` prints diffs without writing. Cannot
  disambiguate per-loop deduplicated handles — that is documented as a manual step.
- `module/` — the Craft module copied into the *target* project (not loaded here).
  `Module.php` registers console controller namespace; `app.php` is a merge-snippet
  for the target's `config/app.php`; `console/controllers/MigrateLinkfieldController.php`
  is the `php craft my-module/migrate-linkfield/run` command (`--dry-run`, `--cleanup`,
  `--field`, `--suffix`, plus `run-direct` fallback).
- `references/` — block-specific deep instructions pulled in only when the relevant
  block runs: `module-setup.md` (Block 2.3), `template-migration.md` (Block 5 API
  map + Twig macros + null-safety), `deploy-guide-a.md` / `deploy-guide-b.md`
  (Block 7, selected by LINKFIELD_PRESENT), `supertable-migration.md` (Block 8).

## Editing rules specific to this skill

- The skill's own global rules (SKILL.md "Global rules") are instructions to the
  *runtime*, not to repo edits — but mirror their intent: minimal diffs, no
  destructive default behavior, every error path stops and reports.
- Keep `SKILL.md` and the support files in sync. Step numbers are referenced by
  name across files (e.g. audit.sh header cites "1.7, 1.7a, 1.8"; SKILL.md Block 5
  cites `references/template-migration.md`). Renumbering a block means updating
  every cross-reference.
- The migration command is destructive against the target DB. The non-interactive
  invocation pattern (`echo "yes" | php craft my-module/migrate-linkfield/run`) and
  the dry-run-before-live ordering are deliberate safety mechanisms — do not
  collapse them.
- MySQL only. The skill does not support Postgres; do not add Postgres paths
  unless explicitly asked.
- `disable-model-invocation: true` in `SKILL.md` frontmatter is intentional — this
  skill runs only when the user explicitly requests it. Do not remove it.
