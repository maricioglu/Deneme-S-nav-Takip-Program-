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
    import pandas as pd

def load_lgs_excel(uploaded_file):
    raw = pd.read_excel(uploaded_file, header=None)  # başlık varsayma
    raw = raw.dropna(axis=1, how="all")              # tamamen boş sütunları at

    # "Öğr.No" satırını bul (asıl kolon başlıklarının başladığı yer)
    header_idx = None
    for i in range(len(raw)):
        row_str = raw.iloc[i].astype(str)
        if row_str.str.contains("Öğr.No", case=False, na=False).any():
            header_idx = i
            break
    if header_idx is None:
        # Bulamazsa en azından ilk satırı başlık yapma, ham döndür
        return raw, None, None

    # Başlık satırını kolon adı yap
    header = raw.iloc[header_idx].tolist()
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = header

    # Tamamen boş satırları at
    df = df.dropna(how="all")

    # Özet satırlarını ayır (Kurum Ortalaması / Genel Ortalama)
    kurum_ort = df[df.iloc[:, 0].astype(str).str.contains("Kurum Ortalaması", na=False)]
    genel_ort = df[df.iloc[:, 0].astype(str).str.contains("Genel Ortalama", na=False)]

    # Bu satırları ana veriden çıkar
    df = df[~df.iloc[:, 0].astype(str).str.contains("Kurum Ortalaması|Genel Ortalama", na=False, regex=True)]

    # Başlık tekrarları / sınıf-sınav satırı gibi satırları da ayıkla (isteğe bağlı ama faydalı)
    df = df[~df.iloc[:, 0].astype(str).str.contains("SINIF|SINAV", na=False)]

    # Sütun isimlerini temizle (boş/None olan kolonları at)
    df = df.loc[:, [c for c in df.columns if str(c).strip() not in ["None", "nan", ""]]]

    return df, kurum_ort, genel_ort


# --- senin mevcut kodunda, uploaded_file geldikten sonra şunu kullan:
df, kurum_ort, genel_ort = load_lgs_excel(uploaded_file)


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
