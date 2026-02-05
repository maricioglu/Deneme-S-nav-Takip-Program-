import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from supabase import create_client
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from io import BytesIO

# --------------------
# AYARLAR
# --------------------
st.set_page_config(page_title="LGS Deneme Takip Sistemi", layout="wide")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))

# --------------------
# EXCEL OKUMA / TEMİZLEME
# --------------------
def load_lgs_excel(uploaded_file):
    raw = pd.read_excel(uploaded_file, header=None)
    raw = raw.dropna(axis=1, how="all")

    header_idx = None
    for i in range(len(raw)):
        row_str = raw.iloc[i].astype(str)
        if row_str.str.contains("Öğr.No", case=False, na=False).any():
            header_idx = i
            break

    if header_idx is None:
        return raw, None, None

    header = raw.iloc[header_idx].tolist()
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = header
    df = df.dropna(how="all")

    first_col = df.iloc[:, 0].astype(str)
    kurum_ort = df[first_col.str.contains("Kurum Ortalaması", na=False)]
    genel_ort = df[first_col.str.contains("Genel Ortalama", na=False)]

    df = df[~first_col.str.contains("Kurum Ortalaması|Genel Ortalama", na=False, regex=True)]
    df = df[~df.iloc[:, 0].astype(str).str.contains("SINIF|SINAV", na=False)]
    df = df.loc[:, [c for c in df.columns if str(c).strip() not in ["None", "nan", ""]]]

    return df, kurum_ort, genel_ort


def normalize_columns_and_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    - 'Ad, Soyad' -> 'Öğrenci Adı' (yoksa başka olası isimleri de dener)
    - 'Toplam Net' yoksa sayısal sütunlardan toplam üretir
    """
    df = df.copy()

    # Sütun adlarını stringe çevirip trimle
    df.columns = [str(c).strip() for c in df.columns]

    # Öğrenci adı sütunu eşleme
    candidate_name_cols = [
        "Öğrenci Adı", "Ad Soyad", "Ad, Soyad", "Ad Soyad ", "Ad Soyadı", "Ad Soyadi", "Ad Soyadİ", "Ad SoyadI"
    ]
    if "Öğrenci Adı" not in df.columns:
        found = None
        for c in candidate_name_cols:
            if c in df.columns:
                found = c
                break
        if found:
            df = df.rename(columns={found: "Öğrenci Adı"})

    # Toplam Net üretimi
    if "Toplam Net" not in df.columns:
        # sayısala çevrilebilen sütunları yakala (Öğr.No gibi ID sütunlarını hariç tut)
        exclude_like = {"Öğr.No", "Öğr No", "Ögr.No", "Ögr No", "Sınıf", "Sinif", "Öğrenci Adı", "Ad, Soyad", "Ad Soyad"}
        numeric_candidates = [c for c in df.columns if c not in exclude_like]

        numeric_df = df[numeric_candidates].apply(pd.to_numeric, errors="coerce")
        # Çok boş olan kolonları düşür (tamamı NaN olanlar)
        numeric_df = numeric_df.dropna(axis=1, how="all")

        if numeric_df.shape[1] > 0:
            df["Toplam Net"] = numeric_df.sum(axis=1, skipna=True)

    return df


# --------------------
# BAŞLIK
# --------------------
st.title("📊 LGS Deneme Sınavı Takip ve Analiz Sistemi")
st.markdown("Psikolojik Danışman kullanımına özel analiz paneli")

# --------------------
# EXCEL YÜKLEME
# --------------------
st.header("📥 Deneme Sonuçlarını Yükle")

uploaded_file = st.file_uploader("Excel dosyasını seçiniz (.xlsx)", type=["xlsx"])

if uploaded_file:
    df, kurum_ort, genel_ort = load_lgs_excel(uploaded_file)
    df = normalize_columns_and_metrics(df)

    st.success("Excel dosyası başarıyla yüklendi.")

    st.subheader("Yüklenen Veri Önizleme")
    st.dataframe(df.head())

    with st.expander("📌 Kurum / Genel Ortalama (varsa)", expanded=False):
        if kurum_ort is not None and len(kurum_ort) > 0:
            st.write("**Kurum Ortalaması**")
            st.dataframe(kurum_ort)
        else:
            st.info("Kurum Ortalaması satırı bulunamadı.")

        if genel_ort is not None and len(genel_ort) > 0:
            st.write("**Genel Ortalama**")
            st.dataframe(genel_ort)
        else:
            st.info("Genel Ortalama satırı bulunamadı.")

    # --------------------
    # ANALİZ
    # --------------------
    if "Öğrenci Adı" in df.columns and "Toplam Net" in df.columns:
        st.header("📈 Toplam Net Gelişimi")

        fig, ax = plt.subplots()
        for ogrenci in df["Öğrenci Adı"].dropna().unique():
            ogr_df = df[df["Öğrenci Adı"] == ogrenci]
            ax.plot(ogr_df.index, ogr_df["Toplam Net"], label=str(ogrenci))

        ax.set_xlabel("Deneme Sırası")
        ax.set_ylabel("Toplam Net")
        ax.legend()
        st.pyplot(fig)

        # --------------------
        # PDF OLUŞTUR
        # --------------------
        st.header("📄 PDF Rapor")

        if st.button("PDF Rapor Oluştur"):
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer)
            styles = getSampleStyleSheet()
            styles["Normal"].fontName = "HeiseiMin-W3"

            elements = []
            elements.append(Paragraph("LGS Deneme Sınavı Analiz Raporu", styles["Title"]))
            elements.append(Spacer(1, 12))

            for ogrenci in df["Öğrenci Adı"].dropna().unique():
                ort_net = df[df["Öğrenci Adı"] == ogrenci]["Toplam Net"].mean()
                elements.append(Paragraph(f"{ogrenci} - Ortalama Net: {ort_net:.2f}", styles["Normal"]))

            doc.build(elements)
            buffer.seek(0)

            st.download_button(
                "PDF'i İndir",
                data=buffer,
                file_name="lgs_analiz_raporu.pdf",
                mime="application/pdf",
            )
    else:
        missing = []
        if "Öğrenci Adı" not in df.columns:
            missing.append("Öğrenci Adı (Ad, Soyad)")
        if "Toplam Net" not in df.columns:
            missing.append("Toplam Net (veya sayısal net sütunları)")
        st.warning("Analiz için gerekli alanlar bulunamadı: " + ", ".join(missing))
else:
    st.info("Devam etmek için bir .xlsx dosyası yükleyin.")
