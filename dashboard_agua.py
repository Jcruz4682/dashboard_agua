# ====================================================
# STREAMLIT: Redistribución de agua en emergencias
# Doctorado en Ciencias Ambientales - UNMSM
# Autor: Mg. Ing. Joel Cruz Machacuay
# ====================================================

import streamlit as st
import os
import pandas as pd
import geopandas as gpd
import folium
from shapely.ops import unary_union
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.validation import make_valid
from streamlit_folium import st_folium
import plotly.express as px

# --- LOGIN SIMPLE ---
USERS = {"jurado1": "clave123", "jurado2": "clave456"}
if "auth" not in st.session_state:
    st.session_state["auth"] = False
if not st.session_state["auth"]:
    st.title("🔐 Acceso restringido")
    user = st.text_input("Usuario")
    pw = st.text_input("Contraseña", type="password")
    if st.button("Ingresar"):
        if user in USERS and USERS[user] == pw:
            st.session_state["auth"] = True
            st.success("Acceso permitido")
        else:
            st.error("Credenciales inválidas")
    st.stop()

# --- TITULO PRINCIPAL ---
st.markdown(
    "<h2 style='text-align:center;'>"
    "MODELO TÉCNICO-OPERATIVO DE REDISTRIBUCIÓN TEMPORAL DE USO DE AGUA INDUSTRIAL PARA EMERGENCIAS HÍDRICAS"
    "</h2>", unsafe_allow_html=True)

# --- RUTA DE DATOS ---
data_dir = os.path.join(os.path.dirname(__file__), "Datos_qgis")
if not os.path.exists(data_dir):
    st.error(f"No se encontró la carpeta de datos: {data_dir}")
    st.stop()

# --- CONFIG CISERNAS ---
cisternas = {"19 m³": {"capacidad": 19}, "34 m³": {"capacidad": 34}}

# ========= CONTROLES =========
st.sidebar.header("⚙️ Configuración del análisis")
modo = st.sidebar.radio("Nivel de análisis", ["Sector", "Distrito", "Combinación Distritos", "Resumen general"])
escenario_sel = st.sidebar.selectbox("Escenario (%)", [10, 20, 30])
cisterna_sel = st.sidebar.radio("Tipo de cisterna", list(cisternas.keys()))
consumo_gal_h = st.sidebar.slider("Consumo de combustible (gal/h)", 5.0, 6.0, 5.5, 0.1)
costo_galon = st.sidebar.number_input("Costo por galón (S/)", 0.0, 20.0, 20.0, 0.5)
velocidad_kmh = st.sidebar.number_input("Velocidad de referencia (km/h)", 1.0, 30.0, 30.0, 1.0)

# ========= FUNCIONES =========
def normalizar(x):
    return str(x).strip().upper().replace("Á","A").replace("É","E").replace("Í","I").replace("Ó","O").replace("Ú","U")

def calcular_costos(aporte, dist_km, tipo_cisterna):
    cap = cisternas[tipo_cisterna]["capacidad"]
    viajes = int(aporte // cap + (aporte % cap > 0))
    horas_por_viaje = (2.0 * dist_km) / max(velocidad_kmh, 1e-6)
    consumo_por_viaje = horas_por_viaje * consumo_gal_h
    costo_por_viaje = consumo_por_viaje * costo_galon
    return viajes, viajes*costo_por_viaje, viajes*consumo_por_viaje

def asignar_pozos(geom_obj, demanda, escenario, tipo_cisterna, pozos_gdf):
    resultados, restante = [], demanda
    total_viajes, total_costo, total_consumo = 0, 0.0, 0.0
    pozos_tmp = []
    for _, pozo in pozos_gdf.iterrows():
        q_m3_dia = float(pozo.get("Q_m3_dia", 0.0))
        if q_m3_dia > 0 and pozo.geometry is not None:
            try:
                dist_km = pozo.geometry.distance(geom_obj) * 111.0
                aporte_disp = q_m3_dia * (escenario / 100.0)
                pozos_tmp.append((dist_km, pozo.get("ID","NA"), aporte_disp, pozo.geometry))
            except Exception:
                continue
    pozos_tmp.sort(key=lambda x: x[0])
    for dist_km, pozo_id, aporte_disp, geom in pozos_tmp:
        if restante <= 0: break
        aporte_asignado = min(aporte_disp, restante)
        viajes, costo, consumo = calcular_costos(aporte_asignado, dist_km, tipo_cisterna)
        resultados.append([pozo_id, aporte_asignado, viajes, costo, consumo, round(dist_km,3), geom])
        restante -= aporte_asignado
        total_viajes += viajes; total_costo += costo; total_consumo += consumo
    return resultados, restante, total_viajes, total_costo, total_consumo

def mostrar_kpis(nombre, demanda, restante, viajes, costo, consumo):
    st.markdown(f"### {nombre}")
    fila1 = st.columns(2)
    fila2 = st.columns(3)
    cobertura = (1-restante/demanda)*100 if demanda>0 else 0
    fila1[0].metric("🚰 Demanda (m³/día)", f"{demanda:,.1f}")
    fila1[1].metric("🎯 Cobertura (%)", f"{cobertura:.1f}%")
    fila2[0].metric("🚛 Viajes", f"{viajes}")
    fila2[1].metric("💵 Costo (S/)", f"{costo:,.2f}")
    fila2[2].metric("⛽ Consumo (gal)", f"{consumo:,.1f}")
    st.caption("⚠️ Costos: solo combustible. No incluye cisternas ni personal.")

def agregar_conclusion(contexto, nombre, demanda, restante, viajes, costo, consumo, pozos):
    if restante > 0:
        st.error(f"**Conclusión:** En **situación de emergencia hídrica en el {contexto.lower()} {nombre}**, "
                 f"se requiere una demanda de **{demanda:.2f} m³/día**. Con los pozos seleccionados, "
                 f"**no se logra cubrir la demanda total**, faltando **{restante:.2f} m³/día**. "
                 f"Se emplean **{len(pozos)} pozos**, con **{viajes} viajes**, "
                 f"consumo de **{consumo:.1f} gal** y **costo combustible** de **S/ {costo:,.2f}**.")
    else:
        st.success(f"**Conclusión:** En **situación de emergencia hídrica en el {contexto.lower()} {nombre}**, "
                   f"se requiere una demanda de **{demanda:.2f} m³/día**. Con los pozos seleccionados, "
                   f"**se cubre la demanda total**. Se emplean **{len(pozos)} pozos**, con **{viajes} viajes**, "
                   f"consumo de **{consumo:.1f} gal** y **costo combustible** de **S/ {costo:,.2f}**.")

def agregar_leyenda(m):
    legend_html = """
    <div style="position: fixed; bottom: 20px; left: 20px; width: 200px;
                background-color: white; border:2px solid grey; z-index:9999;
                font-size:14px; padding: 10px; color:black;">
    <b>Leyenda</b><br>
    <span style="color:blue;">●</span> Pozos<br>
    <span style="color:red;">●</span> Sectores<br>
    <span style="color:green;">●</span> Distritos<br>
    <span style="color:purple;">●</span> Distritos combinados
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    return m

def cargar_shapefile(nombre, solo_poligonos=False):
    try:
        # Intentar leer SHP
        ruta = os.path.join(data_dir, nombre)
        gdf = gpd.read_file(ruta)
    except Exception:
        # Si falla, probar con .gpkg
        base = nombre.replace(".shp", ".gpkg")
        ruta = os.path.join(data_dir, base)
        gdf = gpd.read_file(ruta)

    # --- Limpiar geometrías ---
    gdf = gdf[~gdf["geometry"].isna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()

    def fix_geom(g):
        if g is None or g.is_empty:
            return None
        g = make_valid(g)
        if g.geom_type == "GeometryCollection":
            polys = [geom for geom in g.geoms if geom.geom_type in ["Polygon", "MultiPolygon"]]
            if not polys:
                return None
            g = unary_union(polys)
        if g.geom_type not in ["Polygon", "MultiPolygon"]:
            return None
        return g

    gdf["geometry"] = gdf["geometry"].apply(fix_geom)
    gdf = gdf[~gdf["geometry"].isna()].copy()

    if solo_poligonos:
        def to_multipolygon(geom):
            if geom is None or geom.is_empty:
                return None
            if geom.geom_type == "Polygon":
                return MultiPolygon([geom])
            if geom.geom_type == "MultiPolygon":
                return geom
            return None
        gdf["geometry"] = gdf["geometry"].apply(to_multipolygon)
        gdf = gdf[~gdf["geometry"].isna()].copy()

    gdf["geometry"] = gdf["geometry"].buffer(0)

    return gdf.to_crs(epsg=4326)




# ========= CARGA DE DATOS =========
sectores_gdf = cargar_shapefile("Sectores_F1_ENFEN.shp", solo_poligonos=True)
distritos_gdf = cargar_shapefile("DISTRITOS_Final_limpio.shp", solo_poligonos=True)
pozos_gdf    = cargar_shapefile("Pozos.shp")

try:
    demandas_sectores = pd.read_csv(os.path.join(data_dir, "Demandas_Sectores_30lhd.csv"))
    demandas_distritos = pd.read_csv(os.path.join(data_dir, "Demandas_Distritos_30lhd.csv"))
except Exception as e:
    st.error(f"No se pudo cargar CSVs: {e}")
    st.stop()


# --- Merge con validaciones ---
if not sectores_gdf.empty and "ZONENAME" in sectores_gdf.columns:
    sectores_gdf["ZONENAME"] = sectores_gdf["ZONENAME"].apply(normalizar)
    demandas_sectores["ZONENAME"] = demandas_sectores["ZONENAME"].apply(normalizar)
    sectores_gdf = sectores_gdf.merge(demandas_sectores[["ZONENAME","Demanda_m3_dia"]], on="ZONENAME", how="left")

if not distritos_gdf.empty and "NOMBDIST" in distritos_gdf.columns:
    distritos_gdf["NOMBDIST"] = distritos_gdf["NOMBDIST"].apply(normalizar)
    demandas_distritos["Distrito"] = demandas_distritos["Distrito"].apply(normalizar)
    distritos_gdf = distritos_gdf.merge(
        demandas_distritos[["Distrito","Demanda_Distrito_m3_30_lhd"]],
        left_on="NOMBDIST", right_on="Distrito", how="left"
    )

# ========= LÓGICA PRINCIPAL =========
if modo == "Sector" and not sectores_gdf.empty:
    sectores_ids = sorted(sectores_gdf["ZONENAME"].dropna().unique().tolist())
    sector_sel = st.sidebar.selectbox("Selecciona un sector", sectores_ids)
    row = sectores_gdf[sectores_gdf["ZONENAME"] == sector_sel].iloc[0]
    demanda = float(row.get("Demanda_m3_dia",0))
    resultados, restante, viajes, costo, consumo = asignar_pozos(row.geometry.centroid, demanda, escenario_sel, cisterna_sel, pozos_gdf)

    mostrar_kpis(f"📍 Sector {sector_sel}", demanda, restante, viajes, costo, consumo)

    m = folium.Map(location=[row.geometry.centroid.y, row.geometry.centroid.x], zoom_start=13, tiles="cartodbpositron")
    folium.GeoJson(row.geometry, style_function=lambda x: {"color":"red","fillOpacity":0.3}).add_to(m)
    m = dibujar_pozos(resultados, m)
    m = agregar_leyenda(m)
    st_folium(m, width=900, height=500)

    df_res = pd.DataFrame(resultados, columns=["Pozo_ID","Aporte","Viajes","Costo","Consumo","Dist_km","geom"]).drop(columns="geom")
    st.dataframe(df_res)
    st.plotly_chart(px.bar(df_res, x="Pozo_ID", y="Aporte", title="Aporte por pozo (m³/día)"), use_container_width=True)
    agregar_conclusion("sector", sector_sel, demanda, restante, viajes, costo, consumo, resultados)

elif modo == "Distrito" and not distritos_gdf.empty and "NOMBDIST" in distritos_gdf.columns:
    distritos_ids = sorted(distritos_gdf["NOMBDIST"].dropna().unique().tolist())
    dist_sel = st.sidebar.selectbox("Selecciona un distrito", distritos_ids)
    row = distritos_gdf[distritos_gdf["NOMBDIST"] == dist_sel].iloc[0]
    demanda = float(row.get("Demanda_Distrito_m3_30_lhd",0))
    resultados, restante, viajes, costo, consumo = asignar_pozos(row.geometry.centroid, demanda, escenario_sel, cisterna_sel, pozos_gdf)

    mostrar_kpis(f"🏙️ Distrito {dist_sel}", demanda, restante, viajes, costo, consumo)

    m = folium.Map(location=[row.geometry.centroid.y, row.geometry.centroid.x], zoom_start=11, tiles="cartodbpositron")
    folium.GeoJson(row.geometry, style_function=lambda x: {"color":"green","fillOpacity":0.2}).add_to(m)
    m = dibujar_pozos(resultados, m)
    m = agregar_leyenda(m)
    st_folium(m, width=900, height=500)

    df_res = pd.DataFrame(resultados, columns=["Pozo_ID","Aporte","Viajes","Costo","Consumo","Dist_km","geom"]).drop(columns="geom")
    st.dataframe(df_res)
    st.plotly_chart(px.bar(df_res, x="Pozo_ID", y="Aporte", title="Aporte por pozo (m³/día)"), use_container_width=True)
    agregar_conclusion("distrito", dist_sel, demanda, restante, viajes, costo, consumo, resultados)

elif modo == "Combinación Distritos" and not distritos_gdf.empty and "NOMBDIST" in distritos_gdf.columns:
    criticos = ["ATE","LURIGANCHO","SAN_JUAN_DE_LURIGANCHO","EL_AGUSTINO","SANTA_ANITA"]
    seleccion = st.sidebar.multiselect("Selecciona distritos críticos", criticos, default=criticos)
    if seleccion:
        rows = distritos_gdf[distritos_gdf["NOMBDIST"].isin(seleccion)]
        demanda = rows["Demanda_Distrito_m3_30_lhd"].sum()
        geom_union = unary_union(rows.geometry)
        resultados, restante, viajes, costo, consumo = asignar_pozos(geom_union.centroid, demanda, escenario_sel, cisterna_sel, pozos_gdf)

        mostrar_kpis(f"🌀 Combinación: {', '.join(seleccion)}", demanda, restante, viajes, costo, consumo)

        m = folium.Map(location=[geom_union.centroid.y, geom_union.centroid.x], zoom_start=10, tiles="cartodbpositron")
        folium.GeoJson(geom_union, style_function=lambda x: {"color":"purple","fillOpacity":0.2}).add_to(m)
        m = dibujar_pozos(resultados, m)
        m = agregar_leyenda(m)
        st_folium(m, width=900, height=500)

        df_res = pd.DataFrame(resultados, columns=["Pozo_ID","Aporte","Viajes","Costo","Consumo","Dist_km","geom"]).drop(columns="geom")
        st.dataframe(df_res)
        st.plotly_chart(px.bar(df_res, x="Pozo_ID", y="Aporte", title="Aporte por pozo (m³/día)"), use_container_width=True)
        agregar_conclusion("combinación crítica de distritos", ", ".join(seleccion), demanda, restante, viajes, costo, consumo, resultados)

elif modo == "Resumen general":
    st.subheader("📊 Resumen general")

    # ---- Sectores ----
    resumen_sectores = []
    for _, row in sectores_gdf.iterrows():
        nombre = row.get("ZONENAME","NA"); demanda = float(row.get("Demanda_m3_dia",0))
        if demanda > 0:
            _, restante, viajes, costo, consumo = asignar_pozos(row.geometry.centroid, demanda, escenario_sel, cisterna_sel, pozos_gdf)
            cobertura = (1-restante/demanda)*100 if demanda>0 else 0
            resumen_sectores.append([nombre, demanda, viajes, costo, consumo, restante, cobertura])
    df_sec = pd.DataFrame(resumen_sectores, columns=["Sector","Demanda","Viajes","Costo","Consumo","Faltante","Cobertura_%"])
    st.markdown("### 📍 Sectores"); st.dataframe(df_sec)
    st.plotly_chart(px.bar(df_sec, x="Sector", y="Costo", title="Costo por sector"), use_container_width=True)

    # ---- Distritos ----
    resumen_distritos = []
    if not distritos_gdf.empty and "NOMBDIST" in distritos_gdf.columns:
        for _, row in distritos_gdf.iterrows():
            nombre = row.get("NOMBDIST","NA"); demanda = float(row.get("Demanda_Distrito_m3_30_lhd",0))
            if demanda > 0:
                _, restante, viajes, costo, consumo = asignar_pozos(row.geometry.centroid, demanda, escenario_sel, cisterna_sel, pozos_gdf)
                cobertura = (1-restante/demanda)*100 if demanda>0 else 0
                resumen_distritos.append([nombre, demanda, viajes, costo, consumo, restante, cobertura])
    df_dis = pd.DataFrame(resumen_distritos, columns=["Distrito","Demanda","Viajes","Costo","Consumo","Faltante","Cobertura_%"])
    st.markdown("### 🏙️ Distritos"); st.dataframe(df_dis)
    st.plotly_chart(px.bar(df_dis, x="Distrito", y="Costo", title="Costo por distrito"), use_container_width=True)

    # ---- Combinada ----
    if not distritos_gdf.empty and "NOMBDIST" in distritos_gdf.columns:
        criticos = ["ATE","LURIGANCHO","SAN_JUAN_DE_LURIGANCHO","EL_AGUSTINO","SANTA_ANITA"]
        rows = distritos_gdf[distritos_gdf["NOMBDIST"].isin(criticos)]
        demanda = rows["Demanda_Distrito_m3_30_lhd"].sum()
        _, restante, viajes, costo, consumo = asignar_pozos(unary_union(rows.geometry).centroid, demanda, escenario_sel, cisterna_sel, pozos_gdf)

        st.markdown("### 🌀 Combinación crítica de distritos")
        df_comb = pd.DataFrame({
            "Distrito": criticos,
            "Demanda": [rows.loc[rows["NOMBDIST"]==d,"Demanda_Distrito_m3_30_lhd"].values[0] for d in criticos if d in rows["NOMBDIST"].values]
        })
        st.dataframe(df_comb)
        st.plotly_chart(px.bar(df_comb, x="Distrito", y="Demanda", title="Demanda en combinación crítica"), use_container_width=True)
