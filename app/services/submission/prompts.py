"""Gemini prompts for submission video analysis."""

CHECKLIST_PROMPT = """You are a product analyst. Based on the PROBLEM STATEMENT and SOLUTION
DESCRIPTION below, produce a "Product & Feature Validation Checklist" that
will later be used to evaluate whether a demo video properly showcases
this product.

Structure your output as a numbered checklist with clear sections, similar
to this style:

1. PROBLEM ESTABLISHMENT (The Pain Points)
- ...specific things the video should mention about the problem...

2. CORE SOLUTION / FEATURE DEMONSTRATION
- ...specific capabilities the video should visually demonstrate...

3. WORKFLOW / INTEGRATION
- ...how the solution should be shown working end-to-end...

4. VALUE PROPOSITION & BENCHMARKS
- ...explicit benefits/claims the video should confirm...

Adapt section names and bullet points to fit the specific product described
below (don't just copy the template above verbatim) — extract concrete,
checkable criteria a reviewer can verify against the video. Output plain
text only (no markdown headers like #, just numbered sections and bullets).

--- PROBLEM STATEMENT ---
{problem_statement}
--- END PROBLEM STATEMENT ---

--- SOLUTION DESCRIPTION ---
{solution_description}
--- END SOLUTION DESCRIPTION ---
"""


ANALYZE_VIDEO_PROMPT = """You are a video analysis agent. You have been given a video and a piece of
reference "context" (requirements, a script, guidelines, or a checklist).

Your job:
1. Watch/analyze the video content carefully (visuals, spoken/on-screen
   text, scenes, pacing, and overall narrative).
2. Compare what is actually present in the video against the CONTEXT below.
3. Produce a structured report in Markdown with these sections:

## Video Summary
A concise summary of what happens in the video.

## Key Content Identified
Bullet list of the key scenes, topics, claims, or elements present in the
video.

## Comparison Against Context
For each relevant point in the CONTEXT, state whether the video:
- Matches / Covers it (✅)
- Partially covers it (⚠️)
- Is missing it (❌)
Explain briefly why for each.

## Discrepancies & Issues
Anything in the video that contradicts, conflicts with, or deviates from
the context.

## Overall Assessment
A short verdict (e.g., compliant / non-compliant / needs revision) plus a
1-5 score with justification.

## Recommendations
Concrete, actionable suggestions to align the video with the context.

--- CONTEXT ---
{context}
--- END CONTEXT ---
"""


