# Dataset Migration Manager

A practical skill bundle for migrating legacy datasets into a new dataset platform.

This skill helps with:

- inspecting a legacy dataset
- drafting dataset description and tags
- uploading ZIP datasets through the web platform
- finding and removing older duplicate datasets with the same name
- checking migration results

## Folder structure

```text
dataset-migration-manager/
├── README.md
├── SKILL.md
├── agents/
│   └── openai.yaml
├── scripts/
│   ├── upload_dataset.py
│   ├── cleanup_duplicates.py
│   └── inspect_dataset_source.py
└── references/
    ├── workflow.md
    ├── description-rules.md
    ├── tagging-rules.md
    ├── duplicate-cleanup-rules.md
    └── quality-checklist.md
```

## What each script does

```inspect_dataset_source.py```

Inspect a legacy dataset folder or ZIP file and generate a draft summary, description, and tags.

Use this first before upload.

```upload_dataset.py```

Open the target dataset platform, create a dataset, fill metadata, and import the ZIP file.

This is the main upload automation script.

```cleanup_duplicates.py```

Find datasets with the same name and help remove older duplicates.

Use report `mode` first, then `apply` only after checking the result.

## Recommended workflow

1. Inspect the source dataset
2. Review the suggested description and tags
3. Upload the dataset
4. Check duplicate datasets with the same name
5. Remove old duplicates if the report is correct
6. Verify the final result

## Quick start

1. Inspect a test dataset
python scripts/inspect_dataset_source.py \
  --source "./test_data/ttcps_20250401_0830.zip" \
  --output-format pretty
2. Upload the dataset
python scripts/upload_dataset.py \
  --base-url "http://10.10.91.41/projects/1" \
  --source "./test_data/ttcps_20250401_0830.zip" \
  --dataset-name "ttcps_20250401_0830_test" \
  --description "白天，一人，安全帽，腰包，沒有面具" \
  --tags "ttcps,day,person,helmet,pack,no-mask,legacy" \
  --require-manual-login \
  --screenshot-dir "./debug_shots"
3. Report duplicate datasets
python scripts/cleanup_duplicates.py \
  --base-url "http://10.10.91.41/projects/1" \
  --dataset-name "ttcps_20250401_0830_test" \
  --mode report \
  --require-manual-login
4. Apply duplicate cleanup
python scripts/cleanup_duplicates.py \
  --base-url "http://10.10.91.41/projects/1" \
  --dataset-name "ttcps_20250401_0830_test" \
  --mode apply \
  --require-manual-login \
  --assume-ui-sorted-newest-first

### Notes

Start with a small test dataset first
Use a dataset name ending in _test during early testing
Always run duplicate cleanup in report mode before apply
Keep debug screenshots enabled during first runs
If the website layout changes, update upload_dataset.py before rerunning

### References

See files in references/ for:

* workflow details
* description writing rules
* tag vocabulary rules
* duplicate cleanup safety rules
* final quality checks
