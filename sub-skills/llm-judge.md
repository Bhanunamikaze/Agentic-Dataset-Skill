# llm-judge

Use this after heuristic filtering when records still need semantic scoring.

## Goal

Judge whether each record should pass into the exportable dataset.

## Score on

- instruction-following
- usefulness
- coherence
- grounding or plausibility
- task-fit for the intended dataset

## Output format

Produce one JSON object per record.

Return raw JSONL only:

- output only valid JSON objects
- output exactly one object per line
- do not wrap the output in markdown code fences
- do not add headings, explanations, apologies, or any conversational text before or after the JSON
- if the host tool offers a JSON or structured-output mode, still follow these rules exactly

Required fields per object:

- `id`
- `score`
- `reason`
- `status`

Format:

```json
{"id":"rec_123","score":5,"reason":"Clear, useful, aligned example.","status":"pass"}
```

Rules:

- `score` must be `1` to `5`
- `status` must be `pass` or `fail`
- `reason` must be short and concrete
- the output must stay parseable as JSONL from the first byte to the last byte

Invalid examples:

- `Here is the JSON:` followed by an object
- fenced markdown like ```` ```json ... ``` ````
- multiple objects inside a JSON array
- trailing notes after the last JSON object

Save the review file, then apply it with:

```bash
python3 scripts/verify.py --from-status raw_generated --review-file <review.jsonl>
```

Reference rubric: `resources/references/llm-audit-rubric.md`
