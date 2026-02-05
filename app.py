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
    CEMIL_MERIC-8.xlsx gibi rapor formatını düzgün tabloya çevirir.
    - Üst başlık: ders isimleri (Türkçe, Tarih, ...)
    - Alt başlık: D/Y/N veya Derece bilgileri
    - "Genel Ortalama" / "Kurum Ortalaması" satırlarını ayırır
    - Tekrarlayan kolon isimlerini her tabloda benzersizleştirir (pyarrow hatasını kesin çözer)
    """
    raw = pd.read_excel(uploaded_file, header=None)
    raw = raw.dropna(axis=1, how="all")

    # Deneme adı (genelde 2. satır 1. kolon gibi)
    exam_name = "Deneme"
    try:
        val = raw.iloc[1, 0]
        if pd.notna(val):
            exam_name = str(val).strip()
    except Exception:
        pass

    # Başlık satırı: ilk sütunda "Öğr.No" olan satır
    header_idx = None
    for i in range(len(raw)):
        if str(raw.iloc[i, 0]).strip() == "Öğr.No":
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Başlık satırı bulunamadı: 'Öğr.No' satırı yok.")

    # Üst başlık (ders isimleri): header_idx-1
    top = raw.iloc[header_idx - 1].copy().ffill()

    # Alt başlık (D/Y/N vs): header_idx
    sub = raw.iloc[header_idx].copy()

    cols = []
    for j in range(len(sub)):
        top_j = str(top.iloc[j]).strip() if pd.notna(top.iloc[j]) else ""
        sub_j = str(sub.iloc[j]).strip() if pd.notna(sub.iloc[j]) else ""

        if j == 0:
            cols.append("OgrNo")
        elif j == 1:
            cols.append("AdSoyad")
        elif j == 2:
            cols.append("Sinif")
        else:
            # LGS Puan kolonunu yakala
            if top_j.lower() == "lgs" and sub_j.lower() == "puan":
                cols.append("LGS_Puan")
            # Dereceler
            elif sub_j in ["Sınıf", "Kurum", "İlçe", "İl", "Genel"]:
                cols.append(f"Derece_{sub_j}")
            else:
                # Ders D/Y/N kolonları
                if sub_j in ["D", "Y", "N"]:
                    cols.append(f"{top_j}_{sub_j}")
                else:
                    # Beklenmedik durum: en azından bir isim ver
                    cols.append(top_j if top_j else sub_j if sub_j else f"Kolon_{j}")

    cols = make_unique_columns(cols)

    df = raw.iloc[header_idx + 1 :].copy()
    df.columns = cols
    df = df.dropna(how="all")

    # Ortalama satırlarını ayır (OgrNo kolonu metin olabiliyor)
    first = df["OgrNo"].astype(str)

    genel_ort = df[first.str.contains("Genel Ortalama", na=False)].copy()
    kurum_ort = df[first.str.contains("Kurum Ortalaması", na=False)].copy()

    # Ana veriden çıkar
    df = df[~first.str.contains("Genel Ortalama|Kurum Ortalaması", na=False, regex=True)].copy()

    # Her üç tabloda da kolon adlarını benzersizleştir (kritik fix)
    df.columns = make_unique_columns(df.columns)
    genel_ort.columns = make_unique_columns(genel_ort.columns)
    kurum_ort.columns = make_unique_columns(kurum_ort.columns)

    # Tip düzeltmeleri
    df["OgrNo"] = pd.to_numeric(df["OgrNo"], errors="coerce")
    if "LGS_Puan" in df.columns:
        df["LGS_Puan"] = pd.to_numeric(df["LGS_Puan"], errors="coerce")

    df["Deneme"] = exam_name

    # D/Y/N kolonlarını sayısala çevir
    for c in df.columns:
        if c.endswith("_D") or c.endswith("_Y") or c.endswith("_N"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df.reset_index(drop=True), genel_ort, kurum_ort, exam_name


# --------------------
# UI
# --------------------
st.title("📊 LGS Deneme Takip ve Analiz Sistemi")
st.caption("Excel’den öğrencilerin performansını izleme, filtreleme ve raporlama paneli")

st.header("📥 Deneme Sonuçlarını Yükle")
uploaded_file = st.file_uploader("Excel dosyasını seçiniz (.xlsx)", type=["xlsx"], key="excel_upload")

if not uploaded_file:
    st.info("Devam etmek için Excel dosyasını yükleyin.")
    st.stop()

df, genel_ort, kurum_ort, exam_name = parse_cemil_meric_format(uploaded_file)

st.success(f"Yüklendi ✅  | Deneme: {exam_name} | Öğrenci: {df['AdSoyad'].nunique()}")

# ---------- Sidebar filtreler ----------
st.sidebar.header("🔎 Filtreler")

siniflar = sorted([s for s in df["Sinif"].dropna().unique()])
sec_siniflar = st.sidebar.multiselect("Sınıf", siniflar, default=siniflar)

df_f = df[df["Sinif"].isin(sec_siniflar)].copy()

ogrenciler = sorted([s for s in df_f["AdSoyad"].dropna().unique()])
sec_ogr = st.sidebar.selectbox("Öğrenci (tek)", ["(Seçme)"] + ogrenciler)

# ---------- KPI kartları ----------
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Öğrenci", f"{df_f['AdSoyad'].nunique()}")
with c2:
    st.metric("Sınıf", f"{df_f['Sinif'].nunique()}")
with c3:
    if "LGS_Puan" in df_f.columns and df_f["LGS_Puan"].notna().any():
        st.metric("Ortalama Puan", f"{df_f['LGS_Puan'].mean():.2f}")
    else:
        st.metric("Ortalama Puan", "—")
with c4:
    if "LGS_Puan" in df_f.columns and df_f["LGS_Puan"].notna().any():
        st.metric("En Yüksek Puan", f"{df_f['LGS_Puan'].max():.2f}")
    else:
        st.metric("En Yüksek Puan", "—")

tab1, tab2, tab3 = st.tabs(["📋 Liste", "🏫 Sınıf Analizi", "🧑‍🎓 Öğrenci Analizi"])

with tab1:
    st.subheader("Yüklenen Veri (filtreli)")
    st.dataframe(df_f, use_container_width=True)

    with st.expander("📌 Kurum / Genel Ortalama (Excel’deki satırlar)", expanded=False):
        if len(kurum_ort) > 0:
            st.write("**Kurum Ortalaması**")
            st.dataframe(kurum_ort, use_container_width=True)
        else:
            st.info("Kurum Ortalaması satırı bulunamadı.")

        if len(genel_ort) > 0:
            st.write("**Genel Ortalama**")
            st.dataframe(genel_ort, use_container_width=True)
        else:
            st.info("Genel Ortalama satırı bulunamadı.")

with tab2:
    st.subheader("Sınıf bazlı puan dağılımı ve sıralama")

    if "LGS_Puan" in df_f.columns and df_f["LGS_Puan"].notna().any():
        rank_df = df_f[["AdSoyad", "Sinif", "LGS_Puan"]].dropna().sort_values("LGS_Puan", ascending=False)
        st.dataframe(rank_df, use_container_width=True)

        fig, ax = plt.subplots()
        ax.hist(df_f["LGS_Puan"].dropna(), bins=15)
        ax.set_xlabel("LGS Puan")
        ax.set_ylabel("Öğrenci Sayısı")
        st.pyplot(fig)
    else:
        st.warning("Bu dosyada LGS Puan sütunu bulunamadı veya boş.")

with tab3:
    st.subheader("Öğrenci profili")

    if sec_ogr != "(Seçme)":
        odf = df_f[df_f["AdSoyad"] == sec_ogr].copy()

        c1, c2 = st.columns(2)
        with c1:
            st.write("**Seçili Öğrenci:**", sec_ogr)
            st.write("**Sınıf:**", odf["Sinif"].iloc[0] if len(odf) else "—")
        with c2:
            if "LGS_Puan" in odf.columns and odf["LGS_Puan"].notna().any():
                st.metric("Puan", f"{odf['LGS_Puan'].iloc[0]:.2f}")
            else:
                st.metric("Puan", "—")

        # Net kolonları (varsa)
        net_cols = [c for c in odf.columns if c.endswith("_N")]
        if net_cols:
            st.write("### Ders Netleri (N)")
            show = odf[net_cols].T
            show.columns = ["Net"]
            st.dataframe(show, use_container_width=True)
        else:
            st.info("Bu dosyada ders net (…_N) sütunları bulunamadı.")
    else:
        st.info("Soldan bir öğrenci seçersen detaylar burada görünecek.")
