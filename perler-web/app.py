import base64
import io
import os
from collections import Counter

import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

from palette import MARD_PALETTE, BEAD_INVENTORY
import db

# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="拼豆图纸生成器",
    page_icon="🎨",
    layout="wide",
)

st.title("🎨 拼豆图纸生成器")
st.caption("基于 MARD 拼豆 221 色官方色板 · 支持库存校验 · 一键下载图纸")

# ============================================================
# 核心算法(从 CLI 版本移植,纯函数化)
# ============================================================
def rgb_distance(c1, c2):
    r1, g1, b1 = c1
    r2, g2, b2 = c2
    return (r1 - r2) ** 2 * 0.3 + (g1 - g2) ** 2 * 0.59 + (b1 - b2) ** 2 * 0.11


def find_nearest_color(pixel_rgb, palette):
    best_name, best_rgb, min_d = None, None, float("inf")
    for name, rgb in palette.items():
        d = rgb_distance(pixel_rgb, rgb)
        if d < min_d:
            min_d, best_name, best_rgb = d, name, rgb
    return best_name, best_rgb


def image_to_perler(img: Image.Image, width_beads, height_beads,
                   palette, cell_size, show_grid, show_codes=False):
    img = img.convert("RGBA")
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    img = Image.alpha_composite(bg, img).convert("RGB")

    if height_beads is None:
        ow, oh = img.size
        height_beads = int(round(width_beads * oh / ow))

    img_small = img.resize((width_beads, height_beads), Image.Resampling.LANCZOS)
    # 重要:转成 int32,避免 uint8 减法下溢导致距离计算错误
    pixels = np.array(img_small, dtype=np.int32)

    # 向量化颜色匹配:一次性对所有像素计算到色板中所有颜色的加权距离
    palette_names = list(palette.keys())
    palette_rgb = np.array([palette[n] for n in palette_names], dtype=np.int32)  # (P,3)
    weights = np.array([0.3, 0.59, 0.11], dtype=np.float32)

    flat = pixels.reshape(-1, 3).astype(np.int32)                       # (N,3)
    diff = flat[:, None, :] - palette_rgb[None, :, :]                   # (N,P,3)
    dist = (diff * diff).astype(np.float32) @ weights                   # (N,P)
    nearest_idx = dist.argmin(axis=1).reshape(height_beads, width_beads)

    bead_count = Counter()
    rgb_grid = [[None] * width_beads for _ in range(height_beads)]
    for y in range(height_beads):
        for x in range(width_beads):
            idx = int(nearest_idx[y, x])
            name = palette_names[idx]
            rgb_grid[y][x] = tuple(int(v) for v in palette_rgb[idx])
            bead_count[name] += 1

    canvas = Image.new("RGB",
                       (width_beads * cell_size, height_beads * cell_size),
                       (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    for y in range(height_beads):
        for x in range(width_beads):
            x0, y0 = x * cell_size, y * cell_size
            draw.rectangle([x0, y0, x0 + cell_size, y0 + cell_size],
                           fill=rgb_grid[y][x])
    if show_grid:
        for x in range(width_beads + 1):
            draw.line([(x * cell_size, 0),
                       (x * cell_size, height_beads * cell_size)],
                      fill=(220, 220, 220), width=1)
        for y in range(height_beads + 1):
            draw.line([(0, y * cell_size),
                       (width_beads * cell_size, y * cell_size)],
                      fill=(220, 220, 220), width=1)

    # 在每格上叠加色号文字(类似官方拼豆图样式)
    if show_codes and cell_size >= 12:
        font_size = max(7, int(cell_size * 0.42))
        code_font = _load_font(font_size)
        for y in range(height_beads):
            for x in range(width_beads):
                idx = int(nearest_idx[y, x])
                name = palette_names[idx]
                r, g, b = rgb_grid[y][x]
                # 感知亮度:亮底用黑字,暗底用白字
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                text_color = (0, 0, 0) if lum > 140 else (255, 255, 255)
                bbox = draw.textbbox((0, 0), name, font=code_font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                x0, y0 = x * cell_size, y * cell_size
                tx = x0 + (cell_size - tw) // 2 - bbox[0]
                ty = y0 + (cell_size - th) // 2 - bbox[1]
                draw.text((tx, ty), name, fill=text_color, font=code_font)

    return canvas, bead_count


def _load_font(size=16):
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def generate_legend(bead_count, palette, inventory, cell_size=30):
    items = bead_count.most_common()
    row_h = cell_size + 10
    img = Image.new("RGB", (520, row_h * len(items) + 60), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    font = _load_font(16)
    draw.text((20, 10), "MARD 拼豆用量图例", fill=(30, 30, 30), font=font)
    y = 40
    for name, count in items:
        color = palette.get(name, (200, 200, 200))
        draw.rectangle([20, y, 20 + cell_size, y + cell_size],
                       fill=color, outline=(100, 100, 100))
        if inventory is not None:
            stock = inventory.get(name, 0)
            tag = "✅" if stock >= count else f"❌ 缺{count - stock}"
            text = f"{name}  —  需{count}颗  库存{stock}  {tag}"
        else:
            text = f"{name}  —  {count} 颗"
        draw.text((20 + cell_size + 15, y + 5), text,
                  fill=(30, 30, 30), font=font)
        y += row_h
    return img


def pil_to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ============================================================
# 库存初始化(SQLite + JSON 持久化,详见 db.py)
# - 首次启动 inventory.db 不存在 → 优先从 inventory.json 水合
# - JSON 也不存在 → 从 BEAD_INVENTORY 出厂值水合,并自动生成 inventory.json
# ============================================================
db.init_db(default_inventory=BEAD_INVENTORY)

# ============================================================
# 侧边栏:参数
# ============================================================
with st.sidebar:
    st.header("⚙️ 参数设置")
    width_beads = st.slider("横向豆数", 10, 120, 29, step=1)
    auto_height = st.checkbox("按比例自动计算高度", value=True)
    if auto_height:
        height_beads = None
    else:
        height_beads = st.slider("纵向豆数", 10, 120, 29, step=1)
    cell_size = st.slider("格子像素", 8, 60, 22, step=2)
    show_grid = st.checkbox("显示网格", value=True)
    show_codes = st.checkbox(
        "在格子里写色号(A5/H7…)", value=True,
        help="类似官方拼豆图,在每格中央叠加色号。格子像素 ≥ 12 时才会显示。",
    )

    st.divider()
    st.header("📦 库存")
    check_inventory = st.checkbox("启用库存校验", value=True)
    only_in_stock = st.checkbox("仅使用有库存的颜色", value=False)

# ============================================================
# 主区:三个 Tab
# ============================================================
tab_gen, tab_inv, tab_recognize, tab_palette = st.tabs(
    ["🖼️ 生成图纸", "📦 编辑库存", "🔍 识别已有拼豆图", "🎨 色板"]
)

# ---------- Tab 1: 生成图纸 ----------
with tab_gen:
    uploaded = st.file_uploader("上传图片", type=["png", "jpg", "jpeg", "webp", "bmp"])
    col_l, col_r = st.columns(2)

    if uploaded:
        src = Image.open(uploaded)
        with col_l:
            st.subheader("原图预览")
            st.image(src, width="stretch")

        if st.button("🚀 生成拼豆图纸", type="primary", width="stretch"):
            inv = db.load_inventory() if check_inventory else None
            palette = MARD_PALETTE
            if only_in_stock and inv:
                palette = {k: v for k, v in palette.items() if inv.get(k, 0) > 0}
                st.info(f"📦 仅使用有库存的颜色,共 {len(palette)} 种可用")

            with st.spinner("正在生成…"):
                pattern_img, bead_count = image_to_perler(
                    src, width_beads, height_beads,
                    palette, cell_size, show_grid, show_codes,
                )
                legend_img = generate_legend(
                    bead_count, MARD_PALETTE,
                    inv if check_inventory else None,
                )

            with col_r:
                st.subheader("拼豆图纸")
                st.image(pattern_img, width="stretch")
                st.download_button(
                    "⬇️ 下载图纸 PNG",
                    pil_to_bytes(pattern_img),
                    file_name="perler_pattern.png",
                    mime="image/png",
                    width="stretch",
                )

            st.divider()
            st.subheader("📊 用量统计")

            rows = []
            shortage = 0
            inv_now = db.load_inventory() if check_inventory else {}
            for name, count in bead_count.most_common():
                if check_inventory:
                    stock = inv_now.get(name, 0)
                    diff = stock - count
                    status = "✅ 充足" if diff >= 0 else f"❌ 缺{-diff}"
                    if diff < 0:
                        shortage += 1
                    rows.append({"色号": name, "需要": count, "库存": stock, "状态": status})
                else:
                    rgb = MARD_PALETTE.get(name, (0, 0, 0))
                    rows.append({"色号": name, "需要": count, "RGB": str(rgb)})
            df_use = pd.DataFrame(rows)

            c1, c2, c3 = st.columns(3)
            c1.metric("总豆数", sum(bead_count.values()))
            c2.metric("颜色种类", len(bead_count))
            if check_inventory:
                c3.metric("需补货色号", shortage,
                          delta=None if shortage == 0 else f"-{shortage}",
                          delta_color="inverse")

            st.dataframe(df_use, width="stretch", hide_index=True)

            st.subheader("🏷️ 颜色图例")
            st.image(legend_img)
            st.download_button(
                "⬇️ 下载图例 PNG",
                pil_to_bytes(legend_img),
                file_name="legend.png",
                mime="image/png",
            )

            if check_inventory and shortage > 0:
                st.warning(f"🛒 共 {shortage} 种颜色需要补货")
                shortage_df = df_use[df_use["状态"].str.startswith("❌")]
                st.dataframe(shortage_df, width="stretch", hide_index=True)
                st.download_button(
                    "⬇️ 下载补货清单 CSV",
                    shortage_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name="shortage.csv",
                    mime="text/csv",
                )
    else:
        st.info("👈 在上方上传一张图片开始")

# ---------- Tab 2: 编辑库存(SQLite 持久化) ----------
def _color_swatch_data_url(rgb, size=32):
    """生成色块的 data URL,用于 ImageColumn 显示真实颜色"""
    img = Image.new("RGB", (size, size), tuple(rgb))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


SERIES_LABELS = {
    "A": "黄橙暖色", "B": "绿色",     "C": "蓝青色",
    "D": "紫蓝色",   "E": "粉色",     "F": "红色",
    "G": "棕肤色",   "H": "黑白灰",   "M": "莫兰迪",
}

with tab_inv:
    # 每次 rerun 都从 SQLite 读最新数据(单一数据源)
    inv = db.load_inventory()
    last_ts = db.last_updated()

    # ---- 顶部指标卡 ----
    total_colors = len(inv)
    in_stock_colors = sum(1 for v in inv.values() if v > 0)
    oos_colors = total_colors - in_stock_colors
    total_beads = sum(inv.values())
    coverage = in_stock_colors * 100 // total_colors if total_colors else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🎨 总色号", total_colors)
    m2.metric("✅ 有库存", f"{in_stock_colors}", f"覆盖 {coverage}%")
    m3.metric("❌ 缺货色号", oos_colors,
              delta=None if oos_colors == 0 else f"-{oos_colors}",
              delta_color="inverse")
    m4.metric("📦 库存总颗数", f"{total_beads:,}")
    if last_ts:
        st.caption(f"🕒 数据库最近更新: {last_ts}")

    st.divider()

    # ---- 过滤栏 ----
    f1, f2, f3 = st.columns([3, 2, 3])
    all_series = sorted({k[0] for k in inv.keys()})
    series_filter = f1.multiselect(
        "系列筛选",
        all_series,
        default=all_series,
        format_func=lambda s: f"{s} · {SERIES_LABELS.get(s, '')}",
    )
    status_filter = f2.radio(
        "状态", ["全部", "有库存", "缺货"], horizontal=True,
    )
    search_text = f3.text_input("🔍 搜索色号", placeholder="例如 A12、H7")

    # ---- 构造表格数据 ----
    rows = []
    for code, stock in inv.items():
        if code[0] not in series_filter:
            continue
        if status_filter == "有库存" and stock <= 0:
            continue
        if status_filter == "缺货" and stock > 0:
            continue
        if search_text and search_text.strip().upper() not in code.upper():
            continue
        r, g, b = MARD_PALETTE.get(code, (200, 200, 200))
        rows.append({
            "色块": _color_swatch_data_url((r, g, b)),
            "色号": code,
            "系列": code[0],
            "RGB": f"({r}, {g}, {b})",
            "库存": int(stock),
            "状态": "✅ 有货" if stock > 0 else "❌ 缺货",
        })

    df = pd.DataFrame(rows)

    if df.empty:
        st.info("当前筛选条件下没有色号,试试放宽筛选。")
        edited = df
    else:
        st.caption(f"当前显示 {len(df)} 个色号 · 双击「库存」单元格修改,然后点下方「保存修改」写入数据库")
        edited = st.data_editor(
            df,
            width="stretch",
            height=520,
            hide_index=True,
            column_config={
                "色块": st.column_config.ImageColumn("色块", width="small"),
                "色号": st.column_config.TextColumn("色号", width="small"),
                "系列": st.column_config.TextColumn("系列", width="small"),
                "RGB": st.column_config.TextColumn("RGB"),
                "库存": st.column_config.NumberColumn(
                    "库存 (颗)", min_value=0, step=1, format="%d",
                    help="双击修改数量,点下方「保存修改」写入 SQLite",
                ),
                "状态": st.column_config.TextColumn("状态", width="small"),
            },
            disabled=["色块", "色号", "系列", "RGB", "状态"],
            key="inv_editor",
        )

    st.divider()

    # ---- 操作按钮 ----
    b1, b2, b3 = st.columns(3)
    if b1.button("💾 保存修改", type="primary", width="stretch"):
        if not df.empty:
            updates = {
                row["色号"]: int(row["库存"] or 0)
                for _, row in edited.iterrows()
            }
            db.save_inventory(updates)
            st.success(
                f"✅ 已写入 SQLite 数据库,并自动同步到 inventory.json"
                f"(更新 {len(updates)} 个色号)"
            )
            st.rerun()

    full_csv = pd.DataFrame(
        [{"色号": k, "库存": v} for k, v in inv.items()]
    ).to_csv(index=False).encode("utf-8-sig")
    b2.download_button(
        "⬇️ 导出全部 CSV",
        full_csv,
        file_name="inventory.csv",
        mime="text/csv",
        width="stretch",
    )

    upload_csv = b3.file_uploader(
        "📤 导入 CSV(覆盖整个库存)", type="csv",
        label_visibility="collapsed",
    )
    if upload_csv:
        new_df = pd.read_csv(upload_csv)
        new_inv = {
            row["色号"]: int(row["库存"] or 0)
            for _, row in new_df.iterrows()
            if pd.notna(row.get("色号"))
        }
        db.replace_all(new_inv)
        st.success(f"✅ 已从 CSV 导入 {len(new_inv)} 条库存,数据库已更新")
        st.rerun()

    # ---- 同步到云端 ----
    with st.expander("☁️ 同步到 Streamlit Cloud(推送 inventory.json)", expanded=False):
        st.markdown(
            "本地修改会自动写入两个文件:\n\n"
            "- `inventory.db` — SQLite 数据库(本地用,不进 Git)\n"
            "- `inventory.json` — 文本备份(**这个要提交**,云端数据源)\n\n"
            "**让 Streamlit Cloud 上的访客看到最新数据,只需 push `inventory.json`:**"
        )
        st.code(
            "git add inventory.json\n"
            "git commit -m \"update: 库存数据\"\n"
            "git push",
            language="powershell",
        )
        st.caption("推送后 Streamlit Cloud 会在约 30 秒内自动重新部署。")

    # ---- 各系列概览 ----
    with st.expander("📊 各系列库存概览", expanded=False):
        series_stats = {}
        for code, stock in inv.items():
            s = code[0]
            stat = series_stats.setdefault(
                s, {"色号数": 0, "有库存": 0, "总颗数": 0}
            )
            stat["色号数"] += 1
            stat["总颗数"] += stock
            if stock > 0:
                stat["有库存"] += 1
        series_df = pd.DataFrame([
            {
                "系列": f"{s} · {SERIES_LABELS.get(s, '')}",
                **v,
                "覆盖率": f"{v['有库存'] * 100 // v['色号数']}%",
            }
            for s, v in sorted(series_stats.items())
        ])
        st.dataframe(
            series_df, width="stretch", hide_index=True,
            column_config={
                "总颗数": st.column_config.NumberColumn("总颗数", format="%d"),
            },
        )

# ---------- Tab 3: 识别已有拼豆图(反向计数 + 扣减库存) ----------
with tab_recognize:
    st.subheader("🔍 识别已有拼豆图")
    st.caption(
        "两种识别方式:① OCR 直接读图例文字(推荐,精度最高);"
        "② 逐格采样色块颜色(适合无图例的图)。识别后可一键扣减库存。"
    )

    rec_mode = st.radio(
        "识别方式",
        ["📋 OCR 读图例文字(推荐)", "🎨 整图逐格识别色块"],
        horizontal=True,
        key="rec_mode",
    )

    # ============================================================
    # 模式 A:OCR 读图例文字(推荐)
    # ============================================================
    if rec_mode.startswith("📋"):
        st.info(
            "📋 适用于带图例文字的拼豆图(图例形如 `A5 (191)  A7 (119) …`)。"
            "直接 OCR 解析,无需输入格数,精度最高。"
        )

        @st.cache_resource(show_spinner="正在加载 OCR 模型(首次约 10 秒)…")
        def _get_ocr_engine():
            """返回 (engine, error_message)。失败时 engine=None,error_message 含真实 traceback。"""
            try:
                from rapidocr_onnxruntime import RapidOCR
                return RapidOCR(), None
            except Exception as e:
                import traceback
                return None, f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"

        ocr_file = st.file_uploader(
            "上传带图例的拼豆图",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            key="ocr_uploader",
        )
        ocr_crop = st.slider(
            "只 OCR 图片底部 X% 区域(图例通常在底部)",
            10, 100, 25, step=5, key="ocr_crop_pct",
            help="数值越小越只看底部图例,过滤掉上方拼豆主体的色号文字;"
                 "如果图例在顶部或没有图例,设为 100 全图 OCR。",
        )

        if ocr_file:
            ocr_img = Image.open(ocr_file).convert("RGB")
            arr_ocr = np.array(ocr_img)
            Ho, Wo = arr_ocr.shape[:2]
            cut = Ho * (100 - ocr_crop) // 100
            legend_arr = arr_ocr[cut:, :]
            legend_img = Image.fromarray(legend_arr)

            cp1, cp2 = st.columns(2)
            cp1.image(ocr_img, caption=f"原图 {Wo}×{Ho}",
                      width="stretch")
            cp2.image(
                legend_img,
                caption=f"OCR 区域 {legend_arr.shape[1]}×{legend_arr.shape[0]}",
                width="stretch",
            )

            if st.button("🔬 开始 OCR 识别", type="primary",
                         width="stretch", key="ocr_run"):
                engine, ocr_err = _get_ocr_engine()
                if engine is None:
                    st.error(
                        "❌ OCR 引擎加载失败。常见原因:\n\n"
                        "1. **Python 版本**:`rapidocr-onnxruntime` 要求 Python <3.13。"
                        "在 Streamlit Cloud → Settings → Advanced settings 把 Python 改成 3.12。\n\n"
                        "2. **缺系统库 libGL.so.1**:在 `perler-web/packages.txt` 加 `libgl1`、"
                        "`libglib2.0-0`,push 后 Cloud 会自动 apt 安装。\n\n"
                        "3. **包没装**:确认 `requirements.txt` 含 `rapidocr-onnxruntime>=1.3,<1.5`。\n\n"
                        f"**真实错误 traceback**:\n```\n{ocr_err}\n```"
                    )
                else:
                    with st.spinner("OCR 中…"):
                        result, _elapse = engine(legend_arr)
                    if not result:
                        st.warning("OCR 没读到任何文字,试试调大「OCR 区域」百分比。")
                    else:
                        import re
                        texts = [r[1] for r in result]
                        all_text = " ".join(texts)
                        # 匹配「字母+数字(计数)」,字母限定 A-H 或 M
                        pattern = re.compile(
                            r"([A-Ha-hMm])\s*(\d{1,2})\s*"
                            r"[\(（]\s*(\d{1,5})\s*[\)）]"
                        )
                        matches = pattern.findall(all_text)

                        parsed = {}
                        unknown = []
                        for letter, num, count in matches:
                            code = letter.upper() + num
                            if code in MARD_PALETTE:
                                parsed[code] = parsed.get(code, 0) + int(count)
                            else:
                                unknown.append((code, int(count)))

                        st.session_state["ocr_parsed"] = parsed
                        st.session_state["ocr_raw_lines"] = texts
                        st.session_state["ocr_unknown"] = unknown

        if st.session_state.get("ocr_parsed") is not None:
            parsed = st.session_state["ocr_parsed"]
            raw_lines = st.session_state.get("ocr_raw_lines", [])
            unknown = st.session_state.get("ocr_unknown", [])

            st.divider()
            st.subheader("✅ OCR 解析结果")

            with st.expander(f"🔍 OCR 原始文字({len(raw_lines)} 段)",
                             expanded=False):
                st.code("\n".join(raw_lines))

            if not parsed:
                st.warning(
                    "没有匹配到「色号(数量)」格式的文字。"
                    "请确认图例区域被裁进 OCR 范围,或换用「整图逐格识别色块」模式。"
                )
            else:
                inv_now = db.load_inventory()
                items = sorted(parsed.items(), key=lambda x: -x[1])
                rows = []
                shortage = 0
                for code, need in items:
                    stock = inv_now.get(code, 0)
                    diff = stock - need
                    if diff < 0:
                        shortage += 1
                    rows.append({
                        "色号": code,
                        "需要": need,
                        "库存": stock,
                        "扣减后": max(0, diff),
                        "状态": "✅ 充足" if diff >= 0 else f"❌ 缺{-diff}",
                    })
                ocr_df = pd.DataFrame(rows)

                m1, m2, m3 = st.columns(3)
                m1.metric("总豆数", sum(n for _, n in items))
                m2.metric("色号种类", len(items))
                m3.metric(
                    "需补货色号", shortage,
                    delta=None if shortage == 0 else f"-{shortage}",
                    delta_color="inverse",
                )

                st.dataframe(ocr_df, width="stretch", hide_index=True)

                if unknown:
                    st.warning(
                        f"⚠️ 解析到 {len(unknown)} 个不在 MARD 色板中的色号"
                        "(疑似 OCR 误识),已忽略:"
                        + ", ".join(f"{c}({n})" for c, n in unknown[:20])
                    )

                d1, d2, d3 = st.columns(3)
                d1.download_button(
                    "⬇️ 导出 CSV",
                    ocr_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name="ocr_recognized.csv",
                    mime="text/csv",
                    width="stretch",
                )
                if d2.button("➖ 从库存中扣减", type="primary",
                             width="stretch", key="ocr_deduct"):
                    updates = {}
                    for code, need in items:
                        updates[code] = max(0, inv_now.get(code, 0) - need)
                    db.save_inventory(updates)
                    st.success(
                        f"✅ 已扣减 {len(updates)} 个色号(库存不会变成负数)。"
                    )
                    st.session_state.pop("ocr_parsed", None)
                    st.session_state.pop("ocr_raw_lines", None)
                    st.session_state.pop("ocr_unknown", None)
                    st.rerun()
                if d3.button("🗑️ 清空", width="stretch",
                             key="ocr_clear"):
                    st.session_state.pop("ocr_parsed", None)
                    st.session_state.pop("ocr_raw_lines", None)
                    st.session_state.pop("ocr_unknown", None)
                    st.rerun()

    # ============================================================
    # 模式 B:整图逐格识别色块(原有逻辑,适合无图例图)
    # ============================================================
    else:
        st.info("🎨 适用于纯色块拼豆图(无图例文字)。需要手动输入横/纵格数。")

        rec_file = st.file_uploader(
            "上传拼豆图图片",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            key="rec_uploader",
        )

        rc1, rc2, rc3 = st.columns(3)
        rec_w = rc1.number_input("横向格数", 2, 300, 50, step=1, key="rec_w")
        rec_h = rc2.number_input("纵向格数", 2, 300, 45, step=1, key="rec_h")
        sample_mode = rc3.selectbox(
            "采样方式", ["格子中心 60% 均值", "中心单像素"], index=0,
            help="均值更鲁棒,能避开网格线和文字;单像素更快。",
        )

        rc4, rc5, rc6, rc7 = st.columns(4)
        crop_left = rc4.slider("裁左 %", 0, 40, 0, key="rec_cl")
        crop_right = rc5.slider("裁右 %", 0, 40, 0, key="rec_cr")
        crop_top = rc6.slider("裁上 %", 0, 40, 0, key="rec_ct")
        crop_bottom = rc7.slider("裁下 %", 0, 40, 0, key="rec_cb")
        st.caption(
            "⚠️ 如果图片包含坐标轴 / 图例 / 水印边框,请先用裁剪滑块把它们去掉,"
            "只留纯色块网格区域。横/纵格数要与图纸真实格子数一致。"
        )

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
            pcol1.image(rec_img, caption=f"原图 {W}×{H}",
                        width="stretch")
            pcol2.image(
                cropped_preview,
                caption=f"裁剪后 {arr.shape[1]}×{arr.shape[0]}",
                width="stretch",
            )

            if st.button("🔬 开始识别", type="primary",
                         width="stretch", key="rec_run"):
                HH, WW = arr.shape[:2]
                cw = WW / rec_w
                ch = HH / rec_h

                palette_names = list(MARD_PALETTE.keys())
                palette_rgb = np.array(
                    [MARD_PALETTE[n] for n in palette_names], dtype=np.int32
                )
                weights = np.array([0.3, 0.59, 0.11], dtype=np.float32)

                recognized = [[None] * int(rec_w) for _ in range(int(rec_h))]
                with st.spinner("识别中…"):
                    for yy in range(int(rec_h)):
                        for xx in range(int(rec_w)):
                            gx0 = int(xx * cw)
                            gx1 = int((xx + 1) * cw)
                            gy0 = int(yy * ch)
                            gy1 = int((yy + 1) * ch)
                            if sample_mode == "中心单像素":
                                sample = arr[(gy0 + gy1) // 2, (gx0 + gx1) // 2]
                            else:
                                mx0 = gx0 + (gx1 - gx0) * 2 // 10
                                mx1 = gx1 - (gx1 - gx0) * 2 // 10
                                my0 = gy0 + (gy1 - gy0) * 2 // 10
                                my1 = gy1 - (gy1 - gy0) * 2 // 10
                                if mx1 <= mx0 or my1 <= my0:
                                    sample = arr[(gy0 + gy1) // 2,
                                                  (gx0 + gx1) // 2]
                                else:
                                    sample = arr[my0:my1, mx0:mx1].mean(axis=(0, 1))
                            diff = sample.astype(np.int32) - palette_rgb
                            dist = (diff * diff).astype(np.float32) @ weights
                            idx = int(dist.argmin())
                            recognized[yy][xx] = palette_names[idx]

                counter = Counter()
                for row in recognized:
                    for name in row:
                        counter[name] += 1

                # 重建预览图(用识别到的色号渲染)
                preview = Image.new(
                    "RGB", (int(rec_w) * 16, int(rec_h) * 16), (255, 255, 255)
                )
                pdraw = ImageDraw.Draw(preview)
                for yy in range(int(rec_h)):
                    for xx in range(int(rec_w)):
                        pdraw.rectangle(
                            [xx * 16, yy * 16, (xx + 1) * 16, (yy + 1) * 16],
                            fill=MARD_PALETTE[recognized[yy][xx]],
                        )

                st.session_state["rec_counter"] = dict(counter)
                st.session_state["rec_preview_bytes"] = pil_to_bytes(preview)

        if st.session_state.get("rec_counter"):
            counter = st.session_state["rec_counter"]
            st.divider()
            st.subheader("✅ 识别结果")

            st.image(
                st.session_state["rec_preview_bytes"],
                caption="识别结果重建图(用于核对识别准确度)",
            )

            ex1, ex2 = st.columns(2)
            exclude_h1 = ex1.checkbox(
                "排除 H1 纯白(常作背景)", value=True, key="rec_ex_h1",
            )
            exclude_h2 = ex2.checkbox(
                "排除 H2 接近白(常作背景)", value=False, key="rec_ex_h2",
            )

            excludes = set()
            if exclude_h1:
                excludes.add("H1")
            if exclude_h2:
                excludes.add("H2")

            items = sorted(
                [(k, v) for k, v in counter.items() if k not in excludes],
                key=lambda x: -x[1],
            )

            inv_now = db.load_inventory()
            rows = []
            shortage = 0
            for code, need in items:
                stock = inv_now.get(code, 0)
                diff = stock - need
                if diff < 0:
                    shortage += 1
                rows.append({
                    "色号": code,
                    "需要": need,
                    "库存": stock,
                    "扣减后": max(0, diff),
                    "状态": "✅ 充足" if diff >= 0 else f"❌ 缺{-diff}",
                })
            rec_df = pd.DataFrame(rows)

            m1, m2, m3 = st.columns(3)
            m1.metric("总豆数", sum(n for _, n in items))
            m2.metric("颜色种类", len(items))
            m3.metric(
                "需补货色号", shortage,
                delta=None if shortage == 0 else f"-{shortage}",
                delta_color="inverse",
            )

            st.dataframe(rec_df, width="stretch", hide_index=True)

            d1, d2, d3 = st.columns(3)
            d1.download_button(
                "⬇️ 导出识别用量 CSV",
                rec_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="recognized_usage.csv",
                mime="text/csv",
                width="stretch",
            )
            if d2.button("➖ 从库存中扣减", type="primary",
                         width="stretch", key="rec_deduct"):
                updates = {}
                for code, need in items:
                    updates[code] = max(0, inv_now.get(code, 0) - need)
                db.save_inventory(updates)
                st.success(
                    f"✅ 已扣减 {len(updates)} 个色号(库存不会变成负数)。"
                    "切到「编辑库存」标签页可见最新结果。"
                )
                st.session_state.pop("rec_counter", None)
                st.session_state.pop("rec_preview_bytes", None)
                st.rerun()
            if d3.button("🗑️ 清空识别结果", width="stretch",
                         key="rec_clear"):
                st.session_state.pop("rec_counter", None)
                st.session_state.pop("rec_preview_bytes", None)
                st.rerun()


# ---------- Tab 4: 色板 ----------
with tab_palette:
    st.subheader("MARD 221 色色板")
    cols_per_row = 12
    names = list(MARD_PALETTE.keys())
    for i in range(0, len(names), cols_per_row):
        row = st.columns(cols_per_row)
        for j, name in enumerate(names[i:i + cols_per_row]):
            r, g, b = MARD_PALETTE[name]
            row[j].markdown(
                f"<div style='background:rgb({r},{g},{b});"
                f"height:40px;border-radius:4px;border:1px solid #ccc;'></div>"
                f"<div style='text-align:center;font-size:11px;'>{name}</div>",
                unsafe_allow_html=True,
            )