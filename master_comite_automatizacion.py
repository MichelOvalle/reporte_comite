import streamlit as st
import pandas as pd
import numpy as np
from dateutil.relativedelta import relativedelta
import matplotlib as mpl 
import altair as alt 
from sklearn.linear_model import LinearRegression 

# --- CONFIGURACIÓN DE RUTAS Y DATOS ---
FILE_PATH = r'C:\Users\Gerente Credito\Desktop\reporte_comite\master_comite_automatizacion.xlsx'
SHEET_MASTER = 'master_comite_automatizacion'
SHEET_EJERCICIO = 'ejercicio'

# --- 1. FUNCIÓN DE CARGA Y TRANSFORMACIÓN COMPLETA (AÑADIDA LIMPIZA) ---
@st.cache_data
def load_and_transform_data(file_path):
    """Carga los datos y aplica las transformaciones necesarias, incluyendo la nueva columna 'nombre_sucursal'."""
    try:
        df_master = pd.read_excel(file_path, sheet_name=SHEET_MASTER)
        
        # --- LIMPIEZA CLAVE DE COLUMNAS CATEGÓRICAS AL INICIO ---
        if 'uen' in df_master.columns:
            df_master['uen'] = df_master['uen'].astype(str).str.strip().str.upper()
        if 'nombre_sucursal' in df_master.columns:
            df_master['nombre_sucursal'] = df_master['nombre_sucursal'].astype(str).str.strip()
        
        buckets_mora_30_150 = ["031-060", "061-090", "091-120", "121-150"]
        # Mora 8-90 (Para Solidar)
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
        df_master['Mes_BperturB'] = df_master['mes_apertura'].dt.normalize().dt.to_period('M').dt.to_timestamp()
        
        df_master['Mora_30-150'] = np.where(df_master['bucket'].isin(buckets_mora_30_150), 'Sí', 'No')
        df_master['Mora_08-90'] = np.where(df_master['bucket'].isin(buckets_mora_08_90), 'Sí', 'No')

        digital_origenes = ["Promotor Digital", "Chatbot"]
        df_master['origen'] = df_master['origen'].astype(str).str.strip() 
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
        df_master['operaciones'] = 1
        
        df_master['saldo_capital_total'] = pd.to_numeric(df_master['saldo_capital_total'], errors='coerce').fillna(0)
        
        
        # --- COLUMNAS DE SEGUIMIENTO DE MORA 30-150 (C1 a C25) ---
        
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


# --- FUNCIÓN DE CÁLCULO DE SALDO CONSOLIDADO POR COHORTE ---
def calculate_saldo_consolidado(df, time_column='Mes_BperturB'):
    
    df_filtered = df.dropna(subset=[time_column]).copy()
    
    if df_filtered.empty:
        return pd.DataFrame()

    agg_dict = {'saldo_capital_total': 'sum', 'operaciones': 'sum'} 
    
    for n in range(1, 26):
        agg_dict[f'saldo_capital_total_c{n}'] = 'sum'
        agg_dict[f'saldo_capital_total_890_c{n}'] = 'sum'
        agg_dict[f'capital_c{n}'] = 'sum'

    df_summary = df_filtered.groupby(time_column).agg(agg_dict).reset_index()
    
    df_summary['Mes de Apertura'] = pd.to_datetime(df_summary[time_column].dt.strftime('%Y-%m') + '-01')
    
    df_tasas = df_summary[['Mes de Apertura', 'saldo_capital_total', 'operaciones']].copy()
    
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
    
    df_tasas.rename(columns={'saldo_capital_total': 'Saldo Capital Total (Monto)', 'operaciones': 'Total Operaciones'}, inplace=True)

    return df_tasas


# --- FUNCIONES DE ESTILIZADO Y CÁLCULO DE RESUMEN (Mantenidas) ---

def clean_cell_to_float(val):
    if isinstance(val, str) and val.endswith('%'):
        try:
            return float(val.replace('%', '').replace(',', ''))
        except ValueError:
            return np.nan 
    try:
        return float(val)
    except (ValueError, TypeError):
        return np.nan 

def apply_gradient_by_row(row):
    numeric_rates = row.iloc[3:].apply(clean_cell_to_float).dropna()
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


def style_table(df_display, df_raw_rates):
    
    styler = df_display.style
    
    styler = styler.apply(
        apply_gradient_by_row, 
        axis=1, 
        subset=df_display.columns[3:]
    )
    
    if len(df_display.columns) > 3:
        tasa_cols = df_display.columns[3:].tolist()
        styler = styler.set_properties(
            **{'text-align': 'center'},
            subset=tasa_cols 
        )
        
    styler = styler.set_properties(
        **{'font-weight': 'bold', 'text-align': 'left'},
        subset=[df_display.columns[0]] 
    ).set_properties(
        **{'font-weight': 'bold', 'text-align': 'right'},
        subset=[df_display.columns[1], df_display.columns[2]] 
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


# --- FUNCIÓN DE CÁLCULO ESPECÍFICO C2 POR SUCURSAL (Mora 30-150, utilizada para PR) ---
def calculate_sucursal_c2_mora(df, uen_name):
    """Calcula la mora C2 (30-150) para la UEN y consolida por sucursal."""
    
    df_uen = df[df['uen'] == uen_name].copy()
    
    if df_uen.empty:
        return pd.DataFrame()

    df_summary = df_uen.groupby('nombre_sucursal').agg(
        Capital_C2=('capital_c2', 'sum'),
        Mora_C2=('saldo_capital_total_c2', 'sum'), # Mora 30-150
        Operaciones=('operaciones', 'sum')
    ).reset_index()

    df_summary['% Mora C2'] = np.where(
        df_summary['Capital_C2'] != 0,
        (df_summary['Mora_C2'] / df_summary['Capital_C2']) * 100,
        0
    )
    
    df_summary.rename(columns={'nombre_sucursal': 'Sucursal'}, inplace=True)
    
    df_summary = df_summary[df_summary['Capital_C2'] > 0].sort_values('% Mora C2', ascending=False)
    
    return df_summary[['Sucursal', '% Mora C2', 'Capital_C2', 'Operaciones']]

# --- FUNCIÓN DE CÁLCULO C2 POR SUCURSAL (Mora 8-90, utilizada para SOLIDAR) ---
def calculate_sucursal_c2_mora_890(df, uen_name):
    """Calcula la mora C2 (8-90) para la UEN y consolida por sucursal."""
    
    df_uen = df[df['uen'] == uen_name].copy()
    
    if df_uen.empty:
        return pd.DataFrame()

    df_summary = df_uen.groupby('nombre_sucursal').agg(
        Capital_C2=('capital_c2', 'sum'),
        Mora_C2=('saldo_capital_total_890_c2', 'sum'), # <-- CAMBIO CLAVE: Mora 8-90
        Operaciones=('operaciones', 'sum')
    ).reset_index()

    df_summary['% Mora C2'] = np.where(
        df_summary['Capital_C2'] != 0,
        (df_summary['Mora_C2'] / df_summary['Capital_C2']) * 100,
        0
    )
    
    df_summary.rename(columns={'nombre_sucursal': 'Sucursal'}, inplace=True)
    
    df_summary = df_summary[df_summary['Capital_C2'] > 0].sort_values('% Mora C2', ascending=False)
    
    df_summary['Métrica'] = 'Mora 8-90 C2'
    
    return df_summary[['Sucursal', '% Mora C2', 'Capital_C2', 'Operaciones', 'Métrica']]


# --- FUNCIÓN PARA PRONÓSTICO SIMPLE (Mora 30-150, ¡SOLUCIÓN AL ERROR!) ---
def simple_c2_forecast(df):
    """Realiza un pronóstico simple de regresión lineal para la próxima tasa C2 (30-150)."""
    
    # La Tasa C2 (30-150) es la columna 5: [Mes, Saldo, Ops, Tasa 30-150 C1, Tasa 8-90 C1, Tasa 30-150 C2]
    target_column_index = 5 
    
    if len(df.columns) <= target_column_index:
        return np.nan
        
    df_forecast = df.iloc[:, [0, target_column_index]].copy()
    df_forecast.columns = ['Mes de Apertura', 'Tasa_C2']
    
    df_forecast = df_forecast.dropna(subset=['Tasa_C2'])
    
    if len(df_forecast) < 2:
        return np.nan
        
    df_forecast['X_Time'] = np.arange(len(df_forecast))
    
    X = df_forecast['X_Time'].values.reshape(-1, 1)
    Y = df_forecast['Tasa_C2'].values
    
    next_time_point = len(df_forecast) 
    
    model = LinearRegression()
    model.fit(X, Y)
    
    forecast_value = model.predict([[next_time_point]])
    
    return max(0, forecast_value[0])

# --- FUNCIÓN PARA PRONÓSTICO SIMPLE (Mora 8-90, utilizada para SOLIDAR) ---
def simple_c2_forecast_890(df):
    """Realiza un pronóstico simple de regresión lineal para la próxima tasa C2 (8-90)."""
    
    # La Tasa C2 (8-90) es la columna 6: [..., Tasa 30-150 C2, Tasa 8-90 C2]
    target_column_index = 6
    
    if len(df.columns) <= target_column_index:
        return np.nan
        
    df_forecast = df.iloc[:, [0, target_column_index]].copy()
    df_forecast.columns = ['Mes de Apertura', 'Tasa_C2']
    
    df_forecast = df_forecast.dropna(subset=['Tasa_C2'])
    
    if len(df_forecast) < 2:
        return np.nan
        
    df_forecast['X_Time'] = np.arange(len(df_forecast))
    
    X = df_forecast['X_Time'].values.reshape(-1, 1)
    Y = df_forecast['Tasa_C2'].values
    
    next_time_point = len(df_forecast) 
    
    model = LinearRegression()
    model.fit(X, Y)
    
    forecast_value = model.predict([[next_time_point]])
    
    return max(0, forecast_value[0])

# --- FUNCIÓN DE GRÁFICA DE PRONÓSTICO (Mantenida) ---
def plot_c2_forecast(df_consolidado, forecast_value, uen_name, target_metric):
    """
    Genera la gráfica de tendencia de Mora C2 incluyendo el punto pronosticado.
    target_metric debe ser '30-150' (col 5) o '8-90' (col 6)
    """
    
    # El mapeo de columnas es 1 más alto debido a la estructura de calculate_saldo_consolidado
    col_index_map = {'30-150': 5, '8-90': 6} 
    target_column_index = col_index_map.get(target_metric, 5)
    
    if len(df_consolidado.columns) <= target_column_index:
        return st.warning(f"Datos insuficientes para la gráfica de pronóstico {target_metric} C2.")
    
    df_chart = df_consolidado.iloc[:, [0, target_column_index]].copy()
    df_chart.columns = ['Mes', 'Tasa (%)']
    df_chart['Tipo'] = 'Histórico'
    
    last_month = df_chart['Mes'].max()
    next_month = last_month + relativedelta(months=1)
    
    df_forecast_point = pd.DataFrame([{
        'Mes': next_month,
        'Tasa (%)': forecast_value,
        'Tipo': 'Pronóstico'
    }])
    
    df_final = pd.concat([df_chart, df_forecast_point], ignore_index=True)
    df_final['Tasa (%)'] = pd.to_numeric(df_final['Tasa (%)'], errors='coerce')
    
    line = alt.Chart(df_final[df_final['Tipo'] == 'Histórico']).mark_line(point=True).encode(
        x=alt.X('Mes', type='temporal', title='Mes de Apertura de Cohorte', axis=alt.Axis(format='%Y-%m')),
        y=alt.Y('Tasa (%)', type='quantitative', title=f'Tasa de Mora {target_metric} C2 (%)', scale=alt.Scale(zero=True), axis=alt.Axis(format='.2f')),
        tooltip=[alt.Tooltip('Mes', format='%Y-%m'), alt.Tooltip('Tasa (%)', format='.2f'), 'Tipo'],
        color=alt.value("#1f77b4") 
    )
    
    point = alt.Chart(df_final[df_final['Tipo'] == 'Pronóstico']).mark_point(filled=True, size=150, shape="triangle-down").encode(
        x='Mes',
        y='Tasa (%)',
        tooltip=[alt.Tooltip('Mes', format='%Y-%m'), alt.Tooltip('Tasa (%)', format='.2f'), 'Tipo'],
        color=alt.value("red")
    )
    
    text = point.mark_text(
        align='left',
        baseline='middle',
        dx=7, 
        fontSize=12,
        fontWeight='bold'
    ).encode(
        text=alt.Text('Tasa (%)', format='.2f')
    )
    
    chart = (line + point + text).properties(
        title=f"Tendencia de Mora {target_metric} C2 ({uen_name}) con Pronóstico"
    ).interactive()
    
    st.altair_chart(chart, use_container_width=True)


# --- CARGA PRINCIPAL DEL DATAFRAME ---
df_master = load_and_transform_data(FILE_PATH)


# --- 2. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide")

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
tab1, tab2, tab3 = st.tabs(["Análisis Vintage", "Gráficas Clave y Detalle", "Análisis por Sucursal"])

df_display_raw_30150 = pd.DataFrame()
df_filtered = pd.DataFrame()
df_filtered_master = pd.DataFrame()
selected_uens = [] 


with tab1:
    # --- CONTENIDO DE LA PESTAÑA 1: ANÁLISIS VINTAGE ---
    
    if not df_master['Mes_BperturB'].empty:
        unique_cohort_dates = df_master['Mes_BperturB'].dropna().unique()
        sorted_cohort_dates = pd.Series(pd.to_datetime(unique_cohort_dates)).sort_values(ascending=False)
        last_24_cohorts = sorted_cohort_dates.iloc[:24]
        # df_filtered_master: Solo filtrado por las últimas 24 cohortes
        df_filtered_master = df_master[df_master['Mes_BperturB'].isin(last_24_cohorts)].copy()
        
        if not last_24_cohorts.empty:
            max_date = last_24_cohorts.max().strftime('%Y-%m')
            min_date = last_24_cohorts.min().strftime('%Y-%m')
            st.info(f"Filtro aplicado: Mostrando solo las últimas **{len(last_24_cohorts)} cohortes** de apertura, desde **{min_date}** hasta **{max_date}**.")
        
    if df_filtered_master.empty:
        st.warning("El DataFrame maestro está vacío después de aplicar el filtro de las últimas 24 cohortes. Verifique que haya suficientes datos de cohorte.")
        st.stop()
    
    # --- FILTROS LATERALES ---
    st.sidebar.header("Filtros Interactivos")
    st.sidebar.markdown("**Instrucciones:** Las selecciones a continuación filtran los datos mostrados en la tabla.")

    # 1. Filtro por UEN
    uen_options = df_filtered_master['uen'].unique()
    default_uens = ['PR', 'SOLIDAR'] if 'PR' in uen_options and 'SOLIDAR' in uen_options else uen_options[:min(2, len(uen_options))]
    selected_uens = st.sidebar.multiselect("Selecciona UEN", uen_options, default=default_uens)

    # 2. Filtro por Origen Limpio
    origen_options = df_filtered_master['PR_Origen_Limpio'].unique()
    selected_origen = st.sidebar.multiselect("Selecciona Origen", origen_options, default=origen_options)

    # 3. Filtro por Sucursal
    sucursal_options = df_filtered_master['nombre_sucursal'].dropna().unique()
    selected_sucursales = st.sidebar.multiselect("Selecciona Sucursal", sucursal_options, default=sucursal_options)


    if not selected_uens or not selected_origen or not selected_sucursales:
        st.warning("Por favor, selecciona al menos una opción en todos los filtros del panel lateral.")
        st.stop()

    # df_filtered: Aplicación de TODOS los filtros, se usa para tab1 y tab2
    df_filtered = df_filtered_master[
        (df_filtered_master['uen'].isin(selected_uens)) &
        (df_filtered_master['PR_Origen_Limpio'].isin(selected_origen)) &
        (df_filtered_master['nombre_sucursal'].isin(selected_sucursales)) 
    ].copy()

    if df_filtered.empty:
        st.warning("No hay datos para la combinación de filtros seleccionada.")
        st.stop()


    # --- VISUALIZACIÓN PRINCIPAL: TABLA DE TASAS DE MORA (VINTAGE) ---
    st.header("1. Vintage Mora 30-150")

    try:
        df_tasas_mora_full = calculate_saldo_consolidado(df_filtered) 
        
        if not df_tasas_mora_full.empty:
            
            # 1. AISLAR DATOS: Seleccionar solo columnas 30-150
            cols_30150 = ['Mes de Apertura', 'Saldo Capital Total (Monto)', 'Total Operaciones'] + [
                col for col in df_tasas_mora_full.columns if '(30-150)' in col
            ]
            df_display_raw_30150 = df_tasas_mora_full[cols_30150].copy() 
            
            # 2. RENOMBRAR COLUMNAS DE REPORTE: Eliminar el sufijo (30-150)
            rename_map_30150 = {col: col.replace(' (30-150)', '') 
                                for col in df_display_raw_30150.columns if '(30-150)' in col}
            df_display_raw_30150.rename(columns=rename_map_30150, inplace=True)
            
            
            # --- LÓGICA DE VISUALIZACIÓN Y FORMATO ---
            
            def format_currency(val): return f'{val:,.0f}'
            def format_percent(val): return f'{val:,.2f}%'
            def format_int(val): return f'{val:,.0f}'
                
            df_display_30150 = df_display_raw_30150.copy()
            df_display_30150['Fecha Cohorte DATETIME'] = df_display_30150['Mes de Apertura'].apply(lambda x: x.normalize())
            df_display_30150['Mes de Apertura'] = df_display_30150['Mes de Apertura'].dt.strftime('%Y-%m')
            
            tasa_cols_30150 = [col for col in df_display_30150.columns if col not in ['Mes de Apertura', 'Saldo Capital Total (Monto)', 'Total Operaciones', 'Fecha Cohorte DATETIME']]

            rate_cols_raw_values = df_display_raw_30150.iloc[:, 3:].copy()
            rate_cols_raw_values.columns = tasa_cols_30150
            
            # Aplicar el corte del triángulo y formateo a STRING
            for index, row in df_display_30150.iterrows():
                cohort_date = row['Fecha Cohorte DATETIME'] 
                
                for col in tasa_cols_30150:
                    col_date_str = col.split(' ')[0] 
                    try: col_date = pd.to_datetime(col_date_str + '-01')
                    except: continue

                    if col_date < cohort_date: 
                        df_display_30150.loc[index, col] = '' 
                        rate_cols_raw_values.loc[index, col] = np.nan 
                    else:
                        df_display_30150.loc[index, col] = format_percent(row[col])

            df_display_30150.iloc[:, 1] = df_display_30150.iloc[:, 1].apply(format_currency)
            df_display_30150.iloc[:, 2] = df_display_30150.iloc[:, 2].apply(format_int)

            df_display_30150.drop(columns=['Fecha Cohorte DATETIME'], inplace=True)

            # --- CÁLCULO DE RESUMEN CORREGIDO ---
            
            saldo_col_raw = df_display_raw_30150['Saldo Capital Total (Monto)']
            ops_col_raw = df_display_raw_30150['Total Operaciones'] 
            
            avg_row = pd.Series(index=df_display_30150.columns)
            max_row = pd.Series(index=df_display_30150.columns)
            min_row = pd.Series(index=df_display_30150.columns)
            
            # Capital y Ops
            avg_row.iloc[1] = format_currency(saldo_col_raw.mean())
            avg_row.iloc[2] = format_int(ops_col_raw.mean()) 
            max_row.iloc[1] = format_currency(saldo_col_raw.max())
            max_row.iloc[2] = format_int(ops_col_raw.max())
            min_row.iloc[1] = format_currency(saldo_col_raw.min())
            min_row.iloc[2] = format_int(ops_col_raw.min())
            
            # Tasas
            for i, col_name in enumerate(tasa_cols_30150):
                rate_values = rate_cols_raw_values.iloc[:, i].dropna()
                
                avg_row.iloc[i + 3] = format_percent(rate_values.mean()) if not rate_values.empty else 'N/A'
                max_row.iloc[i + 3] = format_percent(rate_values.max()) if not rate_values.empty else 'N/A'
                
                valid_min = rate_values[rate_values > 0].min()
                min_row.iloc[i + 3] = format_percent(valid_min) if pd.notna(valid_min) else '0.00%'
            
            avg_row.iloc[0] = 'PROMEDIO'
            max_row.iloc[0] = 'MÁXIMO'
            min_row.iloc[0] = 'MÍNIMO'
            
            df_display_30150.loc['MÁXIMO'] = max_row
            df_display_30150.loc['MÍNIMO'] = min_row
            df_display_30150.loc['PROMEDIO'] = avg_row
            
            # Aplicar estilizado usando la tabla RAW para el gradiente
            styler_30150 = style_table(df_display_30150, df_display_raw_30150)
            st.dataframe(styler_30150, hide_index=True)
            
            
            # --- 2. MOSTRAR NUEVA TABLA VINTAGE MORA 8-90 ---
            st.header("2. Vintage Mora 8-90")

            cols_890 = ['Mes de Apertura', 'Saldo Capital Total (Monto)', 'Total Operaciones'] + [
                col for col in df_tasas_mora_full.columns if '(8-90)' in col
            ]
            df_display_raw_890 = df_tasas_mora_full[cols_890].copy()
            
            rename_map_890 = {col: col.replace(' (8-90)', '') 
                              for col in df_display_raw_890.columns if '(8-90)' in col}
            df_display_raw_890.rename(columns=rename_map_890, inplace=True)
            
            df_display_890 = df_display_raw_890.copy()
            df_display_890['Fecha Cohorte DATETIME'] = df_display_890['Mes de Apertura'].apply(lambda x: x.normalize())
            df_display_890['Mes de Apertura'] = df_display_890['Mes de Apertura'].dt.strftime('%Y-%m')
            
            tasa_cols_890 = [col for col in df_display_890.columns if col not in ['Mes de Apertura', 'Saldo Capital Total (Monto)', 'Total Operaciones', 'Fecha Cohorte DATETIME']]

            rate_cols_raw_values_890 = df_display_raw_890.iloc[:, 3:].copy()
            rate_cols_raw_values_890.columns = tasa_cols_890

            # Aplicar el corte del triángulo y formateo a STRING
            for index, row in df_display_890.iterrows():
                cohort_date = row['Fecha Cohorte DATETIME'] 
                for col in tasa_cols_890:
                    col_date_str = col.split(' ')[0] 
                    try: col_date = pd.to_datetime(col_date_str + '-01')
                    except: continue

                    if col_date < cohort_date: 
                        df_display_890.loc[index, col] = '' 
                        rate_cols_raw_values_890.loc[index, col] = np.nan
                    else:
                        df_display_890.loc[index, col] = format_percent(row[col])

            df_display_890.iloc[:, 1] = df_display_890.iloc[:, 1].apply(format_currency)
            df_display_890.iloc[:, 2] = df_display_890.iloc[:, 2].apply(format_int)

            df_display_890.drop(columns=['Fecha Cohorte DATETIME'], inplace=True)
            
            # --- CÁLCULO DE RESUMEN 8-90 CORREGIDO ---
            saldo_col_raw = df_display_raw_890['Saldo Capital Total (Monto)']
            ops_col_raw = df_display_raw_890['Total Operaciones']
            
            avg_row = pd.Series(index=df_display_890.columns)
            max_row = pd.Series(index=df_display_890.columns)
            min_row = pd.Series(index=df_display_890.columns)
            
            # Capital y Ops
            avg_row.iloc[1] = format_currency(saldo_col_raw.mean())
            avg_row.iloc[2] = format_int(ops_col_raw.mean()) 
            max_row.iloc[1] = format_currency(saldo_col_raw.max())
            max_row.iloc[2] = format_int(ops_col_raw.max())
            min_row.iloc[1] = format_currency(saldo_col_raw.min())
            min_row.iloc[2] = format_int(ops_col_raw.min())
            
            # Tasas
            for i, col_name in enumerate(tasa_cols_890):
                rate_values = rate_cols_raw_values_890.iloc[:, i].dropna()
                
                avg_row.iloc[i + 3] = format_percent(rate_values.mean()) if not rate_values.empty else 'N/A'
                max_row.iloc[i + 3] = format_percent(rate_values.max()) if not rate_values.empty else 'N/A'
                
                valid_min = rate_values[rate_values > 0].min()
                min_row.iloc[i + 3] = format_percent(valid_min) if pd.notna(valid_min) else '0.00%'

            avg_row.iloc[0] = 'PROMEDIO'
            max_row.iloc[0] = 'MÁXIMO'
            min_row.iloc[0] = 'MÍNIMO'
            
            df_display_890.loc['MÁXIMO'] = max_row
            df_display_890.loc['MÍNIMO'] = min_row
            df_display_890.loc['PROMEDIO'] = avg_row
            
            styler_890 = style_table(df_display_890, df_display_raw_890)
            st.dataframe(styler_890, hide_index=True)

        else:
            st.warning("No hay datos que cumplan con los criterios de filtro para generar la tabla.")

    except Exception as e:
        st.error("¡Ha ocurrido un error inesperado al generar las tablas Vintage!")
        st.exception(e)
        
with tab2:
    # --- CONTENIDO DE LA PESTAÑA 2: GRÁFICAS CLAVE Y DETALLE ---
    
    st.header("📈 Gráficas Clave del Análisis Vintage")

    if df_display_raw_30150.empty or df_filtered.empty:
        st.info("Por favor, aplique los filtros y genere el reporte en la pestaña 'Análisis Vintage' primero.")
        st.stop()
        
    # --- GRÁFICA 1: CURVAS VINTAGE (Múltiples Cohortes) ---
    st.subheader("1. Curvas de Mora Vintage (Mora 30-150)")
    st.write("Muestra la evolución de la tasa de mora de las **últimas 12 cohortes** disponibles a lo largo de su vida (Antigüedad).")

    df_long = df_display_raw_30150.iloc[:, 0:].copy()
    vintage_cols = df_long.columns[3:].tolist()
    cohortes_a_mostrar = df_long['Mes de Apertura'].sort_values(ascending=False).unique()[:12]
    df_long_filtered = df_long[df_long['Mes de Apertura'].isin(cohortes_a_mostrar)].copy()
    
    if not df_long_filtered.empty:
        df_long_filtered['Cohorte Etiqueta'] = df_long_filtered['Mes de Apertura'].dt.strftime('%Y-%m')
        
        df_long_melt = df_long_filtered.melt(
            id_vars=['Mes de Apertura', 'Cohorte Etiqueta'],
            value_vars=vintage_cols,
            var_name='Mes de Reporte',
            value_name='Tasa (%)'
        )
        
        df_long_melt.dropna(subset=['Tasa (%)'], inplace=True)
        df_long_melt['Tasa (%)'] = pd.to_numeric(df_long_melt['Tasa (%)'], errors='coerce')
        df_long_melt.dropna(subset=['Tasa (%)'], inplace=True)

        df_long_melt['Fecha Reporte'] = df_long_melt['Mes de Reporte'].apply(lambda x: pd.to_datetime(x.split(' ')[0] + '-01', errors='coerce'))
        df_long_melt['Fecha Apertura'] = df_long_melt['Mes de Apertura'].apply(lambda x: pd.to_datetime(x.strftime('%Y-%m') + '-01'))
        
        df_long_melt['Antigüedad (Meses)'] = (
            (df_long_melt['Fecha Reporte'].dt.year - df_long_melt['Fecha Apertura'].dt.year) * 12 +
            (df_long_melt['Fecha Reporte'].dt.month - df_long_melt['Fecha Apertura'].dt.month)
        )
        
        df_long_melt.dropna(subset=['Antigüedad (Meses)'], inplace=True)
        df_long_melt['Antigüedad (Meses)'] = df_long_melt['Antigüedad (Meses)'].astype(int)

        chart1 = alt.Chart(df_long_melt).mark_line(point=True).encode(
            x=alt.X('Antigüedad (Meses)', type='quantitative', title='Antigüedad de la Cohorte (Meses)', 
                    scale=alt.Scale(domainMin=0), 
                    axis=alt.Axis(tickMinStep=1)),
            y=alt.Y('Tasa (%)', type='quantitative', title='Tasa de Mora (%)', 
                    scale=alt.Scale(zero=True), 
                    axis=alt.Axis(format='.2f')),
            color=alt.Color('Cohorte Etiqueta', type='nominal', title='Cohorte (Mes Apertura)'),
            tooltip=['Cohorte Etiqueta', 'Antigüedad (Meses)', alt.Tooltip('Tasa (%)', format='.2f')]
        ).properties(
            title='Curvas Vintage de Mora 30-150'
        ).interactive()
        
        st.altair_chart(chart1, use_container_width=True)


    else:
        st.warning("No hay suficientes datos para generar la gráfica de Curvas Vintage.")


    # --- GRÁFICA 2: SERIE TEMPORAL DE UN PUNTO VINTAGE ESPECÍFICO (C2) ---
    st.subheader("2. Evolución Histórica de Tasa de Mora en $C_2$")
    st.write("Muestra la tendencia de la tasa de mora para el **segundo punto vintage** ($C_2$, o punto de reporte 3) para todas las cohortes.")

    target_column_index = 4 # Mes de Apertura, Saldo, Ops, C1, C2
    
    if len(df_display_raw_30150.columns) > target_column_index:
        
        rate_column_name = df_display_raw_30150.columns[target_column_index]
        df_chart_data_c2 = df_display_raw_30150.iloc[:, [0, target_column_index]].copy()
        new_col_name = f'Tasa Mora Vintage ({rate_column_name})'
        df_chart_data_c2.rename(columns={rate_column_name: new_col_name}, inplace=True)
        df_chart_data_c2[new_col_name] = df_chart_data_c2[new_col_name].astype(float)
        
        chart2 = alt.Chart(df_chart_data_c2).mark_line(point=True).encode(
            x=alt.X('Mes de Apertura', type='temporal', title='Mes de Apertura de la Cohorte', axis=alt.Axis(format='%Y-%m')),
            y=alt.Y(new_col_name, type='quantitative', title='Tasa de Mora (%)', axis=alt.Axis(format='.2f')),
            tooltip=['Mes de Apertura', alt.Tooltip(new_col_name, format='.2f')]
        ).properties(
            title=f"Tendencia de Tasa de Mora en punto Vintage: {rate_column_name}"
        ).interactive()
        
        st.altair_chart(chart2, use_container_width=True)

        st.markdown("### Datos Detallados ($C_2$)")
        df_cohort_column_display = df_chart_data_c2.copy()
        df_cohort_column_display['Mes de Apertura'] = df_cohort_column_display['Mes de Apertura'].dt.strftime('%Y-%m')
        df_cohort_column_display[new_col_name] = df_cohort_column_display[new_col_name].apply(lambda x: f'{x:,.2f}%')
        st.dataframe(df_cohort_column_display, hide_index=True)
        st.markdown(f"**Punto Vintage Mostrado:** La tasa de mora de la cohorte correspondiente al periodo de reporte **{rate_column_name}**.")
        
    else:
        st.warning("El DataFrame de Vintage no tiene suficientes columnas para mostrar el punto C2.")


    # --- GRÁFICA 3: COMPOSICIÓN DEL VOLUMEN POR ORIGEN (Stacked Bar) ---
    st.subheader("3. Composición del Saldo Capital Total por Origen")
    st.write("Muestra cómo se distribuye el volumen de saldo capital por Origen de la Operación a lo largo del tiempo.")
    
    df_volumen = df_filtered.groupby(['Mes_BperturB', 'PR_Origen_Limpio'])['saldo_capital_total'].sum().reset_index()
    df_volumen.rename(columns={'Mes_BperturB': 'Mes de Apertura', 'saldo_capital_total': 'Saldo Capital Total'}, inplace=True)
    
    chart3 = alt.Chart(df_volumen).mark_bar().encode(
        x=alt.X('Mes de Apertura', type='temporal', title='Mes de Apertura', axis=alt.Axis(format='%Y-%m')),
        y=alt.Y('Saldo Capital Total', type='quantitative', title='Saldo Capital Total', axis=alt.Axis(format='$,.0f')),
        color=alt.Color('PR_Origen_Limpio', type='nominal', title='Origen'),
        tooltip=['Mes de Apertura', 'PR_Origen_Limpio', alt.Tooltip('Saldo Capital Total', format='$,.0f')]
    ).properties(
        title='Volumen de Saldo Capital Total por Origen'
    ).interactive()
    
    st.altair_chart(chart3, use_container_width=True)


with tab3:
    # --- CONTENIDO DE LA TÁCTICA 3: ANÁLISIS POR SUCURSAL ---
    st.header("🎯 Análisis de Riesgo por Sucursal (Mora C2)")
    st.write("Esta sección presenta el ranking de sucursales basado en la Tasa de Mora 30-150 (para PR) y 8-90 (para SOLIDAR) en el punto Vintage $C_2$. **Los cálculos aquí presentados NO dependen de los filtros laterales**, utilizando solo las últimas 24 cohortes disponibles.")

    if df_filtered_master.empty:
        st.error("No se pudo obtener el DataFrame de las últimas 24 cohortes (`df_filtered_master`). Verifique la carga de datos.")
        st.stop()
        
    # Definir las UENs a analizar
    uen_pr = 'PR'
    uen_solidar = 'SOLIDAR'
    EXCLUSION_BRANCH = "999.EMPRESA NOMINA COLABORADORES" 
    
    st.markdown("## 1. Ranking de Sucursales por Riesgo (Mora C2)")
    
    # =========================================================================
    # --- 1.1. CÁLCULOS Y PRESENTACIÓN PARA UEN PR (Mora 30-150) ---
    # =========================================================================
    st.subheader(f"1.1. UEN: {uen_pr} (Métrica: Mora 30-150 C2)")
    
    # Usar la función estándar de Mora 30-150
    df_pr_full = calculate_sucursal_c2_mora(df_filtered_master, uen_pr)
    
    if not df_pr_full.empty:
        
        df_pr_ranking = df_pr_full[df_pr_full['Sucursal'] != EXCLUSION_BRANCH].copy()
        df_pr_consolidado = calculate_saldo_consolidado(df_filtered_master[df_filtered_master['uen'] == uen_pr])
        # ¡CORREGIDO!: Llama a la función simple_c2_forecast reincorporada
        forecast_pr = simple_c2_forecast(df_pr_consolidado) 
        
        if df_pr_ranking.empty:
            st.info(f"No hay sucursales válidas para la UEN '{uen_pr}' después de la exclusión.")
        else:
            col1, col2, col_forecast = st.columns(3)
            
            # Máximo
            max_pr = df_pr_ranking.iloc[0] 
            col1.metric(
                label=f"Mayor % Mora C2", 
                value=f"{max_pr['% Mora C2']:,.2f}%", 
                help=f"Sucursal: {max_pr['Sucursal']}. Capital C2: ${max_pr['Capital_C2']:,.0f}. (Excluye {EXCLUSION_BRANCH})"
            )
            
            # Mínimo
            min_pr = df_pr_ranking.iloc[-1] 
            col2.metric(
                label=f"Menor % Mora C2", 
                value=f"{min_pr['% Mora C2']:,.2f}%",
                help=f"Sucursal: {min_pr['Sucursal']}. Capital C2: ${min_pr['Capital_C2']:,.0f}. (Excluye {EXCLUSION_BRANCH})"
            )
            
            # Pronóstico
            col_forecast.metric(
                label=f"Pronóstico C2 Próx. Cohorte",
                value=f"{forecast_pr:,.2f}%" if pd.notna(forecast_pr) else "N/A"
            )
            
            # Gráfica de Tendencia con Pronóstico
            st.markdown("#### Tendencia Histórica y Pronóstico")
            plot_c2_forecast(df_pr_consolidado, forecast_pr, uen_pr, target_metric='30-150')
            
            
            # --- TOP 10 Y BOTTOM 10 PARA PR ---
            
            col_top, col_bottom = st.columns(2)
            
            with col_top:
                st.markdown(f"**Top 10 Sucursales (Mayor Mora C2)** (Excluyendo `{EXCLUSION_BRANCH}`)")
                
                df_top10_pr = df_pr_ranking.head(10).copy()
                
                # Formateo de tabla para mostrar
                df_top10_pr['% Mora C2'] = df_top10_pr['% Mora C2'].apply(lambda x: f'{x:,.2f}%')
                df_top10_pr['Capital_C2'] = df_top10_pr['Capital_C2'].apply(lambda x: f'${x:,.0f}')
                
                # Ajuste de Columnas para Top 10
                df_top10_pr_display = df_top10_pr[['Sucursal', '% Mora C2', 'Capital_C2']].copy()
                
                st.dataframe(df_top10_pr_display.rename(columns={'Capital_C2': 'Capital C2 ($)'}), hide_index=True)

            with col_bottom:
                st.markdown(f"**Bottom 10 Sucursales (Menor Mora C2)** (Excluyendo `{EXCLUSION_BRANCH}`)")

                # Bottom 10: Ordenamos al revés y tomamos los primeros 10 (o simplemente tomamos los últimos 10 de la tabla descendente)
                df_bottom10_pr = df_pr_ranking.tail(10).sort_values('% Mora C2', ascending=True).copy()
                
                # Formateo de tabla para mostrar
                df_bottom10_pr['% Mora C2'] = df_bottom10_pr['% Mora C2'].apply(lambda x: f'{x:,.2f}%')
                df_bottom10_pr['Capital_C2'] = df_bottom10_pr['Capital_C2'].apply(lambda x: f'${x:,.0f}')
                
                # Ajuste de Columnas para Bottom 10
                df_bottom10_pr_display = df_bottom10_pr[['Sucursal', '% Mora C2', 'Capital_C2']].copy()
                
                st.dataframe(df_bottom10_pr_display.rename(columns={'Capital_C2': 'Capital C2 ($)'}), hide_index=True)


    else:
        st.info(f"No hay datos de Mora C2 disponibles para la UEN '{uen_pr}' en las últimas 24 cohortes.")


    st.markdown("---")


    # =========================================================================
    # --- 1.2. CÁLCULOS Y PRESENTACIÓN PARA UEN SOLIDAR (Mora 8-90) ---
    # =========================================================================
    st.subheader(f"1.2. UEN: {uen_solidar} (Métrica: Mora 8-90 C2)")
    
    # **USANDO LA FUNCIÓN DE MORA 8-90**
    df_solidar_full = calculate_sucursal_c2_mora_890(df_filtered_master, uen_solidar) 
    
    if not df_solidar_full.empty:
        
        # Pronóstico para UEN Solidar (Usa la función de pronóstico 8-90)
        df_solidar_consolidado = calculate_saldo_consolidado(df_filtered_master[df_filtered_master['uen'] == uen_solidar])
        forecast_solidar = simple_c2_forecast_890(df_solidar_consolidado)

        col3, col4, col_forecast_solidar = st.columns(3)
        
        # Máximo
        max_solidar = df_solidar_full.iloc[0]
        col3.metric(
            label=f"Mayor % Mora C2", 
            value=f"{max_solidar['% Mora C2']:,.2f}%", 
            help=f"Sucursal: {max_solidar['Sucursal']}. Capital C2: ${max_solidar['Capital_C2']:,.0f}"
        )
        
        # Mínimo
        min_solidar = df_solidar_full.iloc[-1]
        col4.metric(
            label=f"Menor % Mora C2", 
            value=f"{min_solidar['% Mora C2']:,.2f}%",
            help=f"Sucursal: {min_solidar['Sucursal']}. Capital C2: ${min_solidar['Capital_C2']:,.0f}"
        )

        # Pronóstico
        col_forecast_solidar.metric(
            label=f"Pronóstico C2 Próx. Cohorte",
            value=f"{forecast_solidar:,.2f}%" if pd.notna(forecast_solidar) else "N/A"
        )

        # Gráfica de Tendencia con Pronóstico
        st.markdown("#### Tendencia Histórica y Pronóstico")
        plot_c2_forecast(df_solidar_consolidado, forecast_solidar, uen_solidar, target_metric='8-90')
        
        
        # --- TOP 10 Y BOTTOM 10 PARA SOLIDAR ---
        
        col_top_solidar, col_bottom_solidar = st.columns(2)
        
        with col_top_solidar:
            st.markdown(f"**Top 10 Sucursales (Mayor Mora C2)**")
            df_top10_solidar = df_solidar_full.head(10).copy()
            
            # Formateo de tabla para mostrar
            df_top10_solidar['% Mora C2'] = df_top10_solidar['% Mora C2'].apply(lambda x: f'{x:,.2f}%')
            df_top10_solidar['Capital_C2'] = df_top10_solidar['Capital_C2'].apply(lambda x: f'${x:,.0f}')

            # Ajuste de Columnas para Top 10
            df_top10_solidar_display = df_top10_solidar[['Sucursal', '% Mora C2', 'Capital_C2']].copy()

            st.dataframe(df_top10_solidar_display.rename(columns={'Capital_C2': 'Capital C2 ($)'}), hide_index=True)

        with col_bottom_solidar:
            st.markdown(f"**Bottom 10 Sucursales (Menor Mora C2)**")
            
            df_bottom10_solidar = df_solidar_full.tail(10).sort_values('% Mora C2', ascending=True).copy()

            # Formateo de tabla para mostrar
            df_bottom10_solidar['% Mora C2'] = df_bottom10_solidar['% Mora C2'].apply(lambda x: f'{x:,.2f}%')
            df_bottom10_solidar['Capital_C2'] = df_bottom10_solidar['Capital_C2'].apply(lambda x: f'${x:,.0f}')

            # Ajuste de Columnas para Bottom 10
            df_bottom10_solidar_display = df_bottom10_solidar[['Sucursal', '% Mora C2', 'Capital_C2']].copy()

            st.dataframe(df_bottom10_solidar_display.rename(columns={'Capital_C2': 'Capital C2 ($)'}), hide_index=True)


    else:
        st.info(f"No hay datos de Mora C2 disponibles para la UEN '{uen_solidar}' en las últimas 24 cohortes.")