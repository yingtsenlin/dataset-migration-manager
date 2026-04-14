# Duplicate cleanup rules

## Goal

When multiple datasets have the same name, keep only the newest created dataset.
The current dataset list page is sorted by time, so top-to-bottom order may be used as the fallback keep/delete order when visible timestamps are missing.

## Required procedure

1. Group datasets by exact same name.
2. Compare created timestamps when available.
3. Identify:
   - keep target: newest created dataset
   - delete targets: all older datasets with the same name
4. Verify that the keep target is the expected post-upload dataset when possible.
5. Delete only after the keep/delete decision is explicit.

## Safety rules

- If created time is missing, prefer the current UI order because the page is time-sorted.
- If two datasets have the same name and indistinguishable timestamps, keep the topmost one in the current list order.
- If the newest dataset appears incomplete while an older dataset appears valid, do not auto-delete. Report first.
- Prefer exact-name match only unless the user explicitly requests fuzzy matching.
- Use the visible `刪除` trigger first, then confirm with the Ant Design popconfirm `確 定` button.

## Final report format

- dataset name
- kept dataset id or unique handle
- deleted dataset ids or unique handles
- reason for keeping the selected dataset
