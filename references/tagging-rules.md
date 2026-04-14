# Tagging rules

Write tags in english lowercase, comma-separated.

## Fixed rules

- Always include the project tag: ttcps
- Include `legacy` only when reliable source evidence indicates migrated / legacy / old data
- For plant/site codes such as `ttcps01`, keep only the site prefix tag: `ttcps`
- If the title/stem includes generative-AI hints such as `gemini`, `grok`, or `synth`, add `AI Gen`
- Use only approved vocabulary
- Avoid near-duplicate tags

## Preferred tag order

1. project tag
2. time / lighting
3. subject count or subject type
4. equipment / clothing
5. carried objects
6. face visibility / covering
7. source / migration tag

## Approved vocabulary examples

- day
- night
- dawn
- person
- people
- helmet
- vest
- pack
- backpack
- mask
- no-mask
- occlusion
- legacy

## Mapping examples

Description:
白天，一人，安全帽，腰包，沒有口罩

Tags:
ttcps, day, person, helmet, pack, no-mask

Description:
晚上，多人，反光背心，背包，部分遮擋

Tags:
ttcps, night, people, vest, backpack, occlusion

## Hard rules

- Use no-mask instead of phrases like without-mask
- Use people only when there is more than one person
- Keep the vocabulary stable across datasets
- If AI-generated imagery has no filename time token, sample two images to infer lighting; if one looks like day and one looks like night, include both `day` and `night`
