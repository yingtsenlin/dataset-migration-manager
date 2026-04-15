# Dataset Migration Manager

A practical toolkit for migrating legacy ZIP datasets into the YOLO Dataset Manager platform.

## Core scripts

- `scripts/inspect_dataset_source.py`: inspect ZIP/folder sources and draft metadata.
- `scripts/upload_dataset.py`: create dataset and import ZIP via Playwright.
- `scripts/find_datasets_by_creator_status.py`: search datasets and export matched IDs.
- `scripts/delete_datasets_by_id.py`: delete datasets by explicit ID/href only.

## Required cleanup rule

Duplicate deletion must always follow this order:

1. Search first and collect dataset IDs.
2. Review keep/delete decision.
3. Delete by ID only.

For same-name duplicates, keep the largest ID and delete smaller IDs.

## Recommended workflow

1. Inspect source datasets.
2. Confirm description and tags.
3. Upload datasets.
4. Search duplicate candidates and save JSON output.
5. Delete duplicates by ID (keep largest ID).
6. Validate final results.

## Quick start (PowerShell)

### 1. Inspect source ZIP(s)

```powershell
python .\scripts\inspect_dataset_source.py `
  --source ".\test" `
  --output-format pretty
```

### 2. Upload source ZIP(s)

```powershell
python .\scripts\upload_dataset.py `
  --base-url "http://10.10.91.41/projects/1" `
  --source ".\test" `
  --append-test-suffix `
  --require-manual-login `
  --screenshot-dir ".\debug_shots"
```

### 3. Search `_test` datasets and export IDs

```powershell
python .\scripts\find_datasets_by_creator_status.py `
  --base-url "http://10.10.91.41/projects/1" `
  --name-contains "_test" `
  --require-manual-login `
  --output-format pretty `
  --output-file ".\artifacts\find_test_result.json"
```

### 4. Delete duplicates by ID, keep largest ID

```powershell
python .\scripts\delete_datasets_by_id.py `
  --base-url "http://10.10.91.41/projects/1" `
  --from-find-json ".\artifacts\find_test_result.json" `
  --delete-old-only `
  --require-manual-login `
  --result-file ".\artifacts\delete_result.json"
```

## References

- `references/workflow.md`
- `references/description-rules.md`
- `references/tagging-rules.md`
- `references/duplicate-cleanup-rules.md`
- `references/quality-checklist.md`
