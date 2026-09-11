"""Bound image allocations before decoding or constructing a pattern."""
import io
import warnings

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_INPUT_PIXELS = 20_000_000
MAX_WORKING_SIDE = 3200
MAX_CANVAS_PIXELS = 16_000_000


def load_image(data):
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("图片超过 20 MB，请压缩后上传。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.width * source.height > MAX_INPUT_PIXELS:
                    raise ValueError("图片超过 2000 万像素，请裁剪或缩小后上传。")
                source.thumbnail((MAX_WORKING_SIDE, MAX_WORKING_SIDE))
                oriented = ImageOps.exif_transpose(source)
                rgba = oriented.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                return Image.alpha_composite(background, rgba).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("图片损坏、格式不支持或尺寸过大，请重新导出后上传。") from exc


def validate_pattern(width, height, cell_size, palette):
    if not palette:
        raise ValueError("没有可用颜色，请补充库存或关闭“仅使用有库存的颜色”。")
    if not (1 <= width <= 300 and 1 <= height <= 300):
        raise ValueError("图纸横纵豆数需在 1–300 之间；长图请先裁剪或关闭自动高度。")
    if width * height * cell_size * cell_size > MAX_CANVAS_PIXELS:
        raise ValueError("输出图纸超过 1600 万像素，请减小格子像素或豆数。")


def nearest_colors(pixels, palette_rgb, batch_size=1024):
    """Same weighted squared distance, with bounded temporary arrays."""
    flat = np.asarray(pixels, dtype=np.int32).reshape(-1, 3)
    palette_rgb = np.asarray(palette_rgb, dtype=np.int32)
    result = np.empty(len(flat), dtype=np.int32)
    weights = np.array([0.3, 0.59, 0.11], dtype=np.float32)
    for start in range(0, len(flat), batch_size):
        diff = flat[start:start + batch_size, None, :] - palette_rgb[None, :, :]
        distance = (diff * diff).astype(np.float32) @ weights
        result[start:start + batch_size] = distance.argmin(axis=1)
    return result
