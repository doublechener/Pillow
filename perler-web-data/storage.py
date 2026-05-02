"""Supabase Storage 上传与签名 URL。

路径约定:<bucket>/<user_id>/<filename>
RLS 策略只允许写到自己 user_id 目录下,所以拼路径时一定要带 user_id 前缀。
"""
import uuid
from typing import Optional

from supabase_client import get_client, current_user_id

PATTERN_BUCKET = "patterns"
OCR_BUCKET = "ocr-uploads"


def _upload(bucket: str, data: bytes, suffix: str = "png",
            content_type: str = "image/png") -> Optional[str]:
	uid = current_user_id()
	if not uid:
		return None
	path = f"{uid}/{uuid.uuid4().hex}.{suffix}"
	get_client().storage.from_(bucket).upload(
		path, data,
		file_options={"content-type": content_type, "upsert": "false"},
	)
	return path


def upload_pattern(image_bytes: bytes) -> Optional[str]:
	return _upload(PATTERN_BUCKET, image_bytes)


def upload_legend(image_bytes: bytes) -> Optional[str]:
	return _upload(PATTERN_BUCKET, image_bytes)


def upload_ocr_source(image_bytes: bytes,
                       suffix: str = "png") -> Optional[str]:
	return _upload(OCR_BUCKET, image_bytes, suffix=suffix)


def delete_object(bucket: str, path: Optional[str]) -> None:
	"""从 Storage 删除单个文件。path 为空或删除失败都不抛异常(允许孤儿文件存在)。"""
	if not path:
		return
	try:
		get_client().storage.from_(bucket).remove([path])
	except Exception:
		pass


def delete_objects(bucket: str, paths: list[str]) -> None:
	"""批量删除 Storage 文件，失败不抛。"""
	paths = [p for p in paths if p]
	if not paths:
		return
	try:
		get_client().storage.from_(bucket).remove(paths)
	except Exception:
		pass


def signed_url(bucket: str, path: str, expires_in: int = 3600) -> str:
	res = get_client().storage.from_(bucket).create_signed_url(
		path, expires_in
	)
	return res.get("signedURL") or res.get("signed_url") or ""


def download_bytes(bucket: str, path: str) -> bytes:
	return get_client().storage.from_(bucket).download(path)