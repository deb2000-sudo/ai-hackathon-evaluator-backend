"""Gemini prompts for submission video analysis.

Default templates. Admins can override these via the ``ai_evaluation_prompts``
Firestore collection (see ``EvaluationPromptService``). Placeholders must stay
in sync with ``REQUIRED_PLACEHOLDERS`` in ``evaluation_prompt_model``.
"""

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


FIELD_SCORE_PROMPT = """You are a hackathon submission evaluator.

Score the student's answer for the field "{field_label}" using the scoring
instructions below. Be strict but fair.

If the instructions define multiple sub-metrics, score each sub-metric first,
then sum them into the final score (clamped to {max_score}).

Return ONLY valid JSON with this shape:
{{
  "score": <number from 0 to {max_score}>,
  "sub_scores": [
    {{"name": "<sub-metric name>", "score": <number>, "max": <number>, "note": "<brief>"}}
  ],
  "rationale": "<2-5 sentences explaining how you arrived at the final score>"
}}

--- SCORING INSTRUCTIONS ---
{scoring_prompt}
--- END SCORING INSTRUCTIONS ---

--- STUDENT ANSWER ---
{student_answer}
--- END STUDENT ANSWER ---
"""


VIDEO_SCORE_PROMPT = """You are a hackathon demo-video evaluator.

Using the VIDEO ANALYSIS REPORT and SCORING INSTRUCTIONS below, assign a
numeric score from 0 to {max_score} for "Video Explanation".

Return ONLY valid JSON:
{{
  "score": <number from 0 to {max_score}>,
  "rationale": "<2-5 sentences>"
}}

--- SCORING INSTRUCTIONS ---
{scoring_prompt}
--- END SCORING INSTRUCTIONS ---

--- VIDEO ANALYSIS REPORT ---
{video_report}
--- END VIDEO ANALYSIS REPORT ---
"""


DEFAULT_PROMPT_META = {
    "checklist": {
        "name": "Product & Feature Validation Checklist",
        "description": (
            "Builds a checklist from problem statement + solution description "
            "before video analysis. Placeholders: {problem_statement}, {solution_description}."
        ),
    },
    "analyze_video": {
        "name": "Working Demo Video Analysis",
        "description": (
            "Compares the submitted demo video against the checklist/context. "
            "Placeholder: {context}."
        ),
    },
}
