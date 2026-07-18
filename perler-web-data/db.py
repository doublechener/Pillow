"""所有数据访问都走 Supabase Postgres。

RLS 已强制 user_id = auth.uid(),所以这里的查询都不需要手动加
user_id 过滤(insert 时仍然要写 user_id,因为 PG 不会自己填)。
"""
from datetime import datetime
from typing import Dict, List, Optional

from palette import MARD_PALETTE
from supabase_client import get_client, current_user_id
import storage

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


def load_used_totals() -> Dict[str, int]:
	"""返回每个色号累计实际消耗的豆子数。"""
	rows = (
		get_client()
		.table("inventory")
		.select("code, used_total")
		.execute()
	).data or []
	return {r["code"]: int(r.get("used_total") or 0) for r in rows}


def add_used_totals(used: Dict[str, int]) -> None:
	"""把本次实际扣掉的颗数累加到 used_total。"""
	used = {c: max(0, int(n)) for c, n in used.items() if int(n) > 0}
	if not used:
		return
	uid = current_user_id()
	cli = get_client()
	current = load_used_totals()
	payload = [{
		"user_id": uid,
		"code": c,
		"used_total": int(current.get(c, 0)) + n,
		"updated_at": datetime.utcnow().isoformat(),
	} for c, n in used.items()]
	cli.table("inventory").upsert(
		payload, on_conflict="user_id,code"
	).execute()


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
# 库存预警阈值（默认 + 单色覆盖，持久化到 Supabase）
# ============================================================
DEFAULT_LOW = 200
DEFAULT_MID = 500


def load_thresholds() -> Dict[str, tuple]:
	"""返回 {'': (default_low, default_mid), 'A5': (l, m), ...}。

	未设置过任何阈值时返回 {'': (200, 500)}（带兜底默认）。
	"""
	rows = (
		get_client()
		.table("warning_thresholds")
		.select("code, low, mid")
		.execute()
	).data or []
	result: Dict[str, tuple] = {}
	for r in rows:
		code = r.get("code") or ""
		result[code] = (int(r["low"]), int(r["mid"]))
	if "" not in result:
		result[""] = (DEFAULT_LOW, DEFAULT_MID)
	return result


def save_threshold(code: str, low: int, mid: int) -> None:
	"""upsert 一条阈值。code='' 代表全局默认；否则为具体色号覆盖。"""
	uid = current_user_id()
	if not uid:
		return
	if int(low) >= int(mid):
		raise ValueError("low must be less than mid")
	get_client().table("warning_thresholds").upsert({
		"user_id": uid,
		"code": code,
		"low": int(low),
		"mid": int(mid),
		"updated_at": datetime.utcnow().isoformat(),
	}, on_conflict="user_id,code").execute()


def delete_threshold(code: str) -> None:
	"""删除一条单色覆盖；不允许删全局默认（code='' 会被忽略）。"""
	if not code:
		return
	uid = current_user_id()
	if not uid:
		return
	(get_client().table("warning_thresholds")
		.delete()
		.eq("user_id", uid)
		.eq("code", code)
		.execute())


def threshold_for(code: str, thresholds: Dict[str, tuple]) -> tuple:
	"""取一个色号的有效阈值：先看单色覆盖，否则用全局默认。"""
	return thresholds.get(code) or thresholds.get(
		"", (DEFAULT_LOW, DEFAULT_MID))


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
	"""删除一张图纸，同时清理云端图纸 + 图例 PNG。"""
	cli = get_client()
	res = cli.table("patterns").select(
		"image_path, legend_path"
	).eq("id", pattern_id).execute()
	if res.data:
		row = res.data[0]
		storage.delete_object(storage.PATTERN_BUCKET, row.get("image_path"))
		storage.delete_object(storage.PATTERN_BUCKET, row.get("legend_path"))
	cli.table("patterns").delete().eq("id", pattern_id).execute()


def delete_all_patterns() -> int:
	"""清空当前用户的所有图纸 + 云端图片。返回删除的行数。"""
	uid = current_user_id()
	cli = get_client()
	rows = (cli.table("patterns").select("image_path, legend_path")
		.eq("user_id", uid).execute()).data or []
	paths: List[str] = []
	for r in rows:
		if r.get("image_path"): paths.append(r["image_path"])
		if r.get("legend_path"): paths.append(r["legend_path"])
	storage.delete_objects(storage.PATTERN_BUCKET, paths)
	cli.table("patterns").delete().eq("user_id", uid).execute()
	return len(rows)


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


def update_ocr_parsed(ocr_id: str, parsed: Dict[str, int]) -> None:
	"""更新一条 OCR 历史的 parsed 字段(供识别结果增删改实时落库)。

	同步刷新 total_beads / color_count，保证「历史记录」tab 显示一致。
	"""
	get_client().table("ocr_history").update({
		"parsed": parsed,
		"total_beads": int(sum(parsed.values())),
		"color_count": len(parsed),
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
	"""删除一条 OCR 历史，同时清理云端原图。"""
	cli = get_client()
	res = cli.table("ocr_history").select("source_path").eq("id", ocr_id).execute()
	if res.data:
		storage.delete_object(storage.OCR_BUCKET, res.data[0].get("source_path"))
	cli.table("ocr_history").delete().eq("id", ocr_id).execute()


def delete_all_ocr() -> int:
	"""清空当前用户的所有 OCR 历史 + 云端原图。返回删除的行数。"""
	uid = current_user_id()
	cli = get_client()
	rows = (cli.table("ocr_history").select("source_path")
		.eq("user_id", uid).execute()).data or []
	paths = [r["source_path"] for r in rows if r.get("source_path")]
	storage.delete_objects(storage.OCR_BUCKET, paths)
	cli.table("ocr_history").delete().eq("user_id", uid).execute()
	return len(rows)


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


def delete_all_shortages() -> int:
	"""清空当前用户的所有补货清单。返回删除的行数。"""
	uid = current_user_id()
	cli = get_client()
	res = (cli.table("shortage_lists").select("id", count="exact")
		.eq("user_id", uid).execute())
	n = res.count or 0
	cli.table("shortage_lists").delete().eq("user_id", uid).execute()
	return n


# ============================================================
# 库存历史 + 一键撤回(增量入库 / 手改 / OCR 扣减 / CSV 导入 全部入流水)
# ============================================================
SOURCE_LABELS = {
	"restock":     "📥 增量入库",
	"manual_edit": "✏️ 手动编辑",
	"ocr_deduct":  "🔍 OCR 扣减",
	"csv_import":  "📤 CSV 导入",
	"undo":        "↩️ 撤回操作",
}


def _diff_inventory(before: Dict[str, int],
                    after: Dict[str, int]) -> List[dict]:
	"""计算 before → after 的差分列表,仅保留 delta != 0 的色号。"""
	codes = set(before) | set(after)
	changes = []
	for c in sorted(codes):
		b = int(before.get(c, 0))
		a = int(after.get(c, 0))
		if a != b:
			changes.append({"code": c, "before": b, "after": a, "delta": a - b})
	return changes


def record_inventory_change(
	source: str,
	changes: List[dict],
	note: Optional[str] = None,
	ref_id: Optional[str] = None,
) -> Optional[str]:
	"""写一条 inventory_history。changes 为空则不写。"""
	if not changes:
		return None
	uid = current_user_id()
	if not uid:
		return None
	res = get_client().table("inventory_history").insert({
		"user_id": uid, "source": source, "ref_id": ref_id,
		"changes": changes, "note": note,
	}).execute()
	return res.data[0]["id"]


def apply_inventory_delta(
	deltas: Dict[str, int],
	source: str,
	note: Optional[str] = None,
	ref_id: Optional[str] = None,
) -> Optional[str]:
	"""对若干色号做增量变更(正为加,负为减),库存不会被减到 0 以下,
	并写一条历史记录,返回 history id。"""
	deltas = {c: int(d) for c, d in deltas.items()
	          if c in MARD_PALETTE and int(d) != 0}
	if not deltas:
		return None
	inv = load_inventory()
	before = {c: int(inv.get(c, 0)) for c in deltas}
	after = {c: max(0, before[c] + d) for c, d in deltas.items()}
	save_inventory(after)
	# 只有实际消耗才累计“已用总数”；库存不足时按真正扣掉的数量计。
	if source == "ocr_deduct":
		db_used = {c: before[c] - after[c] for c in after if after[c] < before[c]}
		add_used_totals(db_used)
	return record_inventory_change(
		source, _diff_inventory(before, after),
		note=note, ref_id=ref_id)


def apply_inventory_absolute(
	targets: Dict[str, int],
	source: str,
	note: Optional[str] = None,
	ref_id: Optional[str] = None,
	replace_all_mode: bool = False,
) -> Optional[str]:
	"""把若干色号库存设为绝对值,并写一条历史。

	- replace_all_mode=False(默认):upsert 增量,只动 targets 里的色号
	- replace_all_mode=True:整库覆盖(CSV 导入),先 delete-all 再写
	"""
	if not targets:
		return None
	inv = load_inventory()
	if replace_all_mode:
		replace_all(targets)
		before = inv
		after = targets
	else:
		targets = {c: max(0, int(q)) for c, q in targets.items()
		           if c in MARD_PALETTE}
		save_inventory(targets)
		before = {c: int(inv.get(c, 0)) for c in targets}
		after = targets
	return record_inventory_change(
		source, _diff_inventory(before, after),
		note=note, ref_id=ref_id)


def list_inventory_history(limit: int = 200) -> List[dict]:
	return (
		get_client()
		.table("inventory_history")
		.select("*")
		.order("created_at", desc=True)
		.limit(limit)
		.execute()
	).data or []


def undo_inventory_change(history_id: str) -> Optional[str]:
	"""撤回一条历史:把 changes 里每个色号回滚到 before。

	幂等:若该条已被撤回过,直接返回 None;否则写一条 source='undo'
	的新历史,并把原记录标记为 reverted=True。'undo' 类型的记录自身
	不支持再次撤回。"""
	cli = get_client()
	res = cli.table("inventory_history").select("*").eq(
		"id", history_id).execute()
	if not res.data:
		return None
	row = res.data[0]
	if row.get("reverted") or row.get("source") == "undo":
		return None
	rollback: Dict[str, int] = {
		ch["code"]: int(ch["before"])
		for ch in (row.get("changes") or [])
	}
	if not rollback:
		return None
	inv = load_inventory()
	before = {c: int(inv.get(c, 0)) for c in rollback}
	save_inventory(rollback)
	new_id = record_inventory_change(
		source="undo",
		changes=_diff_inventory(before, rollback),
		note=f"撤回 {SOURCE_LABELS.get(row['source'], row['source'])}",
		ref_id=row["id"])
	cli.table("inventory_history").update({
		"reverted": True,
		"reverted_at": datetime.utcnow().isoformat(),
		"reverted_by_id": new_id,
	}).eq("id", history_id).execute()
	return new_id


def delete_all_inventory_history() -> int:
	"""清空当前用户的全部库存变更历史。返回删除的行数。"""
	uid = current_user_id()
	if not uid:
		return 0
	cli = get_client()
	cnt = (cli.table("inventory_history")
	       .select("id", count="exact")
	       .eq("user_id", uid).execute()).count or 0
	cli.table("inventory_history").delete().eq("user_id", uid).execute()
	return cnt