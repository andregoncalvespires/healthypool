"""Testes de integração com o Home Assistant (pytest-homeassistant-custom-component)."""
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.healthy_pool.const import (
    CONF_NAME,
    CONF_TEMP_ENTITY,
    DEFAULTS,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def _enable(enable_custom_integrations):
    yield


async def _setup(hass: HomeAssistant, **extra) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Piscina", data={**DEFAULTS, CONF_NAME: "Piscina", **extra}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _set(hass, entity_id, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )


async def _step(hass, produto=None, quantidade=None):
    data = {}
    if produto:
        data["produto"] = produto
    if quantidade is not None:
        data["quantidade"] = quantidade
    await hass.services.async_call(DOMAIN, "registrar_etapa", data, blocking=True)


async def test_setup_creates_entities_and_volume(hass: HomeAssistant):
    await _setup(hass)
    vol = hass.states.get("sensor.piscina_volume_de_agua")
    assert vol is not None
    assert 32.5 < float(vol.state) < 33.3
    assert vol.attributes["litros"] > 32000
    assert hass.states.get("sensor.piscina_qualidade_da_agua").state == "Sem medição"
    for eid in (
        "number.piscina_alcalinidade_total",
        "number.piscina_ph",
        "number.piscina_cloro_livre",
        "datetime.piscina_data_da_medicao",
        "button.piscina_registrar_etapa",
        "button.piscina_pular_etapa",
        "select.piscina_produto_aplicado",
        "number.piscina_quantidade_aplicada",
        "sensor.piscina_etapa_atual",
        "sensor.piscina_resultado_do_tratamento",
        "sensor.piscina_historico_de_tratamentos",
        "binary_sensor.piscina_precisa_de_tratamento",
        "sensor.piscina_correcao_alcalinidade",
        "sensor.piscina_correcao_ph",
        "sensor.piscina_correcao_cloro",
        "sensor.piscina_adicionar_ph_certo",
        "sensor.piscina_adicionar_ph_mais",
        "sensor.piscina_adicionar_ph_menos",
        "sensor.piscina_adicionar_cloro",
        "sensor.piscina_ultimo_tratamento",
    ):
        assert hass.states.get(eid) is not None, eid


async def test_measure_recommend_and_register_treatment(hass: HomeAssistant):
    await _setup(hass)
    await _set(hass, "number.piscina_alcalinidade_total", 60)
    await _set(hass, "number.piscina_ph", 7.5)
    await _set(hass, "number.piscina_cloro_livre", 1.0)

    assert hass.states.get("sensor.piscina_qualidade_da_agua").state == "Tratar Água"
    assert hass.states.get("binary_sensor.piscina_precisa_de_tratamento").state == "on"
    assert "pH Certo" in hass.states.get("sensor.piscina_correcao_alcalinidade").state
    assert abs(float(hass.states.get("sensor.piscina_adicionar_ph_certo").state) - 2240) <= 20
    assert float(hass.states.get("sensor.piscina_adicionar_cloro").state) > 0
    assert hass.states.get("datetime.piscina_data_da_medicao").state not in (
        "unknown",
        "unavailable",
    )

    # pH Certo pela sugestão; o cloro só depois da nova medição, mas pode ser registrado à mão
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.piscina_registrar_etapa"}, blocking=True
    )
    await _step(hass, "Cloro granulado", 100)
    assert (
        hass.states.get("sensor.piscina_qualidade_da_agua").state
        == "Aguardando nova medição"
    )
    assert float(hass.states.get("sensor.piscina_adicionar_ph_certo").state) == 0

    # nova medição libera as recomendações de novo
    await _set(hass, "number.piscina_alcalinidade_total", 100)
    await _set(hass, "number.piscina_cloro_livre", 3.0)
    assert hass.states.get("sensor.piscina_qualidade_da_agua").state == "Água OK"
    assert hass.states.get("binary_sensor.piscina_precisa_de_tratamento").state == "off"


async def test_record_measurement_service(hass: HomeAssistant):
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN,
        "registrar_medicao",
        {"alcalinidade": 100, "ph": 6.8, "cloro": 3},
        blocking=True,
    )
    assert hass.states.get("sensor.piscina_correcao_ph").state.startswith("Adicionar")
    assert "pH Mais" in hass.states.get("sensor.piscina_correcao_ph").state
    assert float(hass.states.get("sensor.piscina_adicionar_ph_mais").state) > 0


async def test_temperature_sensor_mirrors_entity(hass: HomeAssistant):
    hass.states.async_set(
        "sensor.aquecedor_temp",
        "28.5",
        {"device_class": "temperature", "unit_of_measurement": "°C"},
    )
    await _setup(hass, **{CONF_TEMP_ENTITY: "sensor.aquecedor_temp"})
    assert float(hass.states.get("sensor.piscina_temperatura_da_agua").state) == 28.5
    hass.states.async_set(
        "sensor.aquecedor_temp",
        "86",
        {"device_class": "temperature", "unit_of_measurement": "°F"},
    )
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.piscina_temperatura_da_agua").state) == 30.0


async def test_persistence_across_reload(hass: HomeAssistant):
    entry = await _setup(hass)
    await _set(hass, "number.piscina_alcalinidade_total", 110)
    await hass.async_block_till_done()
    # força gravação do Store e recarrega a integração
    manager = hass.data[DOMAIN][entry.entry_id]
    await manager._store.async_save(manager._as_dict())
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get("number.piscina_alcalinidade_total").state) == 110


async def test_config_flow_creates_entry(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    geometry = {**{k: v for k, v in DEFAULTS.items() if k in (
        "length_cm", "width_cm", "shallow_length_cm", "shallow_depth_cm",
        "deep_depth_cm", "stair_steps", "stair_tread_cm", "stair_width_cm")},
        CONF_NAME: "Piscina"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], geometry)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "products"
    products = {k: v for k, v in DEFAULTS.items() if k.startswith("product_")}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], products)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "limits"

    limits = {k: v for k, v in DEFAULTS.items() if k.startswith(("alk_", "ph_", "cl_"))}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], limits)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Piscina"
    assert result["data"]["stair_steps"] == 3
    assert result["data"]["product_alk_up"] == "genco_ph_certo"


async def test_config_flow_rejects_bad_geometry(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    bad = {
        "length_cm": 700, "width_cm": 395, "shallow_length_cm": 800,
        "shallow_depth_cm": 45, "deep_depth_cm": 155, "stair_steps": 3,
        "stair_tread_cm": 37, "stair_width_cm": 90,
        CONF_NAME: "Piscina",
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], bad)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_geometry"}


async def test_options_flow_updates_geometry(hass: HomeAssistant):
    entry = await _setup(hass)
    before = float(hass.states.get("sensor.piscina_volume_de_agua").state)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    geometry = {k: v for k, v in DEFAULTS.items() if k in (
        "length_cm", "width_cm", "shallow_length_cm", "shallow_depth_cm",
        "deep_depth_cm", "stair_steps", "stair_tread_cm", "stair_width_cm")}
    geometry["length_cm"] = 800
    result = await hass.config_entries.options.async_configure(result["flow_id"], geometry)
    assert result["step_id"] == "products"
    products = {k: v for k, v in DEFAULTS.items() if k.startswith("product_")}
    result = await hass.config_entries.options.async_configure(result["flow_id"], products)
    assert result["step_id"] == "limits"
    limits = {k: v for k, v in DEFAULTS.items() if k.startswith(("alk_", "ph_", "cl_"))}
    limits.update(algaecide_interval_days=7, clarifier_interval_days=7)
    result = await hass.config_entries.options.async_configure(result["flow_id"], limits)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert float(hass.states.get("sensor.piscina_volume_de_agua").state) > before


async def test_freeboard_is_a_number_entity_and_changes_volume(hass: HomeAssistant):
    entry = await _setup(hass)
    state = hass.states.get("number.piscina_altura_livre")
    assert state is not None and float(state.state) == 6.5
    assert state.attributes["unit_of_measurement"] == "cm"

    base = float(hass.states.get("sensor.piscina_volume_de_agua").state)
    await _set(hass, "number.piscina_altura_livre", 5)
    higher = float(hass.states.get("sensor.piscina_volume_de_agua").state)
    await _set(hass, "number.piscina_altura_livre", 8)
    lower = float(hass.states.get("sensor.piscina_volume_de_agua").state)
    assert higher > base > lower
    assert 0.5 < higher - lower < 1.0
    assert hass.states.get("sensor.piscina_volume_de_agua").attributes["altura_livre_cm"] == 8

    # a dose acompanha o volume
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 60, "ph": 7.5, "cloro": 3}, blocking=True
    )
    dose_8 = float(hass.states.get("sensor.piscina_adicionar_ph_certo").state)
    await _set(hass, "number.piscina_altura_livre", 5)
    dose_5 = float(hass.states.get("sensor.piscina_adicionar_ph_certo").state)
    assert dose_5 > dose_8

    # persiste no reload
    manager = hass.data[DOMAIN][entry.entry_id]
    await manager._store.async_save(manager._as_dict())
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get("number.piscina_altura_livre").state) == 5


async def test_legacy_config_freeboard_seeds_the_number(hass: HomeAssistant):
    await _setup(hass, freeboard_cm=7.0)
    assert float(hass.states.get("number.piscina_altura_livre").state) == 7.0


# ---------------------------------------------------------------- manutenção e card
from datetime import timedelta  # noqa: E402

import yaml  # noqa: E402
from homeassistant.helpers.template import Template  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402

LOVELACE = __import__("pathlib").Path(__file__).resolve().parents[1] / "lovelace"
CARD_INPUT = LOVELACE / "card_piscina_1_entradas.yaml"
CARD_INDICATORS = LOVELACE / "card_piscina_2_indicadores.yaml"
CARD_ACTIONS = LOVELACE / "card_piscina_3_acoes.yaml"


def _templates(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _templates(value)
    elif isinstance(node, list):
        for value in node:
            yield from _templates(value)
    elif isinstance(node, str) and ("{{" in node or "{%" in node):
        yield node


def _entity_ids(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("entity", "entity_id") and isinstance(value, str):
                yield value
            else:
                yield from _entity_ids(value)
    elif isinstance(node, list):
        for value in node:
            yield from _entity_ids(value)


async def test_maintenance_entities_and_flow(hass: HomeAssistant):
    await _setup(hass)
    # sem registros: algicida e clarificante pendentes
    assert hass.states.get("binary_sensor.piscina_aplicar_algicida").state == "on"
    assert hass.states.get("binary_sensor.piscina_aplicar_clarificante").state == "on"
    assert abs(float(hass.states.get("sensor.piscina_adicionar_algicida").state) - 165) <= 5
    assert abs(float(hass.states.get("sensor.piscina_adicionar_clarificante").state) - 50) <= 5

    await _step(hass, "Algicida", 165)
    await _step(hass, "Clarificante", 50)
    assert hass.states.get("binary_sensor.piscina_aplicar_algicida").state == "off"
    assert hass.states.get("sensor.piscina_adicionar_algicida").state == "0.0"
    assert "em dia" in hass.states.get("sensor.piscina_algicida").state
    assert hass.states.get("sensor.piscina_algicida").attributes["proxima_aplicacao"]

    # água turva: clarificante corretivo volta a ser pendente; registrar volta para "Limpa"
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.piscina_aspecto_da_agua", "option": "Turva"},
        blocking=True,
    )
    clar = hass.states.get("sensor.piscina_clarificante")
    assert "corretivo" in clar.state or clar.attributes["modo"] == "corretivo"
    assert hass.states.get("select.piscina_aspecto_da_agua").state == "Turva"


async def test_chlorine_blocks_algaecide_for_12h_and_vice_versa(hass: HomeAssistant):
    entry = await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 100, "ph": 7.5, "cloro": 0.5}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.piscina_registrar_etapa"}, blocking=True
    )
    algicida = hass.states.get("sensor.piscina_algicida")
    assert algicida.attributes["situacao"] == "wait"
    assert algicida.attributes["aguardar_ate"]

    # o inverso: algicida aplicado há pouco segura o cloro
    manager = hass.data[DOMAIN][entry.entry_id]
    manager.last_applied.clear()
    manager.cycle = None
    manager.register_step("algicida", 165)
    manager.set_measurement(alkalinity=100, ph=7.5, chlorine=0.5)
    await hass.async_block_till_done()
    msg = hass.states.get("sensor.piscina_correcao_cloro").state
    assert msg.startswith("Aguardar até")


async def test_instructions_sensor(hass: HomeAssistant):
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 170, "ph": 7.5, "cloro": 0.5}, blocking=True
    )
    s = hass.states.get("sensor.piscina_instrucoes_de_aplicacao")
    assert "pendente" in s.state
    text = s.attributes["instrucoes"]
    assert "Ordem de aplicação" in text and "pH Menos" in text
    assert hass.states.get("sensor.piscina_remedir_a_partir_de").state == "unknown"
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.piscina_registrar_etapa"}, blocking=True
    )
    remeasure = dt_util.parse_datetime(hass.states.get("sensor.piscina_remedir_a_partir_de").state)
    assert timedelta(hours=23) < remeasure - dt_util.utcnow() <= timedelta(hours=24)


async def test_lovelace_groups_entities_exist_and_templates_render(hass: HomeAssistant):
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 60, "ph": 7.5, "cloro": 0.5}, blocking=True
    )
    groups = {
        "entradas": yaml.safe_load(CARD_INPUT.read_text()),
        "indicadores": yaml.safe_load(CARD_INDICATORS.read_text()),
        "acoes": yaml.safe_load(CARD_ACTIONS.read_text()),
    }

    for name, tree in groups.items():
        # cada grupo é um único card pronto para uma seção, com cabeçalho
        assert tree["type"] == "vertical-stack", name
        assert tree["cards"][0]["type"] == "heading", name
        missing = [e for e in set(_entity_ids(tree)) if hass.states.get(e) is None]
        assert not missing, f"{name}: entidades que não existem: {missing}"
        for source in _templates(tree):
            rendered = Template(source, hass).async_render(parse_result=False)
            assert "TemplateError" not in rendered, (name, source)

    ids = {name: set(_entity_ids(tree)) for name, tree in groups.items()}

    # 1) entradas: só entidades editáveis (number, datetime, select)
    assert {e.split(".")[0] for e in ids["entradas"]} == {"number", "datetime", "select", "button"}
    for needed in (
        "number.piscina_alcalinidade_total", "number.piscina_ph", "number.piscina_cloro_livre",
        "number.piscina_altura_livre",
        "datetime.piscina_data_da_medicao", "select.piscina_aspecto_da_agua",
    ):
        assert needed in ids["entradas"], needed

    # 2) indicadores: sem botões e sem campos de entrada para editar
    assert not any(e.startswith(("button.", "select.", "datetime.")) for e in ids["indicadores"])
    indicators = groups["indicadores"]["cards"]
    assert Template(indicators[1]["primary"], hass).async_render() == "Tratar Água"
    assert "m³" in Template(indicators[1]["secondary"], hass).async_render()
    for needed in (
        "sensor.piscina_qualidade_da_agua", "sensor.piscina_algicida",
        "sensor.piscina_clarificante", "sensor.piscina_removedor_de_metais",
    ):
        assert needed in ids["indicadores"], needed
    # as correções não dependem de sensor.piscina_correcao_* (nomes que colidem com sensores antigos)
    assert not any("piscina_correcao" in e for e in ids["indicadores"])
    code = "\n".join(l for l in CARD_INDICATORS.read_text().splitlines() if not l.lstrip().startswith("#"))
    assert "piscina_correcao" not in code
    secondary = [Template(c["secondary"], hass).async_render() for c in indicators[2:5]]
    assert all(sec and sec != "unknown" for sec in secondary), secondary
    assert "pH Certo" in secondary[0] and secondary[1] == "pH OK"

    # 3) ações: só orientação; o registro (botões) fica apenas no grupo 1
    actions = groups["acoes"]["cards"]
    howto = next(c for c in actions if c.get("entity") == "sensor.piscina_instrucoes_de_aplicacao")
    popup = howto["tap_action"]["browser_mod"]
    assert popup["service"] == "browser_mod.popup" and popup["data"]["content"]["type"] == "markdown"
    assert not any(c["type"] == "markdown" and "Como aplicar" in c.get("title", "") for c in actions)
    text = Template(popup["data"]["content"]["content"], hass).async_render()
    assert "Ordem de aplicação" in text and "Como aplicar" in text
    assert not any(e.startswith("button.") for e in ids["acoes"])
    assert {e for e in ids["entradas"] if e.startswith("button.")} == {
        "button.piscina_registrar_etapa", "button.piscina_pular_etapa",
    }
    assert "select.piscina_produto_aplicado" in ids["entradas"]
    assert "number.piscina_quantidade_aplicada" in ids["entradas"]
    assert "sensor.piscina_etapa_atual" in CARD_ACTIONS.read_text()




async def _aspect(hass, option):
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.piscina_aspecto_da_agua", "option": option}, blocking=True,
    )


async def test_metals_flow_limits_chlorine_and_registers_window(hass: HomeAssistant):
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 100, "ph": 7.5, "cloro": 3.0}, blocking=True
    )
    await _aspect(hass, "Verde transparente (metais)")

    # cloro 3 ppm: o removedor de metais espera e o cloro não deve ser acrescentado
    metals = hass.states.get("sensor.piscina_removedor_de_metais")
    assert metals.attributes["situacao"] == "blocked"
    assert "no máximo 1 ppm" in metals.state
    assert "não adicionar cloro" in hass.states.get("sensor.piscina_correcao_cloro").state
    # algicida de choque nunca é sugerido quando a cor é de metais
    assert hass.states.get("sensor.piscina_algicida").attributes["modo"] == "manutenção"

    # cloro baixou: removedor de metais liberado com a dose de 50 mL/m³
    await _set(hass, "number.piscina_cloro_livre", 0.8)
    metals = hass.states.get("sensor.piscina_removedor_de_metais")
    assert metals.attributes["situacao"] == "due"
    dose = float(hass.states.get("sensor.piscina_adicionar_removedor_de_metais").state)
    assert abs(dose - 50 * 32.9) <= 60
    assert hass.states.get("binary_sensor.piscina_aplicar_removedor_de_metais").state == "on"
    # cloro baixo NÃO gera pedido de cloro durante o tratamento
    assert hass.states.get("sensor.piscina_correcao_cloro").attributes["situacao"] == "ok"
    assert float(hass.states.get("sensor.piscina_adicionar_cloro").state) == 0

    # com teste de metais informado: 15 mL/m³ por ppm
    await _set(hass, "number.piscina_metais_dissolvidos", 2)
    dose = float(hass.states.get("sensor.piscina_adicionar_removedor_de_metais").state)
    assert abs(dose - 15 * 2 * 32.9) <= 20

    # registrar aplicação: em dia, e a janela de 7 dias mantém o limite de cloro mesmo com água "Limpa"
    await _step(hass, "Removedor de metais (Genquest)", 1600)
    assert hass.states.get("binary_sensor.piscina_aplicar_removedor_de_metais").state == "off"
    assert "Reavalie" in hass.states.get("sensor.piscina_removedor_de_metais").state
    await _aspect(hass, "Limpa")
    await _set(hass, "number.piscina_cloro_livre", 0.5)
    assert hass.states.get("sensor.piscina_correcao_cloro").attributes["situacao"] == "ok"
    assert float(hass.states.get("sensor.piscina_adicionar_cloro").state) == 0
    assert hass.states.get("sensor.piscina_removedor_de_metais").attributes["modo"] == "em ação"
    await _set(hass, "number.piscina_cloro_livre", 3.0)
    assert hass.states.get("sensor.piscina_qualidade_da_agua").state == "Tratar Água"


async def test_green_algae_uses_shock_and_chlorine_is_normal(hass: HomeAssistant):
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 100, "ph": 7.5, "cloro": 0.5}, blocking=True
    )
    await _aspect(hass, "Verde (algas)")
    alg = hass.states.get("sensor.piscina_algicida")
    assert alg.attributes["modo"] == "choque"
    assert hass.states.get("sensor.piscina_correcao_cloro").attributes["situacao"] == "low"
    assert hass.states.get("sensor.piscina_removedor_de_metais").attributes["modo"] == "inativo"


async def test_legacy_green_aspect_and_ph_up_from_label_table(hass: HomeAssistant):
    from homeassistant.helpers.storage import Store

    entry = MockConfigEntry(domain=DOMAIN, title="Piscina", data={**DEFAULTS, CONF_NAME: "Piscina"})
    entry.add_to_hass(hass)
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_save({"aspect": "Verde"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("select.piscina_aspecto_da_agua").state == "Verde (algas)"

    await _aspect(hass, "Limpa")
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 80, "ph": 6.4, "cloro": 3}, blocking=True
    )
    # tabela Genco: 46 g/m³ com alcalinidade 80 e pH 6,4
    grams = float(hass.states.get("sensor.piscina_adicionar_ph_mais").state)
    assert abs(grams - 46 * 32.9) <= 30


async def test_ph_7_2_gets_ph_mais_dose_when_algaecide_needs_the_window(hass: HomeAssistant):
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 100, "ph": 7.2, "cloro": 3.0}, blocking=True
    )
    # algicida de manutenção pendente e bloqueado pelo pH -> pH Mais pela tabela (7,2 até 7,5)
    assert hass.states.get("sensor.piscina_algicida").attributes["situacao"] == "blocked"
    ph = hass.states.get("sensor.piscina_correcao_ph")
    assert ph.state.startswith("Adicionar") and "pH Mais" in ph.state
    grams = float(hass.states.get("sensor.piscina_adicionar_ph_mais").state)
    assert abs(grams - 17 * 32.9) <= 20  # tabela em pH 7,2: 13 (alc. 80) e 21 (alc. 120) -> 17 g/m³ com alc. 100
    assert hass.states.get("sensor.piscina_qualidade_da_agua").state == "Tratar Água"
    text = hass.states.get("sensor.piscina_instrucoes_de_aplicacao").attributes["instrucoes"]
    assert text.index("pH Mais") < text.index("algicida")

    # pH já dentro de 7,4 a 7,6: não há dose de pH Mais
    await _set(hass, "number.piscina_ph", 7.5)
    assert hass.states.get("sensor.piscina_correcao_ph").state == "pH OK"
    assert float(hass.states.get("sensor.piscina_adicionar_ph_mais").state) == 0


async def test_ph_7_7_has_no_invented_dose(hass: HomeAssistant):
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 100, "ph": 7.7, "cloro": 3.0}, blocking=True
    )
    assert hass.states.get("sensor.piscina_correcao_ph").state == "pH OK"  # rótulo: corrigir só acima de 7,8
    assert float(hass.states.get("sensor.piscina_adicionar_ph_menos").state) == 0
    assert "7,8" in hass.states.get("sensor.piscina_algicida").state


async def test_status_sensor_exposes_corrections_for_the_card(hass: HomeAssistant):
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 60, "ph": 7.5, "cloro": 0.5}, blocking=True
    )
    attrs = hass.states.get("sensor.piscina_qualidade_da_agua").attributes
    assert "pH Certo" in attrs["correcao_alcalinidade"]
    assert attrs["correcao_ph"] == "pH OK"
    assert "cloro" in attrs["correcao_cloro"]
    assert attrs["situacao_alcalinidade"] == "low" and attrs["situacao_ph"] == "ok"


async def test_manual_volume_shape(hass: HomeAssistant):
    await _setup(hass, shape="manual", manual_volume_m3=25.0)
    assert float(hass.states.get("sensor.piscina_volume_de_agua").state) == 25.0


async def test_step_by_step_treatment_with_effectiveness(hass: HomeAssistant):
    entry = await _setup(hass)
    manager = hass.data[DOMAIN][entry.entry_id]
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 60, "ph": 7.5, "cloro": 0.5}, blocking=True
    )
    # etapa sugerida: pH Certo, com a quantidade já preenchida
    assert hass.states.get("sensor.piscina_etapa_atual").state.startswith("Aplicar")
    assert "pH Certo" in hass.states.get("sensor.piscina_etapa_atual").state
    assert hass.states.get("select.piscina_produto_aplicado").state == "pH Certo"
    suggested = float(hass.states.get("number.piscina_quantidade_aplicada").state)
    assert abs(suggested - 2240) <= 20

    # aplicou só metade do que foi sugerido
    await _set(hass, "number.piscina_quantidade_aplicada", suggested / 2)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.piscina_registrar_etapa"}, blocking=True
    )
    # a correção espera a nova medição e segura as próximas etapas
    assert hass.states.get("sensor.piscina_etapa_atual").state.startswith("Aguardar até")
    assert hass.states.get("sensor.piscina_correcao_alcalinidade").state == "Aguardando nova medição após o tratamento"
    assert "pH Certo" in hass.states.get("sensor.piscina_ultimo_tratamento").attributes["aplicado"][0]

    # nova medição: 1120 g em 32,9 m³ deveriam subir ~20 ppm; subiu 12
    await _set(hass, "number.piscina_alcalinidade_total", 72)
    result = hass.states.get("sensor.piscina_resultado_do_tratamento")
    item = result.attributes["resultados"][0]
    assert item["parametro"] == "Alcalinidade"
    assert abs(item["esperado"] - 20) <= 1
    assert item["medido"] == 12
    assert item["veredito"] == "abaixo do esperado"
    assert "Medido antes do prazo" in item["observacao"]

    # novo ciclo: o anterior vai para o histórico
    await _step(hass, "pH Certo", 700)
    history = hass.states.get("sensor.piscina_historico_de_tratamentos")
    assert history.state == "1"
    assert history.attributes["historico"][0]["em_andamento"] is True
    assert "pH Certo" in history.attributes["resumo"]


async def test_register_step_without_product_or_amount_fails(hass: HomeAssistant):
    from homeassistant.exceptions import ServiceValidationError

    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 100, "ph": 7.5, "cloro": 3.0}, blocking=True
    )
    await _step(hass, "Algicida", 165)
    await _step(hass, "Clarificante", 50)
    # água em dia e manutenção feita: nenhuma etapa sugerida
    assert hass.states.get("sensor.piscina_etapa_atual").state == "Nenhuma etapa pendente"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "registrar_etapa", {"produto": "pH Mais"}, blocking=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("button", "press", {"entity_id": "button.piscina_pular_etapa"}, blocking=True)


async def test_history_keeps_only_last_20(hass: HomeAssistant):
    entry = await _setup(hass)
    manager = hass.data[DOMAIN][entry.entry_id]
    for i in range(25):
        manager.register_step("ph_certo", 100 + i)
        manager.set_measurement(alkalinity=80 + i)
    manager.register_step("ph_certo", 1)
    assert len(manager.history) == 20
    assert manager.history[0]["etapas"][0]["amount"] == 124


async def test_cycle_and_history_survive_reload(hass: HomeAssistant):
    entry = await _setup(hass)
    manager = hass.data[DOMAIN][entry.entry_id]
    manager.set_measurement(alkalinity=60, ph=7.5, chlorine=3.0)
    manager.register_step("ph_certo", 1000)
    manager.set_measurement(alkalinity=70)
    manager.register_step("ph_certo", 500)  # arquiva o anterior
    await manager._store.async_save(manager._as_dict())
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    again = hass.data[DOMAIN][entry.entry_id]
    assert len(again.history) == 1
    assert again.cycle["steps"][0]["amount"] == 500
    assert hass.states.get("sensor.piscina_historico_de_tratamentos").state == "1"


async def test_maintenance_waits_while_ph_or_alkalinity_correction_is_pending(hass: HomeAssistant):
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 160, "ph": 7.2, "cloro": 0}, blocking=True
    )
    await _step(hass, "pH Menos", 610)
    # pH Menos em várias aplicações (uma por dia): nada mais é sugerido até a nova medição
    state = hass.states.get("sensor.piscina_etapa_atual")
    assert state.state.startswith("Aguardar até")
    assert "pH Menos" in state.state
    assert state.attributes["produto"] is None
    # depois de medir de novo, a manutenção é liberada
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 110, "ph": 7.5, "cloro": 3}, blocking=True
    )
    assert hass.states.get("sensor.piscina_etapa_atual").attributes["produto"] in (
        "Algicida", "Clarificante", "Removedor de metais (Genquest)"
    )


async def test_multi_application_correction_holds_next_steps(hass: HomeAssistant):
    from homeassistant.exceptions import ServiceValidationError

    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 160, "ph": 7.5, "cloro": 3.0}, blocking=True
    )
    first = hass.states.get("sensor.piscina_etapa_atual").state
    assert "pH Menos" in first
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.piscina_registrar_etapa"}, blocking=True
    )
    # 1 de 3 aplicações: espera até amanhã em vez de passar para o clarificante
    text = hass.states.get("sensor.piscina_etapa_atual").state
    assert text.startswith("Aguardar até") and "pH Menos" in text and "1 de" in text
    assert "Clarificante" not in text
    assert hass.states.get("select.piscina_produto_aplicado").state == "unknown"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.piscina_registrar_etapa"}, blocking=True
        )
    # nova medição no dia seguinte libera a próxima dose e as demais etapas
    await _set(hass, "number.piscina_alcalinidade_total", 140)
    text = hass.states.get("sensor.piscina_etapa_atual").state
    assert text.startswith("Aplicar") and "pH Menos" in text


async def test_skip_step_moves_to_next(hass: HomeAssistant):
    entry = await _setup(hass)
    manager = hass.data[DOMAIN][entry.entry_id]
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 100, "ph": 7.5, "cloro": 0.5}, blocking=True
    )
    assert "Cloro" in hass.states.get("sensor.piscina_etapa_atual").state
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.piscina_pular_etapa"}, blocking=True
    )
    assert "Cloro" not in hass.states.get("sensor.piscina_etapa_atual").state
    assert manager.cycle["steps"][-1]["skipped"] is True


async def test_chlorine_after_algaecide_waits_12h(hass: HomeAssistant):
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 100, "ph": 7.5, "cloro": 3.0}, blocking=True
    )
    await _step(hass, "Algicida", 165)
    await _set(hass, "number.piscina_cloro_livre", 0.5)
    state = hass.states.get("sensor.piscina_etapa_atual")
    assert "Cloro granulado só a partir de" in state.state
    assert state.attributes["aguardando"] == "Cloro granulado"


async def test_algaecide_after_chlorine_waits_12h(hass: HomeAssistant):
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 100, "ph": 7.5, "cloro": 0.5}, blocking=True
    )
    await _step(hass, "Cloro granulado", 100)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 100, "ph": 7.5, "cloro": 3.0}, blocking=True
    )
    state = hass.states.get("sensor.piscina_etapa_atual")
    assert "Algicida só a partir de" in state.state
    assert state.attributes["aguardando"] == "Algicida"


async def test_next_action_attribute_for_notifications(hass: HomeAssistant):
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 60, "ph": 7.5, "cloro": 3.0}, blocking=True
    )
    assert hass.states.get("sensor.piscina_etapa_atual").attributes["proxima_acao_em"] is None
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.piscina_registrar_etapa"}, blocking=True
    )
    attrs = hass.states.get("sensor.piscina_etapa_atual").attributes
    when = dt_util.parse_datetime(attrs["proxima_acao_em"])
    assert timedelta(hours=23) < when - dt_util.utcnow() <= timedelta(hours=24)
    assert attrs["proxima_acao_descricao"] == "Medir de novo"

    # cloro depois do algicida: o horário é o fim das 12 h
    await _step(hass, "Algicida", 165)
    await _set(hass, "number.piscina_alcalinidade_total", 100)
    await _set(hass, "number.piscina_cloro_livre", 0.5)
    attrs = hass.states.get("sensor.piscina_etapa_atual").attributes
    when = dt_util.parse_datetime(attrs["proxima_acao_em"])
    assert timedelta(hours=11) < when - dt_util.utcnow() <= timedelta(hours=12)
    assert "Cloro granulado" in attrs["proxima_acao_descricao"]


OTHER_BRAND_ALK_UP = {
    "id": "acme_alk_plus",
    "brand": "Acme",
    "name": "Alcalino Plus",
    "role": "alk_up",
    "unit": "g",
    "remeasure_hours": 12,
    "dosing": {"g_per_m3_per_ppm": 2.0},
    "instructions": ["Dissolva em água antes de aplicar. Depois, corrija o pH com {ph_up}."],
    "source": "Ficha de teste",
}


async def test_custom_product_changes_dose_names_and_instructions(hass: HomeAssistant, tmp_path):
    import json

    hass.config.config_dir = str(tmp_path)
    folder = tmp_path / "healthy_pool_products"
    folder.mkdir()
    (folder / "acme_alk_plus.json").write_text(json.dumps(OTHER_BRAND_ALK_UP), encoding="utf-8")
    (folder / "quebrada.json").write_text("{ não é json", encoding="utf-8")  # ignorada
    (folder / "incompleta.json").write_text(json.dumps({"id": "x"}), encoding="utf-8")  # ignorada

    entry = await _setup(hass, product_alk_up="acme_alk_plus")
    await hass.services.async_call(
        DOMAIN, "registrar_medicao", {"alcalinidade": 60, "ph": 7.5, "cloro": 3.0}, blocking=True
    )
    # 40 ppm x 2,0 g/m³/ppm x ~32,9 m³ (a ficha da Genco daria 1,7)
    dose = float(hass.states.get("sensor.piscina_adicionar_ph_certo").state)
    assert abs(dose - 40 * 2.0 * 32.9) <= 30
    assert "Alcalino Plus" in hass.states.get("sensor.piscina_correcao_alcalinidade").state
    assert hass.states.get("select.piscina_produto_aplicado").state == "Alcalino Plus"
    text = hass.states.get("sensor.piscina_instrucoes_de_aplicacao").attributes["instrucoes"]
    assert "Dissolva em água" in text and "corrija o pH com pH Mais" in text
    assert hass.states.get("sensor.piscina_adicionar_ph_certo").attributes["marca"] == "Acme"

    # a espera vem da ficha (12 h)
    manager = hass.data[DOMAIN][entry.entry_id]
    await hass.services.async_call("button", "press", {"entity_id": "button.piscina_registrar_etapa"}, blocking=True)
    remeasure = dt_util.parse_datetime(hass.states.get("sensor.piscina_remedir_a_partir_de").state)
    assert timedelta(hours=11) < remeasure - dt_util.utcnow() <= timedelta(hours=12)
    assert manager.cycle["steps"][0]["name"] == "Alcalino Plus"


async def test_unknown_product_choice_falls_back_to_default(hass: HomeAssistant):
    entry = await _setup(hass, product_alk_up="nao_existe")
    assert hass.data[DOMAIN][entry.entry_id].products.alk_up.id == "genco_ph_certo"


async def test_register_step_accepts_role_name_or_legacy_key(hass: HomeAssistant):
    from homeassistant.exceptions import ServiceValidationError

    entry = await _setup(hass)
    manager = hass.data[DOMAIN][entry.entry_id]
    await _step(hass, "algaecide", 165)
    await _step(hass, "Clarificante", 50)
    await _step(hass, "Genco pH Certo", 100)
    manager.register_step("ph_menos", 50)  # chave antiga
    assert [s["key"] for s in manager.cycle["steps"]] == ["algaecide", "clarifier", "alk_up", "acid"]
    with pytest.raises(ServiceValidationError):
        await _step(hass, "Produto inexistente", 10)


async def test_legacy_stored_keys_are_migrated(hass: HomeAssistant, hass_storage):
    entry = MockConfigEntry(domain=DOMAIN, title="Piscina", data={**DEFAULTS, CONF_NAME: "Piscina"})
    entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "last_applied": {"algicida": "2026-10-01T10:00:00+00:00", "ph_certo": "2026-10-01T10:00:00+00:00"},
            "cycle": {
                "started_at": "2026-10-01T10:00:00+00:00",
                "before": {},
                "after": {},
                "after_at": {},
                "steps": [{"at": "2026-10-01T10:00:00+00:00", "key": "ph_certo", "name": "pH Certo",
                           "amount": 100, "unit": "g", "param": "alkalinity", "skipped": False}],
            },
            "history": [{"inicio": "2026-09-01T10:00:00+00:00", "fim": "2026-09-02T10:00:00+00:00",
                         "antes": {}, "depois": {}, "resultados": [],
                         "etapas": [{"at": "2026-09-01T10:00:00+00:00", "key": "cloro", "name": "Cloro granulado",
                                     "amount": 50, "unit": "g", "param": "chlorine", "skipped": False}]}],
        },
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager = hass.data[DOMAIN][entry.entry_id]
    assert set(manager.last_applied) == {"algaecide", "alk_up"}
    assert manager.cycle["steps"][0]["key"] == "alk_up"
    assert manager.history[0]["etapas"][0]["key"] == "chlorine"
