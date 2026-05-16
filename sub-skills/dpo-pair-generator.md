# dpo-pair-generator

Use this after `seed-generator` when `task_type` is `dpo`.

## Goal

Generate preference pairs where the `chosen` response clearly demonstrates the target behaviour and the `rejected` response is **plausible but fundamentally flawed** — not random garbage.

## Why this matters

DPO training quality is entirely determined by the signal delta between chosen and rejected responses. If the rejected response is obviously wrong or just shorter, the model learns a trivial shortcut (prefer longer / prefer formal tone) instead of the target capability. The rejected response must be something the base model would plausibly produce.

## What makes a valid rejected response

A valid rejected response is **plausible but suboptimal** in exactly one or two specific ways:

| Pattern | Example |
|---|---|
| Subtle logic bug | Syntactically valid code with an off-by-one error or edge case failure |
| Missed constraint | Correct answer that ignores one of the instruction's explicit constraints |
| Wrong prioritisation | Response that addresses the secondary goal first, burying the primary one |
| Factual near-miss | Mostly correct but one key claim is inaccurate in a non-obvious way |
| Style violation | Correct content but in the wrong format (prose when JSON was required) |
| Scope creep | Over-answers with unrequested information that would confuse a fine-tuned model |

**Never use these as rejected responses:**
- Random gibberish or empty strings
- Obvious refusals ("I cannot help with that")
- Responses that are simply shorter versions of the chosen response
- Responses that are just more polite or more verbose than the chosen response

## Contrastive delta rules

The delta between `chosen` and `rejected` must be **isolated to the specific behaviour being taught**:

1. If teaching constraint-following: the chosen and rejected should be identical in tone, length, and structure — the only difference is whether the constraint is satisfied.
2. If teaching factual accuracy: style and length should match; only the key claim differs.
3. If teaching code correctness: both responses should have similar structure; only the bug is different.

Violating these rules teaches the model to prefer based on a surface signal (length, confidence, politeness) rather than the actual target behaviour.

## DPO pair signal audit

Before importing a DPO pair, verify:
- [ ] Could a human expert identify which response is better within 30 seconds? (If yes, the delta may be too obvious — tighten it.)
- [ ] Does the rejected response look like something the base model would actually produce?
- [ ] Is the only difference between chosen and rejected the behaviour being trained for?
- [ ] Would the pair survive a blind review by someone who doesn't know which is "chosen"?

## Output format

Each DPO record must use `response.format: "preference_pair"` with:
- `response.chosen`: the correct response
- `response.rejected`: the plausible-but-flawed response

```json
{
  "task_type": "dpo",
  "instruction": "Write a Python function that returns all prime numbers up to n using a sieve. Do not use any external libraries.",
  "context": "",
  "response": {
    "format": "preference_pair",
    "chosen": "def sieve(n):\n    is_prime = [True] * (n + 1)\n    is_prime[0] = is_prime[1] = False\n    for i in range(2, int(n**0.5) + 1):\n        if is_prime[i]:\n            for j in range(i*i, n+1, i):\n                is_prime[j] = False\n    return [i for i in range(2, n+1) if is_prime[i]]",
    "rejected": "def sieve(n):\n    primes = []\n    for num in range(2, n+1):\n        if all(num % i != 0 for i in range(2, num)):\n            primes.append(num)\n    return primes"
  },
  "metadata": {
    "difficulty": "hard",
    "persona": "engineer",
    "dpo_delta": "chosen uses O(n log log n) sieve; rejected uses O(n²) trial division — both correct but performance characteristic differs drastically"
  }
}
```

Include a `metadata.dpo_delta` field briefly describing the exact flaw in the rejected response. This aids later auditing.

## Deterministic DPO audit gate

For production DPO runs, enable `dpo_audit.enabled` in the plan. This catches empty/identical chosen-rejected pairs, missing `metadata.dpo_delta`, refusal-like rejected responses, weak hard negatives, and excessive length skew.

## Coverage plan keys

Add a `dpo` section to your coverage plan to enforce DPO-specific quality gates:

```json
{
  "dpo": {
    "min_chosen_length": 30,
    "min_rejected_length": 30,
    "max_length_ratio": 8.0,
    "require_dpo_delta": true,
    "forbid_refusal_in_rejected": true,
    "min_pair_count": 500,
    "max_mean_length_ratio": 3.0,
    "max_share_per_delta": 0.6,
    "blocking": true
  }
}
```

- `min_pair_count` — minimum number of preference_pair records required before the corpus is considered complete.
- `max_mean_length_ratio` — maximum allowed ratio of `mean(chosen_length) / mean(rejected_length)` (or vice versa). Flags corpora where one side is systematically much longer than the other. Defaults to 3.0 when not set.
- `max_share_per_delta` — maximum share of pairs that may share the same `metadata.dpo_delta` value. Prevents delta-type concentration.
- `blocking: true` — when set, any `dpo_findings` produced by `coverage.py` will block build loop completion.
