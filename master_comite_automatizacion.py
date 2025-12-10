import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from dateutil.relativedelta import relativedelta

# --- CONFIGURACIÓN DE RUTAS Y DATOS ---
# 🚨 ¡IMPORTANTE! Revisa que esta ruta sea correcta en tu computadora
FILE_PATH = r'C:\Users\Gerente Credito\Desktop\reporte_comite\master_comite_automatizacion.xlsx'
SHEET_MASTER = 'master_comite_automatizacion'
SHEET_EJERCICIO = 'ejercicio'

# --- 1. FUNCIÓN DE CARGA Y TRANSFORMACIÓN COMPLETA (W a BF) ---
@st.cache_data
def load_and_transform_data(file_path):
    """Carga los datos y aplica todas las transformaciones de Excel (W a BF)."""
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

        # 🚨 CORRECCIÓN AVANZADA: Manejar formatos mixtos y NaNs en mes_apertura
        # Convertir a string y limpiar espacios para manejar datos mixtos o sucios
        df_master['mes_apertura'] = df_master['mes_apertura'].astype(str).str.strip()
        
        # Intentar la conversión, permitiendo que pandas infiera el formato (más flexible)
        df_master['mes_apertura'] = pd.to_datetime(
            df_master['mes_apertura'], 
            errors='coerce', 
            infer_datetime_format=True
        )
        
        # Conversión de fecha de cierre
        df_master['fecha_cierre'] = pd.to_datetime(df_master['fecha_cierre'], errors='coerce')

        # --- CREACIÓN DE COLUMNAS (W a BF) ---
        
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

        # AP: PR_Origen_Limpio
        digital_origenes = ["Promotor Digital", "Chatbot"]
        df_master['PR_Origen_Limpio'] = np.where(df_master['origen'].isin(digital_origenes), "Digital", "Físico")

        # AG, AY: bandera_31-50
        map_31_150 = {"031-060": "SI", "061-090": "SI", "091-120": "SI", "121-150": "SI"}
        df_master['bandera_31-50'] = np.where(df_master['bucket'].isin(map_31_150.keys()), 'SI', 'NO')
        
        # AZ: sdo_31-150
        df_master['sdo_31-150'] = np.where(df_master['bandera_31-50'] == "SI", df_master['saldo_capital_total'], 0)

        # BA: bandera_008-090
        map_ba = {"008-030": "SI", "031-060": "SI", "061-090": "SI"}
        df_master['bandera_008-090'] = np.where(df_master['bucket'].isin(map_ba.keys()), 'SI', 'NO')
        
        # BB: sdo_008-090
        df_master['sdo_008-090'] = np.where(df_master['bandera_008-090'] == "SI", df_master['saldo_capital_total'], 0)

        # --- CÁLCULOS DE PORCENTAJES (SUMAR.SI.CONJUNTO) ---
        
        # AQ: pctNom_x_UEN
        sum_aq = df_master.groupby(['fecha_cierre', 'uen'])['Saldo_Sin_Castigo'].transform('sum')
        df_master['pctNom_x_UEN'] = df_master['tasa_nominal_ponderada'] * df_master['Saldo_Sin_Castigo'] / sum_aq
        df_master['pctNom_x_UEN'] = df_master['pctNom_x_UEN'].fillna(0)
        
        # AR: pctNom_x_UEN_AP
        sum_ar = df_master.groupby(['fecha_cierre', 'Mes_BperturB', 'uen'])['Saldo_Apertura_sin_Castigo'].transform('sum')
        df_master['pctNom_x_UEN_AP'] = df_master['tasa_nominal_apertura'] * df_master['Saldo_Apertura_sin_Castigo'] / sum_ar
        df_master['pctNom_x_UEN_AP'] = df_master['pctNom_x_UEN_AP'].fillna(0)

        # AS: pctNom_x_Tipo_PR
        sum_as = df_master.groupby(['fecha_cierre', 'tipo_cliente'])['Saldo_Sin_Castigo'].transform('sum')
        df_master['pctNom_x_Tipo_PR'] = df_master['tasa_nominal_ponderada'] * df_master['Saldo_Sin_Castigo'] / sum_as
        df_master['pctNom_x_Tipo_PR'] = df_master['pctNom_x_Tipo_PR'].fillna(0)

        # AT: pctNom_x_Tipo_PR_AP
        sum_at = df_master.groupby(['fecha_cierre', 'Mes_BperturB', 'tipo_cliente'])['Saldo_Apertura_sin_Castigo'].transform('sum')
        df_master['pctNom_x_Tipo_PR_AP'] = df_master['tasa_nominal_apertura'] * df_master['Saldo_Apertura_sin_Castigo'] / sum_at
        df_master['pctNom_x_Tipo_PR_AP'] = df_master['pctNom_x_Tipo_PR_AP'].fillna(0)

        # AU: pctNom_x_OG_PR
        sum_au = df_master.groupby(['fecha_cierre', 'PR_Origen_Limpio'])['Saldo_Sin_Castigo'].transform('sum')
        df_master['pctNom_x_OG_PR'] = df_master['tasa_nominal_ponderada'] * df_master['Saldo_Sin_Castigo'] / sum_au
        df_master['pctNom_x_OG_PR'] = df_master['pctNom_x_OG_PR'].fillna(0)

        # AV: pctNom_x_OG_PR_AP
        sum_av = df_master.groupby(['fecha_cierre', 'Mes_BperturB', 'PR_Origen_Limpio'])['Saldo_Apertura_sin_Castigo'].transform('sum')
        df_master['pctNom_x_OG_PR_AP'] = df_master['tasa_nominal_apertura'] * df_master['Saldo_Apertura_sin_Castigo'] / sum_av
        df_master['pctNom_x_OG_PR_AP'] = df_master['pctNom_x_OG_PR_AP'].fillna(0)

        # AW: pctNom_x_Tipo_SOL
        sum_aw = df_master.groupby(['fecha_cierre', 'tipo_cliente_sol'])['Saldo_Sin_Castigo'].transform('sum')
        df_master['pctNom_x_Tipo_SOL'] = df_master['tasa_nominal_ponderada'] * df_master['Saldo_Sin_Castigo'] / sum_aw
        df_master['pctNom_x_Tipo_SOL'] = df_master['pctNom_x_Tipo_SOL'].fillna(0)

        # AX: pctNom_x_Tipo_SOL_AP
        sum_ax = df_master.groupby(['fecha_cierre', 'Mes_BperturB', 'tipo_cliente_sol'])['Saldo_Apertura_sin_Castigo'].transform('sum')
        df_master['pctNom_x_Tipo_SOL_AP'] = df_master['tasa_nominal_apertura'] * df_master['Saldo_Apertura_sin_Castigo'] / sum_ax
        df_master['pctNom_x_Tipo_SOL_AP'] = df_master['pctNom_x_Tipo_SOL_AP'].fillna(0)

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
        st.error(f"Error al cargar o transformar los datos. Detalle: {e}. Por favor, verifique la ruta del archivo y el formato de la columna 'mes_apertura'.")
        return pd.DataFrame()


# --- CARGA PRINCIPAL DEL DATAFRAME ---
# Esta línea ejecuta la carga y TODAS las transformaciones
df_master = load_and_transform_data(FILE_PATH)


# --- 2. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide")
st.title("🛠️ Interfaz de Visualización de Datos Transformados")

if df_master.empty:
    st.error("No se pudo cargar y procesar el DataFrame maestro.")
    st.stop()

# --- FILTROS LATERALES ---
st.sidebar.header("Filtros Interactivos")
st.sidebar.markdown("**Instrucciones:** Las selecciones a continuación filtran los datos mostrados en la gráfica.")

# 1. Filtro por UEN
uen_options = df_master['uen'].unique()
selected_uens = st.sidebar.multiselect("Selecciona UEN", uen_options, default=uen_options[:min(2, len(uen_options))])

# 2. Filtro por Origen Limpio
origen_options = df_master['PR_Origen_Limpio'].unique()
selected_origen = st.sidebar.multiselect("Selecciona Origen", origen_options, default=origen_options)

if not selected_uens or not selected_origen:
    st.warning("Por favor, selecciona al menos una UEN y un Origen en el panel lateral.")
    st.stop()

# Aplicar filtros al DataFrame maestro
df_filtered = df_master[
    (df_master['uen'].isin(selected_uens)) &
    (df_master['PR_Origen_Limpio'].isin(selected_origen))
].copy()

if df_filtered.empty:
    st.warning("No hay datos para la combinación de filtros seleccionada.")
    st.stop()


# --- ESPACIO PARA VISUALIZACIONES (AQUÍ ES DONDE CONTINUAREMOS) ---

st.header("DataFrame 'df_filtered' Listo para Visualización")
st.markdown(f"El DataFrame filtrado contiene **{len(df_filtered)}** filas con todas las columnas calculadas.")
st.dataframe(df_filtered.head()) # Mostrar las primeras filas del df_filtered para verificación.