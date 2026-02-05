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
    genel_ort = df[first.str.contains("Genel Ortalama", na=False)].copy()
    kurum_ort = df[first.str.contains("Kurum Ortalaması", na=False)].copy()
    df = df[~first.str.contains("Genel Ortalama|Kurum Ortalaması", na=False, regex=True)].copy()

    # pyarrow güvenliği
    df.columns = make_unique_columns(df.columns)
    genel_ort.columns = make_unique_columns(genel_ort.columns)
    kurum_ort.columns = make_unique_columns(kurum_ort.columns)

    df["OgrNo"] = pd.to_numeric(df["OgrNo"], errors="coerce")
    if "LGS_Puan" in df.columns:
        df["LGS_Puan"] = pd.to_numeric(df["LGS_Puan"], errors="coerce")

    df["Deneme"] = exam_name
    df["Kademe"] = df["Sinif"].apply(extract_kademe)

    for c in df.columns:
        if c.endswith("_D") or c.endswith("_Y") or c.endswith("_N"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df.reset_index(drop=True), genel_ort, kurum_ort, exam_name

def _to_payload(row: pd.Series) -> dict:
    d = row.to_dict()
    for k, v in list(d.items()):
        if pd.isna(v):
            d[k] = None
    return d

def save_exam_to_supabase(df_exam: pd.DataFrame, exam_name: str):
    # aynı deneme adını tekrar yüklersen mükerrer olmasın
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
        return "Belirgin bir yükseliş var. Düzenli çalışmanın karşılığı alınmış görünüyor."
    if diff >= 5:
        return "Olumlu yönde bir gelişim var. Bu istikrarı korumak önemli."
    if diff <= -20:
        return "Puanlarda belirgin düşüş var. Çalışma düzeni, motivasyon ve sınav kaygısı birlikte değerlendirilmelidir."
    if diff <= -5:
        return "Son denemelerde küçük bir gerileme var. Tekrar planı ve eksik kazanımlar gözden geçirilebilir."
    return "Puanlar genel olarak stabil. İlerleme için hedef derslere odaklı plan faydalı olur."

# --------------------
# UI
# --------------------
st.title("🏫 Akademik Performans Takip Sistemi (5-8)")
st.caption("Deneme ekleme ayrı • Analiz tam genişlik • Kademe bazlı ilk 40 • Öğrenci gelişimi")

tab_add, tab_dash = st.tabs(["➕ Deneme Ekle", "📊 Analiz Paneli"])

# ============ TAB 1: DENEME EKLE ============
with tab_add:
    st.subheader("Deneme Excel Yükle ve Supabase’e Kaydet")

    uploaded_file = st.file_uploader("Excel (.xlsx) yükle", type=["xlsx"], key="excel_upload")
    if uploaded_file:
        df, genel_ort, kurum_ort, exam_name = parse_school_report(uploaded_file)

        st.success(f"Okundu ✅ | Deneme: {exam_name} | Öğrenci: {df['AdSoyad'].nunique()} | Kademe: {sorted(df['Kademe'].dropna().unique().tolist())}")

        c1, c2 = st.columns([2, 1])
        with c1:
            st.write("**Önizleme (ilk 30 satır)**")
            st.dataframe(df.head(30), use_container_width=True)
        with c2:
            with st.expander("📌 Ortalama Satırları", expanded=False):
                if len(kurum_ort) > 0:
                    st.write("**Kurum Ortalaması**")
                    st.dataframe(kurum_ort, use_container_width=True)
                if len(genel_ort) > 0:
                    st.write("**Genel Ortalama**")
                    st.dataframe(genel_ort, use_container_width=True)

        if st.button("✅ Bu denemeyi Supabase’e Kaydet", type="primary"):
            with st.spinner("Kaydediliyor..."):
                save_exam_to_supabase(df, exam_name)
                st.cache_data.clear()
            st.success("Kaydedildi ✅ Şimdi 'Analiz Paneli' sekmesine geçebilirsin.")
    else:
        st.info("Deneme eklemek için Excel dosyanı yükle.")

# ============ TAB 2: ANALİZ PANELİ (TAM GENİŞ) ============
with tab_dash:
    st.subheader("Kademe Bazlı Analiz ve Öğrenci Gelişimi")

    all_df = fetch_all_results()
    if all_df.empty:
        st.warning("Supabase’te henüz kayıt yok. Önce 'Deneme Ekle' sekmesinden Excel yükleyip kaydet.")
        st.stop()

    # Üst filtreler (geniş ekran)
    colA, colB, colC = st.columns([1, 1.5, 1.5])

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

    # KPI satırı
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("Kademe", str(sec_kademe))
    with k2:
        st.metric("Öğrenci", f"{df_f['ad_soyad'].nunique()}")
    with k3:
        st.metric("Ortalama Puan", f"{df_f['lgs_puan'].mean():.2f}" if df_f["lgs_puan"].notna().any() else "—")
    with k4:
        st.metric("En Yüksek", f"{df_f['lgs_puan'].max():.2f}" if df_f["lgs_puan"].notna().any() else "—")

    t1, t2, t3 = st.tabs(["🏅 İlk 40", "🏫 Sınıf Analizi", "🧑‍🎓 Öğrenci"])

    with t1:
        st.write(f"**{sec_kademe}. sınıf • {sec_exam} • İlk 40**")
        top40 = df_f.dropna(subset=["lgs_puan"]).sort_values("lgs_puan", ascending=False).head(40)
        st.dataframe(top40[["ad_soyad", "sinif", "lgs_puan"]], use_container_width=True)

    with t2:
        if df_f["lgs_puan"].notna().any():
            rank_df = df_f[["ad_soyad", "sinif", "lgs_puan"]].dropna().sort_values("lgs_puan", ascending=False)
            st.dataframe(rank_df, use_container_width=True)

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
            st.info("Öğrenciyi seçince gelişim grafiği ve yorum burada görünecek.")
        else:
            s = kdf[kdf["ad_soyad"] == sec_ogr].copy().sort_values("created_at")

            left2, right2 = st.columns([2, 1])
            with left2:
                if s["lgs_puan"].notna().any():
                    fig, ax = plt.subplots()
                    ax.plot(s["exam_name"], s["lgs_puan"], marker="o")
                    ax.set_xlabel("Deneme")
                    ax.set_ylabel("Puan")
                    ax.set_title("Denemeler Boyunca Puan Değişimi")
                    plt.xticks(rotation=25, ha="right")
                    st.pyplot(fig)
                st.dataframe(s[["exam_name", "sinif", "lgs_puan", "created_at"]], use_container_width=True)

            with right2:
                st.write("### Otomatik Yorum")
                st.info(auto_comment(s))
