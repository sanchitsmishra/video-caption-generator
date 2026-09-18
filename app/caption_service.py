"""Video sampling and pretrained visual-caption inference."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from threading import Lock

import cv2
import numpy as np
import torch
from PIL import Image
from transformers import BlipForConditionalGeneration, BlipProcessor


MODEL_ID = "Salesforce/blip-image-captioning-base"
SCENE_SCAN_INTERVAL_SECONDS = 0.75
MAX_SCENE_GAP_SECONDS = 8.0
SCENE_CHANGE_THRESHOLD = 0.32
# A high safeguard for CPU inference. This is intentionally above the old 24-frame
# limit so a montage can retain many meaningful scene changes without attempting to
# caption every raw video frame.
MAX_ANALYSIS_FRAMES = 60
NARRATION_SIMILARITY_THRESHOLD = 0.62


class VideoProcessingError(ValueError):
    """Raised when an uploaded file cannot be decoded as a usable video."""


@dataclass(frozen=True)
class SampledFrame:
    timestamp_seconds: float
    image: Image.Image


@dataclass(frozen=True)
class CaptionedFrame:
    timestamp_seconds: float
    caption: str
    summary_status: str


@dataclass(frozen=True)
class NarrationMoment:
    timestamp_seconds: float
    description: str


class VideoCaptionService:
    """Loads BLIP lazily and uses it to caption representative video frames."""

    def __init__(self) -> None:
        self._processor: BlipProcessor | None = None
        self._model: BlipForConditionalGeneration | None = None
        self._load_lock = Lock()
        self._person_detector: object | None = None
        self._person_detector_available: bool | None = None
        self._detector_load_lock = Lock()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def _ensure_model_loaded(self) -> None:
        if self._model is not None and self._processor is not None:
            return

        # Model loading is expensive and must happen only once per server process.
        with self._load_lock:
            if self._model is None or self._processor is None:
                self._processor = BlipProcessor.from_pretrained(MODEL_ID)
                self._model = BlipForConditionalGeneration.from_pretrained(MODEL_ID)
                self._model.to(self.device)
                self._model.eval()

    def _ensure_person_detector_loaded(self) -> bool:
        """Load a compact person detector only when a caption needs verification."""
        if self._person_detector_available is not None:
            return self._person_detector_available

        with self._detector_load_lock:
            if self._person_detector_available is not None:
                return self._person_detector_available
            try:
                from ultralytics import YOLO

                # The compact pretrained detector downloads its weights only on first use.
                self._person_detector = YOLO("yolo26n.pt")
                self._person_detector_available = True
            except ImportError:
                # Do not cache this state: dependencies can be installed while the
                # development server is running, and the next request should retry.
                return False
            except Exception:
                # Captioning continues if the optional count-verification model is unavailable.
                self._person_detector_available = False
            return self._person_detector_available

    def _count_people(self, image: Image.Image) -> int | None:
        """Return the detected visible-person count, or None when verification is unavailable."""
        if not self._ensure_person_detector_loaded() or self._person_detector is None:
            return None
        try:
            results = self._person_detector.predict(
                source=np.asarray(image),
                classes=[0],  # COCO class 0 is person.
                conf=0.35,
                imgsz=640,
                device=self.device,
                verbose=False,
            )
            boxes = results[0].boxes
            return 0 if boxes is None else len(boxes)
        except Exception:
            return None

    @staticmethod
    def _visual_signature(frame: object) -> object:
        """Create a compact colour signature used only for visual scene-change detection."""
        resized = cv2.resize(frame, (96, 54), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        histogram = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256])
        return cv2.normalize(histogram, histogram).flatten()

    @classmethod
    def sample_frames(cls, video_path: Path) -> list[SampledFrame]:
        """Select actual visual scene changes, with periodic coverage for long static shots.

        The video is scanned roughly every 0.75 seconds. A frame is retained when its
        compact colour signature differs materially from the prior retained frame, or
        when eight seconds have passed without a retained frame. This keeps narration
        tied to scene transitions rather than an arbitrary fixed number of frames.
        """
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise VideoProcessingError("This file could not be opened as a video.")

        try:
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            if frame_count <= 0 or fps <= 0:
                raise VideoProcessingError("The video does not contain readable frames.")

            scan_step = max(1, round(fps * SCENE_SCAN_INTERVAL_SECONDS))
            scan_indices = list(range(0, frame_count, scan_step))
            if scan_indices[-1] != frame_count - 1:
                scan_indices.append(frame_count - 1)

            candidates: list[tuple[SampledFrame, float]] = []
            previous_signature: object | None = None
            previous_timestamp = -MAX_SCENE_GAP_SECONDS
            for frame_index in scan_indices:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if not ok:
                    continue
                timestamp_seconds = frame_index / fps
                signature = cls._visual_signature(frame)
                change_score = (
                    1.0
                    if previous_signature is None
                    else float(cv2.compareHist(previous_signature, signature, cv2.HISTCMP_BHATTACHARYYA))
                )
                is_scene_change = change_score >= SCENE_CHANGE_THRESHOLD
                needs_periodic_coverage = timestamp_seconds - previous_timestamp >= MAX_SCENE_GAP_SECONDS
                if previous_signature is not None and not is_scene_change and not needs_periodic_coverage:
                    continue

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                candidates.append(
                    (
                        SampledFrame(
                        timestamp_seconds=round(frame_index / fps, 2),
                        image=Image.fromarray(rgb_frame),
                        ),
                        change_score,
                    )
                )
                previous_signature = signature
                previous_timestamp = timestamp_seconds

            if len(candidates) > MAX_ANALYSIS_FRAMES:
                # Preserve the opening scene and retain the strongest scene transitions.
                opening_frame = candidates[0]
                strongest_changes = sorted(
                    candidates[1:], key=lambda candidate: candidate[1], reverse=True
                )[: MAX_ANALYSIS_FRAMES - 1]
                candidates = [opening_frame, *strongest_changes]

            frames = [frame for frame, _ in sorted(candidates, key=lambda candidate: candidate[0].timestamp_seconds)]

            if not frames:
                raise VideoProcessingError("No frames could be read from this video.")
            return frames
        finally:
            capture.release()

    def _caption_image(self, image: Image.Image) -> str:
        self._ensure_model_loaded()
        assert self._model is not None and self._processor is not None

        inputs = self._processor(images=image, return_tensors="pt")
        inputs = {name: tensor.to(self.device) for name, tensor in inputs.items()}
        with torch.inference_mode():
            generated_ids = self._model.generate(
                **inputs,
                max_new_tokens=30,
                num_beams=3,
            )
        return self._processor.decode(generated_ids[0], skip_special_tokens=True).strip()

    @staticmethod
    def _apply_person_count(caption: str, person_count: int | None) -> str:
        """Correct singular BLIP wording when a detector visibly finds multiple people.

        The detector can count people but cannot safely infer their gender, so the
        narration deliberately says "people" rather than guessing "men" or "women".
        """
        if person_count is None or person_count < 2:
            return caption

        count_words = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
        people_phrase = f"{count_words[person_count]} people" if person_count in count_words else "several people"
        return re.sub(
            r"\b(?:a|one)\s+(?:man|woman|person|boy|girl)\b",
            people_phrase,
            caption,
            count=1,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _caption_tokens(caption: str) -> set[str]:
        """Return content words for comparing small variations of a BLIP caption."""
        ignored_words = {
            "a", "an", "the", "of", "on", "in", "at", "with", "and", "to", "is", "are",
            "there", "this", "that", "it", "for", "from",
        }
        return {
            word
            for word in re.findall(r"[a-z]+", caption.lower())
            if word not in ignored_words
        }

    @classmethod
    def _caption_similarity(cls, first: str, second: str) -> float:
        first_tokens = cls._caption_tokens(first)
        second_tokens = cls._caption_tokens(second)
        if not first_tokens or not second_tokens:
            return 0.0
        return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)

    @classmethod
    def _narration_tokens(cls, caption: str) -> set[str]:
        """Normalize wording differences that should not cause repeated narration."""
        person_words = {"man", "men", "woman", "women", "people", "person", "boy", "boys", "girl", "girls"}
        count_words = {"one", "two", "three", "four", "five", "six", "several", "group"}
        normalized: set[str] = set()
        for word in cls._caption_tokens(caption):
            if word in count_words:
                continue
            if word in person_words:
                normalized.add("person")
                continue
            if word in {"microphones", "lights"}:
                normalized.add(word.rstrip("s"))
                continue
            if word == "top":
                continue
            normalized.add(word)
        return normalized

    @classmethod
    def _narration_similarity(cls, first: str, second: str) -> float:
        first_tokens = cls._narration_tokens(first)
        second_tokens = cls._narration_tokens(second)
        if not first_tokens or not second_tokens:
            return 0.0
        return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)

    @staticmethod
    def _looks_like_end_card(caption: str) -> bool:
        """Exclude common credit/logo frames unless they are the whole video."""
        lower_caption = caption.lower()
        end_card_signals = (" logo", "text on", "title screen", "black background")
        return any(signal in lower_caption for signal in end_card_signals)

    @classmethod
    def _summarise_video(cls, frame_captions: list[tuple[float, str]]) -> tuple[str, list[str]]:
        """Pick the visual idea supported by the video, not a one-off intro/outro frame.

        BLIP captions every sampled frame independently. This lightweight temporal layer
        groups similar descriptions, prefers scenes seen through the middle of the
        video, and avoids likely logos/end cards when other visual content exists.
        """
        captions = [caption.strip() for _, caption in frame_captions if caption.strip()]
        if not captions:
            raise VideoProcessingError("The model could not generate a caption for this video.")

        non_end_card_indices = [
            index for index, caption in enumerate(captions) if not cls._looks_like_end_card(caption)
        ]
        candidate_indices = non_end_card_indices or list(range(len(captions)))

        best_index = candidate_indices[0]
        best_score = float("-inf")
        caption_count = len(captions)
        for index in candidate_indices:
            comparisons = [
                cls._caption_similarity(captions[index], captions[other_index])
                for other_index in candidate_indices
                if other_index != index
            ]
            consensus = sum(comparisons) / len(comparisons) if comparisons else 1.0
            position = index / max(caption_count - 1, 1)
            middle_preference = 1 - abs(position - 0.5) * 2
            score = consensus * 0.8 + middle_preference * 0.2
            if score > best_score:
                best_index, best_score = index, score

        representative = captions[best_index]
        main_scene_matches = [
            not cls._looks_like_end_card(caption)
            and cls._caption_similarity(representative, caption) >= 0.25
            for caption in captions
        ]
        main_scene_matches[best_index] = True

        summary_statuses = [
            "ignored" if cls._looks_like_end_card(frame_caption)
            else "main_scene" if is_main_scene
            else "additional_scene"
            for frame_caption, is_main_scene in zip(captions, main_scene_matches)
        ]

        meaningful_frame_count = sum(status != "ignored" for status in summary_statuses)
        main_scene_count = sum(status == "main_scene" for status in summary_statuses)
        is_montage = meaningful_frame_count >= 4 and main_scene_count / meaningful_frame_count < 0.65
        if is_montage:
            final_caption = (
                "A montage featuring several different scenes, including "
                f"{representative.rstrip('.')}"
            )
        else:
            final_caption = representative.rstrip(".")
        return final_caption[:1].upper() + final_caption[1:] + ".", summary_statuses

    @classmethod
    def _build_audio_descriptions(cls, frames: list[CaptionedFrame]) -> list[NarrationMoment]:
        """Narrate each meaningful detected scene using a direct, compact sentence.

        Scene detection has already filtered most repeated visuals. This final pass
        removes only near-identical consecutive captions; it must not discard different
        actions or locations just because they share the same person.
        """
        descriptions: list[NarrationMoment] = []
        narrated_captions: list[str] = []

        for frame in frames:
            if frame.summary_status == "ignored":
                continue
            repeats_a_narrated_scene = any(
                cls._narration_similarity(previous_caption, frame.caption)
                >= NARRATION_SIMILARITY_THRESHOLD
                for previous_caption in narrated_captions
            )
            if repeats_a_narrated_scene:
                continue
            descriptions.append(
                NarrationMoment(
                    timestamp_seconds=frame.timestamp_seconds,
                    description=cls._speakable_sentence(frame.caption),
                )
            )
            narrated_captions.append(frame.caption)
        return descriptions

    @staticmethod
    def _speakable_sentence(caption: str) -> str:
        """Make common singular/plural caption forms comfortable to hear aloud."""
        phrase = caption.strip().rstrip(".")
        singular_match = re.match(
            r"^(a|an)\s+(man|woman|person|boy|girl)\s+(.+)$", phrase, flags=re.IGNORECASE
        )
        plural_match = re.match(
            r"^((?:two|three|four|five|six|several)\s+people)\s+(.+)$",
            phrase,
            flags=re.IGNORECASE,
        )
        if singular_match:
            subject = f"{singular_match.group(1)} {singular_match.group(2)}"
            remainder = singular_match.group(3)
            verb = "" if re.match(r"^(is|was|has)\b", remainder, flags=re.IGNORECASE) else " is"
            return f"{subject[:1].upper() + subject[1:]}{verb} {remainder}."
        if plural_match:
            subject, remainder = plural_match.groups()
            verb = "" if re.match(r"^(are|were|have)\b", remainder, flags=re.IGNORECASE) else " are"
            return f"{subject[:1].upper() + subject[1:]}{verb} {remainder}."
        return phrase[:1].upper() + phrase[1:] + "."

    def caption_video(
        self, video_path: Path
    ) -> tuple[str, list[CaptionedFrame], list[NarrationMoment]]:
        frames = self.sample_frames(video_path)
        raw_frame_captions = []
        for frame in frames:
            raw_caption = self._caption_image(frame.image)
            verified_caption = self._apply_person_count(raw_caption, self._count_people(frame.image))
            raw_frame_captions.append((frame.timestamp_seconds, verified_caption))
        caption, summary_statuses = self._summarise_video(raw_frame_captions)
        frame_captions = [
            CaptionedFrame(
                timestamp_seconds=timestamp,
                caption=frame_caption,
                summary_status=summary_status,
            )
            for (timestamp, frame_caption), summary_status in zip(raw_frame_captions, summary_statuses)
        ]
        return caption, frame_captions, self._build_audio_descriptions(frame_captions)
