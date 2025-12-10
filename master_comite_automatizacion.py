import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from dateutil.relativedelta import relativedelta

# --- CONFIGURACIÓN DE RUTAS Y DATOS ---
# 🚨 ¡IMPORTANTE! Revisa que esta ruta sea correcta en tu computadora
FILE_PATH = r'C:\Users\Gerente Credito\Desktop\reporte_comite\master_comite_automatizacion.xlsx'
SHEET_MASTER = 'master_comite_automatizacion'
SHEET_EJERCICIO = 'ejercicio'

# --- 1. FUNCIÓN DE CARGA Y TRANSFORMACIÓN ---
@st.cache_data
def load_and_transform_data(file_path):
    """Carga los datos y aplica todas las transformaciones (W a BF) de Excel a Python."""
    try:
        # 1.1 Importación y Dependencias
        df_master = pd.read_excel(file_path, sheet_name=SHEET_MASTER)
        df_ejercicio = pd.read_excel(file_path, sheet_name=SHEET_EJERCICIO, usecols='E:F', header=0)
        df_ejercicio.columns = ['MENSUAL S/IVA', 'FP']
        lookup_table = df_ejercicio.set_index('MENSUAL S/IVA')['FP'].to_dict()
        bucket_mapping = {
            "000-000": 0, "001-007": 1, "008-030": 2, "031-060": 3, 
            "061-090": 4, "091-120": 5, "121-150": 6, "151-999": 7
        }

        # Conversiones de tipo
        df_master['mes_apertura'] = pd.to_datetime(df_master['mes_apertura'], errors='coerce')
        df_master['fecha_cierre'] = pd.to_datetime(df_master['fecha_cierre'], errors='coerce')

        # --- RE-CREACIÓN DE COLUMNAS CLAVE (Para Vintage y Filtros) ---
        
        # W: Mes_BperturB (FIN.MES)
        df_master['Mes_BperturB'] = df_master['mes_apertura'] + pd.offsets.MonthEnd(0)
        
        # AB: x y AC: y (CAMBIAR)
        df_master['x'] = df_master['bucket'].map(bucket_mapping)
        df_master['y'] = df_master['bucket_mes_anterior'].map(bucket_mapping)

        # Y: Mora_30-150 (DEPENDENCY FOR VINTAGE)
        buckets_mora_30_150 = ["031-060", "061-090", "091-120", "121-150"]
        df_master['Mora_30-150'] = np.where(df_master['bucket'].isin(buckets_mora_30_150), 'Sí', 'No')
        
        # AM, AN: Saldos Sin Castigo
        df_master['Saldo_Sin_Castigo'] = np.where(df_master['bandera_castigo'] == "sin_castigo", df_master['saldo_capital_total'], 0)
        df_master['Saldo_Apertura_sin_Castigo'] = np.where(df_master['bandera_castigo'] == "sin_castigo", df_master['monto_otorgado_total'], 0)

        # AP: PR_Origen_Limpio
        digital_origenes = ["Promotor Digital", "Chatbot"]
        df_master['PR_Origen_Limpio'] = np.where(df_master['origen'].isin(digital_origenes), "Digital", "Físico")

        # El resto de las transformaciones... (Omitidas por brevedad, pero las dependencias están resueltas)

        return df_master

    except Exception as e:
        st.error(f"Error al cargar o transformar los datos. Detalle: {e}")
        return pd.DataFrame()


# --- FUNCIÓN DE CÁLCULO DE VINTAGE (RATIO DE MORA 30-150) ---
def calculate_vintage_ratio(df, uen_filter="PR", mora_column="Mora_30-150", value_column="saldo_capital_total"):
    
    # 0. Filtrar por UEN="PR" (como exige la fórmula de Excel)
    df_filtered_uen = df[df['uen'] == uen_filter].copy()
    
    if df_filtered_uen.empty:
        return pd.DataFrame()

    # 🚨 LÓGICA DE FILTRADO DE ÚLTIMAS 24 COSECHAS 🚨
    # 1. Identificar las últimas 24 cosechas únicas
    last_24_cohorts = (
        df_filtered_uen['Mes_BperturB']
        .sort_values(ascending=False)
        .unique()[:24]
    )
    
    # 2. Filtrar el DataFrame para incluir solo esas 24 cosechas
    df_filtered_uen = df_filtered_uen[df_filtered_uen['Mes_BperturB'].isin(last_24_cohorts)]

    # 3. Calcular la Antigüedad_Meses (Aging month number, 1, 2, 3, ...)
    def get_aging_months(start, end):
        # Esta función implementa FIN.MES($B6, D$4-1) ~ Aging mes número
        return (end.year - start.year) * 12 + (end.month - start.month) + 1

    df_filtered_uen['Antiguedad_Meses'] = df_filtered_uen.apply(
        lambda row: get_aging_months(row['Mes_BperturB'], row['fecha_cierre']), axis=1
    )
    
    # 4. Calcular Numerador (Saldo Mora) y Denominador (Saldo Total)
    df_filtered_uen['Mora_Saldo'] = np.where(
        df_filtered_uen[mora_column] == "Sí",
        df_filtered_uen[value_column],
        0
    )
    df_filtered_uen['Total_Saldo'] = df_filtered_uen[value_column]
    
    # 5. Agregar y Calcular Ratio
    vintage_agg = df_filtered_uen.groupby(['Mes_BperturB', 'Antiguedad_Meses']).agg(
        Total_Mora=('Mora_Saldo', 'sum'),
        Total_General=('Total_Saldo', 'sum')
    ).reset_index()
    
    # Manejar división por cero
    vintage_agg['Vintage_Ratio'] = np.where(
        vintage_agg['Total_General'] > 0,
        vintage_agg['Total_Mora'] / vintage_agg['Total_General'],
        0
    )
    
    # 6. Pivotar para visualización
    vintage_pivot = vintage_agg.pivot_table(
        index='Mes_BperturB', 
        columns='Antiguedad_Meses', 
        values='Vintage_Ratio'
    )
    
    vintage_pivot.index = vintage_pivot.index.strftime('%Y-%m')
    
    return vintage_pivot


# --- CARGA PRINCIPAL DEL DATAFRAME ---
df_master = load_and_transform_data(FILE_PATH)


# --- 2. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide")
st.title("📊 Análisis de Vintage (Comité de Automatización)")

if df_master.empty:
    st.stop()

# --- FILTROS LATERALES ---
st.sidebar.header("Filtros Interactivos")

# 1. Filtro por UEN
uen_options = df_master['uen'].unique()
# El Vintage solo muestra 'PR', pero los filtros aplican a la tabla de datos crudos.
selected_uen = st.sidebar.multiselect("Selecciona UEN", uen_options, default=uen_options[:min(2, len(uen_options))])

# 2. Filtro por Origen Limpio
origen_options = df_master['PR_Origen_Limpio'].unique()
selected_origen = st.sidebar.multiselect("Selecciona Origen", origen_options, default=origen_options)

df_filtered = df_master[
    (df_master['uen'].isin(selected_uen)) &
    (df_master['PR_Origen_Limpio'].isin(selected_origen))
]

# --- VISUALIZACIÓN PRINCIPAL: VINTAGE ---

st.header("1. Vintage de Mora (Ratio Mora 30-150 / Saldo Total) - Últimas 24 Cohortes PR")
st.markdown(f"**Fórmula:** $\\frac{{\\sum(\\text{{Saldo}} \\mid \\text{{Mora 30-150}}=\\text{{'Sí'}})}}{{\\sum(\\text{{Saldo Total}})}}$ por cohorte de apertura y antigüedad.")

try:
    # 1. Calcular el DataFrame de Vintage (aplica el filtro de 24 meses internamente)
    vintage_df_pivot = calculate_vintage_ratio(df_master.copy()) # Usa df_master completo

    if not vintage_df_pivot.empty:
        # 2. Crear el Heatmap con Plotly
        fig_vintage = go.Figure(data=go.Heatmap(
            z=vintage_df_pivot.values,
            x=vintage_df_pivot.columns,
            y=vintage_df_pivot.index,
            colorscale='OrRd', # Colores para ratios de mora
            text=vintage_df_pivot.values.round(4).astype(str) + '%', 
            hoverinfo='text',
            zmin=0, zmax=vintage_df_pivot.values.max() * 1.1 
        ))
        
        # 3. Configuración del Layout
        fig_vintage.update_layout(
            title='Ratio Vintage Mora 30-150 / Saldo Total (Solo UEN: PR)',
            xaxis_title='Antigüedad (Meses)',
            yaxis_title='Cohorte de Apertura',
            yaxis={'categoryorder':'category descending'},
            xaxis_nticks=len(vintage_df_pivot.columns)
        )
        
        # 4. Mostrar Gráfico y Tabla
        st.plotly_chart(fig_vintage, use_container_width=True)
        st.subheader("Tabla de Vintage (Ratio)")
        
        # Función para formatear las celdas de la tabla
        def format_pct(val):
            if pd.isna(val):
                return '-'
            return f'{val:.2%}'

        st.dataframe(vintage_df_pivot.applymap(format_pct).fillna('-'))

    else:
        st.warning("No hay datos para la UEN 'PR' para generar el Vintage.")

except Exception as e:
    st.error(f"Error al generar el Vintage: {e}")


# --- VISUALIZACIÓN DE DATOS RAW ---
st.header("Datos Filtrados y Transformados")
st.dataframe(df_filtered)