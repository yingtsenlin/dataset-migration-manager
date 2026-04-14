# Workflow

This file defines the detailed migration decision flow for `dataset-migration-manager`.

## Primary flow

1. Determine the user's intent.
2. Choose the minimum necessary stage.
3. Inspect the source before generating or applying metadata.
4. Validate metadata before upload.
5. Update automation only if needed.
6. Upload first, clean duplicates second.
7. Validate after every destructive or state-changing action.
8. End with a short operational summary.

## Step 1: classify the request

### A. Full migration

Use the full flow when the user asks to:

- move a legacy dataset to the new platform
- create and upload a new dataset
- upload and then clean duplicates

Follow steps 2 through 7.

### B. Metadata-only preparation

Use inspection plus metadata drafting only when the user asks to:

- inspect a dataset
- draft description and tags
- review the source before upload

Run:

1. inspection
2. metadata drafting
3. concise report

Do not upload or delete.

### C. Upload-script maintenance

Use upload-script maintenance when the user asks to:

- fix the upload automation
- adapt the script to a changed UI
- add a new form field or selector

Run:

1. inspect the script and page assumptions
2. patch the smallest safe area
3. explain the changes
4. optionally run a dry operational test if possible

### D. Duplicate-cleanup only

Use duplicate cleanup only when the user asks to:

- list same-name datasets
- decide what to keep
- delete old duplicates

Run:

1. collect matching datasets by exact name
2. report keep/delete candidates
3. apply deletion only if safety conditions are satisfied

## Step 2: inspect the source dataset

Use `scripts/inspect_dataset_source.py` before upload unless the user explicitly provides final metadata and only wants script execution.

### Inspection checklist

Capture:

- source path
- dataset stem or directory name
- apc id, date token, time token if available
- day or night inferred from the filename time token
- image count
- annotation count
- sample image paths
- sample annotation paths
- detected keywords
- detected class names, preferring actual `labels/*.txt` ids matched through `data.yaml`
- source warnings

### Inspection decision rules

- If images are missing, flag the source as incomplete.
- If annotations are missing, still continue with a conservative metadata draft.
- If both are sparse, draft minimal metadata and ask for manual confirmation only when it blocks correctness.

## Step 3: draft metadata

Use the inspection result as the baseline.

### Description drafting rules

- Use traditional chinese.
- Prefer short, observable phrases.
- Avoid narratives and guesses.
- Use stable ordering such as time, people, gear, carried items, face covering.

### Tag drafting rules

- Use english lowercase.
- Use approved vocabulary only.
- Keep project tags stable.
- Normalize plant/site tags to the site prefix only, without trailing numeric ids.
- Add `AI Gen` when the dataset stem/title includes generative-AI hints such as `gemini`, `grok`, or `synth`.
- Add `legacy` only when reliable source evidence indicates migrated old data.

### Metadata confidence rules

#### High confidence

Use the drafted metadata directly when:

- the inspection finds clear keyword or class evidence
- `data.yaml` and labels agree on the observed classes
- filename tokens strongly support time-of-day or source tags

#### Medium confidence

Use a conservative draft and flag it when:

- only part of the expected evidence is present
- the source suggests likely tags but not enough to fully confirm them

#### Low confidence

Do not over-specify when:

- annotation text is missing
- filenames are weak signals
- the source content is too sparse

Prefer a minimal draft plus a warning.

## Step 4: decide whether to patch the upload script

Before running `scripts/upload_dataset.py`, compare the expected UI behavior with the current website.

### Patch the script when any of these changed

- button labels
- modal structure
- form fields
- upload input location
- import button enable/disable behavior
- dataset list selection behavior

### Patch strategy

- prefer selector updates over flow rewrites
- keep the command-line interface stable when possible
- explain every changed selector or wait condition
- keep existing debug screenshot support intact

## Step 5: upload the dataset

### Standard upload sequence

1. open dataset list page
2. complete manual login if needed
3. create dataset
4. fill name, description, and tags
5. confirm creation
6. select the newly created dataset
7. set the zip file input
8. click import
9. wait for import completion window
10. return to the list page

### Upload stop conditions

Stop and report immediately if:

- the create button cannot be found
- the form fields cannot be filled
- the confirm button never enables
- the zip input cannot be found
- the import button never enables
- the page structure no longer matches the script reliably

Do not continue to cleanup when upload is not clearly successful.

## Step 6: evaluate duplicate cleanup

Use `scripts/cleanup_duplicates.py` after a successful upload when duplicates are expected.

### Safe operating order

1. run report mode
2. inspect keep/delete decision
3. run apply mode only if the keep target is reliable

### Keep/delete decision rules

- match by exact dataset name
- prefer parsed created timestamps
- if timestamps are missing, use the current UI order because the page is currently sorted newest first
- keep the newest dataset only
- delete all older exact-name duplicates only

### Hard stop conditions

Do not apply deletion when:

- fewer than two exact-name datasets are found
- created timestamps conflict or cannot be interpreted
- the supposedly newest dataset looks incomplete
- the page sorting order is unknown and timestamp parsing failed

## Step 7: validate the result

After upload and any cleanup, validate:

- the dataset still exists
- metadata is present
- the uploaded source appears associated with the dataset
- only the intended same-name dataset remains
- no unexpected deletions occurred

## Suggested command patterns

### Inspect only

```powershell
python .\scripts\inspect_dataset_source.py `
  --source ".\path\to\zip-or-folder" `
  --output-format pretty
```

### Upload one dataset with explicit metadata

```powershell
python .\scripts\upload_dataset.py `
  --base-url "http://<dataset-list-url>" `
  --source ".\path\to\single.zip" `
  --dataset-name "<dataset-name>" `
  --description "<description>" `
  --tags "<tag1,tag2,...>" `
  --require-manual-login
```

### Upload a folder of zip files using inferred defaults

```powershell
python .\scripts\upload_dataset.py `
  --base-url "http://<dataset-list-url>" `
  --source ".\path\to\folder-containing-zips" `
  --require-manual-login
```

### Report duplicates

```powershell
python .\scripts\cleanup_duplicates.py `
  --base-url "http://<dataset-list-url>" `
  --dataset-name "<exact-dataset-name>" `
  --mode report `
  --require-manual-login
```

### Apply duplicate cleanup

```powershell
python .\scripts\cleanup_duplicates.py `
  --base-url "http://<dataset-list-url>" `
  --dataset-name "<exact-dataset-name>" `
  --mode apply `
  --require-manual-login
```

## Final summary template

Use this template after any meaningful task:

### Dataset summary

- source:
- dataset name:
- source observations:

### Metadata

- description:
- tags:
- confidence:

### Actions taken

- inspection:
- script edits:
- upload:
- duplicate cleanup:

### Validation

- passed:
- manual checks still needed:

### Risks
