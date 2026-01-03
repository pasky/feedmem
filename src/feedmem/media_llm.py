"""LLM-based media description (OCR, image description)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

_llm: ModuleType | None = None
try:
    import llm as _llm_module

    _llm = _llm_module
except ImportError:
    pass

PROMPT = "Describe this image briefly; transcribe any important text precisely."
MODEL = "gpt-5-mini"
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0


async def describe_image(path: Path) -> str | None:
    """Describe an image using LLM. Returns None on failure."""
    if _llm is None:
        return None

    for attempt in range(MAX_RETRIES):
        try:
            model: Any = _llm.get_async_model(MODEL)
            response = await model.prompt(
                PROMPT,
                attachments=[_llm.Attachment(path=str(path))],
            )
            return await response.text()
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                print(f"media_llm: failed after {MAX_RETRIES} retries: {e}", file=sys.stderr)
                return None
            backoff = INITIAL_BACKOFF * (2**attempt)
            await asyncio.sleep(backoff)
    return None


def _extract_first_frame(video_path: Path) -> Path | None:
    """Extract first frame from video using ffmpeg. Returns temp file path."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            out_path = Path(f.name)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vframes",
                "1",
                "-q:v",
                "2",
                str(out_path),
            ],
            capture_output=True,
            check=True,
        )
        return out_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


async def describe_video(path: Path) -> str | None:
    """Describe video's first frame using LLM. Returns None on failure."""
    frame_path = await asyncio.to_thread(_extract_first_frame, path)
    if not frame_path:
        return None
    try:
        return await describe_image(frame_path)
    finally:
        frame_path.unlink(missing_ok=True)


async def describe_media(path: Path) -> str | None:
    """Describe media file (image or video). Returns None on failure."""
    suffix = path.suffix.lower()
    if suffix in (".mp4", ".mov", ".webm", ".avi"):
        return await describe_video(path)
    elif suffix in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        return await describe_image(path)
    return None
