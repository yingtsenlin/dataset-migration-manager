# Description rules

Write descriptions in traditional chinese.

## Style

- Use short observable phrases.
- Separate phrases with Chinese commas.
- Do not write full narrative sentences.
- Do not infer hidden intent, identity, or causality.
- Prefer concrete visible facts.

## Preferred attribute order

1. Time or lighting
2. Number of people
3. Main subject
4. Headwear or protective gear
5. Carried items
6. Face covering / no face covering
7. Other notable visible traits

## Examples

### Example 1

Observed content:

- daytime
- one person
- helmet
- waist pack
- no mask

Output:
白天，一人，安全帽，腰包，沒有口罩

### Example 2

Observed content:

- nighttime
- two people
- reflective vest
- backpack
- partial face covering

Output:
晚上，多人，反光背心，背包，部分遮擋

## Hard rules

- Use consistent wording for the same concept.
- Do not mix chinese and english in description.
- Keep it concise.
- Use `一人` for `person` and `多人` for `people`.
- If AI-generated imagery has no filename time token, infer day/night from two sampled images; if the samples disagree, keep both `白天` and `晚上`.
