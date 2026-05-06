import base64
import io
import os
from collections import Counter
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

from palette import MARD_PALETTE
from theme import (inject_global_css, render_hero,
                   render_idle_pixel, mascot_html)
import auth
import db
import storage
from storage import PATTERN_BUCKET, OCR_BUCKET

APP_NAME = "豆映工坊"
APP_TAGLINE = "像素映豆 · 库存随手 · 灵感成图"

st.set_page_config(page_title=APP_NAME, page_icon="🧶", layout="wide")
inject_global_css()

# ============================================================
# 登录门
# ============================================================
session = auth.require_login()
db.ensure_inventory_seeded()

# ============================================================
# 顶栏
# ============================================================
top_l, top_r = st.columns([5, 1])
with top_l:
	render_hero(APP_NAME,
	            f"👤 {session['email']} · {APP_TAGLINE} ✨",
	            mascot_size=72)
with top_r:
	st.write("")
	if st.button("🚪 登出", width="stretch"):
		auth.sign_out()
		st.rerun()


# ============================================================
# 核心算法(纯函数,与旧版一致)
# ============================================================
def image_to_perler(img, width_beads, height_beads,
                    palette, cell_size, show_grid, show_codes=False):
	img = img.convert("RGBA")
	bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
	img = Image.alpha_composite(bg, img).convert("RGB")
	if height_beads is None:
		ow, oh = img.size
		height_beads = int(round(width_beads * oh / ow))
	img_small = img.resize((width_beads, height_beads), Image.Resampling.LANCZOS)
	pixels = np.array(img_small, dtype=np.int32)

	names = list(palette.keys())
	prgb = np.array([palette[n] for n in names], dtype=np.int32)
	weights = np.array([0.3, 0.59, 0.11], dtype=np.float32)
	flat = pixels.reshape(-1, 3)
	diff = flat[:, None, :] - prgb[None, :, :]
	dist = (diff * diff).astype(np.float32) @ weights
	nearest = dist.argmin(axis=1).reshape(height_beads, width_beads)

	counter = Counter()
	rgb_grid = [[None] * width_beads for _ in range(height_beads)]
	for y in range(height_beads):
		for x in range(width_beads):
			idx = int(nearest[y, x])
			rgb_grid[y][x] = tuple(int(v) for v in prgb[idx])
			counter[names[idx]] += 1

	canvas = Image.new("RGB",
		(width_beads * cell_size, height_beads * cell_size), (255, 255, 255))
	draw = ImageDraw.Draw(canvas)
	for y in range(height_beads):
		for x in range(width_beads):
			x0, y0 = x * cell_size, y * cell_size
			draw.rectangle([x0, y0, x0+cell_size, y0+cell_size], fill=rgb_grid[y][x])
	if show_grid:
		for x in range(width_beads + 1):
			draw.line([(x*cell_size,0),(x*cell_size,height_beads*cell_size)],
			          fill=(220,220,220), width=1)
		for y in range(height_beads + 1):
			draw.line([(0,y*cell_size),(width_beads*cell_size,y*cell_size)],
			          fill=(220,220,220), width=1)
	if show_codes and cell_size >= 12:
		font = _load_font(max(7, int(cell_size * 0.42)))
		for y in range(height_beads):
			for x in range(width_beads):
				name = names[int(nearest[y, x])]
				r, g, b = rgb_grid[y][x]
				lum = 0.299*r + 0.587*g + 0.114*b
				color = (0,0,0) if lum > 140 else (255,255,255)
				bb = draw.textbbox((0,0), name, font=font)
				tw, th = bb[2]-bb[0], bb[3]-bb[1]
				x0, y0 = x*cell_size, y*cell_size
				draw.text((x0+(cell_size-tw)//2-bb[0],
				           y0+(cell_size-th)//2-bb[1]), name, fill=color, font=font)
	return canvas, counter


def _load_font(size=16):
	for p in ["C:/Windows/Fonts/msyh.ttc",
	          "/System/Library/Fonts/PingFang.ttc",
	          "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
	          "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"]:
		if os.path.exists(p):
			return ImageFont.truetype(p, size)
	return ImageFont.load_default()


def generate_legend(counter, palette, inventory, cell_size=30):
	items = counter.most_common()
	row_h = cell_size + 10
	img = Image.new("RGB", (520, row_h*len(items)+60), (255,255,255))
	draw = ImageDraw.Draw(img)
	font = _load_font(16)
	draw.text((20, 10), "MARD 拼豆用量图例", fill=(30,30,30), font=font)
	y = 40
	for name, count in items:
		color = palette.get(name, (200,200,200))
		draw.rectangle([20, y, 20+cell_size, y+cell_size],
		               fill=color, outline=(100,100,100))
		if inventory is not None:
			stock = inventory.get(name, 0)
			tag = "✅" if stock >= count else f"❌ 缺{count-stock}"
			text = f"{name}  —  需{count}颗  库存{stock}  {tag}"
		else:
			text = f"{name}  —  {count} 颗"
		draw.text((20+cell_size+15, y+5), text, fill=(30,30,30), font=font)
		y += row_h
	return img


def pil_to_bytes(img):
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return buf.getvalue()


def _swatch(rgb, size=32):
	img = Image.new("RGB", (size,size), tuple(rgb))
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


# ============================================================
# 库存自动保存回调(色板模式 / 表格模式各一个)
# ============================================================
def _autosave_palette(code: str, original: int) -> None:
	"""色板模式:某个色号被改 → 立刻 upsert 到云端。"""
	new_val = int(st.session_state.get(f"pal_{code}", original))
	if new_val == original:
		return
	try:
		db.save_inventory({code: new_val})
		st.toast(f"💾 {code}: {original} → {new_val}", icon="✅")
	except Exception as e:
		st.toast(f"❌ {code} 保存失败: {e}", icon="⚠️")


def _autosave_table(original_inv: dict) -> None:
	"""表格模式:data_editor 任何「库存」变更 → 把 diff upsert 到云端。"""
	state = st.session_state.get("inv_editor", {})
	edited = state.get("edited_rows", {}) if isinstance(state, dict) else {}
	code_list = st.session_state.get("inv_editor_codes", [])
	if not edited or not code_list:
		return
	updates: dict[str, int] = {}
	for row_idx, changes in edited.items():
		if "库存" not in changes:
			continue
		try:
			ridx = int(row_idx)
		except (TypeError, ValueError):
			continue
		if ridx >= len(code_list):
			continue
		code = code_list[ridx]
		new_val = max(0, int(changes["库存"] or 0))
		if new_val != int(original_inv.get(code, 0)):
			updates[code] = new_val
	if updates:
		try:
			db.save_inventory(updates)
			st.toast(f"💾 已保存 {len(updates)} 个色号修改", icon="✅")
		except Exception as e:
			st.toast(f"❌ 保存失败: {e}", icon="⚠️")


def _save_ocr_edits(key: str) -> None:
	"""OCR 识别结果可编辑表的实时保存回调。

	支持增 / 删 / 改：
	- 编辑「色号」或「需要」→ state.edited_rows
	- 表格底部 ➕ 添加新行 → state.added_rows
	- 勾选行末复选框删除 → state.deleted_rows（行索引列表）

	重建 parsed dict 后写回 session_state['ocr_parsed'] +
	ocr_history.parsed，同时把 editor 版本号 +1，下一次重渲染
	会拿到全新、状态干净的 editor。
	"""
	state = st.session_state.get(key, {})
	if not isinstance(state, dict):
		return
	edited = state.get("edited_rows") or {}
	added = state.get("added_rows") or []
	deleted = set(state.get("deleted_rows") or [])

	# 当前展示顺序按色号顺序（A1→A2→...→B1→...→M15，与渲染逻辑一致），
	# 回调里也按这个顺序重建，保证 row_idx 对得上
	def _code_key(c: str) -> tuple[int, int]:
		_series_order = {s: i for i, s in enumerate("ABCDEFGHM")}
		return (_series_order.get(c[0], 99),
		        int(c[1:]) if c[1:].isdigit() else 0)
	base = sorted((st.session_state.get("ocr_parsed") or {}).items(),
	              key=lambda x: _code_key(x[0]))
	new_parsed: dict[str, int] = {}

	for i, (code, count) in enumerate(base):
		if i in deleted:
			continue
		ch = edited.get(i, {}) if isinstance(edited, dict) else {}
		new_code = str(ch.get("色号") or code).upper().strip()
		try:
			new_count = int(ch.get("需要", count) or 0)
		except (TypeError, ValueError):
			new_count = 0
		if new_count > 0 and new_code in MARD_PALETTE:
			new_parsed[new_code] = new_parsed.get(new_code, 0) + new_count

	for row in added:
		if not isinstance(row, dict):
			continue
		code = str(row.get("色号") or "").upper().strip()
		try:
			cnt = int(row.get("需要") or 0)
		except (TypeError, ValueError):
			cnt = 0
		if cnt > 0 and code in MARD_PALETTE:
			new_parsed[code] = new_parsed.get(code, 0) + cnt

	st.session_state["ocr_parsed"] = new_parsed
	st.session_state["ocr_editor_ver"] = (
		int(st.session_state.get("ocr_editor_ver", 0)) + 1)

	ocr_id = st.session_state.get("ocr_id")
	if ocr_id:
		try:
			db.update_ocr_parsed(ocr_id, new_parsed)
			st.toast(
				f"💾 已保存（{len(new_parsed)} 色 · "
				f"{sum(new_parsed.values()):,} 颗）", icon="✅")
		except Exception as e:
			st.toast(f"❌ 保存失败：{e}", icon="⚠️")


def _ocr_palette_change(code: str) -> None:
	"""色板模式中某个色号的「需要」颗数改了 → 立刻入 parsed + 入库。

	- 颗数被调为 0 同于删除该色号
	- 同时递增全局 ocr_editor_ver，表格模式 / 色板模式的
	  data_editor / number_input 都会重载拿到最新值
	"""
	cur_ver = int(st.session_state.get("ocr_editor_ver", 0))
	new_val = max(0, int(st.session_state.get(
		f"ocr_pal_v{cur_ver}_{code}", 0) or 0))
	parsed = dict(st.session_state.get("ocr_parsed") or {})
	if new_val == 0:
		parsed.pop(code, None)
	else:
		parsed[code] = new_val
	st.session_state["ocr_parsed"] = parsed
	st.session_state["ocr_editor_ver"] = cur_ver + 1
	ocr_id = st.session_state.get("ocr_id")
	if ocr_id:
		try:
			db.update_ocr_parsed(ocr_id, parsed)
			if new_val == 0:
				st.toast(f"🗑️ 已删除 {code}", icon="✅")
			else:
				st.toast(f"💾 {code}：{new_val:,} 颗", icon="✅")
		except Exception as e:
			st.toast(f"❌ 保存失败：{e}", icon="⚠️")


def _ocr_palette_delete(code: str) -> None:
	"""色板模式删除按钮：从 parsed 移除该色号。"""
	parsed = dict(st.session_state.get("ocr_parsed") or {})
	parsed.pop(code, None)
	st.session_state["ocr_parsed"] = parsed
	st.session_state["ocr_editor_ver"] = (
		int(st.session_state.get("ocr_editor_ver", 0)) + 1)
	ocr_id = st.session_state.get("ocr_id")
	if ocr_id:
		try:
			db.update_ocr_parsed(ocr_id, parsed)
			st.toast(f"🗑️ 已删除 {code}", icon="✅")
		except Exception as e:
			st.toast(f"❌ 删除失败：{e}", icon="⚠️")


def _ocr_palette_add() -> None:
	"""色板模式新增按钮：把表单输入的色号 + 颗数加入 parsed。

	同色号重复添加则叠加，并不覆盖。
	"""
	code = str(st.session_state.get("ocr_pal_add_code") or "").upper().strip()
	try:
		cnt = int(st.session_state.get("ocr_pal_add_cnt") or 0)
	except (TypeError, ValueError):
		cnt = 0
	if cnt <= 0 or code not in MARD_PALETTE:
		st.toast("⚠️ 请选择有效色号并输入正数颗数", icon="⚠️")
		return
	parsed = dict(st.session_state.get("ocr_parsed") or {})
	parsed[code] = parsed.get(code, 0) + cnt
	st.session_state["ocr_parsed"] = parsed
	st.session_state["ocr_editor_ver"] = (
		int(st.session_state.get("ocr_editor_ver", 0)) + 1)
	ocr_id = st.session_state.get("ocr_id")
	if ocr_id:
		try:
			db.update_ocr_parsed(ocr_id, parsed)
			st.toast(f"➕ 已添加 {code} × {cnt}", icon="✅")
		except Exception as e:
			st.toast(f"❌ 添加失败：{e}", icon="⚠️")


SERIES_LABELS = {
	"A":"黄橙暖色","B":"绿色","C":"蓝青色","D":"紫蓝色",
	"E":"粉色","F":"红色","G":"棕肤色","H":"黑白灰","M":"莫兰迪",
}

PAGES = {
	"gen":       "🖼️ 生成图纸",
	"inv":       "📦 编辑库存",
	"recognize": "🔍 识别已有拼豆图",
	"history":   "📚 历史记录",
	"palette":   "🎨 色板",
}

# ============================================================
# 顶栏页面导航(横向 st.radio + CSS 胶囊样式,与底部历史 Tab 视觉一致)
# DOM 稳定可控:label > 圆点(已隐藏) + 文字,任意 Streamlit 版本都吃这套样式
# ============================================================
page = st.radio(
	"页面导航", list(PAGES.values()),
	horizontal=True, label_visibility="collapsed",
	key="nav_page")
st.divider()

with st.sidebar:
	st.markdown(
		f"<div style='display:flex;align-items:center;gap:10px;"
		f"margin-bottom:6px;'>{mascot_html(28)}"
		f"<span style='font-weight:800;font-size:18px;"
		f"background:linear-gradient(90deg,#FF6B9D,#6BB6FF);"
		f"-webkit-background-clip:text;-webkit-text-fill-color:transparent;'>"
		f"{APP_NAME}</span></div>",
		unsafe_allow_html=True)
	st.divider()

	if page == PAGES["gen"]:
		st.subheader("⚙️ 生成参数")
		width_beads = st.slider("横向豆数", 10, 120, 29, step=1)
		auto_height = st.checkbox("按比例自动计算高度", value=True)
		height_beads = None if auto_height else st.slider(
			"纵向豆数", 10, 120, 29, 1)
		cell_size = st.slider("格子像素", 8, 60, 22, step=2)
		show_grid = st.checkbox("显示网格", value=True)
		show_codes = st.checkbox("在格子里写色号(A5/H7…)", value=True)
		st.divider()
		st.subheader("📦 库存联动")
		check_inventory = st.checkbox("启用库存校验", value=True)
		only_in_stock = st.checkbox("仅使用有库存的颜色", value=False)
	elif page == PAGES["inv"]:
		render_idle_pixel("📦 库存编辑参数都在右侧页内\n双模式自由切换 ✿")
	elif page == PAGES["recognize"]:
		render_idle_pixel("🔍 识别参数随上传图片\n即时显示在右侧 ✿")
	elif page == PAGES["history"]:
		render_idle_pixel("📚 翻翻你创作过的拼豆\n灵感都在这里 ✿")
	elif page == PAGES["palette"]:
		render_idle_pixel("🎨 221 色任你浏览\n找色找灵感 ✿")

# ============================================================
# 页面分发
# ============================================================

# ---------- 生成图纸 ----------
if page == PAGES["gen"]:
	uploaded = st.file_uploader("上传图片",
		type=["png","jpg","jpeg","webp","bmp"])
	col_l, col_r = st.columns(2)
	if uploaded:
		src = Image.open(uploaded)
		with col_l:
			st.subheader("原图预览")
			st.image(src, width="stretch")
		name_input = st.text_input("图纸名称(用于历史记录)",
			value=uploaded.name.rsplit(".",1)[0])
		if st.button("🚀 生成拼豆图纸", type="primary", width="stretch"):
			inv = db.load_inventory() if check_inventory else None
			palette = MARD_PALETTE
			if only_in_stock and inv:
				palette = {k:v for k,v in palette.items() if inv.get(k,0) > 0}
				st.info(f"📦 仅使用有库存的颜色,共 {len(palette)} 种可用")
			with st.spinner("正在生成…"):
				pattern_img, counter = image_to_perler(src, width_beads,
					height_beads, palette, cell_size, show_grid, show_codes)
				legend_img = generate_legend(counter, MARD_PALETTE,
					inv if check_inventory else None)
			with col_r:
				st.subheader("拼豆图纸")
				st.image(pattern_img, width="stretch")
				st.download_button("⬇️ 下载图纸 PNG",
					pil_to_bytes(pattern_img), file_name="perler_pattern.png",
					mime="image/png", width="stretch")

			# 上传到 Storage + 入库
			with st.spinner("正在保存到云端…"):
				img_path = storage.upload_pattern(pil_to_bytes(pattern_img))
				legend_path = storage.upload_legend(pil_to_bytes(legend_img))
				actual_h = pattern_img.height // cell_size
				pattern_id = db.insert_pattern(
					name=name_input or "未命名",
					width_beads=width_beads,
					height_beads=actual_h,
					bead_usage=dict(counter),
					params={"cell_size": cell_size, "show_grid": show_grid,
					        "show_codes": show_codes,
					        "only_in_stock": only_in_stock},
					image_path=img_path, legend_path=legend_path,
				)
			st.success(f"✅ 已保存到云端(图纸 ID: {pattern_id[:8]})")

			st.divider()
			st.subheader("📊 用量统计")
			rows, shortage = [], 0
			inv_now = db.load_inventory() if check_inventory else {}
			shortage_items = []
			for name, count in counter.most_common():
				if check_inventory:
					stock = inv_now.get(name, 0)
					diff = stock - count
					status = "✅ 充足" if diff >= 0 else f"❌ 缺{-diff}"
					if diff < 0:
						shortage += 1
						shortage_items.append({"code": name, "need": count,
							"stock": stock, "short": -diff})
					rows.append({"色号":name,"需要":count,"库存":stock,"状态":status})
				else:
					rows.append({"色号":name,"需要":count,
					             "RGB":str(MARD_PALETTE.get(name,(0,0,0)))})
			df_use = pd.DataFrame(rows)
			c1, c2, c3 = st.columns(3)
			c1.metric("总豆数", sum(counter.values()))
			c2.metric("颜色种类", len(counter))
			if check_inventory:
				c3.metric("需补货色号", shortage,
					delta=None if shortage==0 else f"-{shortage}",
					delta_color="inverse")
			st.dataframe(df_use, width="stretch", hide_index=True)
			st.subheader("🏷️ 颜色图例")
			st.image(legend_img)
			st.download_button("⬇️ 下载图例 PNG",
				pil_to_bytes(legend_img), file_name="legend.png",
				mime="image/png")

			if check_inventory and shortage_items:
				total_short = sum(i["short"] for i in shortage_items)
				st.warning(f"🛒 共 **{shortage}** 种颜色需要补货 · 缺 "
				           f"**{total_short}** 颗,详细清单见下方")
				st.dataframe(pd.DataFrame(shortage_items),
					width="stretch", hide_index=True)
				st.download_button("⬇️ 导出补货清单 CSV",
					pd.DataFrame(shortage_items).to_csv(index=False)
						.encode("utf-8-sig"),
					file_name=f"shortage_{pattern_id[:8]}.csv",
					mime="text/csv")
	else:
		st.info("👈 在上方上传一张图片开始")

# ---------- 编辑库存 ----------
elif page == PAGES["inv"]:
	inv = db.load_inventory()
	last_ts = db.last_updated()
	thresholds = db.load_thresholds()  # {'': (lo, mi), 'A5': (lo, mi), ...}
	DEF_LOW, DEF_MID = thresholds.get("", (db.DEFAULT_LOW, db.DEFAULT_MID))

	def _thr_of(code: str) -> tuple:
		return thresholds.get(code) or (DEF_LOW, DEF_MID)

	def _tier(code: str, qty: int) -> str:
		lo, mi = _thr_of(code)
		if qty < lo: return "🔴 紧缺"
		if qty < mi: return "🟡 偏低"
		return "🟢 充足"

	with st.expander("⚙️ 预警区间设置（持久保存到云端）",
	                 expanded=False):
		t_def, t_per = st.tabs(["🌐 默认阈值（全局）", "🎯 单色阈值（覆盖默认）"])

		with t_def:
			dc1, dc2 = st.columns(2)
			low_in = dc1.number_input(
				"🔴 紧缺阈值（低于该值为红色）",
				min_value=1, step=10, value=int(DEF_LOW),
				key="warn_low_input",
				help="低于此颗数 ➜ 🔴 紧缺")
			mid_in = dc2.number_input(
				"🟢 充足阈值（≥ 该值为绿色）",
				min_value=2, step=10, value=int(DEF_MID),
				key="warn_mid_input",
				help="高于或等于此颗数 ➜ 🟢 充足；介于两者之间 ➜ 🟡 偏低")
			db1, db2 = st.columns([1, 4])
			if db1.button("💾 保存默认", type="primary",
			              width="stretch", key="save_def_thr"):
				if low_in >= mid_in:
					st.error("⚠️ 紧缺阈值必须 < 充足阈值")
				else:
					try:
						db.save_threshold("", int(low_in), int(mid_in))
						st.success(
							f"✅ 已保存：🔴 < {low_in} · "
							f"🟡 {low_in}–{mid_in - 1} · 🟢 ≥ {mid_in}")
						st.rerun()
					except Exception as e:
						st.error(f"保存失败：{e}")
			db2.caption(
				f"当前默认：🔴 < {DEF_LOW} · "
				f"🟡 {DEF_LOW}–{DEF_MID - 1} · 🟢 ≥ {DEF_MID}"
				" · 此设置持久保存到云端，所有设备共享")

		with t_per:
			st.caption("可以为指定色号设置不同的紧缺/充足阈值（例如热门色用更高的红线）。"
			           "未设置覆盖的色号会使用「默认阈值」。")
			overrides = sorted(
				[(c, l, m) for c, (l, m) in thresholds.items() if c])
			if overrides:
				ov_df = pd.DataFrame([{
					"色号": c,
					"🔴 紧缺 <": l,
					"🟡 偏低区间": f"{l}–{m - 1}",
					"🟢 充足 ≥": m,
				} for c, l, m in overrides])
				st.dataframe(ov_df, width="stretch", hide_index=True,
				             height=min(360, 40 + 35 * len(overrides)))
				drc1, drc2 = st.columns([3, 1])
				del_code = drc1.selectbox(
					"恢复某色号到默认",
					options=[""] + [c for c, _, _ in overrides],
					format_func=lambda x: "（请选择）" if not x else x,
					key="del_thr_code")
				drc2.write("")
				if drc2.button("🗑️ 移除覆盖", width="stretch",
				               key="del_thr_btn", disabled=not del_code):
					try:
						db.delete_threshold(del_code)
						st.success(f"✅ 已移除 {del_code} 的覆盖，恢复默认")
						st.rerun()
					except Exception as e:
						st.error(f"移除失败：{e}")
			else:
				st.info("还没有任何单色覆盖。在下方添加第一个 ✨")

			st.divider()
			st.markdown("**➕ 新增 / 修改单色阈值**")
			ac1, ac2, ac3, ac4 = st.columns([2, 1, 1, 1])
			new_code = ac1.selectbox("色号",
				list(MARD_PALETTE.keys()),
				key="new_thr_code")
			cur_lo, cur_mi = thresholds.get(new_code, (DEF_LOW, DEF_MID))
			new_low = ac2.number_input("🔴 紧缺 <",
				min_value=1, step=10, value=int(cur_lo),
				key=f"new_thr_low_{new_code}")
			new_mid = ac3.number_input("🟢 充足 ≥",
				min_value=2, step=10, value=int(cur_mi),
				key=f"new_thr_mid_{new_code}")
			ac4.write("")
			ac4.write("")
			if ac4.button("💾 保存", type="primary",
			              width="stretch", key="save_thr_btn"):
				if new_low >= new_mid:
					st.error("⚠️ 紧缺阈值必须 < 充足阈值")
				else:
					try:
						db.save_threshold(
							new_code, int(new_low), int(new_mid))
						st.success(
							f"✅ 已保存 {new_code}："
							f"🔴 < {new_low} · 🟢 ≥ {new_mid}")
						st.rerun()
					except Exception as e:
						st.error(f"保存失败：{e}")

	# 顶部统计：每个色号按各自有效阈值分级
	n_low = sum(1 for c, v in inv.items() if v < _thr_of(c)[0])
	n_mid = sum(1 for c, v in inv.items()
	            if _thr_of(c)[0] <= v < _thr_of(c)[1])
	n_high = len(inv) - n_low - n_mid
	total_beads = sum(inv.values())
	override_cnt = sum(1 for c in thresholds if c)
	m1, m2, m3, m4, m5 = st.columns(5)
	m1.metric("🎨 总色号", len(inv),
		f"⭐ {override_cnt} 个自定义" if override_cnt else None,
		delta_color="off")
	m2.metric("🟢 充足", n_high)
	m3.metric("🟡 偏低", n_mid)
	m4.metric("🔴 紧缺", n_low,
		delta=None if n_low == 0 else f"-{n_low}",
		delta_color="inverse")
	m5.metric("📦 总颗数", f"{total_beads:,}")
	if last_ts:
		st.caption(f"🕒 最近更新: {last_ts}")
	st.divider()

	edit_mode = st.radio("编辑模式",
		["📋 表格模式", "🎨 色板模式"],
		horizontal=True, key="inv_edit_mode",
		help="表格模式适合搜索和导入导出;色板模式按 MARD 色板布局直接看色找色,直观高效")
	all_series = sorted({k[0] for k in inv})

	if edit_mode == "📋 表格模式":
		# ====== 表格模式 ======
		f1,f2,f3 = st.columns([3,2,3])
		series_filter = f1.multiselect("系列筛选", all_series, default=all_series,
			format_func=lambda s: f"{s} · {SERIES_LABELS.get(s,'')}",
			key="tbl_series_filter")
		status_filter = f2.radio("状态",
			["全部", "🟢 充足", "🟡 偏低", "🔴 紧缺"],
			horizontal=True, key="tbl_status_filter")
		search_text = f3.text_input("🔍 搜索色号", placeholder="例如 A12、H7",
			key="tbl_search")

		rows = []
		for code, stock in inv.items():
			if code[0] not in series_filter: continue
			tier = _tier(code, stock)
			if status_filter != "全部" and tier != status_filter: continue
			if search_text and search_text.strip().upper() not in code.upper(): continue
			r,g,b = MARD_PALETTE.get(code, (200,200,200))
			lo, mi = _thr_of(code)
			has_ov = code in thresholds
			rows.append({"色块":_swatch((r,g,b)), "色号":code, "系列":code[0],
			             "RGB":f"({r}, {g}, {b})", "库存":int(stock),
			             "阈值": f"<{lo} / ≥{mi}" + (" ⭐" if has_ov else ""),
			             "状态": tier})
		df = pd.DataFrame(rows)
		if df.empty:
			st.info("当前筛选条件下没有色号。")
		else:
			st.caption(f"显示 {len(df)} 个色号 · ✨ 双击「库存」修改,改完即自动保存到云端")
			# 把当前展示的色号顺序存起来,on_change 回调按 row_idx 反查
			st.session_state["inv_editor_codes"] = [r["色号"] for r in rows]
			st.data_editor(df, width="stretch", height=520, hide_index=True,
				column_config={
					"色块": st.column_config.ImageColumn("色块", width="small"),
					"库存": st.column_config.NumberColumn("库存 (颗)",
						min_value=0, step=1, format="%d"),
				},
				disabled=["色块","色号","系列","RGB","阈值","状态"],
				key="inv_editor",
				on_change=_autosave_table, args=(dict(inv),))
		st.divider()
		b1, b2 = st.columns(2)
		full_csv = pd.DataFrame([{"色号":k,"库存":v} for k,v in inv.items()]
			).to_csv(index=False).encode("utf-8-sig")
		b1.download_button("⬇️ 导出全部 CSV", full_csv,
			file_name="inventory.csv", mime="text/csv", width="stretch",
			key="tbl_export")
		up_csv = b2.file_uploader("📤 导入 CSV(覆盖整个库存)", type="csv",
			label_visibility="collapsed", key="tbl_import")
		if up_csv:
			new_df = pd.read_csv(up_csv)
			new_inv = {row["色号"]: int(row["库存"] or 0)
			           for _, row in new_df.iterrows() if pd.notna(row.get("色号"))}
			db.replace_all(new_inv)
			st.success(f"✅ 已从 CSV 导入 {len(new_inv)} 条")
			st.rerun()

	else:
		# ====== 色板模式 ======
		st.caption("🎨 按 MARD 色板布局编辑库存。每个色块上方为色号(文字色随明度自动黑白),"
		           "下方直接修改颗数;右上小圆点 🔴 紧缺 / 🟡 偏低 / 🟢 充足"
		           "（按该色阈值，左上 ⭐ 表示已自定义）;"
		           "✨ 改完按 Enter / 点别处即自动保存,无需点按钮。")
		pf1, pf2 = st.columns([3, 2])
		pal_series = pf1.multiselect("系列筛选", all_series, default=all_series,
			format_func=lambda s: f"{s} · {SERIES_LABELS.get(s,'')}",
			key="pal_series_filter")
		pal_status = pf2.radio("状态",
			["全部", "🟢 充足", "🟡 偏低", "🔴 紧缺"],
			horizontal=True, key="pal_status_filter")

		cols_per_row = 8
		rendered_codes: list[str] = []

		# 不再用 st.form —— 每个 number_input 自带 on_change,改完一格立刻 upsert
		for series in sorted(pal_series):
			series_codes = [c for c in inv if c[0] == series]
			if pal_status != "全部":
				series_codes = [c for c in series_codes
				                if _tier(c, inv[c]) == pal_status]
			if not series_codes:
				continue
			series_total = sum(inv[c] for c in series_codes)
			st.markdown(
				f"<div style='margin:18px 0 10px;padding:10px 16px;"
				f"background:linear-gradient(90deg,rgba(255,182,217,.18),"
				f"rgba(168,218,255,.18));border-radius:12px;"
				f"border:1px solid rgba(255,182,217,.3);'>"
				f"<b style='font-size:15px;'>{series} · "
				f"{SERIES_LABELS.get(series, '')}</b>"
				f"<span style='font-size:12px;color:#7A7A9A;margin-left:10px;'>"
				f"{len(series_codes)} 色 · 共 {series_total:,} 颗</span></div>",
				unsafe_allow_html=True)
			for i in range(0, len(series_codes), cols_per_row):
				row = st.columns(cols_per_row)
				for j, code in enumerate(series_codes[i:i + cols_per_row]):
					r, g, b = MARD_PALETTE[code]
					lum = 0.299 * r + 0.587 * g + 0.114 * b
					text_color = "#1a1a2e" if lum > 140 else "#ffffff"
					stock = int(inv.get(code, 0))
					_lo, _mi = _thr_of(code)
					dot = ("#FF6B9D" if stock < _lo
					       else "#FFE9A8" if stock < _mi
					       else "#7ED6A0")
					has_ov = code in thresholds
					ov_html = ('<div style="position:absolute;top:3px;left:6px;'
					           'font-size:11px;line-height:1;'
					           'filter:drop-shadow(0 1px 2px rgba(0,0,0,.4));">⭐</div>'
					           if has_ov else '')
					with row[j]:
						st.markdown(
							f'<div style="background:rgb({r},{g},{b});'
							f'color:{text_color};'
							f'border:1.5px solid rgba(0,0,0,.12);'
							f'border-radius:10px 10px 0 0;border-bottom:none;'
							f'padding:14px 4px 10px;text-align:center;'
							f'font-weight:800;font-size:14px;letter-spacing:.5px;'
							f'position:relative;text-shadow:0 1px 2px rgba(0,0,0,.08);">'
							f'{code}{ov_html}'
							f'<div style="position:absolute;top:6px;right:6px;'
							f'width:9px;height:9px;border-radius:50%;'
							f'background:{dot};'
							f'box-shadow:0 0 0 2px rgba(255,255,255,.7);">'
							f'</div></div>',
							unsafe_allow_html=True)
						st.number_input(
							label=code, label_visibility="collapsed",
							min_value=0, step=1, value=stock,
							key=f"pal_{code}",
							on_change=_autosave_palette,
							args=(code, stock))
						rendered_codes.append(code)

		if not rendered_codes:
			st.info("当前筛选条件下没有色号。")
		else:
			st.divider()
			st.caption(f"✨ 共 {len(rendered_codes)} 个色号 · "
			           "改完颗数立即自动保存,无需手动点按钮")

	# ---- 各系列概览 ----
	with st.expander("📊 各系列库存概览", expanded=False):
		series_stats = {}
		for code, stock in inv.items():
			s = code[0]
			stat = series_stats.setdefault(s, {"色号数": 0, "有库存": 0, "总颗数": 0})
			stat["色号数"] += 1
			stat["总颗数"] += stock
			if stock > 0: stat["有库存"] += 1
		series_df = pd.DataFrame([
			{"系列": f"{s} · {SERIES_LABELS.get(s, '')}", **v,
			 "覆盖率": f"{v['有库存'] * 100 // v['色号数']}%"}
			for s, v in sorted(series_stats.items())])
		st.dataframe(series_df, width="stretch", hide_index=True,
			column_config={"总颗数": st.column_config.NumberColumn("总颗数", format="%d")})

# ---------- 识别已有拼豆图 ----------
elif page == PAGES["recognize"]:
	st.subheader("🔍 识别已有拼豆图")
	st.caption("OCR 直接读图例文字 / 逐格采样色块,识别后可一键扣减云端库存。")
	mode = st.radio("识别方式",
		["📋 OCR 读图例文字(推荐)", "🎨 整图逐格识别色块"],
		horizontal=True, key="rec_mode")

	# ===== 模式 A:OCR =====
	if mode.startswith("📋"):
		@st.cache_resource(show_spinner="正在加载 OCR 模型(首次约 10 秒)…")
		def _get_engine():
			try:
				from rapidocr_onnxruntime import RapidOCR
				return RapidOCR(), None
			except Exception as e:
				import traceback
				return None, f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"

		st.markdown(
			"<div style='display:flex;gap:10px;align-items:center;"
			"margin:6px 0 14px;padding:10px 14px;"
			"background:linear-gradient(90deg,rgba(255,233,168,.25),"
			"rgba(255,182,217,.25));border-radius:12px;"
			"border:1px solid rgba(255,182,217,.3);'>"
			"<span style='font-size:13px;color:#3A3A52;'>"
			"不想上传图片？可以直接建个空白清单，"
			"手动选色号 + 输颗数 ➜ 保存 ➜ 一键扣库存。"
			"</span></div>",
			unsafe_allow_html=True)
		if st.button("✍️ 新建空白清单（不上传图片）",
		             width="stretch", key="manual_new_btn",
		             help="跳过 OCR，直接进编辑器；效果跟 OCR 识别后再手改一致"):
			new_id = db.insert_ocr_record(
				parsed={}, unknown_codes=[],
				source_path=None, note="✍️ 手动录入")
			st.session_state["ocr_parsed"] = {}
			st.session_state["ocr_unknown"] = []
			st.session_state["ocr_raw_lines"] = []
			st.session_state["ocr_pair_log"] = []
			st.session_state["ocr_id"] = new_id
			st.session_state["ocr_editor_ver"] = (
				int(st.session_state.get("ocr_editor_ver", 0)) + 1)
			st.toast(f"✍️ 已新建空白清单（{new_id[:8]}）",
			         icon="✅")
			st.rerun()
		ocr_file = st.file_uploader("上传带图例的拼豆图",
			type=["png","jpg","jpeg","webp","bmp"], key="ocr_uploader")
		crop = st.slider("只 OCR 图片底部 X% 区域", 10, 100, 25, step=5,
			key="ocr_crop_pct")

		if ocr_file:
			img = Image.open(ocr_file).convert("RGB")
			arr = np.array(img)
			Ho,Wo = arr.shape[:2]
			cut = Ho * (100-crop) // 100
			legend_arr = arr[cut:, :]
			cp1,cp2 = st.columns(2)
			cp1.image(img, caption=f"原图 {Wo}×{Ho}", width="stretch")
			cp2.image(Image.fromarray(legend_arr),
				caption=f"OCR 区域 {legend_arr.shape[1]}×{legend_arr.shape[0]}",
				width="stretch")
			if st.button("🔬 开始 OCR 识别", type="primary",
			             width="stretch", key="ocr_run"):
				engine, err = _get_engine()
				if engine is None:
					st.error(f"❌ OCR 引擎加载失败:\n```\n{err}\n```")
				else:
					with st.spinner("OCR 中…"):
						result, _ = engine(legend_arr)
					if not result:
						st.warning("OCR 没读到任何文字。")
					else:
						import re
						# RapidOCR 返回 [(box, text, score), ...]; box 是 4 顶点多边形
						texts = [r[1] for r in result]
						boxes = [r[0] for r in result]

						# ── 文本归一化:全/半角括号、冒号统一,保留空格 ──
						def _norm(s: str) -> str:
							return (str(s).strip()
								.replace("（","(").replace("）",")")
								.replace("【","(").replace("】",")")
								.replace("[","(").replace("]",")")
								.replace("：",":").replace("　"," "))

						# ── 正则(放宽,适配 OCR 各种拆段形态) ──
						# 单独色号:A5、H7、m12
						CODE_RE = re.compile(r"^([A-HMa-hm])(\d{1,2})$")
						# 同段「色号 + 任意非数字非字母分隔 + 数量」:
						#   A5(191) / A5：191 / A5 191 / A5×191 / A5-191 / A5 (191)
						INLINE_FULL_RE = re.compile(
							r"^([A-HMa-hm])(\d{1,2})[^\dA-Za-z]+(\d{1,5})\s*\)?\s*$")
						# 段内多组(整行连读):"A5(191) H7(43)" 之类
						ANY_INLINE_RE = re.compile(
							r"([A-HMa-hm])(\d{1,2})[^\dA-Za-z]+(\d{1,5})")
						# 纯数字段(允许括号/冒号/×等修饰): "191" "(191)" ":191" "× 191"
						NUM_WRAP_RE = re.compile(r"^[^\dA-Za-z]*(\d{1,5})[^\dA-Za-z]*$")
						# 纯标点段(无字母无数字):跨段配对时跳过它继续往后看
						PUNCT_ONLY_RE = re.compile(r"^[^\dA-Za-z]+$")

						parsed: dict[str, int] = {}
						unknown: list[tuple[str, int]] = []
						used = [False] * len(texts)
						pair_log: list[str] = []   # 调试用:记录每一对怎么配上的

						def _add(code: str, count, src: str = "") -> None:
							code = code.upper()
							try:
								n = int(count)
							except (TypeError, ValueError):
								return
							if n <= 0: return
							if code in MARD_PALETTE:
								parsed[code] = parsed.get(code, 0) + n
							else:
								unknown.append((code, n))
							if src: pair_log.append(f"{code:>4}={n:<5}  {src}")

						def _box(b):
							xs = [p[0] for p in b]; ys = [p[1] for p in b]
							return {"cx": sum(xs)/4.0, "cy": sum(ys)/4.0,
							        "x0": min(xs), "x1": max(xs),
							        "y0": min(ys), "y1": max(ys),
							        "w": (max(xs)-min(xs)) or 20.0,
							        "h": (max(ys)-min(ys)) or 20.0}

						# 预归一化所有段(后续都用 ntexts 做正则匹配)
						ntexts = [_norm(t) for t in texts]

						# ── 色号纠错(白名单 + 常见 OCR 字符混淆) ──
						# OCR 经常把:'G'读成'6'(G8→68)、'S'读成'5'(F5→FS)、
						# 'L/I/T'读成'1'、'O/Q/D'读成'0'、'B'读成'8'、'Z'读成'2';
						# 还会把相邻段的字符串到色号前面(F25 → LF25)。
						# 思路:用色板做白名单,对疑似色号段尝试单字符替换 + 去前后杂字符,
						# 命中色板就替换 ntexts[i],让后续轮次按正确色号配对。
						_CODE_SUB = {
							"0": "OQD", "1": "ILT", "2": "Z", "5": "S",
							"6": "G", "7": "TY", "8": "B",
							"O": "0", "Q": "0", "D": "0",
							"I": "1", "L": "1", "T": "17",
							"Z": "2", "S": "5", "G": "6",
							"B": "8", "Y": "7",
						}
						_ALL_CODES = set(MARD_PALETTE.keys())

						def _gen_subs(t: str, out: list[str]) -> None:
							"""按 _CODE_SUB 单字符级混淆,枚举 t 的替换候选,命中色板就收集。"""
							def rec(idx: int, cur: list[str]) -> None:
								if idx == len(t):
									cand = "".join(cur)
									if cand in _ALL_CODES:
										out.append(cand)
									return
								ch = t[idx]
								rec(idx + 1, cur + [ch])
								for repl in _CODE_SUB.get(ch, ""):
									rec(idx + 1, cur + [repl])
							if 2 <= len(t) <= 3:
								rec(0, [])

						def _try_fix_code(raw: str) -> str | None:
							s = re.sub(r"[^0-9A-Za-z]", "", raw).upper()
							if not s: return None
							if s in _ALL_CODES: return s
							out: list[str] = []
							if 2 <= len(s) <= 3:
								_gen_subs(s, out)
								if out: return out[0]
							# 长度 4+:尝试去掉首/尾 1-2 个杂字符再搜索
							for k in (1, 2):
								if len(s) - k < 2: continue
								tail = s[k:]
								if tail in _ALL_CODES: return tail
								_gen_subs(tail, out)
								if out: return out[0]
								head = s[:-k]
								if head in _ALL_CODES: return head
								_gen_subs(head, out)
								if out: return out[0]
							return None

						# 色号行中位 y / 中位字高(用于判断「短数字段」是不是误读色号)
						_code_idxs = [i for i, s in enumerate(ntexts)
						              if CODE_RE.match(s) and s.upper() in _ALL_CODES]
						_code_ys = sorted(_box(boxes[i])["cy"] for i in _code_idxs)
						_med_code_y = (_code_ys[len(_code_ys)//2]
						               if _code_ys else None)
						_code_hs = sorted(_box(boxes[i])["h"] for i in _code_idxs)
						_mh_pre = (_code_hs[len(_code_hs)//2]
						           if _code_hs else 20.0)

						fix_log: list[str] = []
						for i, s in enumerate(ntexts):
							if CODE_RE.match(s) and s.upper() in _ALL_CODES:
								continue
							if INLINE_FULL_RE.match(s):
								continue
							if not (2 <= len(s) <= 5):
								continue
							is_pure_num = bool(NUM_WRAP_RE.match(s))
							if is_pure_num:
								# 短数字段(≤3 位)若落在色号行附近,可能是 G→6 / S→5 误读
								if _med_code_y is None: continue
								if abs(_box(boxes[i])["cy"] - _med_code_y) > _mh_pre:
									continue
								if len(re.sub(r"[^0-9]", "", s)) > 3:
									continue
							elif not re.search(r"[A-Za-z]", s):
								continue
							fix = _try_fix_code(s)
							if fix and fix.upper() != s.upper():
								fix_log.append(
									f"✏️ 色号纠错 [{i}] {texts[i]!r} → {fix}")
								ntexts[i] = fix
						pair_log.extend(fix_log)

						# ── 第一轮:同段内嵌(最稳的形态,先吃掉) ──
						# A. 整段就是「色号 + 分隔 + 数量」: A5(191) / A5：191 / A5 191
						# B. 整段含多组:"A5(191) H7(43)" 之类的整行连读(≥2 组才认)
						for i, s in enumerate(ntexts):
							if used[i]: continue
							m = INLINE_FULL_RE.match(s)
							if m:
								_add(m.group(1)+m.group(2), m.group(3),
								     f"[{i}]{texts[i]!r} 段内内嵌")
								used[i] = True
								continue
							multi = ANY_INLINE_RE.findall(s)
							if len(multi) >= 2:
								for letter, num, cnt in multi:
									_add(letter+num, cnt,
									     f"[{i}]{texts[i]!r} 整行连读")
								used[i] = True

						# ── 第二轮:阅读顺序紧邻配对(关键修复) ──
						# 处理 "A5" + "(191)"、"A5" + ":" + "191" 等被 OCR 拆段的场景。
						# 必须在几何配对之前跑,否则容易被「同列下方」抢成下一行的数字。
						for i in range(len(texts)):
							if used[i]: continue
							cm = CODE_RE.match(ntexts[i])
							if not cm: continue
							cb = _box(boxes[i])
							for j in range(i+1, min(i+4, len(texts))):
								if used[j]: continue
								sj = ntexts[j]
								# 撞到下一个色号 / 别人已分配的内嵌段 → 停
								if CODE_RE.match(sj) or INLINE_FULL_RE.match(sj):
									break
								nb = _box(boxes[j])
								# 几何兜底:同行(y 接近) + 紧邻(x 不超过几个字宽)
								# 防止 [F4](x=478) 错配到偏远的 [25]'1'(x=691,y=32)
								if abs(nb["cy"] - cb["cy"]) > cb["h"] * 0.6:
									break
								if abs(nb["cx"] - cb["cx"]) > cb["w"] * 5:
									break
								nm = NUM_WRAP_RE.match(sj)
								if nm:
									_add(cm.group(1)+cm.group(2), nm.group(1),
									     f"[{i}]{texts[i]!r} ⤳ [{j}]{texts[j]!r} 阅读顺序")
									used[i] = True; used[j] = True
									break
								# 跳过纯标点段("(" / ":" / "·" 之类的占位段)继续往后看
								if PUNCT_ONLY_RE.match(sj):
									continue
								break   # 撞到其他文字段(如 "颗"、"个"),停止

						# 中位字高(给后续几何配对当容差基准)
						code_heights = sorted([_box(boxes[i])["h"]
						                       for i in range(len(texts))
						                       if CODE_RE.match(ntexts[i])])
						mh = code_heights[len(code_heights)//2] if code_heights else 20.0

						def _candidates():
							cs = [(i, CODE_RE.match(ntexts[i]))
							      for i in range(len(texts))
							      if not used[i] and CODE_RE.match(ntexts[i])]
							ns = [i for i in range(len(texts))
							      if not used[i] and NUM_WRAP_RE.match(ntexts[i])]
							return cs, ns

						# 中位色号宽,用于识别「OCR 把多列连读成一段」
						code_widths = sorted([_box(boxes[i])["w"]
						                       for i in range(len(texts))
						                       if CODE_RE.match(ntexts[i])])
						mcw = code_widths[len(code_widths)//2] if code_widths else 40.0

						def _is_merged_num(nj: int) -> bool:
							"""数字段疑似多列连读:文本 >=4 位且 bbox 宽 > 1.4×中位色号宽。
							例 '8342' 实为 A17=8 + B11=3 + B16=42。这种段不在第三/四轮认领,
							留给第五轮按列重 OCR 拆分。"""
							nm_tmp = NUM_WRAP_RE.match(ntexts[nj])
							if not nm_tmp: return False
							if len(nm_tmp.group(1)) < 4: return False
							return _box(boxes[nj])["w"] > mcw * 1.4

						# ── 第三轮:同列正下方(色号在上、数量在下,跳过连读段) ──
						# X 容差 max(w×1.5, mh),Y 距离限制在 mh×6 内,避免抢隔壁列。
						code_segs, num_idxs = _candidates()
						for ci, m in code_segs:
							if used[ci]: continue
							cb = _box(boxes[ci])
							x_tol = max(cb["w"] * 1.5, mh)
							best, best_dy = None, float("inf")
							for nj in num_idxs:
								if used[nj]: continue
								if _is_merged_num(nj): continue
								nb = _box(boxes[nj])
								if abs(nb["cx"] - cb["cx"]) > x_tol: continue
								dy = nb["cy"] - cb["cy"]
								if dy < cb["h"] * 0.3: continue
								if dy > mh * 6: continue
								if dy < best_dy:
									best_dy, best = dy, nj
							if best is not None:
								nm = NUM_WRAP_RE.match(ntexts[best])
								if nm:
									_add(m.group(1)+m.group(2), nm.group(1),
									     f"[{ci}]{texts[ci]!r} ↓ [{best}]{texts[best]!r} 同列下方")
									used[ci] = True; used[best] = True

						# ── 第四轮:同行右侧(几何兜底,同样跳过连读段) ──
						code_segs, num_idxs = _candidates()
						for ci, m in code_segs:
							if used[ci]: continue
							cb = _box(boxes[ci])
							y_tol = cb["h"] * 0.7
							best, best_dx = None, float("inf")
							for nj in num_idxs:
								if used[nj]: continue
								if _is_merged_num(nj): continue
								nb = _box(boxes[nj])
								if abs(nb["cy"] - cb["cy"]) > y_tol: continue
								dx = nb["cx"] - cb["cx"]
								if dx < cb["w"] * 0.2: continue
								if dx > mh * 8: continue
								if dx < best_dx:
									best_dx, best = dx, nj
							if best is not None:
								nm = NUM_WRAP_RE.match(ntexts[best])
								if nm:
									_add(m.group(1)+m.group(2), nm.group(1),
									     f"[{ci}]{texts[ci]!r} → [{best}]{texts[best]!r} 同行右侧")
									used[ci] = True; used[best] = True

						# ── 第五轮:批量按列重 OCR(单次调用,解决多列连读) ──
						# 思路:把所有还没配上的色号正下方的窄条**横向拼成一张大图**,
						# 中间用 30px 白条作分隔,**只调一次 engine()**;
						# 再按识别块的 x 中心位置反查它属于哪个色号。
						# N 个未匹配色号 → 仅 1 次 OCR(原本 N 次会卡 30s+)。
						unconsumed = [(i, _box(boxes[i]))
						              for i in range(len(texts))
						              if not used[i] and CODE_RE.match(ntexts[i])]
						unconsumed.sort(key=lambda x: x[1]["cy"])
						rows_of_codes: list[list[tuple[int, dict]]] = []
						for i, bb in unconsumed:
							if (rows_of_codes
							    and abs(rows_of_codes[-1][-1][1]["cy"] - bb["cy"]) < mh * 0.6):
								rows_of_codes[-1].append((i, bb))
							else:
								rows_of_codes.append([(i, bb)])
						H_la, W_la = legend_arr.shape[:2]
						batch_crops: list[tuple[int, np.ndarray]] = []
						for row_codes in rows_of_codes:
							row_codes.sort(key=lambda x: x[1]["cx"])
							for k, (ci, cb) in enumerate(row_codes):
								if k == 0:
									x_left = int(cb["cx"] - cb["w"] * 1.2)
								else:
									x_left = int((row_codes[k-1][1]["cx"] + cb["cx"]) / 2)
								if k == len(row_codes) - 1:
									x_right = int(cb["cx"] + cb["w"] * 1.2)
								else:
									x_right = int((cb["cx"] + row_codes[k+1][1]["cx"]) / 2)
								y_top = int(cb["y1"] + cb["h"] * 0.2)
								y_bot = int(cb["y1"] + cb["h"] * 2.5)
								x_left = max(0, min(W_la - 1, x_left))
								x_right = max(x_left + 1, min(W_la, x_right))
								y_top = max(0, min(H_la - 1, y_top))
								y_bot = max(y_top + 1, min(H_la, y_bot))
								sub = legend_arr[y_top:y_bot, x_left:x_right]
								if sub.size == 0: continue
								batch_crops.append((ci, sub))
						if batch_crops:
							target_h = max(c.shape[0] for _, c in batch_crops)
							GAP = 30
							pieces = []
							offsets: list[tuple[int, int, int]] = []
							cur_x = 0
							gap_block = np.full((target_h, GAP, 3), 255, dtype=np.uint8)
							for idx, (ci, c) in enumerate(batch_crops):
								if c.shape[0] < target_h:
									pad = np.full((target_h - c.shape[0],
									               c.shape[1], 3), 255, dtype=np.uint8)
									c = np.vstack([c, pad])
								if idx > 0:
									pieces.append(gap_block)
									cur_x += GAP
								pieces.append(c)
								offsets.append((cur_x, cur_x + c.shape[1], ci))
								cur_x += c.shape[1]
							stitched = np.hstack(pieces)
							try:
								sub_res, _ = engine(stitched)
							except Exception:
								sub_res = None
							if sub_res:
								for _sb, _st, _sc in sub_res:
									sx = sum(p[0] for p in _sb) / 4.0
									ns = _norm(_st)
									mm = NUM_WRAP_RE.match(ns)
									if not mm: continue
									for x0_, x1_, ci in offsets:
										if x0_ <= sx < x1_ and not used[ci]:
											cm = CODE_RE.match(ntexts[ci])
											_add(cm.group(1)+cm.group(2),
											     mm.group(1),
											     f"[{ci}]{texts[ci]!r} 🔬 批量重OCR='{ns}'")
											used[ci] = True
											break

						# 调试用:带 bbox 中心坐标和“是否被消费”标记的原始段
						debug_lines = []
						for i, (b, t) in enumerate(zip(boxes, texts)):
							bb = _box(b)
							tag = "✓" if used[i] else "·"
							debug_lines.append(
								f"[{i:2d}] ({bb['cx']:5.0f},{bb['cy']:5.0f}) {tag} {t!r}")
						# 上传原图 + 入历史
						src_path = storage.upload_ocr_source(
							ocr_file.getvalue(),
							suffix=ocr_file.name.rsplit(".",1)[-1].lower())
						ocr_id = db.insert_ocr_record(
							parsed=parsed, unknown_codes=unknown,
							source_path=src_path)
						st.session_state["ocr_parsed"] = parsed
						st.session_state["ocr_raw_lines"] = debug_lines
						st.session_state["ocr_pair_log"] = pair_log
						st.session_state["ocr_unknown"] = unknown
						st.session_state["ocr_id"] = ocr_id

		if st.session_state.get("ocr_parsed") is not None:
			parsed = st.session_state["ocr_parsed"]
			raw = st.session_state.get("ocr_raw_lines", [])
			unknown = st.session_state.get("ocr_unknown", [])
			ocr_id = st.session_state.get("ocr_id")
			st.divider()
			st.subheader("✅ OCR 解析结果")
			with st.expander(
				f"🔍 OCR 原始段 + 配对日志({len(raw)} 段)",
				expanded=False):
				st.caption(
					"格式:[段索引] (中心X, 中心Y) ✓已消费 / ·未消费  原始文字")
				st.code("\n".join(raw))
				plog = st.session_state.get("ocr_pair_log", [])
				if plog:
					st.caption(f"配对日志({len(plog)} 对):")
					st.code("\n".join(plog))
			# 识别结果可编辑表(增/删/改 即时入库)
			# 编辑器只管「色号 + 需要颗数」;库存信息只读展示在下方,
			# 库存修改一律去「📦 编辑库存」页面,避免功能对冲
			inv_now = db.load_inventory()
			def _ocr_code_key(c: str) -> tuple[int, int]:
				_series_order = {s: i for i, s in enumerate("ABCDEFGHM")}
				return (_series_order.get(c[0], 99),
				        int(c[1:]) if c[1:].isdigit() else 0)
			items = sorted(parsed.items(), key=lambda x: _ocr_code_key(x[0]))
			ver = int(st.session_state.get("ocr_editor_ver", 0))
			editor_key = f"ocr_editor_v{ver}"
			edit_df = (pd.DataFrame([{"序号": i + 1, "系列": f"{c[0]} · {SERIES_LABELS.get(c[0], '')}", "色号": c, "需要": int(n)} for i, (c, n) in enumerate(items)])
				if items else pd.DataFrame({
					"序号": pd.Series([], dtype="int64"), "系列": pd.Series([], dtype=str), "色号": pd.Series([], dtype=str),
					"需要": pd.Series([], dtype="int64")}))
			tab_table, tab_pal = st.tabs(["📋 表格模式", "🎨 色板模式"])
			tab_table.caption("✏️ 双击单元格修改色号/颗数 · 底部 ➕ 新增一行 · 勾选行末 ☑ 删除一行 · "
			           "改完即自动保存到云端")
			tab_table.data_editor(edit_df,
				width="stretch", hide_index=True, num_rows="dynamic",
				column_config={
					"序号": st.column_config.NumberColumn("#", format="%d", width="small", help="按色号顺序自动编号"),
			       "系列": st.column_config.TextColumn("系列", width="medium", help="A/B/C/D/E/F/G/H/M 色号大类"),
			       "色号": st.column_config.SelectboxColumn(
						"色号", options=list(MARD_PALETTE.keys()),
						required=True, width="small",
						help="从 221 个 MARD 色号里选"),
					"需要": st.column_config.NumberColumn(
						"需要 (颗)", min_value=1, step=1, required=True,
						format="%d", width="small"),
				},
				disabled=["序号", "系列"],
			    key=editor_key,
				on_change=_save_ocr_edits, args=(editor_key,))
			with tab_pal:
				st.caption("🎨 按色号大类直观浏览 · 改颗数即自动保存 · 颗数调为 0 或点 🗑️ 即删除 · "
				           "下方可手动添加色号")
				items_pal = sorted(parsed.items(),
				                   key=lambda x: _ocr_code_key(x[0]))
				if not items_pal:
					st.info("暂无识别结果。可从下方「➕ 手动添加色号」新增，"
					        "或切到「📋 表格模式」批量加。")
				else:
					by_series: dict[str, list[tuple[str, int]]] = {}
					for c, n in items_pal:
						by_series.setdefault(c[0], []).append((c, n))
					cols_per_row = 6
					for s in sorted(by_series,
					                key=lambda x: "ABCDEFGHM".find(x)):
						series_codes = by_series[s]
						series_total = sum(n for _, n in series_codes)
						st.markdown(
							f"<div style='margin:18px 0 10px;padding:10px 16px;"
							f"background:linear-gradient(90deg,rgba(255,182,217,.18),"
							f"rgba(168,218,255,.18));border-radius:12px;"
							f"border:1px solid rgba(255,182,217,.3);'>"
							f"<b style='font-size:15px;'>{s} · "
							f"{SERIES_LABELS.get(s, '')}</b>"
							f"<span style='font-size:12px;color:#7A7A9A;"
							f"margin-left:10px;'>{len(series_codes)} 色 · "
							f"共 {series_total:,} 颗</span></div>",
							unsafe_allow_html=True)
						for i in range(0, len(series_codes), cols_per_row):
							row = st.columns(cols_per_row)
							for j, (code, need) in enumerate(
									series_codes[i:i + cols_per_row]):
								r, g, b = MARD_PALETTE[code]
								lum = 0.299 * r + 0.587 * g + 0.114 * b
								txt = "#1a1a2e" if lum > 140 else "#ffffff"
								with row[j]:
									st.markdown(
										f'<div style="background:rgb({r},{g},{b});'
										f'color:{txt};'
										f'border:1.5px solid rgba(0,0,0,.12);'
										f'border-radius:10px 10px 0 0;'
										f'border-bottom:none;'
										f'padding:14px 4px 10px;text-align:center;'
										f'font-weight:800;font-size:14px;'
										f'letter-spacing:.5px;'
										f'text-shadow:0 1px 2px rgba(0,0,0,.08);">'
										f'{code}</div>',
										unsafe_allow_html=True)
									st.number_input(
										label=f"need_{code}",
										label_visibility="collapsed",
										min_value=0, step=1, value=int(need),
										key=f"ocr_pal_v{ver}_{code}",
										on_change=_ocr_palette_change,
										args=(code,))
									st.button("🗑️ 删除",
										key=f"ocr_pal_del_v{ver}_{code}",
										width="stretch",
										on_click=_ocr_palette_delete,
										args=(code,))
				st.divider()
				with st.expander("➕ 手动添加色号", expanded=False):
					ac1, ac2, ac3 = st.columns([3, 2, 1])
					with ac1:
						st.selectbox("色号",
							options=sorted(MARD_PALETTE.keys(),
							               key=_ocr_code_key),
							key="ocr_pal_add_code",
							format_func=lambda c: f"{c} · "
							                      f"{SERIES_LABELS.get(c[0], '')}")
					with ac2:
						st.number_input("颗数", min_value=1, step=1,
							value=1, key="ocr_pal_add_cnt")
					with ac3:
						st.write("")
						st.button("➕ 添加", type="primary",
							width="stretch",
							on_click=_ocr_palette_add)

			rows, shortage_items = [], []
			for i, (code, need) in enumerate(items):
				stock = inv_now.get(code, 0); diff = stock - need
				if diff < 0:
					shortage_items.append({"code": code, "need": need,
						"stock": stock, "short": -diff})
				rows.append({"序号": i + 1, "系列": f"{code[0]} · {SERIES_LABELS.get(code[0], '')}", "色号": code, "需要": need, "库存": stock,
					"扣减后": max(0, diff),
					"状态": "✅ 充足" if diff >= 0 else f"❌ 缺{-diff}"})
			ocr_df = (pd.DataFrame(rows) if rows
				else pd.DataFrame(columns=["序号", "系列", "色号", "需要", "库存", "扣减后", "状态"]))

			if items:
				m1, m2, m3 = st.columns(3)
				m1.metric("总豆数", sum(n for _, n in items))
				m2.metric("色号种类", len(items))
				m3.metric("需补货色号", len(shortage_items),
					delta=None if not shortage_items else f"-{len(shortage_items)}",
					delta_color="inverse")
				with st.expander("📊 与当前库存对比(🔒 只读)", expanded=True):
					st.caption("🔒 此表只展示缺口,不在这里改库存。"
					           "库存修改请到「📦 编辑库存」页面,避免功能对冲。")
					st.dataframe(ocr_df, width="stretch", hide_index=True)
			else:
				st.info("👇 当前没有色号,可在上方表格底部 ➕ 新增一行手动添加。")

			if unknown:
				st.warning(f"⚠️ {len(unknown)} 个未识别色号:" +
					", ".join(f"{c}({n})" for c, n in unknown[:20]))

			d1, d2, d3 = st.columns(3)
			d1.download_button("⬇️ 导出 CSV",
				ocr_df.to_csv(index=False).encode("utf-8-sig"),
				file_name="ocr_recognized.csv", mime="text/csv",
				width="stretch", disabled=not items)
			if d2.button("➖ 从库存中扣减", type="primary",
			             width="stretch", key="ocr_deduct",
			             disabled=not items):
				updates = {c: max(0, inv_now.get(c, 0) - n) for c, n in items}
				db.save_inventory(updates)
				if ocr_id:
					db.mark_ocr_deducted(ocr_id)
				st.success(f"✅ 已扣减 {len(updates)} 个色号" + (
					f" · 其中 {len(shortage_items)} 个色号原本不足,已扣到 0"
					if shortage_items else ""))
				for k in ("ocr_parsed", "ocr_raw_lines", "ocr_pair_log",
				          "ocr_unknown", "ocr_id", "ocr_editor_ver"):
					st.session_state.pop(k, None)
				st.rerun()
			if d3.button("🗑️ 清空", width="stretch", key="ocr_clear"):
				for k in ("ocr_parsed", "ocr_raw_lines", "ocr_pair_log",
				          "ocr_unknown", "ocr_id", "ocr_editor_ver"):
					st.session_state.pop(k, None)
				st.rerun()

	# ===== 模式 B:逐格识别(无图例时使用)=====
	else:
		st.info("🎨 适用于无图例的纯色块图。逐格采样后会写入 OCR 历史,可一键扣减云端库存。")
		rec_file = st.file_uploader("上传拼豆图图片",
			type=["png","jpg","jpeg","webp","bmp"], key="rec_uploader")

		rc1, rc2, rc3 = st.columns(3)
		rec_w = rc1.number_input("横向格数", 2, 300, 50, step=1, key="rec_w")
		rec_h = rc2.number_input("纵向格数", 2, 300, 45, step=1, key="rec_h")
		sample_mode = rc3.selectbox("采样方式",
			["格子中心 60% 均值", "中心单像素"], index=0,
			help="均值更鲁棒,能避开网格线和文字;单像素更快。")

		rc4, rc5, rc6, rc7 = st.columns(4)
		crop_left   = rc4.slider("裁左 %", 0, 40, 0, key="rec_cl")
		crop_right  = rc5.slider("裁右 %", 0, 40, 0, key="rec_cr")
		crop_top    = rc6.slider("裁上 %", 0, 40, 0, key="rec_ct")
		crop_bottom = rc7.slider("裁下 %", 0, 40, 0, key="rec_cb")
		st.caption("⚠️ 如有坐标轴/图例/水印边框,请用裁剪滑块去掉,只留纯色块网格区域,横/纵格数要与真实格子数一致。")

		if rec_file:
			rec_img = Image.open(rec_file).convert("RGB")
			arr_full = np.array(rec_img, dtype=np.int32)
			H, W = arr_full.shape[:2]
			ax0 = W * crop_left // 100
			ax1 = W - W * crop_right // 100
			ay0 = H * crop_top // 100
			ay1 = H - H * crop_bottom // 100
			arr = arr_full[ay0:ay1, ax0:ax1]
			cropped_preview = Image.fromarray(arr.astype(np.uint8))
			pcol1, pcol2 = st.columns(2)
			pcol1.image(rec_img, caption=f"原图 {W}×{H}", width="stretch")
			pcol2.image(cropped_preview,
				caption=f"裁剪后 {arr.shape[1]}×{arr.shape[0]}",
				width="stretch")

			if st.button("🔬 开始识别", type="primary",
			             width="stretch", key="rec_run"):
				HH, WW = arr.shape[:2]
				cw = WW / rec_w; ch = HH / rec_h
				palette_names = list(MARD_PALETTE.keys())
				palette_rgb = np.array(
					[MARD_PALETTE[n] for n in palette_names], dtype=np.int32)
				weights = np.array([0.3, 0.59, 0.11], dtype=np.float32)
				recognized = [[None]*int(rec_w) for _ in range(int(rec_h))]
				with st.spinner("识别中…"):
					for yy in range(int(rec_h)):
						for xx in range(int(rec_w)):
							gx0=int(xx*cw); gx1=int((xx+1)*cw)
							gy0=int(yy*ch); gy1=int((yy+1)*ch)
							if sample_mode == "中心单像素":
								sample = arr[(gy0+gy1)//2, (gx0+gx1)//2]
							else:
								mx0=gx0+(gx1-gx0)*2//10; mx1=gx1-(gx1-gx0)*2//10
								my0=gy0+(gy1-gy0)*2//10; my1=gy1-(gy1-gy0)*2//10
								if mx1<=mx0 or my1<=my0:
									sample = arr[(gy0+gy1)//2, (gx0+gx1)//2]
								else:
									sample = arr[my0:my1, mx0:mx1].mean(axis=(0,1))
							diff = sample.astype(np.int32) - palette_rgb
							dist = (diff*diff).astype(np.float32) @ weights
							recognized[yy][xx] = palette_names[int(dist.argmin())]

				counter = Counter()
				for row in recognized:
					for name in row: counter[name] += 1

				preview = Image.new("RGB",
					(int(rec_w)*16, int(rec_h)*16), (255,255,255))
				pdraw = ImageDraw.Draw(preview)
				for yy in range(int(rec_h)):
					for xx in range(int(rec_w)):
						pdraw.rectangle(
							[xx*16, yy*16, (xx+1)*16, (yy+1)*16],
							fill=MARD_PALETTE[recognized[yy][xx]])

				# 上传原图 + 入 OCR 历史(以 grid 模式记录)
				suffix = rec_file.name.rsplit(".",1)[-1].lower()
				src_path = storage.upload_ocr_source(rec_file.getvalue(),
				                                     suffix=suffix)
				rec_id = db.insert_ocr_record(
					parsed=dict(counter),
					unknown_codes=[],
					source_path=src_path,
					note="grid-sample")

				st.session_state["rec_counter"] = dict(counter)
				st.session_state["rec_preview_bytes"] = pil_to_bytes(preview)
				st.session_state["rec_id"] = rec_id

		if st.session_state.get("rec_counter"):
			counter = st.session_state["rec_counter"]
			rec_id = st.session_state.get("rec_id")
			st.divider()
			st.subheader("✅ 识别结果")
			st.image(st.session_state["rec_preview_bytes"],
				caption="识别结果重建图(用于核对识别准确度)")

			ex1, ex2 = st.columns(2)
			exclude_h1 = ex1.checkbox("排除 H1 纯白(常作背景)",
				value=True, key="rec_ex_h1")
			exclude_h2 = ex2.checkbox("排除 H2 接近白(常作背景)",
				value=False, key="rec_ex_h2")
			excludes = set()
			if exclude_h1: excludes.add("H1")
			if exclude_h2: excludes.add("H2")

			items = sorted(
				[(k,v) for k,v in counter.items() if k not in excludes],
				key=lambda x:-x[1])
			inv_now = db.load_inventory()
			rows, shortage_items = [], []
			for i, (code, need) in enumerate(items):
				stock = inv_now.get(code, 0); diff = stock - need
				if diff < 0:
					shortage_items.append({"code":code, "need":need,
						"stock":stock, "short":-diff})
				rows.append({"色号":code, "需要":need, "库存":stock,
					"扣减后":max(0,diff),
					"状态":"✅ 充足" if diff>=0 else f"❌ 缺{-diff}"})
			rec_df = pd.DataFrame(rows)

			m1, m2, m3 = st.columns(3)
			m1.metric("总豆数", sum(n for _,n in items))
			m2.metric("颜色种类", len(items))
			m3.metric("需补货色号", len(shortage_items),
				delta=None if not shortage_items else f"-{len(shortage_items)}",
				delta_color="inverse")
			st.dataframe(rec_df, width="stretch", hide_index=True)

			d1, d2, d3 = st.columns(3)
			d1.download_button("⬇️ 导出识别用量 CSV",
				rec_df.to_csv(index=False).encode("utf-8-sig"),
				file_name="recognized_usage.csv", mime="text/csv",
				width="stretch")
			if d2.button("➖ 从库存中扣减", type="primary",
			             width="stretch", key="rec_deduct"):
				updates = {c: max(0, inv_now.get(c,0)-n) for c,n in items}
				db.save_inventory(updates)
				if rec_id:
					db.mark_ocr_deducted(rec_id)
				st.success(f"✅ 已扣减 {len(updates)} 个色号" + (
					f" · 其中 {len(shortage_items)} 个色号原本不足,已扣到 0"
					if shortage_items else ""))
				for k in ("rec_counter","rec_preview_bytes","rec_id"):
					st.session_state.pop(k, None)
				st.rerun()
			if d3.button("🗑️ 清空识别结果", width="stretch",
			             key="rec_clear"):
				for k in ("rec_counter","rec_preview_bytes","rec_id"):
					st.session_state.pop(k, None)
				st.rerun()

# ---------- 历史记录 ----------
elif page == PAGES["history"]:
	st.subheader("📚 历史记录")
	hist_tabs = st.tabs(["🖼️ 我的图纸", "🔍 OCR 历史"])

	# ===== 我的图纸 =====
	with hist_tabs[0]:
		pats = db.list_patterns(limit=100)
		hc1, hc2 = st.columns([3, 1])
		hc1.caption(f"共 {len(pats)} 张图纸")
		confirm_pat = hc1.checkbox("我确认要清空所有图纸(含云端图片)",
			key="confirm_clear_pat")
		if hc2.button("🗑️ 清空全部", key="clear_all_pat",
		              width="stretch", disabled=not confirm_pat):
			n = db.delete_all_patterns()
			st.success(f"✅ 已清空 {n} 张图纸(含云端图片)")
			st.rerun()
		st.divider()
		if not pats:
			st.info("还没有生成过图纸。")
		for p in pats:
			cols = st.columns([1, 3, 1])
			if p.get("image_path"):
				try:
					url = storage.signed_url(PATTERN_BUCKET, p["image_path"])
					cols[0].image(url, width=120)
				except Exception:
					cols[0].caption("(图片不可用)")
			cols[1].markdown(
				f"**{p['name']}** · {p['width_beads']}×{p['height_beads']}  \n"
				f"总豆 {p['total_beads']} · {p['color_count']} 色 · "
				f"{p['created_at'][:19].replace('T',' ')}")
			if cols[2].button("🗑️ 删除", key=f"del_pat_{p['id']}",
			                   width="stretch"):
				db.delete_pattern(p["id"])
				st.toast(f"已删除「{p['name']}」", icon="🗑️")
				st.rerun()

	# ===== OCR 历史 =====
	with hist_tabs[1]:
		ocrs = db.list_ocr_history(limit=100)
		hc1, hc2 = st.columns([3, 1])
		hc1.caption(f"共 {len(ocrs)} 条 OCR 识别记录")
		confirm_ocr = hc1.checkbox("我确认要清空所有 OCR 历史(含云端原图)",
			key="confirm_clear_ocr")
		if hc2.button("🗑️ 清空全部", key="clear_all_ocr",
		              width="stretch", disabled=not confirm_ocr):
			n = db.delete_all_ocr()
			st.success(f"✅ 已清空 {n} 条 OCR 历史(含云端原图)")
			st.rerun()
		st.divider()
		if not ocrs:
			st.info("还没有 OCR 识别记录。")
		for o in ocrs:
			cols = st.columns([4, 1])
			tag = "✅ 已扣减" if o["deducted"] else "🟡 未扣减"
			cols[0].markdown(
				f"**{o['created_at'][:19].replace('T',' ')}** · "
				f"{o['color_count']} 色 / {o['total_beads']} 颗 · {tag}")
			if cols[1].button("🗑️ 删除", key=f"del_ocr_{o['id']}",
			                   width="stretch"):
				db.delete_ocr_record(o["id"])
				st.toast("已删除 OCR 记录", icon="🗑️")
				st.rerun()
			with st.expander("📋 详情:原图 + 解析结果"):
				if o.get("source_path"):
					try:
						url = storage.signed_url(OCR_BUCKET,
						                          o["source_path"])
						st.image(url, width=240)
					except Exception:
						pass
				parsed_df = pd.DataFrame(
					[{"色号": c, "数量": n}
					 for c, n in sorted(o["parsed"].items(),
					                     key=lambda x: -x[1])])
				st.dataframe(parsed_df, width="stretch", hide_index=True)

# ---------- 色板 ----------
elif page == PAGES["palette"]:
	st.subheader("MARD 221 色色板")
	cols_per_row = 12
	names = list(MARD_PALETTE.keys())
	for i in range(0, len(names), cols_per_row):
		row = st.columns(cols_per_row)
		for j, name in enumerate(names[i:i+cols_per_row]):
			r,g,b = MARD_PALETTE[name]
			row[j].markdown(
				f"<div style='background:rgb({r},{g},{b});"
				f"height:40px;border-radius:4px;border:1px solid #ccc;'></div>"
				f"<div style='text-align:center;font-size:11px;'>{name}</div>",
				unsafe_allow_html=True)