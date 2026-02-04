import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from supabase import create_client
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
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
# BAŞLIK
# --------------------
st.title("📊 LGS Deneme Sınavı Takip ve Analiz Sistemi")
st.markdown("Psikolojik Danışman kullanımına özel analiz paneli")

# --------------------
# EXCEL YÜKLEME
# --------------------
st.header("📥 Deneme Sonuçlarını Yükle")

uploaded_file = st.file_uploader(
    "Excel dosyasını seçiniz (.xlsx)",
    type=["xlsx"]
)

if uploaded_file:
    df = pd.read_excel(uploaded_file)

    st.subheader("Yüklenen Veri Önizleme")
    st.dataframe(df.head())

    st.success("Excel dosyası başarıyla yüklendi.")

    # Basit analiz örneği
    if "Öğrenci Adı" in df.columns and "Toplam Net" in df.columns:
        st.header("📈 Toplam Net Gelişimi")

        fig, ax = plt.subplots()
        for ogrenci in df["Öğrenci Adı"].unique():
            ogr_df = df[df["Öğrenci Adı"] == ogrenci]
            ax.plot(ogr_df.index, ogr_df["Toplam Net"], label=ogrenci)

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

            for ogrenci in df["Öğrenci Adı"].unique():
                ort_net = df[df["Öğrenci Adı"] == ogrenci]["Toplam Net"].mean()
                elements.append(
                    Paragraph(f"{ogrenci} - Ortalama Net: {ort_net:.2f}", styles["Normal"])
                )

            doc.build(elements)
            buffer.seek(0)

            st.download_button(
                "PDF'i İndir",
                data=buffer,
                file_name="lgs_analiz_raporu.pdf",
                mime="application/pdf"
            )
