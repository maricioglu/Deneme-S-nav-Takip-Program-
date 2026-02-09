import re
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from supabase import create_client

# PDF (ReportLab)
from io import BytesIO
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
)
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


# --------------------
# STİL (Canva hissi)
# --------------------
st.markdown("""
<style>
.main .block-container {max-width: 1200px; padding-top: 1.2rem;}
.kpi-card{
  border:1px solid rgba(255,255,255,0.12);
  border-radius:16px;
  padding:14px 16px;
  background: rgba(255,255,255,0.03);
}
.kpi-title{font-size:12px; opacity:0.80; margin-bottom:6px;}
.kpi-value{font-size:24px; font-weight:700; line-height:1.1;}
.kpi-sub{font-size:12px; opacity:0.75; margin-top:6px;}
.badge{
  display:inline-block;
  padding:6px 10px;
  border-radius:999px;
  border:1px solid rgba(255,255,255,0.16);
  background: rgba(255,255,255,0.04);
  font-size:12px;
  margin-right:6px;
  margin-bottom:6px;
}
.section-title{
  font-size:18px;
  font-weight:800;
  margin-top:2px;
  margin-bottom:8px;
}
.small-note{font-size:12px; opacity:0.75;}
</style>
""", unsafe_allow_html=True)


# --------------------
# YARDIMCI FONKSİYONLAR
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
        return "🌟 Belirgin yükseliş var. Düzenli çalışmanın karşılığı alınmış görünüyor."
    if diff >= 5:
        return "✅ Olumlu gelişim var. İstikrarı korumak önemli."
    if diff <= -20:
        return "⚠️ Belirgin düşüş var. Çalışma düzeni ve sınav kaygısı birlikte değerlendirilmeli."
    if diff <= -5:
        return "🟠 Küçük bir gerileme var. Eksik kazanımlar ve tekrar planı gözden geçirilebilir."
    return "🟦 Puanlar stabil. İlerleme için hedef derslere odaklı plan faydalı olur."


def get_exam_order(kdf: pd.DataFrame):
    if kdf.empty:
        return []
    order = (
        kdf.groupby("exam_name")["created_at"]
        .min()
        .sort_values()
        .index
        .tolist()
    )
    return order


def get_prev_exam_name(kdf: pd.DataFrame, current_exam: str):
    order = get_exam_order(kdf)
    if current_exam not in order:
        return None
    i = order.index(current_exam)
    return order[i - 1] if i > 0 else None


def compute_risers_fallers(kdf: pd.DataFrame, current_exam: str):
    prev_exam = get_prev_exam_name(kdf, current_exam)
    if not prev_exam:
        return None, None, None

    cur = kdf[kdf["exam_name"] == current_exam][["ad_soyad", "sinif", "lgs_puan"]].copy()
    prev = kdf[kdf["exam_name"] == prev_exam][["ad_soyad", "lgs_puan"]].copy()

    cur = cur.dropna(subset=["lgs_puan"])
    prev = prev.dropna(subset=["lgs_puan"])

    merged = cur.merge(prev, on="ad_soyad", how="inner", suffixes=("_cur", "_prev"))
    merged["degisim"] = merged["lgs_puan_cur"] - merged["lgs_puan_prev"]

    risers = merged.sort_values("degisim", ascending=False).head(10)
    fallers = merged.sort_values("degisim", ascending=True).head(10)

    return prev_exam, risers, fallers


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
    # Türkçe font: assets/fonts/DejaVuSans.ttf
    font_path = "assets/fonts/DejaVuSans.ttf"
    try:
        pdfmetrics.registerFont(TTFont("TRFont", font_path))
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
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)

    elems = []
    elems.append(Paragraph("Öğrenci Akademik Performans Raporu", styles["Title"]))
    elems.append(Spacer(1, 10))
    elems.append(Paragraph(f"<b>Öğrenci:</b> {student_name}", styles["Normal"]))
    elems.append(Paragraph(f"<b>Kademe:</b> {kademe}", styles["Normal"]))
    elems.append(Spacer(1, 10))

    elems.append(Paragraph("Kısa Değerlendirme", styles["Heading2"]))
    elems.append(Paragraph(auto_comment(student_df), styles["Normal"]))
    elems.append(Spacer(1, 12))

    tdf = student_df[["exam_name", "sinif", "lgs_puan", "created_at"]].copy().sort_values("created_at")
    tdf["created_at"] = pd.to_datetime(tdf["created_at"], errors="coerce").dt.strftime("%d.%m.%Y %H:%M")
    tdf["created_at"] = tdf["created_at"].fillna("-")
    tdf["lgs_puan"] = tdf["lgs_puan"].apply(lambda x: "-" if pd.isna(x) else f"{x:.2f}")

    table_data = [["Deneme", "Sınıf", "Puan", "Tarih"]] + tdf.values.tolist()
    tbl = Table(table_data, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("FONTNAME", (0,0), (-1,-1), font_name or "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),
    ]))

    elems.append(Paragraph("Deneme Geçmişi", styles["Heading2"]))
    elems.append(tbl)
    elems.append(Spacer(1, 12))

    # Puan trend grafiği
    score_series = student_df.sort_values("created_at")[["exam_name", "lgs_puan"]].dropna()
    if not score_series.empty:
        fig, ax = plt.subplots(figsize=(7.2, 3.0))
        ax.plot(score_series["exam_name"], score_series["lgs_puan"], marker="o")
        ax.set_title("Denemelere Göre Puan Gelişimi")
        ax.set_xlabel("Deneme")
        ax.set_ylabel("Puan")
        plt.xticks(rotation=25, ha="right")
        plt.tight_layout()

        elems.append(Paragraph("Puan Gelişimi (Grafik)", styles["Heading2"]))
        elems.append(fig_to_rl_image(fig, width=520, height=220))
        elems.append(Spacer(1, 12))

    # Son deneme ders netleri (tablo + grafik)
    try:
        last_row = student_df.sort_values("created_at").iloc[-1]
        nets = payload_to_nets(last_row.get("payload", {}))
    except Exception:
        nets = {}

    if nets:
        net_df = pd.DataFrame({"Ders": list(nets.keys()), "Net": list(nets.values())}).sort_values("Net", ascending=False)

        net_data = [["Ders", "Net"]] + [[r["Ders"], f'{r["Net"]:.2f}'] for _, r in net_df.iterrows()]
        net_tbl = Table(net_data, hAlign="LEFT")
        net_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
            ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
            ("FONTNAME", (0,0), (-1,-1), font_name or "Helvetica"),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("BOTTOMPADDING", (0,0), (-1,0), 8),
        ]))

        elems.append(Paragraph("Son Deneme Ders Bazlı Netler", styles["Heading2"]))
        elems.append(net_tbl)
        elems.append(Spacer(1, 10))

        fig2, ax2 = plt.subplots(figsize=(7.2, 3.0))
        ax2.bar(net_df["Ders"], net_df["Net"])
        ax2.set_title("Son Deneme Ders Bazlı Netler")
        ax2.set_xlabel("Ders")
        ax2.set_ylabel("Net")
        plt.xticks(rotation=35, ha="right")
        plt.tight_layout()

        elems.append(fig_to_rl_image(fig2, width=520, height=220))
        elems.append(Spacer(1, 8))

    doc.build(elems)
    buffer.seek(0)
    return buffer


def build_top40_pdf(kademe: int, exam_name: str, top40_df: pd.DataFrame) -> BytesIO:
    font_name = ensure_pdf_font()
    styles = getSampleStyleSheet()
    if font_name:
        for k in styles.byName:
            styles[k].fontName = font_name

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),     # ✅ tek sayfa için yatay
        rightMargin=24, leftMargin=24, topMargin=18, bottomMargin=18
    )

    elems = []
    title = f"İLK 40 BAŞARI LİSTESİ  |  {kademe}. Sınıf  |  {exam_name}"
    elems.append(Paragraph(title, styles["Title"]))
    elems.append(Spacer(1, 8))

    tdf = top40_df.copy()
    if "Puan" in tdf.columns:
        tdf["Puan"] = tdf["Puan"].apply(lambda x: "-" if pd.isna(x) else f"{float(x):.2f}")

    table_data = [list(tdf.columns)] + tdf.values.tolist()
    tbl = Table(table_data, hAlign="CENTER")

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), font_name or "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (1, -1), "CENTER"),       # Sıra + Okul No
        ("ALIGN", (-1, 1), (-1, -1), "CENTER"),     # Puan
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#9aa7b2")),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]

    # zebra
    for r in range(1, len(table_data)):
        bg = colors.HexColor("#f3f6fb") if r % 2 == 0 else colors.white
        style_cmds.append(("BACKGROUND", (0, r), (-1, r), bg))

    # ilk 3 vurgu
    for r in [1, 2, 3]:
        if r < len(table_data):
            style_cmds.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#fff2cc")))

    tbl.setStyle(TableStyle(style_cmds))
    elems.append(tbl)

    doc.build(elems)
    buffer.seek(0)
    return buffer


# --------------------
# UI
# --------------------
st.title("🏫 Akademik Performans Takip Sistemi (5-8)")
st.caption("Deneme ekleme ayrı • Analiz tam genişlik • Kademe bazlı ilk 40 • Öğrenci gelişimi • PDF rapor")

tab_add, tab_dash = st.tabs(["➕ Deneme Ekle", "📊 Analiz Paneli"])


# =========================
# TAB 1: DENEME EKLE
# =========================
with tab_add:
    st.markdown('<div class="section-title">Deneme Excel Yükle ve Kaydet</div>', unsafe_allow_html=True)
    st.markdown('<div class="small-note">Her denemeden sonra Excel yükleyip kaydedin. Analiz paneli geçmişi otomatik getirir.</div>', unsafe_allow_html=True)

    uploaded_file = st.file_uploader("Excel (.xlsx) yükle", type=["xlsx"], key="excel_upload")

    if uploaded_file:
        df, exam_name = parse_school_report(uploaded_file)

        st.markdown(
            f'<span class="badge">Deneme: {exam_name}</span>'
            f'<span class="badge">Öğrenci: {df["AdSoyad"].nunique()}</span>'
            f'<span class="badge">Kademeler: {sorted(df["Kademe"].dropna().unique().tolist())}</span>',
            unsafe_allow_html=True
        )

        st.write("### Önizleme (ilk 30)")
        st.dataframe(df.head(30), use_container_width=True)

        if st.button("✅ Supabase’e Kaydet", type="primary"):
            with st.spinner("Kaydediliyor..."):
                save_exam_to_supabase(df, exam_name)
                st.cache_data.clear()
            st.success("Kaydedildi ✅ Analiz Paneli sekmesine geçebilirsin.")
    else:
        st.info("Yeni deneme eklemek için Excel dosyanı yükle.")


# =========================
# TAB 2: ANALİZ PANELİ
# =========================
with tab_dash:
    all_df = fetch_all_results()
    if all_df.empty:
        st.warning("Supabase’te kayıt yok. Önce 'Deneme Ekle' sekmesinden Excel yükleyip kaydet.")
        st.stop()

    st.markdown('<div class="section-title">Kademe Bazlı Analiz</div>', unsafe_allow_html=True)

    colA, colB, colC = st.columns([1, 1.6, 1.8])
    kademeler = sorted([int(x) for x in all_df["kademe"].dropna().unique()])

    with colA:
        sec_kademe = st.selectbox("Kademe", kademeler)

    kdf = all_df[all_df["kademe"] == sec_kademe].copy()
    exam_order = get_exam_order(kdf)
    exams = exam_order if exam_order else sorted([e for e in kdf["exam_name"].dropna().unique()])

    with colB:
        sec_exam = st.selectbox("Deneme", exams)

    df_exam = kdf[kdf["exam_name"] == sec_exam].copy()
    siniflar = sorted([s for s in df_exam["sinif"].dropna().unique()])

    with colC:
        sec_siniflar = st.multiselect("Sınıf", siniflar, default=siniflar)

    df_f = df_exam[df_exam["sinif"].isin(sec_siniflar)].copy()

    avg_score = df_f["lgs_puan"].mean() if df_f["lgs_puan"].notna().any() else None
    max_score = df_f["lgs_puan"].max() if df_f["lgs_puan"].notna().any() else None
    min_score = df_f["lgs_puan"].min() if df_f["lgs_puan"].notna().any() else None

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(f'<div class="kpi-card"><div class="kpi-title">Kademe</div><div class="kpi-value">{sec_kademe}</div><div class="kpi-sub">Seçili kademe</div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="kpi-card"><div class="kpi-title">Öğrenci</div><div class="kpi-value">{df_f["ad_soyad"].nunique()}</div><div class="kpi-sub">Filtreli toplam</div></div>', unsafe_allow_html=True)
    k3.markdown(
        f'<div class="kpi-card"><div class="kpi-title">Ortalama Puan</div><div class="kpi-value">{avg_score:.2f}</div><div class="kpi-sub">Bu deneme</div></div>'
        if avg_score is not None else
        '<div class="kpi-card"><div class="kpi-title">Ortalama Puan</div><div class="kpi-value">—</div><div class="kpi-sub">Veri yok</div></div>',
        unsafe_allow_html=True
    )
    k4.markdown(
        f'<div class="kpi-card"><div class="kpi-title">Min / Max</div><div class="kpi-value">{min_score:.2f} / {max_score:.2f}</div><div class="kpi-sub">Bu deneme</div></div>'
        if (min_score is not None and max_score is not None) else
        '<div class="kpi-card"><div class="kpi-title">Min / Max</div><div class="kpi-value">—</div><div class="kpi-sub">Veri yok</div></div>',
        unsafe_allow_html=True
    )

    t1, t2, t3, t4 = st.tabs(["🏅 İlk 40", "📈 Dağılım & Sıralama", "🧑‍🎓 Öğrenci", "🚀 Değişim"])

    # -------------------------
    # TOP 40 (İstenen şekilde)
    # -------------------------
    with t1:
        st.markdown(
            f'<span class="badge">{sec_kademe}. Sınıf</span>'
            f'<span class="badge">{sec_exam}</span>'
            f'<span class="badge">İlk 40</span>',
            unsafe_allow_html=True
        )

        top40 = (
            df_f.dropna(subset=["lgs_puan"])
               .sort_values("lgs_puan", ascending=False)
               .head(40)
               .reset_index(drop=True)
        )

        # Sıra 1'den başlasın
        top40.insert(0, "Sıra", range(1, len(top40) + 1))

        # İlk 3'e madalya: ayrı sütun yok, isim yanında
        def name_with_medal(row):
            r = int(row["Sıra"])
            m = "🥇 " if r == 1 else "🥈 " if r == 2 else "🥉 " if r == 3 else ""
            return m + str(row.get("ad_soyad", "")).strip()

        top40["Ad Soyad"] = top40.apply(name_with_medal, axis=1)

        # Okul No eklensin
        show = top40[["Sıra", "ogr_no", "Ad Soyad", "sinif", "lgs_puan"]].copy()
        show.columns = ["Sıra", "Okul No", "Ad Soyad", "Sınıf", "Puan"]
        show["Puan"] = pd.to_numeric(show["Puan"], errors="coerce").round(2)

        # Ortalanmış görünüm
        padL, center, padR = st.columns([1, 8, 1])
        with center:
            st.dataframe(show, use_container_width=True, hide_index=True)

        # CSV indir
        st.download_button(
            "⬇️ İlk 40’ı indir (CSV)",
            data=show.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"ilk40_{sec_kademe}_{sec_exam}.csv",
            mime="text/csv"
        )

        # Tek sayfa, renkli PDF indir
        top40_pdf = build_top40_pdf(sec_kademe, sec_exam, show)
        st.download_button(
            "📄 İlk 40 PDF İndir (Tek Sayfa)",
            data=top40_pdf,
            file_name=f"ilk40_{sec_kademe}_{sec_exam}.pdf",
            mime="application/pdf"
        )

    with t2:
        if df_f["lgs_puan"].notna().any():
            left, right = st.columns([1.2, 1])

            with left:
                rank_df = df_f[["ogr_no", "ad_soyad", "sinif", "lgs_puan"]].dropna().sort_values("lgs_puan", ascending=False)
                rank_df.columns = ["Okul No", "Ad Soyad", "Sınıf", "Puan"]
                st.dataframe(rank_df, use_container_width=True, hide_index=True)

            with right:
                st.markdown("### Puan Dağılımı")
                fig, ax = plt.subplots()
                ax.hist(df_f["lgs_puan"].dropna(), bins=18)
                ax.set_xlabel("Puan")
                ax.set_ylabel("Öğrenci Sayısı")
                st.pyplot(fig)
        else:
            st.warning("Bu denemede puan verisi yok.")

    with t3:
        ogr_list = sorted([s for s in df_f["ad_soyad"].dropna().unique()])
        sec_ogr = st.selectbox("Öğrenci seç", ["(Seçme)"] + ogr_list)

        if sec_ogr == "(Seçme)":
            st.info("Öğrenci seçince gelişim grafiği, ders netleri ve PDF butonu görünecek.")
        else:
            s = kdf[kdf["ad_soyad"] == sec_ogr].copy().sort_values("created_at")

            last_score = s["lgs_puan"].dropna().iloc[-1] if s["lgs_puan"].notna().any() else None
            first_score = s["lgs_puan"].dropna().iloc[0] if s["lgs_puan"].notna().any() else None
            delta = (last_score - first_score) if (last_score is not None and first_score is not None) else None

            a, b, c = st.columns([1.5, 1, 1])
            a.markdown(f'<div class="kpi-card"><div class="kpi-title">Öğrenci</div><div class="kpi-value">{sec_ogr}</div><div class="kpi-sub">Kademe: {sec_kademe}</div></div>', unsafe_allow_html=True)
            b.markdown(
                f'<div class="kpi-card"><div class="kpi-title">Son Puan</div><div class="kpi-value">{last_score:.2f}</div><div class="kpi-sub">Son kayıt</div></div>'
                if last_score is not None else
                '<div class="kpi-card"><div class="kpi-title">Son Puan</div><div class="kpi-value">—</div><div class="kpi-sub">Veri yok</div></div>',
                unsafe_allow_html=True
            )
            c.markdown(
                f'<div class="kpi-card"><div class="kpi-title">Değişim</div><div class="kpi-value">{delta:+.2f}</div><div class="kpi-sub">İlk → Son</div></div>'
                if delta is not None else
                '<div class="kpi-card"><div class="kpi-title">Değişim</div><div class="kpi-value">—</div><div class="kpi-sub">Veri yok</div></div>',
                unsafe_allow_html=True
            )

            left, right = st.columns([1.6, 1])

            with left:
                st.markdown("### Gelişim Grafiği")
                if s["lgs_puan"].notna().any():
                    fig, ax = plt.subplots()
                    ax.plot(s["exam_name"], s["lgs_puan"], marker="o")
                    ax.set_xlabel("Deneme")
                    ax.set_ylabel("Puan")
                    ax.set_title("Denemeler Boyunca Puan Değişimi")
                    plt.xticks(rotation=25, ha="right")
                    st.pyplot(fig)

                st.markdown("### Ders Bazlı Netler (Son Deneme)")
                try:
                    last_row = s.dropna(subset=["created_at"]).sort_values("created_at").iloc[-1]
                    nets = payload_to_nets(last_row.get("payload", {}))
                except Exception:
                    nets = {}

                if nets:
                    net_df = pd.DataFrame({"Ders": list(nets.keys()), "Net": list(nets.values())}).sort_values("Net", ascending=False)
                    fig, ax = plt.subplots()
                    ax.bar(net_df["Ders"], net_df["Net"])
                    ax.set_xlabel("Ders")
                    ax.set_ylabel("Net")
                    plt.xticks(rotation=35, ha="right")
                    st.pyplot(fig)
                else:
                    st.info("Ders netleri bulunamadı (payload boş olabilir).")

                st.markdown("### Deneme Kayıtları")
                show_s = s[["exam_name", "sinif", "lgs_puan", "created_at"]].copy()
                show_s.columns = ["Deneme", "Sınıf", "Puan", "Kayıt Zamanı"]
                st.dataframe(show_s, use_container_width=True, hide_index=True)

            with right:
                st.markdown("### Otomatik Yorum")
                st.info(auto_comment(s))

                pdf_buf = build_student_pdf(sec_ogr, sec_kademe, s)
                st.download_button(
                    "📄 PDF Raporu İndir",
                    data=pdf_buf,
                    file_name=f"{sec_ogr}_rapor.pdf",
                    mime="application/pdf"
                )

    with t4:
        st.markdown("### En Çok Yükselen / Düşen Öğrenciler")
        prev_exam, risers, fallers = compute_risers_fallers(kdf, sec_exam)

        if prev_exam is None:
            st.info("Bu deneme için karşılaştıracak bir önceki deneme bulunamadı.")
        else:
            st.caption(f"Karşılaştırma: **{prev_exam} → {sec_exam}**")

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 🚀 En Çok Yükselen 10")
                show_r = risers[["ad_soyad", "sinif", "lgs_puan_prev", "lgs_puan_cur", "degisim"]].copy()
                show_r.columns = ["Ad Soyad", "Sınıf", "Önceki Puan", "Son Puan", "Değişim"]
                st.dataframe(show_r, use_container_width=True, hide_index=True)

            with c2:
                st.markdown("#### 📉 En Çok Düşen 10")
                show_f = fallers[["ad_soyad", "sinif", "lgs_puan_prev", "lgs_puan_cur", "degisim"]].copy()
                show_f.columns = ["Ad Soyad", "Sınıf", "Önceki Puan", "Son Puan", "Değişim"]
                st.dataframe(show_f, use_container_width=True, hide_index=True)
