import os
from google import genai
from google.genai import types

def transcribe_large_video(project_id: str, gcs_uri: str, output_txt_path: str, location: str = "us-central1"):
    """
    Transcribes a long video file stored in GCS using Gemini on Vertex AI.
    
    Args:
        project_id: Your Google Cloud Project ID
        gcs_uri: The GCS path to your file (e.g., 'gs://my-bucket/video.mp4')
        output_txt_path: Local path where the transcription text file will be saved
        location: Google Cloud region (e.g., 'us-central1')
    """
    print("Initializing Vertex AI Client...")
    # Initialize the modern GenAI client pointing to Vertex AI backend
    client = genai.Client(
        vertexai=True,
        project=project_id,
        location=location,
        http_options=types.HttpOptions(api_version="v1")
    )
    
    # Determine MIME type based on file extension
    if gcs_uri.endswith(".mp4"):
        mime_type = "video/mp4"
    elif gcs_uri.endswith(".mkv"):
        mime_type = "video/x-matroska"
    else:
        mime_type = "video/mp4" # fallback default

    # Define the multimodal input referencing the GCS file
    video_part = types.Part.from_uri(
        file_uri=gcs_uri,
        mime_type=mime_type
    )
    
    # Construct a strong prompt instructing formatting, speaker tracking, and timestamps
    prompt = """
    You are an expert transcription assistant. 
    Process the provided video's audio and generate an accurate, detailed transcription. 
    
    Requirements:
    1. Organize the text by speaker turns (e.g., Speaker 1, Speaker 2).
    2. Insert timestamps at natural paragraph breaks or when the speaker changes (Format: [HH:MM:SS]).
    3. Maintain the original language of the speech. Do not summarize; capture the full dialogue.
    """
    
    print(f"Sending transcription request for {gcs_uri} to Gemini...")
    print("Note: For a 4-hour file, processing may take several minutes. Please wait...")
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt, video_part],
            config=types.GenerateContentConfig(
                temperature=0.1,        # Low temperature for highest transcription accuracy
                audio_timestamp=True,   # Optimizes the backend model pipeline for audio analysis
            ),
        )
        
        # Save response text to local file
        with open(output_txt_path, "w", encoding="utf-8") as f:
            f.write(response.text)
            
        print(f"\nSuccess! Transcription saved successfully to: {output_txt_path}")
        
    except Exception as e:
        print(f"An error occurred during transcription: {e}")

if __name__ == "__main__":
    # CONFIGURATION
    GCP_PROJECT_ID = "nxt-create-deb"       # <-- Replace with your GCP Project ID
    GCS_VIDEO_URI = "gs://audio-transcribe-debashis/Aurora Day-1.mp4" # <-- Replace with your GCS path
    OUTPUT_FILE = "transcription_output.txt"
    GCP_LOCATION = "us-central1"                 # <-- Adjust region if necessary
    
    transcribe_large_video(
        project_id=GCP_PROJECT_ID,
        gcs_uri=GCS_VIDEO_URI,
        output_txt_path=OUTPUT_FILE,
        location=GCP_LOCATION
    )