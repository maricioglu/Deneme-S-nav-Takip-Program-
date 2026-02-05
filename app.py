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

# Türkçe PDF fontu
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))

# --------------------
# EXCEL OKUMA / TEMİZLEME
# --------------------
def load_lgs_excel(uploaded_file):
    raw = pd.read_excel(uploaded_file, header=None)
    raw = raw.dropna(axis=1, how="all")

    # "Öğr.No" satırını bul (asıl kolon başlıklarının başladığı yer)
    header_idx = None
    for i in range(len(raw)):
        row_str = raw.iloc[i].astype(str)
        if row_str.str.contains("Öğr.No", case=False, na=False).any():
            header_idx = i
            break

    if header_idx is None:
        # Başlık satırını bulamazsa ham veriyi döndür
        return raw, None, None

    header = raw.iloc[header_idx].tolist()
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = header
    df = df.dropna(how="all")

    # Özet satırlarını ayır
    first_col = df.iloc[:, 0].astype(str)
    kurum_ort = df[first_col.str.contains("Kurum Ortalaması", na=False)]
    genel_ort = df[first_col.str.contains("Genel Ortalama", na=False)]

    # Özet satırlarını ana veriden çıkar
    df = df[~first_col.str.contains("Kurum Ortalaması|Genel Ortalama", na=False, regex=True)]

    # Başlık tekrarları / sınıf-sınav satırları
    df = df[~df.iloc[:, 0].astype(str).str.contains("SINIF|SINAV", na=False)]

    # Boş kolonları at
    df = df.loc[:, [c for c in df.columns if str(c).strip() not in ["None", "nan", ""]]]

    return df, kurum_ort, genel_ort


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

    st.success("Excel dosyası başarıyla yüklendi.")

    st.subheader("Yüklenen Veri Önizleme")
    st.dataframe(df.head())

    # (İstersen) Kurum/Genel ortalamayı göster
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
    # BASİT ANALİZ (ÖRNEK)
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
        st.warning("Analiz için 'Öğrenci Adı' ve 'Toplam Net' sütunları bulunamadı. Excel şablonunu kontrol edin.")
else:
    st.info("Devam etmek için bir .xlsx dosyası yükleyin.")

