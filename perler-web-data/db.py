"""所有数据访问都走 Supabase Postgres。

RLS 已强制 user_id = auth.uid(),所以这里的查询都不需要手动加
user_id 过滤(insert 时仍然要写 user_id,因为 PG 不会自己填)。
"""
from datetime import datetime
from typing import Dict, List, Optional

from palette import MARD_PALETTE
from supabase_client import get_client, current_user_id

ALL_CODES = list(MARD_PALETTE.keys())


# ============================================================
# 库存
# ============================================================
def ensure_inventory_seeded() -> None:
	"""首次登录时把 221 个色号灌进去(全 0)。

	用 upsert + ignoreDuplicates,即使 SQL 触发器、之前的 ensure 调用
	已经灌过,这里也是幂等的。
	"""
	uid = current_user_id()
	if not uid:
		return
	cli = get_client()
	existing = cli.table("inventory").select("code", count="exact").execute()
	if (existing.count or 0) >= len(ALL_CODES):
		return
	payload = [
		{"user_id": uid, "code": c, "quantity": 0}
		for c in ALL_CODES
	]
	cli.table("inventory").upsert(
		payload,
		on_conflict="user_id,code",
		ignore_duplicates=True,
	).execute()


def load_inventory() -> Dict[str, int]:
	rows = (
		get_client()
		.table("inventory")
		.select("code, quantity")
		.execute()
	).data or []
	return {r["code"]: int(r["quantity"]) for r in rows}


def save_inventory(updates: Dict[str, int]) -> None:
	if not updates:
		return
	uid = current_user_id()
	now = datetime.utcnow().isoformat()
	payload = [
		{"user_id": uid, "code": c,
		 "quantity": max(0, int(q)),
		 "updated_at": now}
		for c, q in updates.items()
	]
	get_client().table("inventory").upsert(
		payload, on_conflict="user_id,code"
	).execute()


def replace_all(inventory: Dict[str, int]) -> None:
	cli = get_client()
	uid = current_user_id()
	cli.table("inventory").delete().eq("user_id", uid).execute()
	save_inventory(inventory)


def last_updated() -> Optional[str]:
	rows = (
		get_client()
		.table("inventory")
		.select("updated_at")
		.order("updated_at", desc=True)
		.limit(1)
		.execute()
	).data or []
	return rows[0]["updated_at"] if rows else None


# ============================================================
# 图纸历史
# ============================================================
def insert_pattern(
	name: str,
	width_beads: int,
	height_beads: int,
	bead_usage: Dict[str, int],
	params: dict,
	image_path: Optional[str] = None,
	legend_path: Optional[str] = None,
) -> str:
	uid = current_user_id()
	res = get_client().table("patterns").insert({
		"user_id": uid,
		"name": name,
		"width_beads": int(width_beads),
		"height_beads": int(height_beads),
		"total_beads": int(sum(bead_usage.values())),
		"color_count": len(bead_usage),
		"image_path": image_path,
		"legend_path": legend_path,
		"params": params,
		"bead_usage": bead_usage,
	}).execute()
	return res.data[0]["id"]


def list_patterns(limit: int = 50) -> List[dict]:
	return (
		get_client()
		.table("patterns")
		.select("*")
		.order("created_at", desc=True)
		.limit(limit)
		.execute()
	).data or []


def delete_pattern(pattern_id: str) -> None:
	get_client().table("patterns").delete().eq("id", pattern_id).execute()


# ============================================================
# OCR 历史
# ============================================================
def insert_ocr_record(
	parsed: Dict[str, int],
	unknown_codes: List[tuple],
	source_path: Optional[str] = None,
	note: Optional[str] = None,
) -> str:
	uid = current_user_id()
	res = get_client().table("ocr_history").insert({
		"user_id": uid,
		"source_path": source_path,
		"parsed": parsed,
		"unknown_codes": [
			{"code": c, "count": n} for c, n in unknown_codes
		],
		"note": note,
		"total_beads": int(sum(parsed.values())),
		"color_count": len(parsed),
	}).execute()
	return res.data[0]["id"]


def mark_ocr_deducted(ocr_id: str) -> None:
	get_client().table("ocr_history").update({
		"deducted": True,
		"deducted_at": datetime.utcnow().isoformat(),
	}).eq("id", ocr_id).execute()


def list_ocr_history(limit: int = 50) -> List[dict]:
	return (
		get_client()
		.table("ocr_history")
		.select("*")
		.order("created_at", desc=True)
		.limit(limit)
		.execute()
	).data or []


def delete_ocr_record(ocr_id: str) -> None:
	get_client().table("ocr_history").delete().eq("id", ocr_id).execute()


# ============================================================
# 补货清单
# ============================================================
def insert_shortage(
	source: str,
	items: List[dict],
	ref_id: Optional[str] = None,
) -> Optional[str]:
	"""items: [{'code','need','stock','short'}, ...] - 只传 short>0 的项。"""
	if not items:
		return None
	uid = current_user_id()
	res = get_client().table("shortage_lists").insert({
		"user_id": uid,
		"source": source,
		"ref_id": ref_id,
		"items": items,
		"total_shortage": sum(int(i["short"]) for i in items),
	}).execute()
	return res.data[0]["id"]


def list_shortages(limit: int = 50) -> List[dict]:
	return (
		get_client()
		.table("shortage_lists")
		.select("*")
		.order("created_at", desc=True)
		.limit(limit)
		.execute()
	).data or []


def delete_shortage(short_id: str) -> None:
	get_client().table("shortage_lists").delete().eq("id", short_id).execute()