---
name: dataset-migration-manager
description: manage migration of legacy datasets into a new dataset platform. use when chatgpt needs to prepare dataset zips, inspect metadata, upload via playwright, resume interrupted uploads, verify uploaded datasets actually exist on the site, clean duplicates by explicit IDs, and report migration results.
---

# Dataset migration manager

Use this skill as an end-to-end migration workflow, not a single upload command.

## Required resources

- `scripts/name_standardization.py`
- `scripts/prepare_renamed_zips.py`
- `scripts/inspect_dataset_source.py`
- `scripts/upload_dataset.py`
- `scripts/find_datasets_by_creator_status.py`
- `scripts/delete_datasets_by_id.py`
- `scripts/verify_project_datasets.py`
- `references/workflow.md`
- `references/description-rules.md`
- `references/tagging-rules.md`
- `references/duplicate-cleanup-rules.md`
- `references/quality-checklist.md`

## Default operating order

Unless the user explicitly asks for only one stage, execute tasks in this order:

1. Prepare source ZIPs into the user-specified output folder.
2. Inspect prepared ZIPs and draft metadata.
3. Patch upload automation only if UI changed.
4. Upload datasets.
5. If interrupted, resume only pending datasets from logs.
6. Verify target dataset names really exist on the project page.
7. Run duplicate cleanup by explicit dataset IDs when needed.
8. Produce a concise result report.

Use `references/workflow.md` for branching logic and safety checks.

## Stage 1: prepare source ZIPs (required)

Always run `scripts/prepare_renamed_zips.py` before inspect/upload when the source is a folder.

### What this stage does

- normalizes dataset names with shared rules
- converts `cam...` to `CGTD...`
- normalizes `ttc...` to `ttcps...`
- ensures each ZIP contains `data.yaml`
- writes processed ZIPs into a target output folder without mutating source folder

### Default command

```powershell
python .\scripts\prepare_renamed_zips.py `
  --source ".\path\to\source" `
  --output ".\path\to\prepared"
```

## Stage 2: inspect and metadata draft

Use `scripts/inspect_dataset_source.py` on prepared ZIPs.

```powershell
python .\scripts\inspect_dataset_source.py `
  --source ".\path\to\prepared" `
  --output-format pretty
```

Inspection expectations:

- image / annotation counts
- class evidence from `labels/*.txt` + `data.yaml`
- suggested description and tags
- warnings for incomplete sources

## Stage 3: upload

Use `scripts/upload_dataset.py` as the only uploader.

```powershell
python .\scripts\upload_dataset.py `
  --base-url "http://<dataset-list-url>" `
  --source ".\path\to\prepared" `
  --username "<username>" `
  --password "<password>" `
  --headless
```

Upload rules:

- report source/name/description/tags before upload
- stop immediately on create/import failures
- do not run duplicate deletion when upload success is unclear

## Stage 4: interrupted upload resume

If upload was interrupted:

1. parse upload logs and collect already uploaded ZIP names
2. diff against prepared folder
3. upload only pending ZIPs
4. report pending count, resumed count, missing count

Keep log files in `artifacts/` only as long as needed; clean temporary files after confirmation.

## Stage 5: existence verification (required after bulk upload)

Use `scripts/verify_project_datasets.py` to verify target names exist on the project page.

```powershell
python .\scripts\verify_project_datasets.py `
  --base-url "http://<dataset-list-url>" `
  --target-file ".\artifacts\target_names.txt" `
  --username "<username>" `
  --password "<password>" `
  --headless `
  --output-file ".\artifacts\verify_result.json"
```

Required output:

- target count
- matched count
- missing count
- missing name list (if any)

## Stage 6: duplicate cleanup (ID-first only)

Use `scripts/find_datasets_by_creator_status.py` + `scripts/delete_datasets_by_id.py`.

Rules:

- search first and export IDs
- review keep/delete candidates
- delete by explicit IDs only
- for same-name duplicates, keep the largest ID

## Stage 7: final report format

### Dataset summary

- source folder
- prepared output folder
- total target count

### Upload summary

- uploaded count
- resumed count (if any)
- failed count (if any)

### Verification summary

- matched count
- missing count
- missing names

### Cleanup summary

- duplicate groups reviewed
- IDs deleted
- IDs kept

### Risks / manual follow-up

- unresolved UI instability
- unclear/missing metadata evidence
- items needing manual website confirmation
