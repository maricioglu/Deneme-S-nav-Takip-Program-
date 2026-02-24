import re
import os
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from supabase import create_client

# PDF (ReportLab)
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --------------------
# AYARLAR
# --------------------
st.set_page_config(page_title="Akademik Takip (5-8)", layout="wide")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

TABLE = "lgs_results"
LOGO_PATH = "assets/images/logo.jpg"  # varsa kullanılır
FONT_PATH = "assets/fonts/DejaVuSans.ttf"  # Türkçe için

# --------------------
# STİL
# --------------------
st.markdown("""
<style>
/* Layout */
.main .block-container {max-width: 1280px; padding-top: 1.2rem; padding-bottom: 2.2rem;}
/* Soft background */
.stApp {
  background:
    radial-gradient(1100px 600px at 8% 10%, rgba(0, 122, 255, 0.10), transparent 55%),
    radial-gradient(900px 500px at 92% 18%, rgba(255, 153, 0, 0.10), transparent 55%),
    radial-gradient(1000px 700px at 50% 100%, rgba(0, 200, 150, 0.08), transparent 60%);
}
/* Card look */
.card {
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 18px;
  padding: 14px 16px;
  background: rgba(255,255,255,0.04);
  box-shadow: 0 8px 24px rgba(0,0,0,0.08);
}
.kpi-row {display:flex; gap:12px; flex-wrap:wrap;}
.kpi-card{flex:1; min-width:220px;}
.kpi-title{font-size:12px; opacity:.75; margin-bottom:4px;}
.kpi-value{font-size:28px; font-weight:800; letter-spacing:0.2px;}
.kpi-sub{font-size:12px; opacity:.65; margin-top:2px;}
/* Section header */
.section-title{
  font-size: 15px;
  font-weight: 800;
  margin: 8px 0 10px 0;
  display:flex; align-items:center; gap:8px;
}
.badge{
  display:inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11px;
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.10);
}
/* Buttons */
.stButton>button, .stDownloadButton>button{
  border-radius: 12px !important;
  padding: 0.55rem 0.9rem !important;
  font-weight: 700 !important;
}
/* Tabs */
.stTabs [data-baseweb="tab-list"] {gap: 6px;}
.stTabs [data-baseweb="tab"]{
  border-radius: 12px !important;
  padding: 10px 14px !important;
  background: rgba(255,255,255,0.05);
}
.stTabs [aria-selected="true"]{
  background: rgba(0,122,255,0.18) !important;
  border: 1px solid rgba(0,122,255,0.25) !important;
}
/* Dataframe nicer */
[data-testid="stDataFrame"] {border-radius: 14px; overflow:hidden; border: 1px solid rgba(255,255,255,0.10);}
</style>
""", unsafe_allow_html=True)

# --------------------
# YARDIMCI
# --------------------
def make_unique_columns(col_list):
    seen = {}
    out = []
    for c in col_list:
        name = str(c).strip()
        if name == "" or name.lower() in ["none", "nan"]:
            name = "Kolon"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out

def extract_kademe(sinif: str):
    if not sinif:
        return None
    m = re.match(r"^\s*(\d+)\s*[-/ ]", str(sinif))
    if m:
        return int(m.group(1))
    m2 = re.match(r"^\s*(\d+)", str(sinif))
    if m2:
        return int(m2.group(1))
    return None

@st.cache_data(show_spinner=False)
def parse_school_report(uploaded_file):
    raw = pd.read_excel(uploaded_file, header=None)
    raw = raw.dropna(axis=1, how="all")

    exam_name = "Deneme"
    try:
        v = raw.iloc[1, 0]
        if pd.notna(v):
            exam_name = str(v).strip()
    except Exception:
        pass

    header_idx = None
    for i in range(len(raw)):
        if str(raw.iloc[i, 0]).strip() == "Öğr.No":
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Başlık satırı bulunamadı: 'Öğr.No' yok.")

    grp = raw.iloc[header_idx - 2].copy().ffill()
    top = raw.iloc[header_idx - 1].copy().ffill()
    sub = raw.iloc[header_idx].copy()

    cols = []
    for j in range(len(sub)):
        g = str(grp.iloc[j]).strip() if pd.notna(grp.iloc[j]) else ""
        t = str(top.iloc[j]).strip() if pd.notna(top.iloc[j]) else ""
        s = str(sub.iloc[j]).strip() if pd.notna(sub.iloc[j]) else ""

        if j == 0:
            cols.append("OgrNo")
        elif j == 1:
            cols.append("AdSoyad")
        elif j == 2:
            cols.append("Sinif")
        else:
            if g.lower() == "lgs" and t.lower() == "puan":
                cols.append("LGS_Puan")
            elif t.lower() == "dereceler" and s in ["Sınıf", "Kurum", "İlçe", "İl", "Genel"]:
                cols.append(f"Derece_{s}")
            elif s in ["D", "Y", "N"]:
                cols.append(f"{t}_{s}")
            else:
                base = t if t else g if g else f"Kolon_{j}"
                suffix = f"_{s}" if s else ""
                cols.append(f"{base}{suffix}")

    cols = make_unique_columns(cols)

    df = raw.iloc[header_idx + 1:].copy()
    df.columns = cols
    df = df.dropna(how="all")

    first = df["OgrNo"].astype(str)
    df = df[~first.str.contains("Genel Ortalama|Kurum Ortalaması", na=False, regex=True)].copy()

    df.columns = make_unique_columns(df.columns)

    df["OgrNo"] = pd.to_numeric(df["OgrNo"], errors="coerce")
    if "LGS_Puan" in df.columns:
        df["LGS_Puan"] = pd.to_numeric(df["LGS_Puan"], errors="coerce")

    df["Deneme"] = exam_name
    df["Kademe"] = df["Sinif"].apply(extract_kademe)

    for c in df.columns:
        if c.endswith("_D") or c.endswith("_Y") or c.endswith("_N"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df.reset_index(drop=True), exam_name

def _to_payload(row: pd.Series) -> dict:
    d = row.to_dict()
    for k, v in list(d.items()):
        if pd.isna(v):
            d[k] = None
    return d

def save_exam_to_supabase(df_exam: pd.DataFrame, exam_name: str):
    supabase.table(TABLE).delete().eq("exam_name", exam_name).execute()

    rows = []
    for _, r in df_exam.iterrows():
        rows.append({
            "exam_name": exam_name,
            "exam_date": None,
            "kademe": int(r["Kademe"]) if pd.notna(r.get("Kademe")) else None,
            "ogr_no": int(r["OgrNo"]) if pd.notna(r.get("OgrNo")) else None,
            "ad_soyad": str(r.get("AdSoyad", "")).strip(),
            "sinif": str(r.get("Sinif", "")).strip() if pd.notna(r.get("Sinif")) else None,
            "lgs_puan": float(r.get("LGS_Puan")) if pd.notna(r.get("LGS_Puan")) else None,
            "payload": _to_payload(r),
        })

    chunk = 300
    for i in range(0, len(rows), chunk):
        supabase.table(TABLE).insert(rows[i:i+chunk]).execute()

@st.cache_data(show_spinner=False, ttl=30)
def fetch_all_results():
    res = supabase.table(TABLE).select(
        "exam_name,kademe,ogr_no,ad_soyad,sinif,lgs_puan,created_at,payload"
    ).execute()
    return pd.DataFrame(res.data or [])

def auto_comment(student_df: pd.DataFrame) -> str:
    if student_df.empty or student_df["lgs_puan"].dropna().empty:
        return "Bu öğrenci için yeterli puan verisi bulunamadı."
    s = student_df.sort_values("created_at")
    last = s["lgs_puan"].dropna().iloc[-1]
    first = s["lgs_puan"].dropna().iloc[0]
    diff = last - first
    if diff >= 20:
        return "Belirgin yükseliş var. Düzenli çalışmanın karşılığı alınmış görünüyor."
    if diff >= 5:
        return "Olumlu gelişim var. İstikrarı korumak önemli."
    if diff <= -20:
        return "Belirgin düşüş var. Çalışma düzeni ve sınav kaygısı birlikte değerlendirilmeli."
    if diff <= -5:
        return "Son denemelerde küçük bir gerileme var. Eksik kazanımlar ve tekrar planı gözden geçirilebilir."
    return "Puanlar stabil. İlerleme için hedef derslere odaklı plan faydalı olur."

def get_exam_order(kdf: pd.DataFrame):
    if kdf.empty:
        return []
    return (
        kdf.groupby("exam_name")["created_at"]
        .min()
        .sort_values()
        .index
        .tolist()
    )

def payload_to_nets(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    dersler = set()
    for k in payload.keys():
        if isinstance(k, str) and (k.endswith("_D") or k.endswith("_Y") or k.endswith("_N")):
            dersler.add(k.rsplit("_", 1)[0].strip())
    nets = {}
    for ders in sorted(dersler):
        d = float(payload.get(f"{ders}_D") or 0)
        y = float(payload.get(f"{ders}_Y") or 0)
        nets[ders] = d - (y / 3.0)
    return nets

# --------------------
# PDF HELPERS
# --------------------
def ensure_pdf_font():
    try:
        pdfmetrics.registerFont(TTFont("TRFont", FONT_PATH))
        return "TRFont"
    except Exception:
        return None

def fig_to_rl_image(fig, width=520, height=220):
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return RLImage(buf, width=width, height=height)

def build_student_pdf(student_name: str, kademe: int, student_df: pd.DataFrame) -> BytesIO:
    font_name = ensure_pdf_font()
    styles = getSampleStyleSheet()
    if font_name:
        for k in styles.byName:
            styles[k].fontName = font_name

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=24, leftMargin=24, topMargin=20, bottomMargin=20)

    elems = []
    # logo + başlık
    if os.path.exists(LOGO_PATH):
        header = Table(
            [[RLImage(LOGO_PATH, width=55, height=55),
              Paragraph("<b>Cemil Meriç Ortaokulu</b><br/>Öğrenci Akademik Performans Raporu", styles["Title"])]],
            colWidths=[65, 430]
        )
        header.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "MIDDLE")]))
        elems.append(header)
    else:
        elems.append(Paragraph("Öğrenci Akademik Performans Raporu", styles["Title"]))

    elems.append(Spacer(1, 8))
    elems.append(Paragraph(f"<b>Öğrenci:</b> {student_name}", styles["Normal"]))
    elems.append(Paragraph(f"<b>Kademe:</b> {kademe}", styles["Normal"]))
    elems.append(Spacer(1, 10))

    elems.append(Paragraph("Kısa Değerlendirme", styles["Heading2"]))
    elems.append(Paragraph(auto_comment(student_df), styles["Normal"]))
    elems.append(Spacer(1, 10))

    tdf = student_df[["exam_name", "sinif", "lgs_puan", "created_at"]].copy().sort_values("created_at")
    tdf["created_at"] = pd.to_datetime(tdf["created_at"], errors="coerce").dt.strftime("%d.%m.%Y %H:%M")
    tdf["created_at"] = tdf["created_at"].fillna("-")
    tdf["lgs_puan"] = tdf["lgs_puan"].apply(lambda x: "-" if pd.isna(x) else f"{x:.2f}")

    table_data = [["Deneme", "Sınıf", "Puan", "Tarih"]] + tdf.values.tolist()
    tbl = Table(table_data, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0F2D52")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#9aa7b2")),
        ("FONTNAME", (0,0), (-1,-1), font_name or "Helvetica"),
        ("FONTSIZE", (0,0), (-1,0), 10),
        ("FONTSIZE", (0,1), (-1,-1), 9),
        ("TOPPADDING", (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    elems.append(tbl)
    elems.append(Spacer(1, 10))

    # puan trend grafiği
    score_series = student_df.sort_values("created_at")[["exam_name", "lgs_puan"]].dropna()
    if not score_series.empty:
        fig, ax = plt.subplots(figsize=(7.2, 2.8))
        ax.plot(score_series["exam_name"], score_series["lgs_puan"], marker="o")
        ax.set_title("Denemelere Göre Puan Gelişimi")
        ax.set_xlabel("Deneme")
        ax.set_ylabel("Puan")
        plt.xticks(rotation=25, ha="right")
        plt.tight_layout()
        elems.append(fig_to_rl_image(fig, width=520, height=210))
        elems.append(Spacer(1, 10))

    # son deneme net grafiği
    try:
        last_row = student_df.sort_values("created_at").iloc[-1]
        nets = payload_to_nets(last_row.get("payload", {}))
    except Exception:
        nets = {}

    if nets:
        net_df = pd.DataFrame({"Ders": list(nets.keys()), "Net": list(nets.values())}).sort_values("Net", ascending=False)
        fig2, ax2 = plt.subplots(figsize=(7.2, 2.8))
        ax2.bar(net_df["Ders"], net_df["Net"])
        ax2.set_title("Son Deneme Ders Bazlı Netler")
        ax2.set_xlabel("Ders")
        ax2.set_ylabel("Net")
        plt.xticks(rotation=35, ha="right")
        plt.tight_layout()
        elems.append(fig_to_rl_image(fig2, width=520, height=210))

    doc.build(elems)
    buffer.seek(0)
    return buffer


def build_top40_pdf(kademe: int, exam_name: str, top40_df: pd.DataFrame) -> BytesIO:
    """
    TEK SAYFA PDF (A4 yatay):
    - Logo + başlık
    - Sıkı kolon genişlikleri / küçük font
    - Zebra satır
    Not: Emoji/madalya kullanılmaz (yazıcı/PDF font uyumluluğu için).
    """
    font_name = ensure_pdf_font()
    styles = getSampleStyleSheet()
    if font_name:
        for k in styles.byName:
            styles[k].fontName = font_name

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=8, leftMargin=8, topMargin=6, bottomMargin=6
    )

    elems = []

    # Header (logo + başlık)
    if os.path.exists(LOGO_PATH):
        logo = RLImage(LOGO_PATH, width=45, height=45)
        title = Paragraph(
            f"<b>Cemil Meriç Ortaokulu</b><br/>"
            f"İlk 40 Başarı Listesi — <b>{kademe}. Sınıf</b><br/>"
            f"Deneme: <b>{exam_name}</b>",
            styles["Normal"]
        )
        h = Table([[logo, title]], colWidths=[55, 745])
        h.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        elems.append(h)
    else:
        elems.append(Paragraph(f"İlk 40 — {kademe}. Sınıf — {exam_name}", styles["Title"]))

    elems.append(Spacer(1, 4))

    tdf = top40_df.copy()

    # Puan formatı
    if "Puan" in tdf.columns:
        tdf["Puan"] = tdf["Puan"].apply(lambda x: "" if pd.isna(x) else f"{float(x):.2f}")

    # Ad Soyad temizliği (ekranda emoji varsa PDF'de at)
    if "Ad Soyad" in tdf.columns:
        tdf["Ad Soyad"] = tdf["Ad Soyad"].astype(str)
        for bad in ["🥇", "🥈", "🥉", "🏅", "★"]:
            tdf["Ad Soyad"] = tdf["Ad Soyad"].str.replace(bad, "", regex=False)
        tdf["Ad Soyad"] = tdf["Ad Soyad"].str.strip()

    table_data = [list(tdf.columns)] + tdf.values.tolist()

    # Kolon genişlikleri (tek sayfa - sıkı)
    col_widths = []
    for col in tdf.columns:
        if col == "Sıra":
            col_widths.append(26)
        elif col == "Okul No":
            col_widths.append(58)
        elif col == "Ad Soyad":
            col_widths.append(360)
        elif col == "Sınıf":
            col_widths.append(55)
        elif col == "Puan":
            col_widths.append(55)
        elif col == "Deneme Sayısı":
            col_widths.append(55)
        elif col == "Denemeler":
            col_widths.append(220)
        else:
            col_widths.append(60)

    # Satır yükseklikleri sabit (tek sayfa için)
    row_heights = [12] + [10] * (len(table_data) - 1)

    tbl = Table(table_data, colWidths=col_widths, rowHeights=row_heights, hAlign="CENTER")

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F2D52")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), font_name or "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),       # başlık
        ("FONTSIZE", (0, 1), (-1, -1), 6.2),    # içerik
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9aa7b2")),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (1, -1), "CENTER"),
        ("ALIGN", (-1, 1), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]

    # Zebra satır
    for r in range(1, len(table_data)):
        bg = colors.HexColor("#F3F6FB") if r % 2 == 0 else colors.white
        style_cmds.append(("BACKGROUND", (0, r), (-1, r), bg))

    tbl.setStyle(TableStyle(style_cmds))
    elems.append(tbl)

    doc.build(elems)
    buffer.seek(0)
    return buffer


# --------------------
# UI HEADER (logo)
# --------------------
h1, h2 = st.columns([1, 6])
with h1:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=120)
with h2:
    st.title("🏫 Akademik Performans Takip Sistemi (5-8)")
    st.caption("Deneme ekleme • Analiz • İlk 40 • PDF rapor")

tab_add, tab_dash = st.tabs(["➕ Deneme Ekle", "📊 Analiz Paneli"])

# --------------------
# TAB 1: Deneme ekle
# --------------------
with tab_add:
    st.markdown('<div class="section-title">Deneme Excel Yükle ve Kaydet</div>', unsafe_allow_html=True)
    uploaded_file = st.file_uploader("Excel (.xlsx) yükle", type=["xlsx"], key="excel_upload")
    if uploaded_file:
        df, exam_name = parse_school_report(uploaded_file)
        st.dataframe(df.head(30), use_container_width=True)

        if st.button("✅ Supabase’e Kaydet", type="primary"):
            with st.spinner("Kaydediliyor..."):
                save_exam_to_supabase(df, exam_name)
                st.cache_data.clear()
            st.success("Kaydedildi ✅ Analiz Paneli sekmesine geçebilirsin.")

# --------------------
# TAB 2: Analiz Paneli
# --------------------
with tab_dash:
    all_df = fetch_all_results()
    if all_df.empty:
        st.warning("Supabase’te kayıt yok.")
        st.stop()

    colA, colB, colC = st.columns([1, 1.6, 1.8])
    kademeler = sorted([int(x) for x in all_df["kademe"].dropna().unique()])

    with colA:
        sec_kademe = st.selectbox("Kademe", kademeler)

    # --- Deneme seçimi (Tüm denemeler ortalaması opsiyonlu) ---
    ALL_LABEL = "📌 TÜM DENEMELER (ORTALAMA)"

    kdf = all_df[all_df["kademe"] == sec_kademe].copy()
    exams = get_exam_order(kdf) or sorted([e for e in kdf["exam_name"].dropna().unique()])
    exam_options = [ALL_LABEL] + list(exams)

    with colB:
        sec_exam = st.selectbox("Deneme", exam_options)

    # Seçime göre veri
    if sec_exam == ALL_LABEL:
        df_exam = kdf.copy()
    else:
        df_exam = kdf[kdf["exam_name"] == sec_exam].copy()

    siniflar = sorted([s for s in df_exam["sinif"].dropna().unique()])

    with colC:
        sec_siniflar = st.multiselect("Sınıf", siniflar, default=siniflar)

    df_f = df_exam[df_exam["sinif"].isin(sec_siniflar)].copy()

    avg_score = df_f["lgs_puan"].mean() if df_f["lgs_puan"].notna().any() else None
    max_score = df_f["lgs_puan"].max() if df_f["lgs_puan"].notna().any() else None

    k1, k2, k3 = st.columns(3)
    k1.markdown(f'<div class="kpi-card"><div class="kpi-title">Öğrenci</div><div class="kpi-value">{df_f["ad_soyad"].nunique()}</div><div class="kpi-sub">Filtreli</div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="kpi-card"><div class="kpi-title">Ortalama</div><div class="kpi-value">{avg_score:.2f}</div><div class="kpi-sub">Puan</div></div>' if avg_score is not None else
                '<div class="kpi-card"><div class="kpi-title">Ortalama</div><div class="kpi-value">—</div><div class="kpi-sub">Puan</div></div>', unsafe_allow_html=True)
    k3.markdown(f'<div class="kpi-card"><div class="kpi-title">En Yüksek</div><div class="kpi-value">{max_score:.2f}</div><div class="kpi-sub">Puan</div></div>' if max_score is not None else
                '<div class="kpi-card"><div class="kpi-title">En Yüksek</div><div class="kpi-value">—</div><div class="kpi-sub">Puan</div></div>', unsafe_allow_html=True)

    t1, t2 = st.tabs(["🏅 İlk 40", "🧑‍🎓 Öğrenci"])

    with t1:
        if sec_exam == ALL_LABEL:
            # TÜM denemeler: öğrenci bazında ortalama + deneme sayısı + deneme listesi
            g = (
                df_f.dropna(subset=["lgs_puan"])
                   .groupby(["ogr_no", "ad_soyad", "sinif"], as_index=False)
                   .agg(
                       lgs_puan=("lgs_puan", "mean"),
                       deneme_sayisi=("exam_name", "nunique"),
                       denemeler=("exam_name", lambda s: ", ".join(sorted(set([x for x in s.dropna().astype(str)]))))
                   )
            )

            # TEK SAYFA PDF için: deneme isimlerini kısalt (ilk 3 + “+N”)
            def short_exam_list(full: str, max_items: int = 3) -> str:
                items = [x.strip() for x in str(full).split(",") if x.strip()]
                if len(items) <= max_items:
                    return ", ".join(items)
                return ", ".join(items[:max_items]) + f" +{len(items) - max_items}"

            g["denemeler_kisa"] = g["denemeler"].apply(short_exam_list)

            top40 = (
                g.sort_values(["lgs_puan", "deneme_sayisi"], ascending=[False, False])
                 .head(40)
                 .reset_index(drop=True)
            )
        else:
            # TEK deneme: mevcut mantık
            top40 = (
                df_f.dropna(subset=["lgs_puan"])
                   .sort_values("lgs_puan", ascending=False)
                   .head(40)
                   .reset_index(drop=True)
            )

        top40.insert(0, "Sıra", range(1, len(top40) + 1))


        # Ekranda gösterilecek tablo
        # --- Top40 tabloyu güvenli şekilde oluştur (kolon adı farklarını tolere eder) ---

# top40 içinde hangi isimler var kontrol edip tek bir standarda çekiyoruz
t = top40.copy()

# bazı yerlerde kolon adları farklı olabiliyor -> normalize
rename_map = {}
if "ogr_no" in t.columns: rename_map["ogr_no"] = "Okul No"
if "okul_no" in t.columns: rename_map["okul_no"] = "Okul No"

if "ad_soyad" in t.columns: rename_map["ad_soyad"] = "Ad Soyad"
if "Ad Soyad" in t.columns: rename_map["Ad Soyad"] = "Ad Soyad"

if "sinif" in t.columns: rename_map["sinif"] = "Sınıf"
if "Sınıf" in t.columns: rename_map["Sınıf"] = "Sınıf"

if "lgs_puan" in t.columns: rename_map["lgs_puan"] = "Puan"
if "Puan" in t.columns: rename_map["Puan"] = "Puan"

# deneme sayısı / deneme listesi kolonları
if "deneme_sayisi" in t.columns: rename_map["deneme_sayisi"] = "Deneme Sayısı"
if "Deneme Sayısı" in t.columns: rename_map["Deneme Sayısı"] = "Deneme Sayısı"

if "denemeler_kisa" in t.columns: rename_map["denemeler_kisa"] = "Denemeler"
if "Denemeler" in t.columns: rename_map["Denemeler"] = "Denemeler"

t = t.rename(columns=rename_map)

# Sıra kolonu yoksa üret
if "Sıra" not in t.columns:
    t = t.reset_index(drop=True)
    t.insert(0, "Sıra", range(1, len(t) + 1))

# gösterilecek kolonlar: olanları al
wanted = ["Sıra", "Okul No", "Ad Soyad", "Sınıf", "Puan"]
if sec_exam == ALL_LABEL:  # tüm denemeler ortalama modunda ek kolonlar
    wanted += ["Deneme Sayısı", "Denemeler"]

cols_available = [c for c in wanted if c in t.columns]
show = t[cols_available].copy()

# puanı yuvarla (varsa)
if "Puan" in show.columns:
    show["Puan"] = pd.to_numeric(show["Puan"], errors="coerce").round(2)

st.dataframe(show, use_container_width=True, hide_index=True)

        # PDF için: denemeler kısa olsun (tek sayfayı korur)
        pdf_df = show.copy()
        if "Denemeler" in pdf_df.columns and sec_exam == ALL_LABEL:
            pdf_df["Denemeler"] = top40["denemeler_kisa"].values

        pdf_exam_name = sec_exam if sec_exam != ALL_LABEL else "TÜM DENEMELER ORTALAMASI"
        top40_pdf = build_top40_pdf(sec_kademe, pdf_exam_name, pdf_df)

        st.download_button(
            "📄 İlk 40 PDF (Tek Sayfa)",
            data=top40_pdf,
            file_name=f"ilk40_{sec_kademe}_{pdf_exam_name}.pdf",
            mime="application/pdf"
        )
    with t2:
        ogr_list = sorted([s for s in df_f["ad_soyad"].dropna().unique()])
        sec_ogr = st.selectbox("Öğrenci seç", ["(Seçme)"] + ogr_list)

        if sec_ogr != "(Seçme)":
            s = kdf[kdf["ad_soyad"] == sec_ogr].copy().sort_values("created_at")

            if s["lgs_puan"].notna().any():
                fig, ax = plt.subplots()
                ax.plot(s["exam_name"], s["lgs_puan"], marker="o")
                ax.set_xlabel("Deneme")
                ax.set_ylabel("Puan")
                plt.xticks(rotation=25, ha="right")
                st.pyplot(fig)

            st.info(auto_comment(s))

            pdf_buf = build_student_pdf(sec_ogr, sec_kademe, s)
            st.download_button(
                "📄 Öğrenci PDF Raporu",
                data=pdf_buf,
                file_name=f"{sec_ogr}_rapor.pdf",
                mime="application/pdf"
            )