# dataset-strategy

Use this when the user asks to generate, normalize, or restructure a dataset.

## Goal

Turn the user request into a concrete dataset plan before any records are written.

## Required decisions

1. Classify the request:
   - Topic-driven synthetic dataset generation
   - URL or reference-material structuring
   - Existing dataset normalization
   - Verify-only audit
   - Export-only request
2. Choose `task_type`:
   - `sft` for single best answers
   - `dpo` for chosen/rejected preference pairs
3. Define the taxonomy:
   - domains, subtopics, personas, difficulty spread, edge cases
4. Define the target output:
   - OpenAI preset
   - HuggingFace preset
   - Flat CSV/JSONL
   - Custom schema file

## Important rule

Do not hardcode one universal user-facing header layout.

- The canonical internal schema stays fixed.
- The final export schema is chosen per user request.
- If the user needs custom columns, create a schema file from `resources/templates/custom_flat_schema.json`.

## Output contract

Produce a concise plan with:

- request type
- task type
- source mode
- source type
- target format
- target schema or custom column list
- intended example count
- taxonomy buckets
- quality requirements
- resume or fresh-run decision

## Source-type mapping

- Topic-driven generation -> `generated`
- URL/reference-material structuring -> `url_reference`
- Existing dataset normalization -> `raw_dataset`
- Internet-research collection -> `internet_research`

Always state the chosen `source_type` explicitly before moving into the script layer.
