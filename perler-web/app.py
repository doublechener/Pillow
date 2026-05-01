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
                   palette, cell_size, show_grid):
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
    cell_size = st.slider("格子像素", 8, 60, 20, step=2)
    show_grid = st.checkbox("显示网格", value=True)

    st.divider()
    st.header("📦 库存")
    check_inventory = st.checkbox("启用库存校验", value=True)
    only_in_stock = st.checkbox("仅使用有库存的颜色", value=False)

# ============================================================
# 主区:三个 Tab
# ============================================================
tab_gen, tab_inv, tab_palette = st.tabs(["🖼️ 生成图纸", "📦 编辑库存", "🎨 色板"])

# ---------- Tab 1: 生成图纸 ----------
with tab_gen:
    uploaded = st.file_uploader("上传图片", type=["png", "jpg", "jpeg", "webp", "bmp"])
    col_l, col_r = st.columns(2)

    if uploaded:
        src = Image.open(uploaded)
        with col_l:
            st.subheader("原图预览")
            st.image(src, use_container_width=True)

        if st.button("🚀 生成拼豆图纸", type="primary", use_container_width=True):
            inv = db.load_inventory() if check_inventory else None
            palette = MARD_PALETTE
            if only_in_stock and inv:
                palette = {k: v for k, v in palette.items() if inv.get(k, 0) > 0}
                st.info(f"📦 仅使用有库存的颜色,共 {len(palette)} 种可用")

            with st.spinner("正在生成…"):
                pattern_img, bead_count = image_to_perler(
                    src, width_beads, height_beads,
                    palette, cell_size, show_grid,
                )
                legend_img = generate_legend(
                    bead_count, MARD_PALETTE,
                    inv if check_inventory else None,
                )

            with col_r:
                st.subheader("拼豆图纸")
                st.image(pattern_img, use_container_width=True)
                st.download_button(
                    "⬇️ 下载图纸 PNG",
                    pil_to_bytes(pattern_img),
                    file_name="perler_pattern.png",
                    mime="image/png",
                    use_container_width=True,
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

            st.dataframe(df_use, use_container_width=True, hide_index=True)

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
                st.dataframe(shortage_df, use_container_width=True, hide_index=True)
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
            use_container_width=True,
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
    if b1.button("💾 保存修改", type="primary", use_container_width=True):
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
        use_container_width=True,
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
            series_df, use_container_width=True, hide_index=True,
            column_config={
                "总颗数": st.column_config.NumberColumn("总颗数", format="%d"),
            },
        )

# ---------- Tab 3: 色板 ----------
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