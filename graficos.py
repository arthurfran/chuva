from pathlib import Path
import unicodedata

import pandas as pd
import plotly.express as px
import streamlit as st


# ==========================================================
# CONFIGURAÇÃO GERAL
# ==========================================================
st.set_page_config(
    page_title="Dashboard ZCAS",
    page_icon="🌧️",
    layout="wide",
)

MESES_ORDEM = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
]

ARQUIVO_PADRAO = "Ideia TCC(1).xlsx"
ABA_DADOS = "Export"


# ==========================================================
# FUNÇÕES AUXILIARES
# ==========================================================
def normalizar_texto(texto: str) -> str:
    """Remove acentos, espaços duplicados e padroniza nomes de colunas."""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("utf-8")
    texto = texto.replace(" ", "_").replace("-", "_")
    while "__" in texto:
        texto = texto.replace("__", "_")
    return texto


def converter_data_excel(serie: pd.Series) -> pd.Series:
    """Converte datas vindas do Excel, tanto em formato serial quanto datetime/texto."""
    if pd.api.types.is_datetime64_any_dtype(serie):
        return pd.to_datetime(serie, errors="coerce")

    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_datetime(serie, unit="D", origin="1899-12-30", errors="coerce")

    return pd.to_datetime(serie, dayfirst=True, errors="coerce")


@st.cache_data(show_spinner=False)
def carregar_dados(arquivo) -> pd.DataFrame:
    df = pd.read_excel(arquivo, sheet_name=ABA_DADOS)

    # Padroniza nomes internos, preservando os significados da planilha.
    df.columns = [normalizar_texto(c) for c in df.columns]

    mapa_colunas = {
        "zcas_por_ano": "ano",
        "zcas_data_inicio_fim": "periodo_zcas",
        "data_inicio": "data_inicio",
        "data_fim": "data_fim",
        "zcas_duracao": "duracao_dias",
        "mes": "mes",
        "fenomeno": "fenomeno",
        "novo_evento": "novo_evento",
    }

    df = df.rename(columns={c: mapa_colunas.get(c, c) for c in df.columns})

    colunas_necessarias = [
        "ano", "periodo_zcas", "data_inicio", "data_fim",
        "duracao_dias", "mes", "fenomeno", "novo_evento"
    ]

    faltantes = [c for c in colunas_necessarias if c not in df.columns]
    if faltantes:
        raise ValueError(f"Colunas não encontradas na aba '{ABA_DADOS}': {faltantes}")

    # --- NOVIDADE: Verifica se há dados de ciclones e os inclui se existirem ---
    colunas_ciclone = ["track_id", "tempo_de_vida_ciclone_em_dias"]
    for col in colunas_ciclone:
        if col in df.columns:
            colunas_necessarias.append(col)

    df = df[colunas_necessarias].copy()
    df = df.dropna(subset=["ano", "data_inicio"], how="all")

    df["ano"] = pd.to_numeric(df["ano"], errors="coerce").astype("Int64")
    df["duracao_dias"] = pd.to_numeric(df["duracao_dias"], errors="coerce")
    df["novo_evento"] = pd.to_numeric(df["novo_evento"], errors="coerce").fillna(0).astype(int)
    df["data_inicio"] = converter_data_excel(df["data_inicio"])
    df["data_fim"] = converter_data_excel(df["data_fim"])
    df["mes"] = df["mes"].astype(str).str.strip()
    df["fenomeno"] = df["fenomeno"].astype(str).str.strip()

    df = df.sort_values(["data_inicio", "data_fim"]).reset_index(drop=True)

    # O campo NOVO EVENTO resolve o problema de eventos que continuam no mês/ano seguinte.
    # Cada vez que NOVO EVENTO = 1, inicia-se um novo episódio de ZCAS.
    df["evento_id"] = df["novo_evento"].cumsum()

    # Garante que todas as linhas tenham um identificador válido.
    df.loc[df["evento_id"] == 0, "evento_id"] = 1

    return df


def montar_tabela_eventos(df: pd.DataFrame) -> pd.DataFrame:
    eventos = (
        df.groupby("evento_id", as_index=False)
        .agg(
            data_inicio=("data_inicio", "min"),
            data_fim=("data_fim", "max"),
            duracao_total_dias=("duracao_dias", "sum"),
            ano_inicio=("ano", "min"),
            ano_fim=("ano", "max"),
            fenomeno=("fenomeno", lambda x: " / ".join(sorted(set(x.dropna().astype(str))))),
            meses=("mes", lambda x: " / ".join([m for m in MESES_ORDEM if m in set(x)])),
            registros=("periodo_zcas", "count"),
        )
    )

    eventos["periodo_evento"] = (
        eventos["data_inicio"].dt.strftime("%d/%m/%Y")
        + " - "
        + eventos["data_fim"].dt.strftime("%d/%m/%Y")
    )

    return eventos


def filtrar_dados(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filtros")

    anos = sorted(df["ano"].dropna().astype(int).unique())
    fenomenos = sorted(df["fenomeno"].dropna().unique())
    meses_existentes = [m for m in MESES_ORDEM if m in set(df["mes"].dropna())]

    anos_sel = st.sidebar.multiselect("Ano", anos, default=anos)
    fenomenos_sel = st.sidebar.multiselect("Fenômeno", fenomenos, default=fenomenos)
    meses_sel = st.sidebar.multiselect("Mês", meses_existentes, default=meses_existentes)

    dur_min = int(df["duracao_dias"].min())
    dur_max = int(df["duracao_dias"].max())
    duracao_sel = st.sidebar.slider(
        "Duração do registro de ZCAS (dias)",
        min_value=dur_min,
        max_value=dur_max,
        value=(dur_min, dur_max),
    )

    filtrado = df[
        df["ano"].astype(int).isin(anos_sel)
        & df["fenomeno"].isin(fenomenos_sel)
        & df["mes"].isin(meses_sel)
        & df["duracao_dias"].between(duracao_sel[0], duracao_sel[1])
    ].copy()

    return filtrado


def formatar_numero(valor, casas=0):
    if pd.isna(valor):
        return "-"
    if casas == 0:
        return f"{valor:,.0f}".replace(",", ".")
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ==========================================================
# INTERFACE
# ==========================================================
st.title("🌧️ Dashboard de Eventos de ZCAS")
st.caption("Análise exploratória baseada na aba Export da planilha de eventos de ZCAS.")

arquivo_local = Path(ARQUIVO_PADRAO)

with st.sidebar:
    st.subheader("Base de dados")
    arquivo_upload = st.file_uploader("Carregar planilha", type=["xlsx"])

    if arquivo_upload is None and arquivo_local.exists():
        arquivo_dados = arquivo_local
        st.success(f"Usando arquivo local: {ARQUIVO_PADRAO}")
    elif arquivo_upload is not None:
        arquivo_dados = arquivo_upload
        st.success("Usando arquivo carregado no navegador.")
    else:
        arquivo_dados = None
        st.warning(f"Coloque o arquivo {ARQUIVO_PADRAO} na pasta do app ou carregue-o acima.")

if arquivo_dados is None:
    st.info("Aguardando a planilha para iniciar o dashboard.")
    st.stop()

try:
    df = carregar_dados(arquivo_dados)
except Exception as erro:
    st.error("Não foi possível carregar a planilha.")
    st.exception(erro)
    st.stop()

# Aplica filtros na visão de registros.
df_filtrado = filtrar_dados(df)
eventos_filtrados = montar_tabela_eventos(df_filtrado) if not df_filtrado.empty else pd.DataFrame()
eventos_total = montar_tabela_eventos(df)

if df_filtrado.empty:
    st.warning("Nenhum registro encontrado para os filtros selecionados.")
    st.stop()

# ==========================================================
# KPIs
# ==========================================================
total_eventos = eventos_filtrados["evento_id"].nunique()
total_registros = len(df_filtrado)
total_dias = df_filtrado["duracao_dias"].sum()
duracao_media_evento = eventos_filtrados["duracao_total_dias"].mean()
ano_inicio = int(df_filtrado["ano"].min())
ano_fim = int(df_filtrado["ano"].max())

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric("Eventos de ZCAS", formatar_numero(total_eventos))
kpi2.metric("Registros na planilha", formatar_numero(total_registros))
kpi3.metric("Dias com ZCAS", formatar_numero(total_dias))
kpi4.metric("Duração média/evento", f"{formatar_numero(duracao_media_evento, 1)} dias")
kpi5.metric("Período analisado", f"{ano_inicio}–{ano_fim}")

st.divider()

# ==========================================================
# GRÁFICOS DO DASHBOARD
# ==========================================================
st.subheader("Gráficos do dashboard")

# ==========================================================
# PRIMEIRA LINHA
# Eventos iniciados por ano | Soma da duração dos registros por ano
# ==========================================================
col1, col2 = st.columns(2)

with col1:
    ocorrencias_ano = (
        df_filtrado.groupby("ano", as_index=False)["novo_evento"]
        .sum()
        .rename(columns={"novo_evento": "eventos_iniciados"})
    )

    fig = px.bar(
        ocorrencias_ano,
        x="ano",
        y="eventos_iniciados",
        title="Eventos iniciados por ano",
        labels={"ano": "Ano", "eventos_iniciados": "Nº de eventos"},
        text_auto=True,
    )
    fig.update_layout(xaxis=dict(dtick=1), xaxis_title="Ano", yaxis_title="Nº de eventos iniciados")
    st.plotly_chart(fig, use_container_width=True)

with col2:
    dias_ano = (
        df_filtrado.groupby("ano", as_index=False)["duracao_dias"]
        .sum()
        .rename(columns={"duracao_dias": "dias_zcas"})
    )

    fig = px.bar(
        dias_ano,
        x="ano",
        y="dias_zcas",
        title="Soma da duração dos registros por ano",
        labels={"ano": "Ano", "dias_zcas": "Dias com ZCAS"},
        text_auto=True,
    )
    fig.update_layout(xaxis=dict(dtick=1), xaxis_title="Ano", yaxis_title="Total de dias com ZCAS")
    st.plotly_chart(fig, use_container_width=True)


# ==========================================================
# SEGUNDA LINHA
# Eventos iniciados por fenômeno | Eventos por fenômeno por década
# ==========================================================
col1, col2 = st.columns(2)

with col1:
    por_fenomeno = (
        df_filtrado.groupby("fenomeno", as_index=False)
        .agg(eventos=("novo_evento", "sum"))
        .sort_values("eventos", ascending=False)
    )

    fig = px.bar(
        por_fenomeno,
        x="fenomeno",
        y="eventos",
        title="Eventos iniciados por fenômeno",
        labels={"fenomeno": "Fenômeno", "eventos": "Nº de eventos"},
        text_auto=True,
    )
    fig.update_layout(xaxis_title="Fenômeno", yaxis_title="Nº de eventos iniciados")
    st.plotly_chart(fig, use_container_width=True)

with col2:
    eventos_fenomeno_decada = df_filtrado.copy()
    eventos_fenomeno_decada["decada"] = (eventos_fenomeno_decada["ano"].astype(int) // 10) * 10
    eventos_fenomeno_decada["decada"] = eventos_fenomeno_decada["decada"].astype(str) + "s"

    eventos_fenomeno_decada = (
        eventos_fenomeno_decada.groupby(["fenomeno", "decada"], as_index=False)["novo_evento"]
        .sum()
        .rename(columns={"novo_evento": "eventos"})
        .sort_values(["fenomeno", "decada"])
    )

    fig = px.bar(
        eventos_fenomeno_decada,
        x="fenomeno",
        y="eventos",
        color="decada",
        barmode="group",
        title="Eventos iniciados por fenômeno, separados por década",
        labels={"fenomeno": "Fenômeno", "eventos": "Nº de eventos", "decada": "Década"},
        text_auto=True,
    )
    fig.update_layout(xaxis_title="Fenômeno", yaxis_title="Nº de eventos iniciados", legend_title_text="Década")
    st.plotly_chart(fig, use_container_width=True)


# ==========================================================
# TERCEIRA LINHA
# Eventos iniciados por mês | Eventos por mês por década
# ==========================================================
col1, col2 = st.columns(2)

with col1:
    por_mes = df_filtrado.groupby("mes", as_index=False)["novo_evento"].sum().rename(columns={"novo_evento": "eventos"})
    por_mes["mes"] = pd.Categorical(por_mes["mes"], categories=MESES_ORDEM, ordered=True)
    por_mes = por_mes.sort_values("mes")

    fig = px.bar(
        por_mes,
        x="mes",
        y="eventos",
        title="Eventos iniciados por mês",
        labels={"mes": "Mês", "eventos": "Nº de eventos"},
        text_auto=True,
    )
    fig.update_layout(xaxis_title="Mês", yaxis_title="Nº de eventos iniciados")
    st.plotly_chart(fig, use_container_width=True)

with col2:
    mes_decada = df_filtrado.copy()
    mes_decada["decada"] = (mes_decada["ano"].astype(int) // 10) * 10
    mes_decada["decada"] = mes_decada["decada"].astype(str) + "s"

    mes_decada = (
        mes_decada.groupby(["decada", "mes"], as_index=False)["novo_evento"]
        .sum()
        .rename(columns={"novo_evento": "eventos"})
    )

    mes_decada["mes"] = pd.Categorical(mes_decada["mes"], categories=MESES_ORDEM, ordered=True)
    mes_decada = mes_decada.sort_values(["decada", "mes"])

    fig = px.bar(
        mes_decada,
        x="mes",
        y="eventos",
        color="decada",
        barmode="group",
        title="Eventos iniciados por mês, separados por década",
        labels={"mes": "Mês", "eventos": "Nº de eventos", "decada": "Década"},
        text_auto=True,
    )
    fig.update_layout(xaxis_title="Mês", yaxis_title="Nº de eventos iniciados", legend_title_text="Década")
    st.plotly_chart(fig, use_container_width=True)


# ==========================================================
# QUARTA LINHA
# Dias de eventos por mês | Dias de eventos por mês por década
# ==========================================================
col1, col2 = st.columns(2)

with col1:
    dias_por_mes = df_filtrado.groupby("mes", as_index=False)["duracao_dias"].sum().rename(columns={"duracao_dias": "dias_zcas"})
    dias_por_mes["mes"] = pd.Categorical(dias_por_mes["mes"], categories=MESES_ORDEM, ordered=True)
    dias_por_mes = dias_por_mes.sort_values("mes")

    fig = px.bar(
        dias_por_mes,
        x="mes",
        y="dias_zcas",
        title="Dias de eventos de ZCAS por mês",
        labels={"mes": "Mês", "dias_zcas": "Dias de eventos de ZCAS"},
        text_auto=True,
    )
    fig.update_layout(xaxis_title="Mês", yaxis_title="Total de dias com ZCAS")
    st.plotly_chart(fig, use_container_width=True)

with col2:
    dias_mes_decada = df_filtrado.copy()
    dias_mes_decada["decada"] = (dias_mes_decada["ano"].astype(int) // 10) * 10
    dias_mes_decada["decada"] = dias_mes_decada["decada"].astype(str) + "s"

    dias_mes_decada = (
        dias_mes_decada.groupby(["decada", "mes"], as_index=False)["duracao_dias"]
        .sum()
        .rename(columns={"duracao_dias": "dias_zcas"})
    )

    dias_mes_decada["mes"] = pd.Categorical(dias_mes_decada["mes"], categories=MESES_ORDEM, ordered=True)
    dias_mes_decada = dias_mes_decada.sort_values(["decada", "mes"])

    fig = px.bar(
        dias_mes_decada,
        x="mes",
        y="dias_zcas",
        color="decada",
        barmode="group",
        title="Dias de eventos de ZCAS por mês, separados por década",
        labels={"mes": "Mês", "dias_zcas": "Dias de eventos de ZCAS", "decada": "Década"},
        text_auto=True,
    )
    fig.update_layout(xaxis_title="Mês", yaxis_title="Total de dias com ZCAS", legend_title_text="Década")
    st.plotly_chart(fig, use_container_width=True)


# ==========================================================
# QUINTA LINHA
# Número de dias por fenômeno | Número de dias por fenômeno por década
# ==========================================================
col1, col2 = st.columns(2)

with col1:
    dias_por_fenomeno = (
        df_filtrado.groupby("fenomeno", as_index=False)["duracao_dias"]
        .sum()
        .rename(columns={"duracao_dias": "dias_zcas"})
        .sort_values("dias_zcas", ascending=False)
    )

    fig = px.bar(
        dias_por_fenomeno,
        x="fenomeno",
        y="dias_zcas",
        title="Número de dias de ZCAS por fenômeno",
        labels={"fenomeno": "Fenômeno", "dias_zcas": "Número de dias com ZCAS"},
        text_auto=True,
    )
    fig.update_layout(xaxis_title="Fenômeno", yaxis_title="Total de dias com ZCAS")
    st.plotly_chart(fig, use_container_width=True)

with col2:
    dias_fenomeno_decada = df_filtrado.copy()
    dias_fenomeno_decada["decada"] = (dias_fenomeno_decada["ano"].astype(int) // 10) * 10
    dias_fenomeno_decada["decada"] = dias_fenomeno_decada["decada"].astype(str) + "s"

    dias_fenomeno_decada = (
        dias_fenomeno_decada.groupby(["fenomeno", "decada"], as_index=False)["duracao_dias"]
        .sum()
        .rename(columns={"duracao_dias": "dias_zcas"})
        .sort_values(["fenomeno", "decada"])
    )

    fig = px.bar(
        dias_fenomeno_decada,
        x="fenomeno",
        y="dias_zcas",
        color="decada",
        barmode="group",
        title="Número de dias de ZCAS por fenômeno, separados por década",
        labels={"fenomeno": "Fenômeno", "dias_zcas": "Número de dias com ZCAS", "decada": "Década"},
        text_auto=True,
    )
    fig.update_layout(xaxis_title="Fenômeno", yaxis_title="Total de dias com ZCAS", legend_title_text="Década")
    st.plotly_chart(fig, use_container_width=True)


# ==========================================================
# SEXTA LINHA
# Número de eventos por duração em dias
# ==========================================================
eventos_por_duracao = (
    eventos_filtrados.groupby("duracao_total_dias", as_index=False)
    .agg(numero_eventos=("evento_id", "count"))
    .sort_values("duracao_total_dias")
)

fig = px.bar(
    eventos_por_duracao,
    x="duracao_total_dias",
    y="numero_eventos",
    title="Número de eventos de ZCAS por duração em dias",
    labels={"duracao_total_dias": "Duração do evento (dias)", "numero_eventos": "Número de eventos"},
    text_auto=True,
)
fig.update_layout(xaxis_title="Duração do evento de ZCAS (dias)", yaxis_title="Número de eventos", xaxis=dict(dtick=1))
st.plotly_chart(fig, use_container_width=True)


# ==========================================================
# SÉTIMA LINHA (NOVA)
# Número de ciclones por mês | Quantidade de ciclones por tempo de vida
# ==========================================================
if "track_id" in df_filtrado.columns and "tempo_de_vida_ciclone_em_dias" in df_filtrado.columns:
    st.markdown("---")
    st.subheader("🌀 Análise de Ciclones Associados")
    
    col1, col2 = st.columns(2)
    
    # Remove registros sem ciclones identificados
    df_ciclones = df_filtrado.dropna(subset=["track_id"]).copy()
    
    if not df_ciclones.empty:
        df_ciclones["tempo_de_vida_ciclone_em_dias"] = pd.to_numeric(df_ciclones["tempo_de_vida_ciclone_em_dias"], errors="coerce")
        
        # Agrupa por track_id para garantir que não contaremos o mesmo ciclone mais de uma vez (já que ele pode se estender por vários registros na ZCAS)
        df_ciclones_unicos = df_ciclones.groupby("track_id", as_index=False).agg({
            "mes": "first",
            "tempo_de_vida_ciclone_em_dias": "first"
        })
        
        with col1:
            ciclones_mes = df_ciclones_unicos.groupby("mes", as_index=False)["track_id"].count().rename(columns={"track_id": "qtd"})
            ciclones_mes["mes"] = pd.Categorical(ciclones_mes["mes"], categories=MESES_ORDEM, ordered=True)
            ciclones_mes = ciclones_mes.sort_values("mes")
            
            fig_mes = px.bar(
                ciclones_mes,
                x="mes",
                y="qtd",
                title="Número de Ciclones por Mês",
                labels={"mes": "Mês", "qtd": "Nº de Ciclones"},
                text_auto=True
            )
            fig_mes.update_layout(xaxis_title="Mês", yaxis_title="Número de Ciclones")
            st.plotly_chart(fig_mes, use_container_width=True)
            
        with col2:
            fig_vida = px.histogram(
                df_ciclones_unicos.dropna(subset=["tempo_de_vida_ciclone_em_dias"]),
                x="tempo_de_vida_ciclone_em_dias",
                title="Quantidade de Ciclones por Tempo de Vida",
                labels={"tempo_de_vida_ciclone_em_dias": "Tempo de Vida (Dias)", "count": "Quantidade de Ciclones"},
                text_auto=True
            )
            fig_vida.update_layout(
                xaxis_title="Tempo de Vida (Dias)", 
                yaxis_title="Quantidade de Ciclones",
                bargap=0.1
            )
            st.plotly_chart(fig_vida, use_container_width=True)


# ==========================================================
# VISÃO TEMPORAL E MAPA DE CALOR
# ==========================================================
st.markdown("---")
st.subheader("Distribuição temporal")

heat = (
    df_filtrado.groupby(["ano", "mes"], as_index=False)["novo_evento"]
    .sum()
    .rename(columns={"novo_evento": "eventos"})
)
heat["mes"] = pd.Categorical(heat["mes"], categories=MESES_ORDEM, ordered=True)
heat_pivot = heat.pivot(index="mes", columns="ano", values="eventos").reindex(MESES_ORDEM).fillna(0)

fig = px.imshow(
    heat_pivot,
    aspect="auto",
    text_auto=True,
    title="Mapa de calor: eventos iniciados por mês e ano",
    labels=dict(x="Ano", y="Mês", color="Eventos"),
)
st.plotly_chart(fig, use_container_width=True)


# ==========================================================
# TABELAS
# ==========================================================
aba1, aba2, aba3 = st.tabs(["Eventos consolidados", "Registros da planilha", "Resumo anual"])

with aba1:
    st.write(
        "Tabela consolidada por episódio de ZCAS. Eventos que atravessam mês ou ano são agrupados pelo campo `NOVO EVENTO`."
    )
    tabela_eventos = eventos_filtrados[
        [
            "evento_id", "periodo_evento", "duracao_total_dias",
            "ano_inicio", "ano_fim", "fenomeno", "meses", "registros"
        ]
    ].rename(
        columns={
            "evento_id": "Evento",
            "periodo_evento": "Período",
            "duracao_total_dias": "Duração total (dias)",
            "ano_inicio": "Ano inicial",
            "ano_fim": "Ano final",
            "fenomeno": "Fenômeno",
            "meses": "Meses",
            "registros": "Registros agrupados",
        }
    )
    st.dataframe(tabela_eventos, use_container_width=True, hide_index=True)

with aba2:
    tabela_registros = df_filtrado.copy()
    tabela_registros["data_inicio"] = tabela_registros["data_inicio"].dt.strftime("%d/%m/%Y")
    tabela_registros["data_fim"] = tabela_registros["data_fim"].dt.strftime("%d/%m/%Y")
    tabela_registros = tabela_registros.rename(
        columns={
            "ano": "Ano",
            "periodo_zcas": "Período original",
            "data_inicio": "Data início",
            "data_fim": "Data fim",
            "duracao_dias": "Duração",
            "mes": "Mês",
            "fenomeno": "Fenômeno",
            "novo_evento": "Novo evento",
            "evento_id": "Evento",
        }
    )
    st.dataframe(tabela_registros, use_container_width=True, hide_index=True)

with aba3:
    resumo_anual = (
        df_filtrado.groupby("ano", as_index=False)
        .agg(
            eventos_iniciados=("novo_evento", "sum"),
            dias_zcas=("duracao_dias", "sum"),
            registros=("periodo_zcas", "count"),
        )
    )
    resumo_anual["duracao_media_registro"] = resumo_anual["dias_zcas"] / resumo_anual["registros"]
    resumo_anual = resumo_anual.rename(
        columns={
            "ano": "Ano",
            "eventos_iniciados": "Eventos iniciados",
            "dias_zcas": "Dias com ZCAS",
            "registros": "Registros",
            "duracao_media_registro": "Duração média por registro",
        }
    )
    st.dataframe(resumo_anual, use_container_width=True, hide_index=True)


# ==========================================================
# DOWNLOAD DOS DADOS TRATADOS
# ==========================================================
st.sidebar.divider()
st.sidebar.download_button(
    "Baixar registros filtrados em CSV",
    data=df_filtrado.to_csv(index=False).encode("utf-8-sig"),
    file_name="zcas_registros_filtrados.csv",
    mime="text/csv",
)

st.sidebar.download_button(
    "Baixar eventos consolidados em CSV",
    data=eventos_filtrados.to_csv(index=False).encode("utf-8-sig"),
    file_name="zcas_eventos_consolidados.csv",
    mime="text/csv",
)