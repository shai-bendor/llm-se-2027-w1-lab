# Unspecified decisions

The brief did not tell you everything. Every time you or your agent chose
something the brief did not specify, add a line here.

Examples of the kind of thing that counts: what fields the record has, what
happens to an issue with no clear type, how confident is confident enough,
what the output looks like when the model returns nothing usable.

You will need this list in W2, when we reconstruct the requirements this
build implicitly assumed. The comparison across the cohort is the lesson, so
write down what you actually decided, not what you think is the right answer.

---

- Record fields: issue_type, component, severity, has_reproduction_steps, summary, confidence, needs_human_review, error (plus repo, number) — mirrors the dataset's gold fields; duplicate_candidate omitted because one issue alone cannot show duplication.
- issue_type vocabulary: bug / enhancement / documentation / question / other (union of repos.toml types; hono's "meta" folded into "other").
- Component: per-repo closed list from repos.toml; anything outside the repo's list becomes null (textual always null); never pooled across repos.
- Severity: low / medium / high / critical with a rubric written into the prompt; there is no gold, so the rubric itself is the definition. Enhancements, docs and questions are expected to be "low".
- Confidence = model's self-reported probability that issue_type is correct, clamped to [0, 1]; not calibrated.
- needs_human_review = confidence < 0.6, or issue_type == "other", or triage failed.
- Model input is repo + title + body only; GitHub labels and gold_* fields are dropped, because labels are the source of gold and new issues arrive unlabelled.
- Issue text is untrusted: prompt tells the model it is data, outputs are validated against closed vocabularies, and nothing touches a shell.
- Bodies longer than 6000 chars are truncated (head kept) before the model call.
- Invalid model output (bad enum, non-bool, non-number confidence) or any model exception yields a failed record (classification fields null, error set, needs_human_review true), not a crash; CLI exits 1 if any record failed.
- An unknown issue type has no special path: the model must pick "other", which forces review.
- Model: whatever LLM_MODEL names (gemini/gemini-3.6-flash here), DSPy Predict (no chain-of-thought), provider-default temperature, DSPy's default caching.
- Output format: pretty JSON for one issue, JSON Lines for --count > 1; ASCII-escaped so it prints on Windows consoles.
- CLI input: a JSON file / stdin holding one issue object, or --split train|dev --index N [--count K]; the sealed test split is refused.
