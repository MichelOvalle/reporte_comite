import streamlit as st
import pandas as pd
import numpy as np
from dateutil.relativedelta import relativedelta
import matplotlib as mpl 
import altair as alt 

# --- CONFIGURACIÓN DE RUTAS Y DATOS ---
FILE_PATH = r'C:\Users\Gerente Credito\Desktop\reporte_comite\master_comite_automatizacion.xlsx'
SHEET_MASTER = 'master_comite_automatizacion'
SHEET_EJERCICIO = 'ejercicio'

# --- 1. FUNCIÓN DE CARGA Y TRANSFORMACIÓN COMPLETA ---
@st.cache_data
def load_and_transform_data(file_path):
    """Carga los datos y aplica las transformaciones necesarias, incluyendo las columnas C1 a C25, CAPITAL_C1 a CAPITAL_C25 y las nuevas 890_C1 a 890_C25."""
    try:
        df_master = pd.read_excel(file_path, sheet_name=SHEET_MASTER)
        
        buckets_mora_30_150 = ["031-060", "061-090", "091-120", "121-150"]
        buckets_mora_08_90 = ["008-030", "031-060", "061-090"]

        def convert_mes_apertura(value):
            if pd.isna(value) or value in ['nan', 'NaN', '']:
                return pd.NaT
            if isinstance(value, (int, float)) and value > 1000:
                try:
                    return pd.to_datetime(value, unit='D', origin='1899-12-30')
                except:
                    pass
            try:
                return pd.to_datetime(str(value).strip(), errors='coerce', infer_datetime_format=True)
            except:
                return pd.NaT

        df_master['mes_apertura'] = df_master['mes_apertura'].apply(convert_mes_apertura)
        df_master['fecha_cierre'] = pd.to_datetime(df_master['fecha_cierre'], errors='coerce')

        # W: Mes_BperturB (FIN.MES)
        # Aseguramos que Mes_BperturB sea el día 1 del mes para una comparación limpia
        df_master['Mes_BperturB'] = df_master['mes_apertura'].dt.normalize().dt.to_period('M').dt.to_timestamp()
        
        df_master['Mora_30-150'] = np.where(df_master['bucket'].isin(buckets_mora_30_150), 'Sí', 'No')
        df_master['Mora_08-90'] = np.where(df_master['bucket'].isin(buckets_mora_08_90), 'Sí', 'No')

        digital_origenes = ["Promotor Digital", "Chatbot"]
        df_master['PR_Origen_Limpio'] = np.where(df_master['origen'].isin(digital_origenes), "Digital", "Físico")

        def get_month_diff(date1, date2):
            if pd.isna(date1) or pd.isna(date2):
                return np.nan
            return (date2.year - date1.year) * 12 + (date2.month - date1.month)

        df_master['dif_mes'] = df_master.apply(
            lambda row: get_month_diff(row['Mes_BperturB'], row['fecha_cierre']), axis=1
        )

        df_master['saldo_capital_total_30150'] = np.where(
            df_master['Mora_30-150'] == 'Sí',
            df_master['saldo_capital_total'],
            0
        )
        df_master['saldo_capital_total_890'] = np.where(
            df_master['Mora_08-90'] == 'Sí',
            df_master['saldo_capital_total'],
            0
        )
        df_master['saldo_capital_total'] = pd.to_numeric(df_master['saldo_capital_total'], errors='coerce').fillna(0)
        
        
        # --- COLUMNAS DE SEGUIMIENTO DE MORA 30-150 (C1 a C25) ---
        
        # C1 (Mes de Antigüedad 0): APLICAMOS LÓGICA DE DIF_MES=0
        df_master['saldo_capital_total_c1'] = np.where(
            df_master['dif_mes'] == 0,
            df_master['saldo_capital_total_30150'], 
            0
        ) 
        
        for n in range(1, 25):
            col_index = n + 1 
            col_name = f'saldo_capital_total_c{col_index}'
            
            df_master[col_name] = np.where(
                df_master['dif_mes'] == n,
                df_master['saldo_capital_total_30150'], 
                0
            )

        # --- NUEVAS COLUMNAS DE SEGUIMIENTO DE MORA 8-90 (890_C1 a 890_C25) ---
        
        df_master['saldo_capital_total_890_c1'] = np.where(
            df_master['dif_mes'] == 0,
            df_master['saldo_capital_total_890'],
            0
        )
        
        for n in range(1, 25):
            col_index = n + 1 
            col_name = f'saldo_capital_total_890_c{col_index}'
            
            df_master[col_name] = np.where(
                df_master['dif_mes'] == n,
                df_master['saldo_capital_total_890'], 
                0
            )

        # --- COLUMNAS DE CAPITAL (CAPITAL_C1 a CAPITAL_C25) ---
        
        df_master['capital_c1'] = np.where(
            df_master['dif_mes'] == 0,
            df_master['saldo_capital_total'],
            0
        )

        for n in range(1, 25):
            col_index = n + 1 
            col_name = f'capital_c{col_index}'
            
            df_master[col_name] = np.where(
                df_master['dif_mes'] == n,
                df_master['saldo_capital_total'], 
                0
            )
        
        return df_master

    except Exception as e:
        st.error(f"Error al cargar o transformar los datos. Detalle: {e}. Por favor, verifique la ruta del archivo y el formato de la columna 'mes_apertura'.")
        return pd.DataFrame()


# --- FUNCIÓN DE CÁLCULO DE SALDO CONSOLIDADO POR COHORTE (¡CALCULA LA TASA DE MORA!) ---
def calculate_saldo_consolidado(df, time_column='Mes_BperturB'):
    
    df_filtered = df.dropna(subset=[time_column]).copy()
    
    if df_filtered.empty:
        return pd.DataFrame()

    agg_dict = {'saldo_capital_total': 'sum'}
    
    for n in range(1, 26):
        agg_dict[f'saldo_capital_total_c{n}'] = 'sum'
        agg_dict[f'saldo_capital_total_890_c{n}'] = 'sum'
        agg_dict[f'capital_c{n}'] = 'sum'

    df_summary = df_filtered.groupby(time_column).agg(agg_dict).reset_index()
    
    # Normalizar Mes de Apertura a Datetime limpio
    df_summary['Mes de Apertura'] = pd.to_datetime(df_summary[time_column].dt.strftime('%Y-%m') + '-01')
    
    df_tasas = df_summary[['Mes de Apertura', 'saldo_capital_total']].copy()
    
    max_fecha_cierre = df_filtered['fecha_cierre'].max()
    
    for n in range(1, 26):
        antiguedad = n - 1 
        target_date = max_fecha_cierre - relativedelta(months=antiguedad)
        date_label = target_date.strftime('%Y-%m')
        
        mora_30150_col_orig = f'saldo_capital_total_c{n}'
        mora_890_col_orig = f'saldo_capital_total_890_c{n}'
        capital_col_orig = f'capital_c{n}'
        
        # Tasa 30-150
        tasa_30150 = np.where(
            df_summary[capital_col_orig] != 0,
            (df_summary[mora_30150_col_orig] / df_summary[capital_col_orig]) * 100,
            0
        )
        col_name_30150 = f'{date_label} (30-150)'
        df_tasas[col_name_30150] = tasa_30150

        # Tasa 8-90
        tasa_890 = np.where(
            df_summary[capital_col_orig] != 0,
            (df_summary[mora_890_col_orig] / df_summary[capital_col_orig]) * 100,
            0
        )
        col_name_890 = f'{date_label} (8-90)'
        df_tasas[col_name_890] = tasa_890

    df_tasas = df_tasas.sort_values('Mes de Apertura', ascending=True)
    
    df_tasas.rename(columns={'saldo_capital_total': 'Saldo Capital Total (Monto)'}, inplace=True)

    return df_tasas


# --- FUNCIÓN DE ESTILIZADO DE DATAFRAME (FORMATO CONDICIONAL) ---

def clean_cell_to_float(val):
    if isinstance(val, str) and val.endswith('%'):
        try:
            return float(val.replace('%', '').replace(',', ''))
        except ValueError:
            return np.nan 
    # Asegurarse de que los valores numéricos también sean tratados
    try:
        return float(val)
    except (ValueError, TypeError):
        return np.nan 

def apply_gradient_by_row(row):
    numeric_rates = row.iloc[2:].apply(clean_cell_to_float).dropna()
    styles = [''] * len(row)
    if len(numeric_rates) < 2:
        return styles

    cmap = mpl.cm.get_cmap('RdYlGn_r')
    v_min = numeric_rates.min()
    v_max = numeric_rates.max()
    
    if v_min == v_max:
        color_rgb = cmap(0.5)
        neutral_style = f'background-color: rgba({int(color_rgb[0]*255)}, {int(color_rgb[1]*255)}, {int(color_rgb[2]*255)}, 0.5); text-align: center;'
        for col_name in numeric_rates.index:
            col_loc = row.index.get_loc(col_name)
            styles[col_loc] = neutral_style
        return styles

    norm = mpl.colors.Normalize(v_min, v_max)
    
    for col_index, val in numeric_rates.items():
        rgba = cmap(norm(val))
        style_color = f'background-color: rgba({int(rgba[0]*255)}, {int(rgba[1]*255)}, {int(rgba[2]*255)}, 1.0); text-align: center;'
        col_loc = row.index.get_loc(col_index)
        styles[col_loc] = style_color
    return styles


def style_table(df_display):
    # tasa_cols se definirá después de la eliminación de la columna temporal
    
    styler = df_display.style
    
    # 1. Aplicar el gradiente fila por fila (HEATMAP)
    # Se debe hacer antes del cálculo de PROMEDIO/MAXIMO/MINIMO
    styler = styler.apply(
        apply_gradient_by_row, 
        axis=1, 
        subset=df_display.columns
    )
    
    # Aseguramos tasa_cols para el styler después de la posible eliminación de columnas
    if len(df_display.columns) > 2:
        tasa_cols = df_display.columns[2:].tolist()
        # 2. Aplicar formato de texto y negritas a las celdas de datos
        styler = styler.set_properties(
            **{'text-align': 'center'},
            subset=tasa_cols 
        )
        
    styler = styler.set_properties(
        **{'font-weight': 'bold', 'text-align': 'left'},
        subset=[df_display.columns[0]] 
    ).set_properties(
        **{'font-weight': 'bold', 'text-align': 'right'},
        subset=[df_display.columns[1]] 
    )
    
    def highlight_summary_rows(row):
        is_avg = (row.name == 'PROMEDIO')
        is_max = (row.name == 'MÁXIMO')
        is_min = (row.name == 'MÍNIMO')
        
        if is_avg or is_max or is_min:
            color = '#F0F0F0' if is_max or is_min else '#E6F3FF'
            return [f'font-weight: bold; background-color: {color};'] * len(row) 
        return [''] * len(row)

    styler = styler.apply(highlight_summary_rows, axis=1)

    return styler

# --- CARGA PRINCIPAL DEL DATAFRAME ---
df_master = load_and_transform_data(FILE_PATH)


# --- 2. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide")

# 🚨 SOLUCIÓN PARA EL ENCABEZADO: INYECTAR CSS GLOBALMENTE
HEADER_CSS = """
<style>
div.stDataFrame {
    width: 100%;
}
.stDataFrame th {
    background-color: #ADD8E6 !important; /* Celeste */
    color: black !important;
    font-weight: bold !important; /* Negritas */
    text-align: center !important;
}
.stDataFrame div[data-testid="stDataframeHeaders"] th {
    background-color: #ADD8E6 !important; 
}
</style>
"""
st.markdown(HEADER_CSS, unsafe_allow_html=True)
st.title("📊 Análisis Vintage")

if df_master.empty:
    st.error("No se pudo cargar y procesar el DataFrame maestro.")
    st.stop()


# --- CREACIÓN DE PESTAÑAS (TABS) ---
tab1, tab2 = st.tabs(["Análisis Vintage", "Configuración / Parámetros"])

# Inicializamos una variable para almacenar los datos brutos de la cohorte
# Esto es necesario porque el cálculo ocurre dentro de tab1
df_display_raw_30150 = pd.DataFrame()


with tab1:
    # --- CONTENIDO DE LA PESTAÑA 1: ANÁLISIS VINTAGE ---
    
    # --- 🛑 FILTRO PARA VISUALIZACIÓN: ÚLTIMAS 24 COHORTES DE APERTURA ---
    if not df_master['Mes_BperturB'].empty:
        unique_cohort_dates = df_master['Mes_BperturB'].dropna().unique()
        sorted_cohort_dates = pd.Series(pd.to_datetime(unique_cohort_dates)).sort_values(ascending=False)
        last_24_cohorts = sorted_cohort_dates.iloc[:24]
        # Usamos df_filtered_master para el filtrado de 24 cohortes
        df_filtered_master = df_master[df_master['Mes_BperturB'].isin(last_24_cohorts)].copy()
        
        if not last_24_cohorts.empty:
            max_date = last_24_cohorts.max().strftime('%Y-%m')
            min_date = last_24_cohorts.min().strftime('%Y-%m')
            st.info(f"Filtro aplicado: Mostrando solo las últimas **{len(last_24_cohorts)} cohortes** de apertura, desde **{min_date}** hasta **{max_date}**.")
        
    if 'df_filtered_master' not in locals() or df_filtered_master.empty:
        st.warning("El DataFrame maestro está vacío después de aplicar el filtro de las últimas 24 cohortes. Verifique que haya suficientes datos de cohorte.")
        st.stop()
    
    # --- FILTROS LATERALES ---
    st.sidebar.header("Filtros Interactivos")
    st.sidebar.markdown("**Instrucciones:** Las selecciones a continuación filtran los datos mostrados en la tabla.")

    # 1. Filtro por UEN
    uen_options = df_filtered_master['uen'].unique()
    selected_uens = st.sidebar.multiselect("Selecciona UEN", uen_options, default=uen_options[:min(2, len(uen_options))])

    # 2. Filtro por Origen Limpio
    origen_options = df_filtered_master['PR_Origen_Limpio'].unique()
    selected_origen = st.sidebar.multiselect("Selecciona Origen", origen_options, default=origen_options)

    if not selected_uens or not selected_origen:
        st.warning("Por favor, selecciona al menos una UEN y un Origen en el panel lateral.")
        st.stop()

    # Aplicar filtros al DataFrame maestro
    df_filtered = df_filtered_master[
        (df_filtered_master['uen'].isin(selected_uens)) &
        (df_filtered_master['PR_Origen_Limpio'].isin(selected_origen))
    ].copy()

    if df_filtered.empty:
        st.warning("No hay datos para la combinación de filtros seleccionada.")
        st.stop()


    # --- VISUALIZACIÓN PRINCIPAL: TABLA DE TASAS DE MORA (VINTAGE) ---
    st.header("1. Vintage Mora 30-150")

    try:
        # Calcular la Tabla Consolidada y las Tasas (Incluye 30-150 y 8-90)
        df_tasas_mora_full = calculate_saldo_consolidado(df_filtered) 
        
        # ----------------------------------------------------------------------------------
        # --- 1. MOSTRAR VINTAGE MORA 30-150 (Principal) ---
        # ----------------------------------------------------------------------------------

        if not df_tasas_mora_full.empty:
            
            # 1. AISLAR DATOS: Seleccionar solo columnas 30-150
            cols_30150 = ['Mes de Apertura', 'Saldo Capital Total (Monto)'] + [
                col for col in df_tasas_mora_full.columns if '(30-150)' in col
            ]
            df_display_raw_30150 = df_tasas_mora_full[cols_30150].copy() # <--- GUARDAMOS LA COPIA BRUTA AQUÍ
            
            # 2. RENOMBRAR COLUMNAS DE REPORTE: Eliminar el sufijo (30-150)
            rename_map_30150 = {col: col.replace(' (30-150)', '') 
                                for col in df_display_raw_30150.columns if '(30-150)' in col}
            df_display_raw_30150.rename(columns=rename_map_30150, inplace=True)
            
            
            # --- LÓGICA DE VISUALIZACIÓN COMPARTIDA ---
            
            def format_currency(val):
                return f'{val:,.0f}'
            def format_percent(val):
                return f'{val:,.2f}%'
                
            df_display_30150 = df_display_raw_30150.copy()
            
            # CREAR COLUMNA TEMPORAL DATETIME PARA LA LÓGICA DE CORTE
            df_display_30150['Fecha Cohorte DATETIME'] = df_display_30150['Mes de Apertura'].apply(lambda x: x.normalize())
            
            # FORMATO DE LA COLUMNA DE DISPLAY A STRING
            df_display_30150['Mes de Apertura'] = df_display_30150['Mes de Apertura'].dt.strftime('%Y-%m')
            
            tasa_cols_30150 = [col for col in df_display_30150.columns if col not in ['Mes de Apertura', 'Saldo Capital Total (Monto)', 'Fecha Cohorte DATETIME']]

            for index, row in df_display_30150.iterrows():
                cohort_date = row['Fecha Cohorte DATETIME'] # Usamos la columna temporal DATETIME para la comparación
                
                for col in tasa_cols_30150:
                    col_date_str = col.split(' ')[0] 
                    
                    try:
                        col_date = pd.to_datetime(col_date_str + '-01')
                    except:
                        continue

                    # LÓGICA DE CORTE: Si la fecha de reporte es estrictamente menor a la de cohorte, es vacío.
                    if col_date < cohort_date: 
                        df_display_30150.loc[index, col] = '' 
                    else:
                        df_display_30150.loc[index, col] = format_percent(row[col])

            df_display_30150.iloc[:, 1] = df_display_30150.iloc[:, 1].apply(format_currency)

            # ELIMINAR LA COLUMNA TEMPORAL DATETIME ANTES DE MOSTRAR
            df_display_30150.drop(columns=['Fecha Cohorte DATETIME'], inplace=True)

            # --- CÁLCULO DE RESUMEN 30-150 ---
            
            saldo_col_raw = df_display_raw_30150['Saldo Capital Total (Monto)']
            # rate_cols_raw es la data bruta de las tasas (sin las dos primeras columnas)
            rate_cols_raw = df_display_raw_30150.iloc[:, 2:]
            
            avg_row = pd.Series(index=df_display_30150.columns)
            max_row = pd.Series(index=df_display_30150.columns)
            min_row = pd.Series(index=df_display_30150.columns)
            
            # Cálculo de Saldo Capital Total (Columna 1)
            avg_row.iloc[1] = format_currency(saldo_col_raw.mean())
            max_row.iloc[1] = format_currency(saldo_col_raw.max())
            min_row.iloc[1] = format_currency(saldo_col_raw.min())
            
            # Cálculo de Tasas (Columnas 2 en adelante)
            for i, col_name in enumerate(rate_cols_raw.columns):
                # Usamos el índice de la columna en df_display_30150 (i + 2) para insertar el resultado
                rate_values = rate_cols_raw.iloc[:, i]
                
                avg_row.iloc[i + 2] = format_percent(rate_values.mean())
                max_row.iloc[i + 2] = format_percent(rate_values.max())
                min_row.iloc[i + 2] = format_percent(rate_values.min())
            
            avg_row.iloc[0] = 'PROMEDIO'
            max_row.iloc[0] = 'MÁXIMO'
            min_row.iloc[0] = 'MÍNIMO'
            
            df_display_30150.loc['MÁXIMO'] = max_row
            df_display_30150.loc['MÍNIMO'] = min_row
            df_display_30150.loc['PROMEDIO'] = avg_row
            
            # APLICAR ESTILOS
            styler_30150 = style_table(df_display_30150)
            st.dataframe(styler_30150, hide_index=True)
            
            
            # ----------------------------------------------------------------------------------
            # --- 2. MOSTRAR NUEVA TABLA VINTAGE MORA 8-90 ---
            # ----------------------------------------------------------------------------------
            st.header("2. Vintage Mora 8-90")

            # 1. AISLAR DATOS: Seleccionar solo columnas 8-90
            cols_890 = ['Mes de Apertura', 'Saldo Capital Total (Monto)'] + [
                col for col in df_tasas_mora_full.columns if '(8-90)' in col
            ]
            df_display_raw_890 = df_tasas_mora_full[cols_890].copy()
            
            # 2. RENOMBRAR COLUMNAS DE REPORTE: Eliminar el sufijo (8-90)
            rename_map_890 = {col: col.replace(' (8-90)', '') 
                              for col in df_display_raw_890.columns if '(8-90)' in col}
            df_display_raw_890.rename(columns=rename_map_890, inplace=True)
            
            
            # --- LÓGICA DE VISUALIZACIÓN COMPARTIDA (PARA 8-90) ---

            df_display_890 = df_display_raw_890.copy()
            
            # CREAR COLUMNA TEMPORAL DATETIME PARA LA LÓGICA DE CORTE
            df_display_890['Fecha Cohorte DATETIME'] = df_display_890['Mes de Apertura'].apply(lambda x: x.normalize())
            
            # FORMATO DE LA COLUMNA DE DISPLAY A STRING
            df_display_890['Mes de Apertura'] = df_display_890['Mes de Apertura'].dt.strftime('%Y-%m')
            
            tasa_cols_890 = [col for col in df_display_890.columns if col not in ['Mes de Apertura', 'Saldo Capital Total (Monto)', 'Fecha Cohorte DATETIME']]


            for index, row in df_display_890.iterrows():
                cohort_date = row['Fecha Cohorte DATETIME'] # Usamos la columna temporal DATETIME para la comparación
                
                for col in tasa_cols_890:
                    col_date_str = col.split(' ')[0] 
                    
                    try:
                        col_date = pd.to_datetime(col_date_str + '-01')
                    except:
                        continue

                    # LÓGICA DE CORTE: Si la fecha de reporte es estrictamente menor a la de cohorte, es vacío.
                    if col_date < cohort_date: 
                        df_display_890.loc[index, col] = '' 
                    else:
                        df_display_890.loc[index, col] = format_percent(row[col])

            df_display_890.iloc[:, 1] = df_display_890.iloc[:, 1].apply(format_currency)

            # ELIMINAR LA COLUMNA TEMPORAL DATETIME ANTES DE MOSTRAR
            df_display_890.drop(columns=['Fecha Cohorte DATETIME'], inplace=True)
            
            # --- CÁLCULO DE RESUMEN 8-90 ---
            
            saldo_col_raw = df_display_raw_890['Saldo Capital Total (Monto)']
            # rate_cols_raw_890 es la data bruta de las tasas (sin las dos primeras columnas)
            rate_cols_raw_890 = df_display_raw_890.iloc[:, 2:]
            
            avg_row = pd.Series(index=df_display_890.columns)
            max_row = pd.Series(index=df_display_890.columns)
            min_row = pd.Series(index=df_display_890.columns)
            
            # Cálculo de Saldo Capital Total (Columna 1)
            avg_row.iloc[1] = format_currency(saldo_col_raw.mean())
            max_row.iloc[1] = format_currency(saldo_col_raw.max())
            min_row.iloc[1] = format_currency(saldo_col_raw.min())
            
            # Cálculo de Tasas (Columnas 2 en adelante)
            for i, col_name in enumerate(rate_cols_raw_890.columns):
                # Usamos el índice de la columna en df_display_890 (i + 2) para insertar el resultado
                rate_values = rate_cols_raw_890.iloc[:, i]
                
                avg_row.iloc[i + 2] = format_percent(rate_values.mean())
                max_row.iloc[i + 2] = format_percent(rate_values.max())
                min_row.iloc[i + 2] = format_percent(rate_values.min())
            
            avg_row.iloc[0] = 'PROMEDIO'
            max_row.iloc[0] = 'MÁXIMO'
            min_row.iloc[0] = 'MÍNIMO'
            
            df_display_890.loc['MÁXIMO'] = max_row
            df_display_890.loc['MÍNIMO'] = min_row
            df_display_890.loc['PROMEDIO'] = avg_row
            
            # APLICAR ESTILOS
            styler_890 = style_table(df_display_890)
            st.dataframe(styler_890, hide_index=True)


        else:
            st.warning("No hay datos que cumplan con los criterios de filtro para generar la tabla.")

    except Exception as e:
        # 🚨 LÍNEA DE DIAGNÓSTICO: Muestra el error de Python en detalle
        st.error("¡Ha ocurrido un error inesperado al generar las tablas Vintage!")
        st.exception(e)
        
with tab2:
    # --- CONTENIDO DE LA PESTAÑA 2: CONFIGURACIÓN / PARÁMETROS ---
    st.header("⚙️ Tasa de Mora (Segundo Punto Vintage, $C_2$)")
    
    # Revisa si la variable df_display_raw_30150 fue generada y no está vacía
    if not df_display_raw_30150.empty:
        # La columna de la segunda tasa de mora (C2) está en el índice 3 del DataFrame bruto
        # (Índice 0: Mes de Apertura, Índice 1: Saldo Capital Total, Índice 2: C1, Índice 3: C2)
        target_column_index = 3
        
        # 1. Verificar si existe la columna requerida
        if len(df_display_raw_30150.columns) > target_column_index:
            
            # Obtener el nombre de la columna de la tasa
            rate_column_name = df_display_raw_30150.columns[target_column_index]
            
            # 2. Seleccionar solo las columnas Mes de Apertura (Índice 0) y la columna de tasa requerida (Índice 3)
            # Aseguramos que Mes de Apertura sea tipo Datetime para la gráfica
            df_chart_data = df_display_raw_30150.iloc[:, [0, target_column_index]].copy()
            
            # Renombrar para claridad
            new_col_name = f'Tasa Mora Vintage ({rate_column_name})'
            df_chart_data.rename(columns={rate_column_name: new_col_name}, inplace=True)
            
            # 3. Preparar los datos para la gráfica (convertir tasa a float para Altair)
            df_chart_data[new_col_name] = df_chart_data[new_col_name].astype(float)
            
            # --- 4. Generar Gráfica Altair ---
            chart = alt.Chart(df_chart_data).mark_line(point=True).encode(
                # CORRECCIÓN: Usamos 'temporal' y 'quantitative' en lugar de 'T' y 'Q'
                x=alt.X('Mes de Apertura', type='temporal', title='Mes de Apertura de la Cohorte', axis=alt.Axis(format='%Y-%m')),
                y=alt.Y(new_col_name, type='quantitative', title='Tasa de Mora (%)', axis=alt.Axis(format='.2f')),
                tooltip=['Mes de Apertura', alt.Tooltip(new_col_name, format='.2f')]
            ).properties(
                title=f"Evolución de Tasa de Mora Vintage: {rate_column_name}"
            ).interactive()
            
            st.altair_chart(chart, use_container_width=True)
            
            st.markdown(f"Esta gráfica muestra la tendencia de la tasa de mora en el punto **$C_2$** para las cohortes filtradas. ") # Trigger de imagen conceptual de Vintage
            
            # --- 5. Mostrar Tabla de Datos (Formato String) ---
            st.markdown("### Datos Detallados")
            
            # Crear una copia para la tabla para aplicar formatos de string
            df_cohort_column = df_chart_data.copy()
            
            # Formatear la columna de Mes de Apertura a String para la tabla
            df_cohort_column['Mes de Apertura'] = df_cohort_column['Mes de Apertura'].dt.strftime('%Y-%m')
            
            # Formatear la columna de Tasa de Mora a porcentaje String para la tabla
            for col in [new_col_name]:
                df_cohort_column[col] = df_cohort_column[col].apply(lambda x: f'{x:,.2f}%')


            st.dataframe(df_cohort_column, hide_index=True)
            
            st.markdown(f"**Punto Vintage Mostrado:** La tasa de mora de la cohorte correspondiente al periodo de reporte **{rate_column_name}**.")
            
        else:
            st.warning("El DataFrame de Vintage no tiene suficientes columnas (se requieren al menos 4) para mostrar la segunda columna de tasas de mora.")
            
    else:
        st.info("La tabla de Vintage debe ser cargada y filtrada en la pestaña 'Análisis Vintage' primero, o la combinación de filtros no arrojó resultados.")