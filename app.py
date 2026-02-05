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
        try:
            return int(m.group(1))
        except:
            return None
    # bazen "8F" gibi olabilir
    m2 = re.match(r"^\s*(\d+)", str(sinif))
    if m2:
        try:
            return int(m2.group(1))
        except:
            return None
    return None

@st.cache_data(show_spinner=False)
def parse_school_report(uploaded_file):
    """
    Bu okul rapor formatını okur:
    satır0: okul + grup başlıklar
    satır1: deneme adı + ders isimleri + (LGS/Puan) + Dereceler
    satır2: 'Öğr.No' + alt başlık (D/Y/N veya derece türleri)
    """
    raw = pd.read_excel(uploaded_file, header=None)
    raw = raw.dropna(axis=1, how="all")

    # deneme adı genelde satır1 col0
    exam_name = "Deneme"
    try:
        v = raw.iloc[1, 0]
        if pd.notna(v):
            exam_name = str(v).strip()
    except Exception:
        pass

    # header satırı: "Öğr.No"
    header_idx = None
    for i in range(len(raw)):
        if str(raw.iloc[i, 0]).strip() == "Öğr.No":
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Başlık satırı bulunamadı: 'Öğr.No' yok.")

    grp = raw.iloc[header_idx - 2].copy().ffill()  # örn: Sözel (TÜR), LGS
    top = raw.iloc[header_idx - 1].copy().ffill()  # örn: Türkçe, Puan, Dereceler
    sub = raw.iloc[header_idx].copy()              # örn: D/Y/N veya Sınıf/Kurum/...

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
            # ✅ LGS Puan
            if g.lower() == "lgs" and t.lower() == "puan":
                cols.append("LGS_Puan")
            # Dereceler
            elif t.lower() == "dereceler" and s in ["Sınıf", "Kurum", "İlçe", "İl", "Genel"]:
                cols.append(f"Derece_{s}")
            # Ders D/Y/N
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

    # ortalama satırları
    first = df["OgrNo"].astype(str)
    genel_ort = df[first.str.contains("Genel Ortalama", na=False)].copy()
    kurum_ort = df[first.str.contains("Kurum Ortalaması", na=False)].copy()
    df = df[~first.str.contains("Genel Ortalama|Kurum Ortalaması", na=False, regex=True)].copy()

    # pyarrow güvenliği
    df.columns = make_unique_columns(df.columns)
    genel_ort.columns = make_unique_columns(genel_ort.columns)
    kurum_ort.columns = make_unique_columns(kurum_ort.columns)

    # tip düzeltme
    df["OgrNo"] = pd.to_numeric(df["OgrNo"], errors="coerce")
    if "LGS_Puan" in df.columns:
        df["LGS_Puan"] = pd.to_numeric(df["LGS_Puan"], errors="coerce")

    df["Deneme"] = exam_name
    df["Kademe"] = df["Sinif"].apply(extract_kademe)

    # Net kolonları sayısal
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
    # aynı denemeyi tekrar yüklersen önce sil (mükerrer olmasın)
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

def auto_comment(student_df: pd.DataFrame):
    """
    Basit ama rehberlik diliyle işe yarayan yorum.
    (Son 3 deneme trendine göre.)
    """
    if student_df.empty or student_df["lgs_puan"].dropna().empty:
        return "Bu öğrenci için yeterli puan verisi bulunamadı."

    s = student_df.sort_values("created_at")
    last = s["lgs_puan"].dropna().iloc[-1]
    first = s["lgs_puan"].dropna().iloc[0]
    diff = last - first

    if diff >= 20:
        trend = "Belirgin bir yükseliş var. Düzenli çalışmanın karşılığı alınmış görünüyor."
    elif diff >= 5:
        trend = "Olumlu yönde bir gelişim var. Bu istikrarı korumak önemli."
    elif diff <= -20:
        trend = "Puanlarda belirgin düşüş var. Çalışma düzeni, motivasyon ve sınav kaygısı birlikte değerlendirilmelidir."
    elif diff <= -5:
        trend = "Son denemelerde küçük bir gerileme var. Tekrar planı ve eksik kazanımlar gözden geçirilebilir."
    else:
        trend = "Puanlar genel olarak stabil. İlerleme için hedef derslere odaklı plan faydalı olur."

    return trend

# --------------------
# UI
# --------------------
st.title("🏫 Akademik Performans Takip Sistemi (5-8)")
st.caption("Her kademe kendi içinde değerlendirilir • İlk 40 • Öğrenci gelişimi • Otomatik yorum")

left, right = st.columns([1.1, 1])

with left:
    st.header("1) Deneme Excel Yükle ve Kaydet")
    uploaded_file = st.file_uploader("Excel (.xlsx) yükle", type=["xlsx"], key="excel_upload")

    if uploaded_file:
        df, genel_ort, kurum_ort, exam_name = parse_school_report(uploaded_file)

        st.success(f"Okundu ✅ | Deneme: {exam_name} | Öğrenci: {df['AdSoyad'].nunique()} | Kademe: {sorted(df['Kademe'].dropna().unique().tolist())}")

        with st.expander("📌 Kurum / Genel Ortalama", expanded=False):
            if len(kurum_ort) > 0:
                st.write("**Kurum Ortalaması**")
                st.dataframe(kurum_ort, use_container_width=True)
            if len(genel_ort) > 0:
                st.write("**Genel Ortalama**")
                st.dataframe(genel_ort, use_container_width=True)

        st.subheader("Önizleme (ilk 20)")
        st.dataframe(df.head(20), use_container_width=True)

        if st.button("✅ Bu denemeyi Supabase’e Kaydet", type="primary"):
            with st.spinner("Kaydediliyor..."):
                save_exam_to_supabase(df, exam_name)
                st.cache_data.clear()
            st.success("Kaydedildi ✅ (Artık geçmişte görünecek)")

with right:
    st.header("2) Kademeye Göre Analiz")
    all_df = fetch_all_results()

    if all_df.empty:
        st.info("Supabase’te henüz kayıt yok. Soldan Excel yükleyip kaydet.")
        st.stop()

    # Kademe seçimi
    kademeler = sorted([int(x) for x in all_df["kademe"].dropna().unique()])
    sec_kademe = st.selectbox("Kademe seç", kademeler)

    kdf = all_df[all_df["kademe"] == sec_kademe].copy()

    # Deneme seçimi (kademe içinde)
    exams = sorted([e for e in kdf["exam_name"].dropna().unique()])
    sec_exam = st.selectbox("Deneme seç", exams)

    df_exam = kdf[kdf["exam_name"] == sec_exam].copy()

    # Sidebar filtre
    st.sidebar.header("🔎 Filtreler")
    siniflar = sorted([s for s in df_exam["sinif"].dropna().unique()])
    sec_siniflar = st.sidebar.multiselect("Sınıf", siniflar, default=siniflar)
    df_f = df_exam[df_exam["sinif"].isin(sec_siniflar)].copy()

    ogr_list = sorted([s for s in df_f["ad_soyad"].dropna().unique()])
    sec_ogr = st.sidebar.selectbox("Öğrenci", ["(Seçme)"] + ogr_list)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Kademe", str(sec_kademe))
    with c2:
        st.metric("Öğrenci", f"{df_f['ad_soyad'].nunique()}")
    with c3:
        st.metric("Ortalama Puan", f"{df_f['lgs_puan'].mean():.2f}" if df_f["lgs_puan"].notna().any() else "—")
    with c4:
        st.metric("En Yüksek", f"{df_f['lgs_puan'].max():.2f}" if df_f["lgs_puan"].notna().any() else "—")

    tabA, tabB, tabC = st.tabs(["🏅 İlk 40", "🏫 Sınıf Analizi", "🧑‍🎓 Öğrenci Gelişimi"])

    with tabA:
        st.subheader(f"{sec_kademe}. sınıf • {sec_exam} • İlk 40")
        top40 = df_f.dropna(subset=["lgs_puan"]).sort_values("lgs_puan", ascending=False).head(40)
        st.dataframe(top40[["ad_soyad", "sinif", "lgs_puan"]], use_container_width=True)

    with tabB:
        st.subheader("Puan dağılımı ve sıralama")
        if df_f["lgs_puan"].notna().any():
            rank_df = df_f[["ad_soyad", "sinif", "lgs_puan"]].dropna().sort_values("lgs_puan", ascending=False)
            st.dataframe(rank_df, use_container_width=True)

            fig, ax = plt.subplots()
            ax.hist(df_f["lgs_puan"].dropna(), bins=15)
            ax.set_xlabel("Puan")
            ax.set_ylabel("Öğrenci Sayısı")
            st.pyplot(fig)
        else:
            st.warning("Bu denemede puan verisi yok.")

    with tabC:
        st.subheader("Öğrenci bazlı trend + yorum")
        if sec_ogr == "(Seçme)":
            st.info("Sol menüden bir öğrenci seç.")
        else:
            s = kdf[kdf["ad_soyad"] == sec_ogr].copy().sort_values("created_at")

            st.write(f"**Öğrenci:** {sec_ogr}  |  **Kademe:** {sec_kademe}")

            if s["lgs_puan"].notna().any():
                fig, ax = plt.subplots()
                ax.plot(s["exam_name"], s["lgs_puan"], marker="o")
                ax.set_xlabel("Deneme")
                ax.set_ylabel("Puan")
                ax.set_title("Denemeler Boyunca Puan Değişimi")
                plt.xticks(rotation=30, ha="right")
                st.pyplot(fig)

                st.write("### Otomatik Yorum")
                st.info(auto_comment(s))

                st.write("### Kayıtlar")
                st.dataframe(s[["exam_name", "sinif", "lgs_puan", "created_at"]], use_container_width=True)
            else:
                st.warning("Bu öğrenci için puan verisi bulunamadı.")
