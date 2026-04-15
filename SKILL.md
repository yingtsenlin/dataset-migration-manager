---
name: dataset-migration-manager
description: manage migration of legacy datasets into a new dataset platform. use when chatgpt needs to inspect legacy dataset contents, draft dataset descriptions and tags from filenames and annotations, adapt or run the existing playwright upload automation, remove duplicate datasets with the same exact name while keeping the newest one, or validate a migration result.
---

# Dataset migration manager

Use this skill to handle legacy-to-new dataset migration as a controlled workflow, not as a single upload action.

## Required resources

Use these bundled files directly:

- `scripts/inspect_dataset_source.py`
- `scripts/upload_dataset.py`
- `scripts/cleanup_duplicates.py`
- `scripts/find_datasets_by_creator_status.py`
- `references/workflow.md`
- `references/description-rules.md`
- `references/tagging-rules.md`
- `references/duplicate-cleanup-rules.md`
- `references/quality-checklist.md`

## Default operating order

Unless the user explicitly asks for only one stage, execute tasks in this order:

1. Inspect the source dataset.
2. Draft or revise metadata.
3. Review the upload automation and patch only if needed.
4. Upload the dataset.
5. Report duplicate-cleanup candidates.
6. Apply cleanup only when the keep target is reliable.
7. Validate the result.
8. Produce a concise final summary.

Use `references/workflow.md` for branching logic and task classification.

## Stage 1: inspect the source dataset

Use `scripts/inspect_dataset_source.py` before upload unless the user explicitly provides final metadata and only wants execution.

### Inspection goals

Collect or infer:

- source kind: zip or directory
- dataset name candidate
- `apc_id`, `date_token`, `time_token` when present in the filename stem
- day or night inferred from the filename time token
- image count
- annotation count
- representative image and annotation paths
- keyword hits from annotations and filenames
- class names observed from `labels/*.txt`, matched against `data.yaml`
- draft description
- draft tags
- source warnings

### Default command pattern

```powershell
python .\scripts\inspect_dataset_source.py `
  --source ".\path\to\zip-or-folder" `
  --output-format pretty
```

Use `--output-format json` when another tool or script needs to consume the result.

### Inspection interpretation rules

- Treat `suggested_description`, `suggested_tags`, and `notes` as the baseline draft.
- Prefer actual label classes matched through `data.yaml` over filename-only guesses.
- If the source contains no common annotation files, continue with conservative metadata and mention the warning.
- If the source contains no common image files, stop and report unless the user explicitly wants metadata drafting only.
- When multiple ZIPs are found in a source directory, inspect all of them and treat each ZIP as a separate migration target.

## Status Verification Utility

Use `scripts/find_datasets_by_creator_status.py` when the user asks to filter datasets by creator and review status.

Important behavior:

- Status labels are read from card tags in `ant-card-extra` (for example `待審核`).
- Default matching includes common alias pairs:
  - `審核中` also matches `待審核`
  - `待審核` also matches `審核中`
- Add `--strict-status` if exact status text is required.

Default command pattern:

```powershell
python .\scripts\find_datasets_by_creator_status.py `
  --base-url "http://<dataset-list-url>" `
  --creator "林盈岑" `
  --status "審核中" `
  --require-manual-login `
  --output-format pretty
```

## Stage 2: generate or revise metadata

Use:

- `references/description-rules.md`
- `references/tagging-rules.md`

### Metadata priorities

Priority order:

1. explicit user-provided values
2. reliable inspection output from `inspect_dataset_source.py`
3. fallback inference from the upload script naming rules

### Metadata rules

- Keep descriptions in traditional chinese.
- Keep tags in english lowercase.
- Prefer observable facts over guesses.
- Preserve stable project tags such as `ttcps` when supported by the source stem or project rules.
- Normalize plant/site tags to the alphabetic site prefix only, such as `ttcps01` -> `ttcps`.
- If the dataset title or stem contains generative-AI hints such as `gemini`, `grok`, or `synth`, add the tag `AI Gen`.
- In descriptions, use `一人` for `person` and `多人` for `people`.
- For AI-generated imagery without a filename time token, sample two images to infer day/night; if the samples disagree, keep both tags.
- Add `legacy` only when the filename or other reliable source evidence indicates legacy / migrated / old data.

### Important consistency rule

`upload_dataset.py` has a simpler filename-based fallback than `inspect_dataset_source.py`.

- Prefer the inspection result when it is available.
- Only rely on upload-script defaults when inspection is skipped or when the user intentionally wants a quick filename-based upload.

## Stage 3: review and adapt the upload automation

Use `scripts/upload_dataset.py` as the primary upload entrypoint.

Do not rewrite it from scratch unless reuse is clearly impractical. Prefer the smallest safe patch.

### Current upload-script capabilities

- accept a single ZIP or a directory containing multiple ZIP files
- pause for manual login with `--require-manual-login`
- override metadata in single-ZIP mode with:
  - `--dataset-name`
  - `--description`
  - `--tags`
- change browser channel and headless mode
- capture optional debug screenshots with `--screenshot-dir`
- keep or remove debug screenshots using `--keep-debug-screenshots`

### Default command pattern

```powershell
python .\scripts\upload_dataset.py `
  --base-url "http://<dataset-list-url>" `
  --source ".\path\to\zip-or-folder" `
  --require-manual-login
```

### Single-dataset override pattern

```powershell
python .\scripts\upload_dataset.py `
  --base-url "http://<dataset-list-url>" `
  --source ".\path\to\single.zip" `
  --dataset-name "<dataset-name>" `
  --description "<description>" `
  --tags "<tag1,tag2,...>" `
  --require-manual-login
```

### When to patch the upload script

Before running upload, inspect whether the website changed in any of these ways:

- create-dataset button text or placement
- modal structure
- selectors for name, description, or tags
- ZIP upload input
- import button text or enable/disable behavior
- dataset-list entry structure after creation

If the UI changed, explain:

1. what changed in the website
2. which selector or wait logic was updated
3. whether the change affects upload only or also cleanup

## Stage 4: upload the dataset

Before upload, print or state:

- source path
- final dataset name
- final description
- final tags

Operational rules:

- use screenshots when debugging unstable UI behavior
- return to the dataset list page after each upload batch
- if an import fails, stop and report before cleanup
- when multiple ZIPs are uploaded from a folder, do not use per-file metadata overrides on that same command

## Stage 5: duplicate cleanup

Use `scripts/cleanup_duplicates.py` after upload whenever same-name duplicates may exist.

Always start with report mode unless the user explicitly asks to apply deletion immediately and the safety conditions are satisfied.

### Safe default command

```powershell
python .\scripts\cleanup_duplicates.py `
  --base-url "http://<dataset-list-url>" `
  --dataset-name "<exact-dataset-name>" `
  --mode report `
  --require-manual-login
```

### Apply command

```powershell
python .\scripts\cleanup_duplicates.py `
  --base-url "http://<dataset-list-url>" `
  --dataset-name "<exact-dataset-name>" `
  --mode apply `
  --require-manual-login
```

### Cleanup rules

Also follow `references/duplicate-cleanup-rules.md`.

- Match exact same name only unless the user explicitly requests fuzzy matching.
- Default mode uses current UI order (newest on top): keep the top item and delete lower duplicates.
- If UI sorting is uncertain, switch to report mode first and require explicit confirmation before apply.
- Only disable `--assume-ui-sorted-newest-first` when the page is not reliably sorted newest-first.
- Never claim a delete is safe if the keep target cannot be explained.

## Stage 6: validate the migration result

After upload and optional cleanup, validate with `references/quality-checklist.md`.

At minimum, verify:

- dataset exists
- description exists
- tags exist
- uploaded source appears present
- duplicate cleanup did not remove the newest target incorrectly

## Response format

Unless the user asks for a different format, produce:

### Dataset summary
- source path
- inferred or provided dataset name
- image and annotation counts
- notable keywords or classes

### Metadata
- final description
- final tags
- why these values were chosen
- confidence level

### Script changes
- changed files
- selector or logic updates
- risk level

### Upload result
- attempted command
- outcome
- screenshots used or not used

### Duplicate cleanup
- report or apply mode
- keep target
- delete targets
- reason for the decision

### Validation
- checks passed
- checks not confirmed
- manual follow-up items

