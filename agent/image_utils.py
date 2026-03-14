import base64
import mimetypes
from pathlib import Path

from utils.pptx_image_utils import convert_pptx_first_page_to_png


def image_data_url(image_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(image_path.name)
    if not mime_type:
        mime_type = "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def ensure_image_exists(
    image_path: Path,
    *,
    auto_render_image: bool = True,
    render_dpi: int = 200,
    render_backend: str = "auto",
    poppler_path: str | None = None,
) -> Path:
    path = image_path.resolve()
    if path.exists():
        return path
    if not auto_render_image:
        raise FileNotFoundError(f"Image not found: {path}")

    pptx_path = path.with_suffix(".pptx")
    if not pptx_path.exists():
        raise FileNotFoundError(
            f"Image missing and source PPTX not found for auto render: {path} / {pptx_path}"
        )

    convert_pptx_first_page_to_png(
        pptx_path=pptx_path,
        output_png=path,
        dpi=render_dpi,
        backend=render_backend,
        poppler_path=poppler_path,
    )
    if not path.exists():
        raise RuntimeError(f"Auto rendered image not found: {path}")
    return path
