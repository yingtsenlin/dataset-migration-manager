# Dataset Migration Manager

A practical toolkit for migrating legacy ZIP datasets into the YOLO Dataset Manager platform.

## Core scripts

- `scripts/name_standardization.py`: shared naming normalization rules used by other scripts.
- `scripts/prepare_renamed_zips.py`: normalize names, ensure `data.yaml`, and export ZIPs to target folder.
- `scripts/inspect_dataset_source.py`: inspect ZIP/folder sources and draft metadata.
- `scripts/upload_dataset.py`: create dataset and import ZIP via Playwright.
- `scripts/find_datasets_by_creator_status.py`: search datasets and export matched IDs.
- `scripts/delete_datasets_by_id.py`: delete datasets by explicit ID/href only.
- `scripts/verify_project_datasets.py`: verify whether target dataset names really exist in the project page.

## Required cleanup rule

Duplicate deletion must always follow this order:

1. Search first and collect dataset IDs.
2. Review keep/delete decision.
3. Delete by ID only.

For same-name duplicates, keep the largest ID and delete smaller IDs.

## Recommended workflow

1. Prepare ZIPs to target folder (normalize names + ensure `data.yaml`).
2. Inspect prepared datasets.
3. Confirm description and tags.
4. Upload prepared datasets.
5. Search duplicate candidates and save JSON output.
6. Delete duplicates by ID (keep largest ID).
7. Validate final results.

## Quick start (PowerShell)

### 1. Prepare ZIPs to your target folder

```powershell
python .\scripts\prepare_renamed_zips.py `
  --source ".\test" `
  --output ".\test\rename"
```

This step automatically:

- normalizes naming rules (for example `cam16_260416_1012.zip` -> `CGTD16_260416_1012.zip`)
- keeps stable site prefixes (`ttc` -> `ttcps`)
- adds `data.yaml` when missing
- writes processed ZIPs into your specified folder

### 2. Inspect source ZIP(s)

```powershell
python .\scripts\inspect_dataset_source.py `
  --source ".\test\rename" `
  --output-format pretty
```

### 3. Upload source ZIP(s)

```powershell
python .\scripts\upload_dataset.py `
  --base-url "http://10.10.91.41/projects/1" `
  --source ".\test\rename" `
  --append-test-suffix `
  --require-manual-login `
  --screenshot-dir ".\debug_shots"
```

### 4. Search `_test` datasets and export IDs

```powershell
python .\scripts\find_datasets_by_creator_status.py `
  --base-url "http://10.10.91.41/projects/1" `
  --name-contains "_test" `
  --require-manual-login `
  --output-format pretty `
  --output-file ".\artifacts\find_test_result.json"
```

### 5. Delete duplicates by ID, keep largest ID

```powershell
python .\scripts\delete_datasets_by_id.py `
  --base-url "http://10.10.91.41/projects/1" `
  --from-find-json ".\artifacts\find_test_result.json" `
  --delete-old-only `
  --require-manual-login `
  --result-file ".\artifacts\delete_result.json"
```

### 6. Verify uploaded dataset names exist in project

```powershell
python .\scripts\verify_project_datasets.py `
  --base-url "http://10.10.91.41/projects/1" `
  --target-file ".\artifacts\remaining_zips.txt" `
  --username "<username>" `
  --password "<password>" `
  --headless `
  --output-file ".\artifacts\verify_result.json"
```

## References

- `references/workflow.md`
- `references/description-rules.md`
- `references/tagging-rules.md`
- `references/duplicate-cleanup-rules.md`
- `references/quality-checklist.md`
