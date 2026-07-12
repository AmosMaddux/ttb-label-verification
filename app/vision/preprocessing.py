"""Image preprocessing before vision extraction.

The vision model receives a normalized JPEG rather than the raw upload. This
keeps payload size bounded, applies EXIF orientation, and preserves enough
detail for label text extraction.
"""

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.vision.config import env_int


MAX_LONG_EDGE = env_int("MAX_LONG_EDGE", 1400)
JPEG_QUALITY = env_int("JPEG_QUALITY", 76)


class ImagePreprocessingError(ValueError):
    """Raised when uploaded bytes cannot be decoded as an image.

    Inputs:
        A message describing the preprocessing failure.

    Outputs:
        An exception handled by `VisionService`, which returns an empty
        extraction instead of crashing the request.
    """

    pass


@dataclass(frozen=True)
class PreparedImage:
    """Normalized image payload sent to the vision provider.

    Inputs:
        JPEG bytes, content type, and final pixel dimensions.

    Outputs:
        An immutable data object consumed by `VisionService`.
    """

    data: bytes
    content_type: str
    width: int
    height: int


def prepare_image(image_bytes: bytes) -> PreparedImage:
    """Decode, orient, resize, and JPEG-compress an uploaded image.

    Inputs:
        Raw uploaded image bytes in a supported format.

    Outputs:
        `PreparedImage` with JPEG bytes and dimensions. Raises
        `ImagePreprocessingError` when the input is not a readable image.
    """
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            corrected = ImageOps.exif_transpose(image)
            rgb = corrected.convert("RGB")
            resized = _resize_to_long_edge(rgb, MAX_LONG_EDGE)
            output = BytesIO()
            resized.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            data = output.getvalue()
            return PreparedImage(
                data=data,
                content_type="image/jpeg",
                width=resized.width,
                height=resized.height,
            )
    except (OSError, UnidentifiedImageError) as exc:
        raise ImagePreprocessingError("Input could not be processed as an image.") from exc


def _resize_to_long_edge(image: Image.Image, max_long_edge: int) -> Image.Image:
    """Resize an image so its longest edge does not exceed a limit.

    Inputs:
        A Pillow image and the maximum allowed long-edge pixel count.

    Outputs:
        A copied image when no resizing is needed, or a resized image preserving
        the original aspect ratio.
    """
    long_edge = max(image.size)
    if long_edge <= max_long_edge:
        return image.copy()

    scale = max_long_edge / long_edge
    size = (round(image.width * scale), round(image.height * scale))
    return image.resize(size, Image.Resampling.LANCZOS)
