from pydantic import BaseModel, Field


class FrameCaption(BaseModel):
    """Caption generated for one sampled moment in the uploaded video."""

    timestamp_seconds: float = Field(ge=0)
    caption: str
    summary_status: str = Field(
        description="Whether this frame supports the main scene, is another scene, or is an outro."
    )


class AudioDescription(BaseModel):
    """A visual description intended to be spoken when the video reaches this moment."""

    timestamp_seconds: float = Field(ge=0)
    description: str


class CaptionResponse(BaseModel):
    """Result returned after a video has been visually captioned."""

    caption: str
    device: str
    sampled_frames: int = Field(ge=1)
    frame_captions: list[FrameCaption]
    audio_descriptions: list[AudioDescription]
