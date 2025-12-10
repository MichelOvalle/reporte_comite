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

        # --- RE-CREACIÓN DE COLUMNAS CLAVE (W a BF) ---
        
        # W: Mes_BperturB (FIN.MES)
        df_master['Mes_BperturB'] = df_master['mes_apertura'] + pd.offsets.MonthEnd(0)
        
        # AB: x y AC: y (CAMBIAR)
        df_master['x'] = df_master['bucket'].map(bucket_mapping)
        df_master['y'] = df_master['bucket_mes_anterior'].map(bucket_mapping)

        # X: Mora_8-90
        buckets_mora_8_90 = ["008-030", "031-060", "061-090"]
        df_master['Mora_8-90'] = np.where(df_master['bucket'].isin(buckets_mora_8_90), 'Sí', 'No')

        # Y: Mora_30-150
        buckets_mora_30_150 = ["031-060", "061-090", "091-120", "121-150"]
        df_master['Mora_30-150'] = np.where(df_master['bucket'].isin(buckets_mora_30_150), 'Sí', 'No')
        
        # Z: tasa_SDO y AA: tasa_AP (BUSCAR)
        df_master['tasa_SDO'] = df_master['tasa_nominal_ponderada'].map(lookup_table)
        df_master['tasa_AP'] = df_master['tasa_nominal_apertura'].map(lookup_table)
        
        # AE: CONTENCION (Depende de x y y)
        conditions_cont = [
            df_master['bandera_castigo'] == "castigo_mes",
            (df_master['x'] == df_master['y']) | (df_master['x'] < df_master['y']),
            df_master['x'] > df_master['y'],
        ]
        choices_cont = ["151-999 SE CASTIGO", "CONTENCION", "EMPEORO"]
        inner_result = np.select(conditions_cont, choices_cont, default=df_master['bucket_mes_anterior'].astype(str) + " CASTIGO")
        df_master['CONTENCION'] = np.where(df_master['x'].isna() | df_master['y'].isna(), "N/D", inner_result)

        # AF: 008-090 
        map_008_090 = {"008-030": "SI", "031-060": "SI", "061-090": "SI"}
        df_master['008-090'] = df_master['bucket_mes_anterior'].map(map_008_090).fillna("NO")
        
        # AD: DESC
        conditions_desc = [
            df_master['bandera_castigo'] == "castigo_mes", df_master['x'] == df_master['y'],
            df_master['x'] > df_master['y'], df_master['x'] < df_master['y'],
        ]
        choices_desc = [
            "151-999 SE CASTIGO", df_master['bucket_mes_anterior'] + " MANTUVO",
            df_master['bucket_mes_anterior'] + " EMPEORO", df_master['bucket_mes_anterior'] + " MEJORO",
        ]
        df_master['DESC'] = np.select(conditions_desc, choices_desc, default=df_master['bucket_mes_anterior'].astype(str) + " CASTIGO")
        
        # AH: act y AI: ant
        df_master['act'] = np.where(df_master['x'] <= 4, 0, 1)
        df_master['ant'] = np.where(df_master['y'] <= 4, 0, 1)

        # AJ: DESC1
        conditions_desc1 = [df_master['act'] == df_master['ant'], df_master['ant'] > df_master['act']]
        choices_desc1 = ["Mantiene", "Vencido-Vigente"]
        df_master['DESC1'] = np.select(conditions_desc1, choices_desc1, default="Vigente-Vencido")

        # AK, AL: Constantes
        df_master['Rango_Monto'] = 0
        df_master['Rango_Saldo'] = 0

        # AM, AN: Saldos Sin Castigo
        df_master['Saldo_Sin_Castigo'] = np.where(df_master['bandera_castigo'] == "sin_castigo", df_master['saldo_capital_total'], 0)
        df_master['Saldo_Apertura_sin_Castigo'] = np.where(df_master['bandera_castigo'] == "sin_castigo", df_master['monto_otorgado_total'], 0)

        # AO: Saldo_Contencion
        df_master['Saldo_Contencion'] = np.where(df_master['CONTENCION'] == "N/D", 0, df_master['saldo_capital_total'])

        # AP: PR_Origen_Limpio (DEPENDENCY FOR FILTERS)
        digital_origenes = ["Promotor Digital", "Chatbot"]
        df_master['PR_Origen_Limpio'] = np.where(df_master['origen'].isin(digital_origenes), "Digital", "Físico")

        # AG: bandera_31-50
        map_31_150 = {"031-060": "SI", "061-090": "SI", "091-120": "SI", "121-150": "SI"}
        df_master['bandera_31-50'] = df_master['bucket'].map(map_31_150).fillna("NO")
        
        # AZ: sdo_31-150
        df_master['sdo_31-150'] = np.where(df_master['bandera_31-50'] == "SI", df_master['saldo_capital_total'], 0)

        # BA: bandera_008-090
        map_ba = {"008-030": "SI", "031-060": "SI", "061-090": "SI"}
        df_master['bandera_008-090'] = df_master['bucket'].map(map_ba).fillna("NO")
        
        # BB: sdo_008-090
        df_master['sdo_008-090'] = np.where(df_master['bandera_008-090'] == "SI", df_master['saldo_capital_total'], 0)

        # --- CÁLCULOS DE PORCENTAJES (Solo los necesarios para el dashboard) ---
        
        # BC: pctNom_x_terr
        sum_bc = df_master.groupby(['fecha_cierre', 'territorio'])['Saldo_Sin_Castigo'].transform('sum')
        df_master['pctNom_x_terr'] = df_master['tasa_nominal_ponderada'] * df_master['Saldo_Sin_Castigo'] / sum_bc
        df_master['pctNom_x_terr'] = df_master['pctNom_x_terr'].fillna(0)
        
        # BD: pctNomAP_x_terr
        sum_bd = df_master.groupby(['fecha_cierre', 'territorio'])['Saldo_Apertura_sin_Castigo'].transform('sum')
        df_master['pctNomAP_x_terr'] = df_master['tasa_nominal_apertura'] * df_master['Saldo_Apertura_sin_Castigo'] / sum_bd
        df_master['pctNomAP_x_terr'] = df_master['pctNomAP_x_terr'].fillna(0)
        
        # BE: Tipo_Tasa_SDO
        df_master['Tipo_Tasa_SDO'] = "Alta"
        
        # BF: Tipo_Tasa_AP
        df_master['Tipo_Tasa_AP'] = np.select(
            [df_master['tasa_AP'].isin([68, 69, 70, 71, 72]), df_master['tasa_AP'].isin([73, 74, 75, 76])],
            ["Baja", "Media"],
            default="Alta"
        )

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

    # 1. Filtrado de ÚLTIMAS 24 COSECHAS
    last_24_cohorts = (
        df_filtered_uen['Mes_BperturB']
        .sort_values(ascending=False)
        .unique()[:24]
    )
    df_filtered_uen = df_filtered_uen[df_filtered_uen['Mes_BperturB'].isin(last_24_cohorts)]

    # 2. Calcular la Antigüedad_Meses (Aging month number, 1, 2, 3, ...)
    def get_aging_months(start, end):
        return (end.year - start.year) * 12 + (end.month - start.month) + 1

    df_filtered_uen['Antiguedad_Meses'] = df_filtered_uen.apply(
        lambda row: get_aging_months(row['Mes_BperturB'], row['fecha_cierre']), axis=1
    )
    
    # 3. Calcular Numerador (Saldo Mora) y Denominador (Saldo Total)
    df_filtered_uen['Mora_Saldo'] = np.where(
        df_filtered_uen[mora_column] == "Sí",
        df_filtered_uen[value_column],
        0
    )
    df_filtered_uen['Total_Saldo'] = df_filtered_uen[value_column]
    
    # 4. Agregar y Calcular Ratio
    vintage_agg = df_filtered_uen.groupby(['Mes_BperturB', 'Antiguedad_Meses']).agg(
        Total_Mora=('Mora_Saldo', 'sum'),
        Total_General=('Total_Saldo', 'sum')
    ).reset_index()
    
    vintage_agg['Vintage_Ratio'] = np.where(
        vintage_agg['Total_General'] > 0,
        vintage_agg['Total_Mora'] / vintage_agg['Total_General'],
        0
    )
    
    # 5. Pivotar para visualización
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
st.title("📊 Análisis del Comité de Automatización")

if df_master.empty:
    st.stop()

# --- FILTROS LATERALES ---
st.sidebar.header("Filtros Interactivos")

# 1. Filtro por UEN
uen_options = df_master['uen'].unique()
selected_uen = st.sidebar.multiselect("Selecciona UEN", uen_options, default=uen_options[:min(2, len(uen_options))])

# 2. Filtro por Origen Limpio
origen_options = df_master['PR_Origen_Limpio'].unique()
selected_origen = st.sidebar.multiselect("Selecciona Origen", origen_options, default=origen_options)

df_filtered = df_master[
    (df_master['uen'].isin(selected_uen)) &
    (df_master['PR_Origen_Limpio'].isin(selected_origen))
]

if df_filtered.empty:
    st.warning("No hay datos que coincidan con los filtros seleccionados.")
    st.stop()


# --- VISUALIZACIONES PRINCIPALES ---

st.header("1. Vintage de Mora (Ratio Mora 30-150 / Saldo Total) - Últimas 24 Cohortes PR")
st.markdown(f"**Fórmula:** $\\frac{{\\sum(\\text{{Saldo}} \\mid \\text{{Mora 30-150}}=\\text{{'Sí'}})}}{{\\sum(\\text{{Saldo Total}})}}$ por cohorte de apertura y antigüedad.")

try:
    # Calcular el DataFrame de Vintage
    vintage_df_pivot = calculate_vintage_ratio(df_master.copy()) 

    if not vintage_df_pivot.empty:
        # 2. Crear el Heatmap con Plotly
        fig_vintage = go.Figure(data=go.Heatmap(
            z=vintage_df_pivot.values,
            x=vintage_df_pivot.columns,
            y=vintage_df_pivot.index,
            colorscale='OrRd', 
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


col1, col2 = st.columns(2)

with col1:
    st.header("2. Saldo Total por Bucket")

    # Agrupar datos filtrados para la gráfica
    df_bucket_summary = df_filtered.groupby(['bucket'])['saldo_capital_total'].sum().reset_index()
    df_bucket_summary.columns = ['Bucket', 'Saldo Total']

    # Gráfico de barras interactivo
    fig_bucket = px.bar(
        df_bucket_summary, 
        x='Bucket', 
        y='Saldo Total', 
        title='Saldo Capital Total por Días de Mora',
        color='Bucket',
        template='plotly_white'
    )
    st.plotly_chart(fig_bucket, use_container_width=True)

with col2:
    st.header("3. Saldo por Estrategia de Contención")

    # Agrupar por PR_Origen_Limpio y CONTENCION
    # Nota: La columna CONTENCION necesita ser calculada en load_and_transform_data si se usa aquí.
    # Asumiremos que las columnas necesarias están disponibles tras la carga.
    try:
        df_contencion_summary = df_filtered.groupby(['PR_Origen_Limpio', 'CONTENCION'])['saldo_capital_total'].sum().reset_index()
        # Gráfico de barras apiladas
        fig_contencion = px.bar(
            df_contencion_summary,
            x='PR_Origen_Limpio',
            y='saldo_capital_total',
            color='CONTENCION',
            title='Saldo Segmentado por Origen y Contención',
            template='plotly_white'
        )
        st.plotly_chart(fig_contencion, use_container_width=True)
    except KeyError:
        st.warning("La columna 'CONTENCION' no se cargó completamente. No se puede generar la gráfica 3.")


st.header("4. Tasa Nominal Ponderada (pctNom_x_terr) por Territorio")

# Agrupar por Territorio y calcular la suma de pctNom_x_terr (Tasa Ponderada Total)
# Nota: La columna pctNom_x_terr necesita ser calculada en load_and_transform_data si se usa aquí.
try:
    df_pct_summary = df_filtered.groupby('territorio')['pctNom_x_terr'].sum().reset_index()
    df_pct_summary.columns = ['Territorio', 'Tasa Ponderada Total']

    # Gráfico de pastel (Pie Chart)
    fig_pie = px.pie(
        df_pct_summary,
        values='Tasa Ponderada Total',
        names='Territorio',
        title='Distribución de Tasa Nominal Ponderada por Territorio',
        hole=.3
    )
    st.plotly_chart(fig_pie, use_container_width=True)
except KeyError:
    st.warning("La columna 'pctNom_x_terr' no se cargó completamente. No se puede generar la gráfica 4.")

# --- VISUALIZACIÓN DE DATOS RAW ---
st.header("Datos Filtrados y Transformados")
st.dataframe(df_filtered)