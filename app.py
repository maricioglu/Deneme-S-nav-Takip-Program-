import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from supabase import create_client

# --------------------
# AYARLAR
# --------------------
st.set_page_config(page_title="LGS Deneme Takip Sistemi", layout="wide")

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

@st.cache_data(show_spinner=False)
def parse_cemil_meric_format(uploaded_file):
    """
    Bu fonksiyon senin Excel formatını (3 satırlı başlık) doğru okur:
    - Satır0: Grup başlık (Sözel (TÜR), Toplam, LGS, ...)
    - Satır1: Ders/Alan (Türkçe, Tarih, ..., Puan, Dereceler)
    - Satır2: Alt başlık (D/Y/N veya Derece türü)
    """
    raw = pd.read_excel(uploaded_file, header=None)
    raw = raw.dropna(axis=1, how="all")

    # Deneme adı (genelde 2. satır 1. kolon)
    exam_name = "Deneme"
    try:
        v = raw.iloc[1, 0]
        if pd.notna(v):
            exam_name = str(v).strip()
    except Exception:
        pass

    # "Öğr.No" satırını bul (başlıkların başladığı satır)
    header_idx = None
    for i in range(len(raw)):
        if str(raw.iloc[i, 0]).strip() == "Öğr.No":
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Başlık satırı bulunamadı: 'Öğr.No' satırı yok.")

    # 3 başlık satırı: grup / ders / alt
    grp = raw.iloc[header_idx - 2].copy().ffill()   # Satır0 benzeri
    top = raw.iloc[header_idx - 1].copy().ffill()   # Satır1 (Türkçe, Tarih, Puan, Dereceler)
    sub = raw.iloc[header_idx].copy()               # Satır2 (D/Y/N veya Sınıf/Kurum/...)

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
            # ✅ LGS Puan: grup=LGS ve ders= Puan (sub boş olabilir)
            if g.lower() == "lgs" and t.lower() == "puan":
                cols.append("LGS_Puan")
            # Dereceler: ders = Dereceler, alt = Sınıf/Kurum/İlçe/İl/Genel
            elif t.lower() == "dereceler" and s in ["Sınıf", "Kurum", "İlçe", "İl", "Genel"]:
                cols.append(f"Derece_{s}")
            # Ders D/Y/N: ders adı + alt başlık
            elif s in ["D", "Y", "N"]:
                # örn: Türkçe_D
                cols.append(f"{t}_{s}")
            # Toplam D/Y/N: grup=Toplam, alt = D/Y/N ama t boş gelebilir
            elif g.lower() == "toplam" and s in ["D", "Y", "N"]:
                cols.append(f"Toplam_{s}")
            else:
                # Fallback
                base = t if t else g if g else f"Kolon_{j}"
                suffix = f"_{s}" if s else ""
                cols.append(f"{base}{suffix}")

    cols = make_unique_columns(cols)

    df = raw.iloc[header_idx + 1:].copy()
    df.columns = cols
    df = df.dropna(how="all")

    # Ortalama satırlarını ayır
    first = df["OgrNo"].astype(str)
    genel_ort = df[first.str.contains("Genel Ortalama", na=False)].copy()
    kurum_ort = df[first.str.contains("Kurum Ortalaması", na=False)].copy()
    df = df[~first.str.contains("Genel Ortalama|Kurum Ortalaması", na=False, regex=True)].copy()

    # pyarrow güvenliği
    df.columns = make_unique_columns(df.columns)
    genel_ort.columns = make_unique_columns(genel_ort.columns)
    kurum_ort.columns = make_unique_columns(kurum_ort.columns)

    # Tip düzeltme
    df["OgrNo"] = pd.to_numeric(df["OgrNo"], errors="coerce")
    if "LGS_Puan" in df.columns:
        df["LGS_Puan"] = pd.to_numeric(df["LGS_Puan"], errors="coerce")

    df["Deneme"] = exam_name

    # D/Y/N kolonlarını sayısala çevir
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
    # Aynı denemeyi tekrar yükleyince mükerrer olmasın diye önce sil
    supabase.table(TABLE).delete().eq("exam_name", exam_name).execute()

    rows = []
    for _, r in df_exam.iterrows():
        rows.append({
            "exam_name": exam_name,
            "exam_date": None,
            "ogr_no": int(r["OgrNo"]) if pd.notna(r.get("OgrNo")) else None,
            "ad_soyad": str(r.get("AdSoyad", "")).strip(),
            "sinif": str(r.get("Sinif", "")).strip() if pd.notna(r.get("Sinif")) else None,
            "lgs_puan": float(r.get("LGS_Puan")) if pd.notna(r.get("LGS_Puan")) else None,
            "payload": _to_payload(r),
        })

    # parçalı insert
    chunk = 300
    for i in range(0, len(rows), chunk):
        supabase.table(TABLE).insert(rows[i:i+chunk]).execute()


@st.cache_data(show_spinner=False, ttl=30)
def fetch_all_results():
    res = supabase.table(TABLE).select("exam_name,ogr_no,ad_soyad,sinif,lgs_puan,created_at").execute()
    return pd.DataFrame(res.data or [])


# --------------------
# UI
# --------------------
st.title("📊 LGS Deneme Takip ve Analiz Sistemi")
st.caption("Excel yükle → Supabase'e kaydet → geçmişten trend ve analiz")

left, right = st.columns([1.1, 1])

with left:
    st.header("1) Excel Yükle ve Kaydet")
    uploaded_file = st.file_uploader("Rapor (.xlsx)", type=["xlsx"], key="excel_upload")

    if uploaded_file:
        df, genel_ort, kurum_ort, exam_name = parse_cemil_meric_format(uploaded_file)

        st.success(f"Okundu ✅ | Deneme: {exam_name} | Öğrenci: {df['AdSoyad'].nunique()}")

        st.subheader("Önizleme (ilk 20 satır)")
        st.dataframe(df.head(20), use_container_width=True)

        with st.expander("📌 Kurum / Genel Ortalama (Excel’deki satırlar)", expanded=False):
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
            st.success("Kaydedildi ✅")

with right:
    st.header("2) Geçmiş Denemelerden Analiz")

    all_df = fetch_all_results()
    if all_df.empty:
        st.info("Supabase’te kayıt yok. Soldan Excel yükleyip kaydet.")
        st.stop()

    exams = sorted([e for e in all_df["exam_name"].dropna().unique()])
    sec_exam = st.selectbox("Deneme seç", exams)

    df_exam = all_df[all_df["exam_name"] == sec_exam].copy()

    st.sidebar.header("🔎 Filtreler")
    siniflar = sorted([s for s in df_exam["sinif"].dropna().unique()])
    sec_siniflar = st.sidebar.multiselect("Sınıf", siniflar, default=siniflar)

    df_f = df_exam[df_exam["sinif"].isin(sec_siniflar)].copy()

    ogr_list = sorted([s for s in df_f["ad_soyad"].dropna().unique()])
    sec_ogr = st.sidebar.selectbox("Öğrenci", ["(Seçme)"] + ogr_list)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Öğrenci", f"{df_f['ad_soyad'].nunique()}")
    with c2:
        st.metric("Sınıf", f"{df_f['sinif'].nunique()}")
    with c3:
        st.metric("Ortalama Puan", f"{df_f['lgs_puan'].mean():.2f}" if df_f["lgs_puan"].notna().any() else "—")

    tabA, tabB, tabC = st.tabs(["📋 Liste", "🏫 Sınıf", "📈 Öğrenci Trend"])

    with tabA:
        st.dataframe(df_f.sort_values(["sinif", "lgs_puan"], ascending=[True, False]), use_container_width=True)

    with tabB:
        if df_f["lgs_puan"].notna().any():
            rank_df = df_f[["ad_soyad", "sinif", "lgs_puan"]].dropna().sort_values("lgs_puan", ascending=False)
            st.dataframe(rank_df, use_container_width=True)

            fig, ax = plt.subplots()
            ax.hist(df_f["lgs_puan"].dropna(), bins=15)
            ax.set_xlabel("LGS Puan")
            ax.set_ylabel("Öğrenci Sayısı")
            st.pyplot(fig)
        else:
            st.warning("Bu denemede puan verisi yok.")

    with tabC:
        if sec_ogr == "(Seçme)":
            st.info("Sol menüden bir öğrenci seç.")
        else:
            all_student = all_df[all_df["ad_soyad"] == sec_ogr].copy().sort_values("created_at")

            st.write(f"**Öğrenci:** {sec_ogr}")

            if all_student["lgs_puan"].notna().any():
                fig, ax = plt.subplots()
                ax.plot(all_student["exam_name"], all_student["lgs_puan"], marker="o")
                ax.set_xlabel("Deneme")
                ax.set_ylabel("Puan")
                ax.set_title("Denemeler Boyunca Puan Değişimi")
                plt.xticks(rotation=30, ha="right")
                st.pyplot(fig)

                st.dataframe(all_student[["exam_name", "sinif", "lgs_puan", "created_at"]], use_container_width=True)
            else:
                st.warning("Bu öğrenci için puan verisi bulunamadı.")
