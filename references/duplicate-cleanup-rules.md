# Duplicate cleanup rules

## Goal

When multiple datasets have the same name, keep only the newest created dataset.
The current dataset list page is sorted by time, so keep the top item and delete items below it when `--assume-ui-sorted-newest-first` is enabled (default).

## Required procedure

1. Group datasets by exact same name.
2. When `--assume-ui-sorted-newest-first` is enabled, use top-to-bottom list order directly.
3. When UI-order mode is disabled, compare created timestamps when available.
4. Identify:
   - keep target: newest created dataset
   - delete targets: all older datasets with the same name
5. Verify that the keep target is the expected post-upload dataset when possible.
6. Delete only after the keep/delete decision is explicit.

## Safety rules

- In default mode, always treat top as newest and delete lower duplicates.
- If two datasets have the same name and indistinguishable timestamps, keep the topmost one in the current list order.
- If the newest dataset appears incomplete while an older dataset appears valid, do not auto-delete. Report first.
- Prefer exact-name match only unless the user explicitly requests fuzzy matching.
- Use the visible `刪除` trigger first, then confirm with the Ant Design popconfirm `確 定` button.

## Final report format

- dataset name
- kept dataset id or unique handle
- deleted dataset ids or unique handles
- reason for keeping the selected dataset
