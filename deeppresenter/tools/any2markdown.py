import base64
import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path

from fastmcp import FastMCP
from markitdown import MarkItDown
from PIL import Image

from deeppresenter.utils.log import set_logger, warning
from deeppresenter.utils.mineru_api import parse_pdf_offline, parse_pdf_online

mcp = FastMCP(name="Any2Markdown")


def _file_hash(file_path: str) -> str:
    """Compute MD5 hash of a file for cache key."""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_cache_dir(output_folder: str) -> Path:
    """Return the cache directory for any2markdown results."""
    cache_dir = Path(output_folder).parent / ".cache" / "any2markdown"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _cache_lookup(cache_dir: Path, file_hash: str) -> dict | None:
    """Look up cached result by file hash."""
    cache_file = cache_dir / f"{file_hash}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            # Verify cached files still exist
            if Path(cached.get("markdown_file", "")).exists():
                return cached
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _cache_store(cache_dir: Path, file_hash: str, result: dict) -> None:
    """Store conversion result to cache."""
    cache_file = cache_dir / f"{file_hash}.json"
    try:
        cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


IMAGE_EXTENSIONS = [
    "bmp",
    "jpg",
    "jpeg",
    "pgm",
    "png",
    "ppm",
    "tif",
    "tiff",
    "webp",
]
MINERU_API_URL = os.getenv("MINERU_API_URL", None)
MINERU_API_KEY = os.getenv("MINERU_API_KEY", None)
_MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB
_WARN_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@mcp.tool()
async def convert_to_markdown(file_path: str, output_folder: str) -> dict:
    """Convert a file to markdown, it could accept pdf, docx, doc, etc.
    Args:
        file_path: The path of the file to be converted
        output_folder: The folder to save the converted markdown and images, should be empty or not exist

    Returns:
        The converted results, with file saved to the specified path
    """
    assert os.path.exists(file_path), f"Error: file {file_path} does not exist"

    # File size guard
    file_size = os.path.getsize(file_path)
    if file_size > _MAX_FILE_SIZE:
        return {
            "success": False,
            "error": f"文件过大（{file_size / 1024 / 1024:.1f}MB），超过 {_MAX_FILE_SIZE / 1024 / 1024:.0f}MB 限制。请压缩后重试。",
        }
    if file_size > _WARN_FILE_SIZE:
        warning(f"Large file ({file_size / 1024 / 1024:.1f}MB): {file_path}")

    # Check cache
    fhash = _file_hash(file_path)
    cache_dir = _get_cache_dir(output_folder)
    cached = _cache_lookup(cache_dir, fhash)
    if cached is not None:
        return cached

    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)
    assert len(list(output_path.iterdir())) == 0, (
        f"Output folder {output_folder} is not empty"
    )

    markdown_file = output_path / f"{Path(file_path).stem}.md"

    if file_path.lower().endswith(".pdf") and (MINERU_API_KEY or MINERU_API_URL):
        if MINERU_API_KEY:
            await parse_pdf_online(file_path, str(output_path), MINERU_API_KEY)
        elif MINERU_API_URL:
            await parse_pdf_offline(file_path, str(output_path), MINERU_API_URL)
        for f in output_path.glob("*"):
            if f.name.lower().endswith(".md"):
                os.rename(f, str(markdown_file))
            elif f.name.lower().endswith((".json", ".pdf")):
                os.remove(f)
        with open(str(markdown_file), encoding="utf-8") as f:
            markdown = f.read()
    else:
        conver_result = MarkItDown().convert_local(file_path, keep_data_uris=True)
        markdown = parse_base64_images(
            conver_result.text_content, output_path / "images"
        )

    for match in re.findall(r"!\[.*?\]\((.*?)\)", markdown):
        local_path = match.split()[0].strip("\"'")
        p = Path(local_path)
        if (output_path / local_path).exists():
            p = output_path / local_path
        if p.exists():
            markdown = markdown.replace(local_path, str(p.resolve()))
    with open(str(markdown_file), "w", encoding="utf-8") as f:
        f.write(markdown)

    images = output_path.glob("images/*")
    images_with_info = []
    for img_path in images:
        try:
            with Image.open(img_path) as img:
                images_with_info.append((img_path, *img.size))
        except Exception:
            continue

    images_with_info.sort(key=lambda x: int(x[1]), reverse=True)

    result = {
        "success": True,
        "markdown_file": str(markdown_file),
        "images": f"Found {len(images_with_info)} images\n"
        + "".join([f"- {img[0]}: {img[1]}x{img[2]}\n" for img in images_with_info]),
    }
    _cache_store(cache_dir, fhash, result)
    return result


def parse_base64_images(markdown: str, image_dir: Path) -> str:
    """Save base64 images to local, and convert those links to local paths"""
    image_dir.mkdir(exist_ok=True, parents=True)
    for image_match in re.finditer(
        r"!\[([^\]]*)\]\((data:image/([^;]+);base64,([^)]+))\)", markdown
    ):
        _, data_uri, image_format, base64_data = image_match.groups()

        if image_format.lower() not in IMAGE_EXTENSIONS:
            markdown = markdown.replace(image_match.group(0), "")
            warning(f"Unsupported image format: {image_format}, image will be ignored")
            continue

        image_data = base64.b64decode(base64_data)
        image_path = image_dir / (uuid.uuid4().hex[:4] + "." + image_format)

        with open(image_path, "wb") as f:
            f.write(image_data)

        # Replace data URI with relative path
        markdown = markdown.replace(data_uri, str(image_path))

    return markdown


if __name__ == "__main__":
    assert len(sys.argv) == 2, "Usage: python any2markdown.py <workspace>"
    work_dir = Path(sys.argv[1])
    assert work_dir.exists(), f"Workspace {work_dir} does not exist."
    os.chdir(work_dir)
    set_logger(
        f"any2markdown-{work_dir.stem}", work_dir / ".history" / "any2markdown.log"
    )

    mcp.run(show_banner=False)
