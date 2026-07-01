import sys
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
client = genai.Client(
    enterprise=True, project="nxt-create-deb", location="global",
)

MODEL = "gemini-3.5-flash"

# GCS URI of the video to analyze (gs://bucket-name/path/to/video.mp4)
VIDEO_URI = "gs://hackathon-video-analyzer/Debashis_Nayak_fb8b0087-b282-4a06-8836-1d597af67c9f/BUILDSTACK NEURA-CDN VIDEO.mp4"
VIDEO_MIME_TYPE = "video/mp4"

# ---------------------------------------------------------------------------
# Instead of hardcoding CONTEXT, we now generate it from a PROBLEM_STATEMENT
# and SOLUTION_DESCRIPTION using the model itself. Edit these two inputs to
# describe whatever product/idea the video is supposed to demonstrate.
# ---------------------------------------------------------------------------
PROBLEM_STATEMENT = """
Neura CDN solves the common problems faced in modern UI development, where creating HTML and CSS components manually is time-consuming and often leads to inconsistency across projects. Developers usually have to design, code, reuse, and manage components separately, which slows down development and increases maintenance effort.
"""

SOLUTION_DESCRIPTION = """
Neura CDN provides a solution by simplifying and accelerating UI development using artificial intelligence. The platform automatically generates clean, reusable HTML and CSS components, eliminating the need for manual design and repetitive coding work.
These AI-generated components are deployed directly through a CDN, allowing users to integrate them into their projects with just a few simple instructions. This approach reduces development time, improves performance through fast CDN delivery, and ensures a consistent, high-quality user interface across multiple projects.
"""

REPORT_OUTPUT_PATH = "video_analysis_report.md"


# ---------------------------------------------------------------------------
# Step 1: Reference the video directly from Cloud Storage (no upload needed)
# ---------------------------------------------------------------------------
def get_video_part(video_uri: str, mime_type: str = VIDEO_MIME_TYPE):
    print(f"Referencing video from GCS: {video_uri}")
    return types.Part.from_uri(file_uri=video_uri, mime_type=mime_type)


# ---------------------------------------------------------------------------
# Step 2: Generate the CONTEXT checklist from the problem + solution using
# the same model, instead of hardcoding it.
# ---------------------------------------------------------------------------
def generate_context(problem_statement: str, solution_description: str) -> str:
    prompt = f"""
You are a product analyst. Based on the PROBLEM STATEMENT and SOLUTION
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

    print("Generating validation context from problem statement + solution description...")
    response = client.models.generate_content(
        model=MODEL,
        contents=[prompt],
    )
    context = response.text
    print("Context generated.\n")
    return context


# ---------------------------------------------------------------------------
# Step 3: Ask the model to analyze the video and compare it to the context
# ---------------------------------------------------------------------------
def analyze_video(video_part, context: str) -> str:
    prompt = f"""
You are a video analysis agent. You have been given a video and a piece of
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

    print("Sending video + context to model for analysis...")
    response = client.models.generate_content(
        model=MODEL,
        contents=[video_part, prompt],
    )
    return response.text


# ---------------------------------------------------------------------------
# Step 4: Save the report
# ---------------------------------------------------------------------------
def save_report(report_text: str, output_path: str):
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\nReport saved to: {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    video_uri = sys.argv[1] if len(sys.argv) > 1 else VIDEO_URI

    try:
        context = generate_context(PROBLEM_STATEMENT, SOLUTION_DESCRIPTION)
        print("===== GENERATED CONTEXT =====\n")
        # print(context)
        print("==============================\n")

        video_part = get_video_part(video_uri)
        report = analyze_video(video_part, context)

        print("\n===== VIDEO ANALYSIS REPORT SAVED =====\n")
        # print(report)

        save_report(report, REPORT_OUTPUT_PATH)

    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    main()