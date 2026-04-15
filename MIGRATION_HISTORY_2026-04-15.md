# Migration History - 2026-04-15

## Scope

- Target project URL: `http://10.10.91.41/projects/1`
- Source directory used for re-upload:
  `D:\Users\yingtsenlin\Desktop\搬運\已上傳至資料庫`
- Input list: `artifacts/find_result.json` (recovered to valid JSON before execution)

## Execution Summary

1. Parsed and recovered dataset name/id list from `find_result.json` due to JSON encoding corruption.
2. Matched dataset names to ZIP files in source folder:
   - requested: 101
   - matched: 101
   - missing: 0
3. Attempted ID-based deletion for all recovered IDs:
   - target_count: 101
   - deleted_ok: 0
   - deleted_failed: 101
   - reason in logs: target href cards not found in current list page
4. Re-uploaded matched ZIPs from staged folder:
   - uploaded datasets: 101
   - upload script completed with `all datasets uploaded`

## Key Output Files (during run)

- `artifacts/find_result_recovered.json`
- `artifacts/find_result_recovered_nobom.json`
- `artifacts/reupload_match_report_20260415_163547.json`
- `artifacts/delete_from_find_result.json`
- `artifacts/reupload_from_find_20260415_163547/` (staged ZIPs)
- `debug_shots/` (runtime screenshots)

## Cleanup Note

Per request, temporary runtime outputs (for example `artifacts`, `debug_shots`) are removed after this history file is generated.
