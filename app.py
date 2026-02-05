import re
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from supabase import create_client

# --------------------
# AYARLAR
# --------------------
st.set_page_config(page_title="Akademik Takip (5-8)", layout="wide")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

TABLE = "lgs_results"

# --------------------
# STİL (kart görünümü + tipografi)
# --------------------
st.markdown("""
<style>
/* Canva benzeri kartlar */
.kpi-card{
  border:1px solid rgba(255,255,255,0.12);
  border-radius:16px;
  padding:14px 16px;
  background: rgba(255,255,255,0.03);
}
.kpi-title{font-size:12px; opacity:0.8; margin-bottom:6px;}
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
}
.section-title{
  font-size:18px;
  font-weight:700;
  margin-top:4px;
}
.small-note{font-size:12px; opacity:0.75;}
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
        "exam_name,kademe,ogr_no,ad_soyad,sinif,lgs_puan,created_at"
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
        return "🌟 Belirgin bir yükseliş var. Düzenli çalışmanın karşılığı alınmış görünüyor."
    if diff >= 5:
        return "✅ Olumlu yönde gelişim var. Bu istikrarı korumak önemli."
    if diff <= -20:
        return "⚠️ Puanlarda belirgin düşüş var. Çalışma düzeni ve sınav kaygısı birlikte değerlendirilmeli."
    if diff <= -5:
        return "🟠 Son denemelerde küçük bir gerileme var. Eksik kazanımlar ve tekrar planı gözden geçirilebilir."
    return "🟦 Puanlar genel olarak stabil. İlerleme için hedef derslere odaklı plan faydalı olur."

def fmt_df_for_ui(df_in: pd.DataFrame) -> pd.DataFrame:
    """
    Kullanıcıya görünen tablo başlıklarını Türkçeleştir + estetik düzenle.
    """
    df = df_in.copy()
    rename_map = {
        "ad_soyad": "Ad Soyad",
        "sinif": "Sınıf",
        "lgs_puan": "Puan",
        "exam_name": "Deneme",
        "created_at": "Kayıt Zamanı",
    }
    for k, v in rename_map.items():
        if k in df.columns:
            df = df.rename(columns={k: v})
    return df

# --------------------
# UI
# --------------------
st.title("🏫 Akademik Performans Takip Sistemi (5-8)")
st.caption("Canva tarzı kartlar • Kademe bazlı ilk 40 • Öğrenci gelişimi • Otomatik yorum")

tab_add, tab_dash = st.tabs(["➕ Deneme Ekle", "📊 Analiz Paneli"])

# -------- Deneme Ekle --------
with tab_add:
    st.markdown('<div class="section-title">Deneme Excel Yükle ve Kaydet</div>', unsafe_allow_html=True)
    st.markdown('<div class="small-note">Her denemeden sonra Excel yükleyip kaydedin. Analiz paneli geçmişi otomatik getirir.</div>', unsafe_allow_html=True)

    uploaded_file = st.file_uploader("Excel (.xlsx)", type=["xlsx"], key="excel_upload")
    if uploaded_file:
        df, exam_name = parse_school_report(uploaded_file)

        st.markdown(
            f'<span class="badge">Deneme: {exam_name}</span>'
            f'<span class="badge">Öğrenci: {df["AdSoyad"].nunique()}</span>'
            f'<span class="badge">Kademeler: {sorted(df["Kademe"].dropna().unique().tolist())}</span>',
            unsafe_allow_html=True
        )

        st.write("### Önizleme")
        st.dataframe(df.head(30), use_container_width=True)

        if st.button("✅ Supabase’e Kaydet", type="primary"):
            with st.spinner("Kaydediliyor..."):
                save_exam_to_supabase(df, exam_name)
                st.cache_data.clear()
            st.success("Kaydedildi ✅ Analiz Paneli sekmesine geçebilirsin.")
    else:
        st.info("Excel yükleyerek yeni deneme ekleyebilirsin.")

# -------- Analiz Paneli (tam geniş) --------
with tab_dash:
    all_df = fetch_all_results()
    if all_df.empty:
        st.warning("Supabase’te kayıt yok. Önce 'Deneme Ekle' sekmesinden Excel yükleyip kaydet.")
        st.stop()

    st.markdown('<div class="section-title">Kademe Bazlı Analiz</div>', unsafe_allow_html=True)

    # Üst filtreler (tam geniş)
    colA, colB, colC = st.columns([1, 1.6, 1.8])
    kademeler = sorted([int(x) for x in all_df["kademe"].dropna().unique()])
    with colA:
        sec_kademe = st.selectbox("Kademe", kademeler)

    kdf = all_df[all_df["kademe"] == sec_kademe].copy()
    exams = sorted([e for e in kdf["exam_name"].dropna().unique()])
    with colB:
        sec_exam = st.selectbox("Deneme", exams)

    df_exam = kdf[kdf["exam_name"] == sec_exam].copy()
    siniflar = sorted([s for s in df_exam["sinif"].dropna().unique()])
    with colC:
        sec_siniflar = st.multiselect("Sınıf", siniflar, default=siniflar)

    df_f = df_exam[df_exam["sinif"].isin(sec_siniflar)].copy()

    # KPI Kartları
    avg_score = df_f["lgs_puan"].mean() if df_f["lgs_puan"].notna().any() else None
    max_score = df_f["lgs_puan"].max() if df_f["lgs_puan"].notna().any() else None

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(f'<div class="kpi-card"><div class="kpi-title">Kademe</div><div class="kpi-value">{sec_kademe}</div><div class="kpi-sub">Seçili kademe</div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="kpi-card"><div class="kpi-title">Öğrenci</div><div class="kpi-value">{df_f["ad_soyad"].nunique()}</div><div class="kpi-sub">Filtreli toplam</div></div>', unsafe_allow_html=True)
    k3.markdown(f'<div class="kpi-card"><div class="kpi-title">Ortalama Puan</div><div class="kpi-value">{avg_score:.2f}</div><div class="kpi-sub">Bu deneme (filtreli)</div></div>' if avg_score is not None else
              '<div class="kpi-card"><div class="kpi-title">Ortalama Puan</div><div class="kpi-value">—</div><div class="kpi-sub">Veri yok</div></div>', unsafe_allow_html=True)
    k4.markdown(f'<div class="kpi-card"><div class="kpi-title">En Yüksek Puan</div><div class="kpi-value">{max_score:.2f}</div><div class="kpi-sub">Bu deneme (filtreli)</div></div>' if max_score is not None else
              '<div class="kpi-card"><div class="kpi-title">En Yüksek Puan</div><div class="kpi-value">—</div><div class="kpi-sub">Veri yok</div></div>', unsafe_allow_html=True)

    t1, t2, t3 = st.tabs(["🏅 İlk 40", "📈 Dağılım & Sıralama", "🧑‍🎓 Öğrenci Raporu"])

    # --- İlk 40 ---
    with t1:
        st.markdown(f'<span class="badge">{sec_kademe}. Sınıf</span><span class="badge">{sec_exam}</span><span class="badge">İlk 40</span>', unsafe_allow_html=True)

        top40 = (
            df_f.dropna(subset=["lgs_puan"])
               .sort_values("lgs_puan", ascending=False)
               .head(40)
               .reset_index(drop=True)
        )
        # Sıra 1’den başlasın
        top40.insert(0, "Sıra", range(1, len(top40) + 1))

        show = top40[["Sıra", "ad_soyad", "sinif", "lgs_puan"]].copy()
        show = show.rename(columns={"ad_soyad": "Ad Soyad", "sinif": "Sınıf", "lgs_puan": "Puan"})

        st.dataframe(show, use_container_width=True, hide_index=True)

        # İndirme (Excel)
        st.download_button(
            "⬇️ İlk 40’ı Excel olarak indir",
            data=show.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"ilk40_{sec_kademe}_{sec_exam}.csv",
            mime="text/csv"
        )

    # --- Dağılım & Sıralama ---
    with t2:
        if df_f["lgs_puan"].notna().any():
            left, right = st.columns([1.2, 1])
            with left:
                rank_df = df_f[["ad_soyad", "sinif", "lgs_puan"]].dropna().sort_values("lgs_puan", ascending=False)
                rank_df = rank_df.rename(columns={"ad_soyad": "Ad Soyad", "sinif": "Sınıf", "lgs_puan": "Puan"})
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

    # --- Öğrenci ---
    with t3:
        ogr_list = sorted([s for s in df_f["ad_soyad"].dropna().unique()])
        sec_ogr = st.selectbox("Öğrenci seç", ["(Seçme)"] + ogr_list)

        if sec_ogr == "(Seçme)":
            st.info("Öğrenciyi seçince gelişim grafiği, özet ve yorum görünecek.")
        else:
            s = kdf[kdf["ad_soyad"] == sec_ogr].copy().sort_values("created_at")

            # Öğrenci kartı
            last_score = s["lgs_puan"].dropna().iloc[-1] if s["lgs_puan"].notna().any() else None
            first_score = s["lgs_puan"].dropna().iloc[0] if s["lgs_puan"].notna().any() else None
            delta = (last_score - first_score) if (last_score is not None and first_score is not None) else None

            b1, b2, b3 = st.columns([1.2, 1, 1])
            b1.markdown(f'<div class="kpi-card"><div class="kpi-title">Öğrenci</div><div class="kpi-value">{sec_ogr}</div><div class="kpi-sub">Kademe: {sec_kademe}</div></div>', unsafe_allow_html=True)
            b2.markdown(f'<div class="kpi-card"><div class="kpi-title">Son Puan</div><div class="kpi-value">{last_score:.2f}</div><div class="kpi-sub">{s["exam_name"].dropna().iloc[-1]}</div></div>' if last_score is not None else
                        '<div class="kpi-card"><div class="kpi-title">Son Puan</div><div class="kpi-value">—</div><div class="kpi-sub">Veri yok</div></div>', unsafe_allow_html=True)
            b3.markdown(f'<div class="kpi-card"><div class="kpi-title">Değişim</div><div class="kpi-value">{delta:+.2f}</div><div class="kpi-sub">İlk → Son</div></div>' if delta is not None else
                        '<div class="kpi-card"><div class="kpi-title">Değişim</div><div class="kpi-value">—</div><div class="kpi-sub">Veri yok</div></div>', unsafe_allow_html=True)

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

                st.markdown("### Deneme Kayıtları")
                show = s[["exam_name", "sinif", "lgs_puan", "created_at"]].copy()
                show = fmt_df_for_ui(show)
                st.dataframe(show, use_container_width=True, hide_index=True)

            with right:
                st.markdown("### Otomatik Yorum")
                st.info(auto_comment(s))
                st.markdown("### Öneri")
                st.write("- Haftalık tekrar planı (Türkçe/Mat/Fen odaklı)")
                st.write("- Yanlış analizi: her denemeden sonra 20 dk")
                st.write("- Süre yönetimi: deneme sırasında bölümleme")
