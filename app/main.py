"""FastAPI application for the Video Caption Generator prototype."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.caption_service import VideoCaptionService, VideoProcessingError
from app.schemas import AudioDescription, CaptionResponse, FrameCaption


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

app = FastAPI(title="Video Caption Generator", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
caption_service = VideoCaptionService()


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "device": caption_service.device}


@app.post("/api/caption", response_model=CaptionResponse)
async def generate_caption(video: UploadFile = File(...)) -> CaptionResponse:
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Upload an MP4, MOV, AVI, MKV, or WEBM video file.",
        )

    with tempfile.TemporaryDirectory(prefix="video-caption-") as temp_dir:
        upload_path = Path(temp_dir) / f"upload{suffix}"
        uploaded_bytes = 0
        with upload_path.open("wb") as output:
            while chunk := await video.read(1024 * 1024):
                uploaded_bytes += len(chunk)
                if uploaded_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Video must be 200 MB or smaller.")
                output.write(chunk)

        try:
            caption, frame_captions, audio_descriptions = caption_service.caption_video(upload_path)
        except VideoProcessingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:  # Keep model/runtime details out of the browser response.
            raise HTTPException(
                status_code=500,
                detail="Caption generation failed. Check the server terminal for details.",
            ) from error
        finally:
            await video.close()

    return CaptionResponse(
        caption=caption,
        device=caption_service.device,
        sampled_frames=len(frame_captions),
        frame_captions=[
            FrameCaption(
                timestamp_seconds=frame.timestamp_seconds,
                caption=frame.caption,
                summary_status=frame.summary_status,
            )
            for frame in frame_captions
        ],
        audio_descriptions=[
            AudioDescription(
                timestamp_seconds=moment.timestamp_seconds,
                description=moment.description,
            )
            for moment in audio_descriptions
        ],
    )
