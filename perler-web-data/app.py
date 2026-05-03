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
	total_colors = len(inv)
	in_stock = sum(1 for v in inv.values() if v > 0)
	oos = total_colors - in_stock
	total_beads = sum(inv.values())
	coverage = in_stock * 100 // total_colors if total_colors else 0
	m1,m2,m3,m4 = st.columns(4)
	m1.metric("🎨 总色号", total_colors)
	m2.metric("✅ 有库存", f"{in_stock}", f"覆盖 {coverage}%")
	m3.metric("❌ 缺货色号", oos,
		delta=None if oos==0 else f"-{oos}", delta_color="inverse")
	m4.metric("📦 库存总颗数", f"{total_beads:,}")
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
		status_filter = f2.radio("状态", ["全部","有库存","缺货"],
			horizontal=True, key="tbl_status_filter")
		search_text = f3.text_input("🔍 搜索色号", placeholder="例如 A12、H7",
			key="tbl_search")

		rows = []
		for code, stock in inv.items():
			if code[0] not in series_filter: continue
			if status_filter == "有库存" and stock <= 0: continue
			if status_filter == "缺货" and stock > 0: continue
			if search_text and search_text.strip().upper() not in code.upper(): continue
			r,g,b = MARD_PALETTE.get(code, (200,200,200))
			rows.append({"色块":_swatch((r,g,b)), "色号":code, "系列":code[0],
			             "RGB":f"({r}, {g}, {b})", "库存":int(stock),
			             "状态":"✅ 有货" if stock>0 else "❌ 缺货"})
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
				disabled=["色块","色号","系列","RGB","状态"],
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
		           "下方直接修改颗数;右上小圆点 🔴 缺货 / 🟡 1–49 / 🟢 ≥50;"
		           "✨ 改完按 Enter / 点别处即自动保存,无需点按钮。")
		pf1, pf2 = st.columns([3, 2])
		pal_series = pf1.multiselect("系列筛选", all_series, default=all_series,
			format_func=lambda s: f"{s} · {SERIES_LABELS.get(s,'')}",
			key="pal_series_filter")
		pal_status = pf2.radio("状态", ["全部", "有库存", "缺货"],
			horizontal=True, key="pal_status_filter")

		cols_per_row = 8
		rendered_codes: list[str] = []

		# 不再用 st.form —— 每个 number_input 自带 on_change,改完一格立刻 upsert
		for series in sorted(pal_series):
			series_codes = [c for c in inv if c[0] == series]
			if pal_status == "有库存":
				series_codes = [c for c in series_codes if inv[c] > 0]
			elif pal_status == "缺货":
				series_codes = [c for c in series_codes if inv[c] <= 0]
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
					dot = ("#FF6B9D" if stock == 0
					       else "#FFE9A8" if stock < 50
					       else "#7ED6A0")
					with row[j]:
						st.markdown(
							f'<div style="background:rgb({r},{g},{b});'
							f'color:{text_color};'
							f'border:1.5px solid rgba(0,0,0,.12);'
							f'border-radius:10px 10px 0 0;border-bottom:none;'
							f'padding:14px 4px 10px;text-align:center;'
							f'font-weight:800;font-size:14px;letter-spacing:.5px;'
							f'position:relative;text-shadow:0 1px 2px rgba(0,0,0,.08);">'
							f'{code}'
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
						texts = [r[1] for r in result]
						all_text = " ".join(texts)
						pat = re.compile(
							r"([A-Ha-hMm])\s*(\d{1,2})\s*[\(（]\s*(\d{1,5})\s*[\)）]")
						parsed, unknown = {}, []
						for letter,num,count in pat.findall(all_text):
							code = letter.upper()+num
							if code in MARD_PALETTE:
								parsed[code] = parsed.get(code,0) + int(count)
							else:
								unknown.append((code, int(count)))
						# 上传原图 + 入历史
						src_path = storage.upload_ocr_source(
							ocr_file.getvalue(),
							suffix=ocr_file.name.rsplit(".",1)[-1].lower())
						ocr_id = db.insert_ocr_record(
							parsed=parsed, unknown_codes=unknown,
							source_path=src_path)
						st.session_state["ocr_parsed"] = parsed
						st.session_state["ocr_raw_lines"] = texts
						st.session_state["ocr_unknown"] = unknown
						st.session_state["ocr_id"] = ocr_id

		if st.session_state.get("ocr_parsed") is not None:
			parsed = st.session_state["ocr_parsed"]
			raw = st.session_state.get("ocr_raw_lines", [])
			unknown = st.session_state.get("ocr_unknown", [])
			ocr_id = st.session_state.get("ocr_id")
			st.divider()
			st.subheader("✅ OCR 解析结果")
			with st.expander(f"🔍 OCR 原始文字({len(raw)} 段)", expanded=False):
				st.code("\n".join(raw))
			if not parsed:
				st.warning("未匹配到「色号(数量)」格式。")
			else:
				inv_now = db.load_inventory()
				items = sorted(parsed.items(), key=lambda x:-x[1])
				rows, shortage_items = [], []
				for code, need in items:
					stock = inv_now.get(code, 0); diff = stock-need
					if diff < 0:
						shortage_items.append({"code":code,"need":need,
							"stock":stock,"short":-diff})
					rows.append({"色号":code,"需要":need,"库存":stock,
						"扣减后":max(0,diff),
						"状态":"✅ 充足" if diff>=0 else f"❌ 缺{-diff}"})
				ocr_df = pd.DataFrame(rows)
				m1,m2,m3 = st.columns(3)
				m1.metric("总豆数", sum(n for _,n in items))
				m2.metric("色号种类", len(items))
				m3.metric("需补货色号", len(shortage_items),
					delta=None if not shortage_items else f"-{len(shortage_items)}",
					delta_color="inverse")
				st.dataframe(ocr_df, width="stretch", hide_index=True)
				if unknown:
					st.warning(f"⚠️ {len(unknown)} 个未识别色号:"+
						", ".join(f"{c}({n})" for c,n in unknown[:20]))

				d1,d2,d3 = st.columns(3)
				d1.download_button("⬇️ 导出 CSV",
					ocr_df.to_csv(index=False).encode("utf-8-sig"),
					file_name="ocr_recognized.csv", mime="text/csv",
					width="stretch")
				if d2.button("➖ 从库存中扣减", type="primary",
				             width="stretch", key="ocr_deduct"):
					updates = {c: max(0, inv_now.get(c,0)-n) for c,n in items}
					db.save_inventory(updates)
					if ocr_id:
						db.mark_ocr_deducted(ocr_id)
					st.success(f"✅ 已扣减 {len(updates)} 个色号" + (
						f" · 其中 {len(shortage_items)} 个色号原本不足,已扣到 0"
						if shortage_items else ""))
					for k in ("ocr_parsed","ocr_raw_lines","ocr_unknown","ocr_id"):
						st.session_state.pop(k, None)
					st.rerun()
				if d3.button("🗑️ 清空", width="stretch", key="ocr_clear"):
					for k in ("ocr_parsed","ocr_raw_lines","ocr_unknown","ocr_id"):
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
			for code, need in items:
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