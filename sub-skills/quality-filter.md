# quality-filter

Use this before or during `verify.py`.

## Fail fast on

- placeholder responses like `[PENDING_RESPONSE]`
- refusal language
- empty or trivial answers
- broken schema structure
- records that clearly ignore the user task
- metadata-only variants that still have `rewrite_required: true`
- response length violations (see task-relative minimums below)
- verbosity mismatches (disproportionately long or short for the task type)

## Task-relative minimum lengths

Do not apply a single blanket minimum. Use intent-based heuristics:

| Intent type | Minimum response length | Notes |
|---|---|---|
| Code generation | ≥ 5 lines of code | Trivial one-liners only valid for one-liner tasks |
| Code review | ≥ 50 words | Must address at least one specific issue |
| Explanation / tutorial | ≥ 80 words | Must have structure (steps, list, or paragraphs) |
| Regex / one-liner generation | ≥ 5 chars | Short is valid; check correctness instead |
| Factual Q&A | ≥ 15 words | Must include the actual answer, not just a reference |
| Multi-turn reply | ≥ 20 words | Context-dependent; check against conversation history |

Any record failing its intent-based minimum should be failed before LLM judging.

## Syntax hooks

Before sending any code-containing record to the LLM judge, run lightweight linters:

- **Python code blocks**: validate with `ast.parse()`. A `SyntaxError` is an automatic fail.
- **JSON outputs**: parse with `json.loads()`. Invalid JSON in a "return JSON" task is an automatic fail.
- **Shell scripts**: check for obviously unclosed quotes or empty variable expansions if detectable.
- **SQL**: check for unmatched parentheses or unclosed string literals.

These checks are fast, deterministic, and catch a class of errors the LLM judge frequently overlooks.

## Heuristic expectation

If the record fails deterministic checks, mark it as failed before asking for a judge pass.

## Deterministic command

```bash
python3 scripts/verify.py --from-status raw_generated --from-status augmented
```
