# 3-minute version

For "can you quickly show me what you built?"

1. **Problem (20s).** Raw GTM alerts make sellers do homework. This system turns signals into one decision with evidence, or holds back and says why. Synthetic data, public reference build.

2. **Architecture (20s).** Architecture tab, diagram B. Code decides. The model labels intent, extracts quoted mentions and drafts one sentence. People handle ambiguity. Slack is only the delivery surface.

3. **One recommendation (35s).** Scenario 1. Flow strip: identity MATCH 0.95 → champion CONFIRMED → Tier 1, no open deal → DELIVER. Show the card.

4. **Evidence (20s).** Sources tab. Every line on the card points at a warehouse, CRM or enrichment record. "Why did the system decide this?" is a rule trace, not model reasoning.

5. **Uncertainty (25s).** Scenario 2. Two Jordan Morales at 0.47. NEEDS_REVIEW, and no seller saw anything.

6. **Feedback (30s).** Scenario 5. Correct → Wrong person. The exclusion is stored and the rerun is suppressed. A second vendor reports it 20 days later: still suppressed.

7. **Hardest failure (30s).** Scenario 6. The first version stopped repeating the mistake but left the CRM wrong. Now corrections undo the writes they make untrue. Idempotency covers repeats, not reversal.

Stop there. Offer the inspector or the code if they want more.
