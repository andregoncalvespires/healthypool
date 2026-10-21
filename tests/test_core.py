"""Testes dos módulos puros (volume e dosagem). Rode com: python3 -m pytest tests -q"""
import importlib.util
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "healthy_pool"


def _load(name):
    import importlib
    import types

    if "hp" not in sys.modules:
        pkg = types.ModuleType("hp")
        pkg.__path__ = [str(BASE)]
        sys.modules["hp"] = pkg
    return importlib.import_module(f"hp.{name}")


volume = _load("volume")
dosing = _load("dosing")
maintenance = _load("maintenance")

GEOM = volume.PoolGeometry(
    length_cm=700,
    width_cm=395,
    shallow_length_cm=200,
    shallow_depth_cm=45,
    deep_depth_cm=155,
    stair_steps=3,
    stair_tread_cm=37,
    stair_width_cm=90,
)


def test_volume_default():
    v = volume.water_volume_m3(GEOM, 6.5)
    assert 32.5 < v < 33.3, v


def test_volume_freeboard_range():
    v5 = volume.water_volume_m3(GEOM, 5)
    v8 = volume.water_volume_m3(GEOM, 8)
    assert v5 > v8
    assert 0.3 < v5 - v8 < 1.0


def test_volume_without_stairs_is_simple_box_sum():
    g = volume.PoolGeometry(700, 400, 200, 50, 150)
    expected = (400 * 500 * 150 + 400 * 200 * 50) / 1e6
    assert abs(volume.water_volume_m3(g, 0) - expected) < 0.01


def test_alkalinity_low_uses_label_dose():
    # 33 m3, 60 ppm -> alvo 100: 40 ppm * 1,7 g * 33 = 2244 g
    res = dosing.analyze(33, 60, 7.5, 3.0)
    assert res.alkalinity.status == dosing.STATUS_LOW
    assert res.alkalinity.product == dosing.PRODUCT_ALK_UP
    assert abs(res.alkalinity.amount - 2240) <= 10
    assert res.ph.status == dosing.STATUS_OK  # pH está ok
    assert res.overall == dosing.OVERALL_TREAT


def test_alkalinity_high_splits_applications():
    # 170 ppm -> 70 ppm * 1 ml * 33 = 2310 ml, máx 660 ml por aplicação -> 4 aplicações
    res = dosing.analyze(33, 170, 7.5, 3.0)
    assert res.alkalinity.status == dosing.STATUS_HIGH
    assert res.alkalinity.product == dosing.PRODUCT_PH_DOWN
    assert res.alkalinity.applications == 4
    assert abs(res.alkalinity.amount - 2310) <= 10


def test_ph_blocked_until_alkalinity_ok():
    res = dosing.analyze(33, 60, 6.8, 3.0)
    assert res.ph.status == dosing.STATUS_BLOCKED


def test_ph_low_soda_ash_in_ballpark_of_old_table():
    # Tabela antiga do André: alc 100, pH 7,0 -> 7,4 ~ 32 g/m³; alc 80 -> 21 g/m³
    g100 = dosing.soda_ash_grams_per_m3(100, 7.0, 7.4)
    g80 = dosing.soda_ash_grams_per_m3(80, 7.0, 7.4)
    assert 20 < g100 < 35, g100
    assert 15 < g80 < 25, g80
    assert g100 > g80


def test_ph_low_grows_with_alkalinity_and_deficit():
    a = dosing.soda_ash_grams_per_m3(100, 7.0, 7.5)
    b = dosing.soda_ash_grams_per_m3(100, 6.6, 7.5)
    c = dosing.soda_ash_grams_per_m3(140, 7.0, 7.5)
    assert b > a
    assert c > a


def test_ph_low_recommendation():
    res = dosing.analyze(33, 100, 6.8, 3.0)
    assert res.ph.status == dosing.STATUS_LOW
    assert res.ph.product == dosing.PRODUCT_PH_UP
    assert res.ph.amount > 0


def test_ph_high_label_doses():
    mild = dosing.analyze(33, 100, 7.9, 3.0)
    strong = dosing.analyze(33, 100, 8.2, 3.0)
    assert mild.ph.product == dosing.PRODUCT_PH_DOWN
    assert abs(mild.ph.amount - 330) <= 10  # 10 ml/m³
    assert abs(strong.ph.amount - 660) <= 10  # 20 ml/m³


def test_chlorine_dose_dichlor_56():
    # (3 - 0.5) ppm * 33 m³ / 0,56 = 147 g
    res = dosing.analyze(33, 100, 7.5, 0.5)
    assert res.chlorine.status == dosing.STATUS_LOW
    assert abs(res.chlorine.amount - 150) <= 10


def test_chlorine_high_and_ok():
    assert dosing.analyze(33, 100, 7.5, 6).chlorine.status == dosing.STATUS_HIGH
    res = dosing.analyze(33, 100, 7.5, 3)
    assert res.chlorine.message == "Cloro OK"
    assert res.overall == dosing.OVERALL_OK
    assert not res.needs_treatment


def test_unknown_and_incomplete():
    assert dosing.analyze(33, None, None, None).overall == dosing.OVERALL_NO_DATA
    assert dosing.analyze(33, 100, 7.5, None).overall == dosing.OVERALL_INCOMPLETE


def test_treatment_pending():
    res = dosing.analyze(33, 60, 7.5, 3.0, treatment_pending=True)
    assert res.alkalinity.status == dosing.STATUS_PENDING
    assert res.alkalinity.amount == 0
    assert res.overall == dosing.OVERALL_PENDING
    assert res.amount_for(dosing.PRODUCT_ALK_UP) == 0


def test_amount_for_sums_products():
    res = dosing.analyze(33, 170, 7.5, 0.5)
    assert res.amount_for(dosing.PRODUCT_PH_DOWN) > 0
    assert res.amount_for(dosing.PRODUCT_CHLORINE) > 0


# ---------------------------------------------------------------- manutenção
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=timezone.utc)


def _alg(aspect="Limpa", last=None, last_cl=None, ph=7.5, cl=3.0, days=7):
    return maintenance.evaluate_algaecide(33, aspect, last, last_cl, ph, cl, NOW, days)


def test_algaecide_dose_and_first_application_due():
    item = _alg()
    assert item.status == maintenance.ITEM_DUE
    assert abs(item.amount_ml - 165) <= 5  # 5 mL/m³ * 33
    assert item.mode == "manutenção"


def test_algaecide_weekly_interval():
    recent = _alg(last=NOW - timedelta(days=3))
    assert recent.status == maintenance.ITEM_OK
    assert recent.amount_ml == 0
    assert recent.next_due == NOW - timedelta(days=3) + timedelta(days=7)
    assert _alg(last=NOW - timedelta(days=8)).status == maintenance.ITEM_DUE


def test_algaecide_waits_12h_after_chlorine():
    item = _alg(last_cl=NOW - timedelta(hours=4))
    assert item.status == maintenance.ITEM_WAIT
    assert item.wait_until == NOW - timedelta(hours=4) + timedelta(hours=12)
    assert _alg(last_cl=NOW - timedelta(hours=13)).status == maintenance.ITEM_DUE


def test_algaecide_blocked_when_ph_out_of_7_4_to_7_6():
    assert _alg(ph=7.8).status == maintenance.ITEM_BLOCKED
    assert _alg(ph=7.2).status == maintenance.ITEM_BLOCKED
    assert _alg(ph=None).status == maintenance.ITEM_DUE


def test_algaecide_shock_when_green_algae_weekly_interval():
    item = _alg(aspect=maintenance.ASPECT_GREEN, last=NOW - timedelta(days=8))
    assert item.mode == "choque"
    assert item.status == maintenance.ITEM_DUE
    assert abs(item.amount_ml - 230) <= 5  # 7 mL/m³ * 33
    assert any("íons de cobre" in n for n in item.notes)
    # choque contém cobre: repetir só após 7 dias (rótulo: uso semanal)
    assert _alg(aspect=maintenance.ASPECT_GREEN, last=NOW - timedelta(days=3)).status == maintenance.ITEM_OK


def test_algaecide_is_maintenance_when_green_is_metals():
    item = _alg(aspect=maintenance.ASPECT_METALS)
    assert item.mode == "manutenção"  # nunca choque (cobre) quando a cor é de metais


def test_clarifier_preventive_and_corrective():
    prev = maintenance.evaluate_clarifier(33, "Limpa", None, NOW, 7)
    assert prev.mode == "preventivo" and abs(prev.amount_ml - 50) <= 5
    corr = maintenance.evaluate_clarifier(33, "Turva", NOW - timedelta(days=2), NOW, 7)
    assert corr.mode == "corretivo" and corr.status == maintenance.ITEM_DUE
    assert abs(corr.amount_ml - 150) <= 5  # 4,5 mL/m³ * 33
    assert any("6 a 8 h" in n for n in corr.notes)


def test_instructions_markdown_orders_and_explains():
    res = dosing.analyze(33, 170, 7.5, 0.5)
    alg = _alg(last=NOW)  # em dia
    clar = maintenance.evaluate_clarifier(33, "Limpa", NOW, NOW, 7)
    met = _metals()
    text, count = maintenance.build_instructions(res, alg, clar, met, NOW)
    assert count == 2  # pH Menos e cloro
    assert "Ordem de aplicação" in text
    assert "balde plástico" in text  # instrução do pH Menos
    assert text.index("pH Menos") < text.index("Cloro granulado")

    ok = dosing.analyze(33, 100, 7.5, 3)
    text, count = maintenance.build_instructions(ok, alg, clar, met, NOW)
    assert count == 0 and text == "Nenhuma aplicação pendente."


# ---------------------------------------------------- tabela oficial do pH Mais
def test_ph_up_matches_manufacturer_table_exactly():
    table = {
        80: {6.4: 46, 6.6: 38, 6.8: 30, 7.0: 21, 7.2: 13},
        120: {6.4: 74, 6.6: 61, 6.8: 48, 7.0: 34, 7.2: 21},
    }
    for alk, rows in table.items():
        for ph, grams in rows.items():
            assert abs(dosing.label_ph_up_g_per_m3(alk, ph) - grams) < 1e-9, (alk, ph)


def test_ph_up_interpolates_between_table_points():
    assert abs(dosing.label_ph_up_g_per_m3(100, 7.0) - 27.5) < 1e-9  # entre 21 e 34
    assert abs(dosing.label_ph_up_g_per_m3(80, 6.5) - 42.0) < 1e-9  # entre 46 e 38
    assert dosing.label_ph_up_g_per_m3(100, 7.5) == 0.0  # na meta não há dose
    assert dosing.label_ph_up_g_per_m3(100, 7.1) < dosing.label_ph_up_g_per_m3(100, 6.9)


def test_ph_up_extrapolates_below_table_and_never_negative():
    assert dosing.label_ph_up_g_per_m3(80, 6.2) > 46
    assert dosing.label_ph_up_g_per_m3(60, 7.2) >= 0


def test_ph_up_recommendation_uses_table_not_chemistry():
    res = dosing.analyze(33, 80, 6.4, 3.0)
    assert res.ph.product == dosing.PRODUCT_PH_UP
    assert abs(res.ph.amount - 46 * 33) <= 10  # 1518 g, não os ~4000 g do modelo químico


def test_ph_up_target_other_than_7_5_scales_dose():
    t = dosing.Targets(ph_target=7.8, ph_min=7.2, ph_max=8.2)
    base = dosing.ph_up_g_per_m3(100, 7.0, 7.5)
    assert dosing.ph_up_g_per_m3(100, 7.0, 7.8) > base


def test_remeasure_hours_follow_the_labels():
    assert dosing.REMEASURE_HOURS[dosing.PRODUCT_PH_UP] == 1
    assert dosing.REMEASURE_HOURS[dosing.PRODUCT_PH_DOWN] == 24
    assert dosing.REMEASURE_HOURS[dosing.PRODUCT_ALK_UP] == 24


def test_multi_application_acid_is_one_per_day():
    res = dosing.analyze(33, 170, 7.5, 3.0)
    assert res.alkalinity.applications == 4
    assert "uma por dia" in res.alkalinity.message
    assert "dia seguinte" in res.alkalinity.note


# ------------------------------------------------------ removedor de metais
def _metals(aspect="Limpa", last=None, alk=100, ph=7.5, cl=0.8, ppm=0.0):
    return maintenance.evaluate_metals(33, aspect, last, alk, ph, cl, ppm, NOW)


def test_metals_inactive_for_clear_water():
    item = _metals()
    assert item.status == maintenance.ITEM_OK and item.amount_ml == 0
    assert "Não necessário" in item.message


def test_metals_dose_without_test_uses_removal_dose():
    item = _metals(maintenance.ASPECT_METALS)
    assert item.status == maintenance.ITEM_DUE
    assert abs(item.amount_ml - 1650) <= 10  # 50 mL/m³ * 33
    assert any("sugere metais" in n for n in item.notes)
    assert any("50 mL/m³" in n for n in item.notes)
    assert any("1 L" in n and "1,6 frasco" in n.replace("1,7", "1,6") or "frasco" in n for n in item.notes)


def test_metals_dose_with_test_is_15ml_per_ppm():
    item = _metals(maintenance.ASPECT_METALS, ppm=2.0)
    assert abs(item.amount_ml - 990) <= 10  # 15 * 2 * 33
    assert any("15 mL/m³ por ppm" in n for n in item.notes)


def test_metals_blocked_by_chlorine_ph_and_alkalinity():
    assert _metals(maintenance.ASPECT_METALS, cl=3.0).status == maintenance.ITEM_BLOCKED
    assert "no máximo 1 ppm" in _metals(maintenance.ASPECT_METALS, cl=3.0).message
    assert "pH" in _metals(maintenance.ASPECT_METALS, ph=7.9).message
    assert "alcalinidade" in _metals(maintenance.ASPECT_METALS, alk=60).message
    # sem medir o cloro: libera, mas pede confirmação
    unknown = _metals(maintenance.ASPECT_METALS, cl=None)
    assert unknown.status == maintenance.ITEM_DUE
    assert "Confirme" in unknown.notes[0]


def test_metals_stains_adds_brushing_and_backwash():
    item = _metals(maintenance.ASPECT_STAINS)
    text = " ".join(item.notes)
    assert "Escove" in text and "retrolave" in text


def test_metals_repeat_after_one_week_and_window():
    recent = _metals(maintenance.ASPECT_METALS, last=NOW - timedelta(days=3))
    assert recent.status == maintenance.ITEM_OK and "Reavalie" in recent.message
    assert _metals(maintenance.ASPECT_METALS, last=NOW - timedelta(days=8)).status == maintenance.ITEM_DUE
    # fora do aspecto de metais, mas dentro de 7 dias: ainda em ação
    active = _metals("Limpa", last=NOW - timedelta(days=3))
    assert active.mode == "em ação" and "sem choque" in active.message
    assert maintenance.metals_window_end(NOW - timedelta(days=8), NOW) is None
    assert maintenance.metals_window_end(None, NOW) is None


def test_cap_chlorine_never_asks_to_add_chlorine():
    res = dosing.analyze(33, 100, 7.5, 0.5)
    assert res.chlorine.status == dosing.STATUS_LOW
    dosing.cap_chlorine(res, 0.5, 1.0, "Removedor de metais")
    assert res.chlorine.status == dosing.STATUS_OK and res.chlorine.amount == 0
    assert res.chlorine.product is None
    assert res.overall == dosing.OVERALL_OK
    assert "limitar o uso" in res.chlorine.note

    high = dosing.analyze(33, 100, 7.5, 3.0)
    dosing.cap_chlorine(high, 3.0, 1.0, "Removedor de metais")
    assert high.chlorine.status == dosing.STATUS_HIGH
    assert high.overall == dosing.OVERALL_TREAT
    assert "não adicionar cloro nem fazer choque" in high.chlorine.message


def test_instructions_include_metals_and_warnings():
    res = dosing.analyze(33, 100, 7.5, 3.0)
    dosing.cap_chlorine(res, 3.0, 1.0, "Removedor de metais")
    alg = _alg(last=NOW)
    clar = maintenance.evaluate_clarifier(33, "Limpa", NOW, NOW, 7)
    met = _metals(maintenance.ASPECT_METALS, cl=3.0)
    text, count = maintenance.build_instructions(res, alg, clar, met, NOW)
    assert "Atenção" in text and "não adicionar cloro" in text
    assert "removedor de metais" in text.lower()
    assert count == 1  # só o removedor de metais (bloqueado); o aviso de cloro não conta


def test_aspect_options_and_legacy_value():
    assert maintenance.ASPECTS == (
        "Limpa",
        "Turva",
        "Verde (algas)",
        "Verde transparente (metais)",
        "Manchas coloridas (metais)",
    )
    assert maintenance.LEGACY_ASPECTS["Verde"] == maintenance.ASPECT_GREEN


# ------------------------------------------------ validação contra o documento Word
def test_algaecide_note_does_not_ask_for_chlorine_during_metals_window():
    normal = maintenance.evaluate_algaecide(33, "Limpa", None, None, 7.5, 3.0, NOW, 7)
    assert any("2 e 4 ppm" in n for n in normal.notes)
    capped = maintenance.evaluate_algaecide(33, "Limpa", None, None, 7.5, 0.5, NOW, 7, chlorine_limited=True)
    assert not any("Mantenha o cloro livre entre 2 e 4 ppm" in n for n in capped.notes)
    assert any("Conflito entre rótulos" in n for n in capped.notes)
    # com cloro baixo não pede para corrigi-lo (o removedor de metais exige até 1 ppm)
    assert not any("fora de 2 a 4 ppm" in n for n in capped.notes)


def test_clarifier_and_shock_notes_follow_label_steps():
    clar = maintenance.evaluate_clarifier(33, "Turva", None, NOW, 7)
    assert any("Dilua a dose em um balde" in n for n in clar.notes)
    shock = _alg(aspect=maintenance.ASPECT_GREEN)
    assert any("30 a 60 min" in n for n in shock.notes)


def test_metals_sources_note_is_only_what_the_label_supports():
    notes = " ".join(_metals(maintenance.ASPECT_METALS).notes)
    assert "Costuma aparecer" not in notes
    assert "água de poço" in notes and "íons de cobre" in notes


def test_release_times_are_per_product():
    res = dosing.analyze(33, 60, 7.5, 3.0)
    text, _ = maintenance.build_instructions(
        res, _alg(last=NOW), maintenance.evaluate_clarifier(33, "Limpa", NOW, NOW, 7), _metals(), NOW
    )
    assert "1 h após o removedor de metais" in text
    assert "abaixo de 10 ppm" in text


# ------------------------------------------------- janela de pH 7,4 a 7,6
def test_blocked_by_is_reported():
    assert _alg(ph=7.2).blocked_by == "ph"
    assert _metals(maintenance.ASPECT_METALS, ph=7.2).blocked_by == "ph"
    assert _metals(maintenance.ASPECT_METALS, alk=60).blocked_by == "alkalinity"
    assert _metals(maintenance.ASPECT_METALS, cl=3.0).blocked_by == "chlorine"
    assert _alg().blocked_by is None


def test_ph_block_message_has_no_invented_dose_above_7_6():
    high = _alg(ph=7.7).message
    assert "7,4 a 7,6" in high and "a partir de pH 7,8" in high
    low = _alg(ph=7.2).message
    assert "7,4 a 7,6" in low and "7,8" not in low


def test_metals_note_mentions_bottles_and_no_test_dependency():
    notes = " ".join(_metals(maintenance.ASPECT_METALS).notes)
    assert "frasco" in notes
    assert "teste de metais" not in notes


def test_other_pool_shapes():
    from custom_components.healthy_pool.volume import PoolGeometry, water_volume_m3

    base = dict(length_cm=500, width_cm=300, shallow_length_cm=0, shallow_depth_cm=100, deep_depth_cm=140)
    # redonda: diâmetro 400, profundidade média 120, altura livre 10 -> pi*2^2*1,1
    round_ = PoolGeometry(**{**base, "length_cm": 400, "deep_depth_cm": 120}, shape="redonda")
    assert abs(water_volume_m3(round_, 10) - 3.14159 * 4 * 1.1) < 0.01
    # oval: pi/4 * 5 * 3 * 1,3
    oval = PoolGeometry(**{**base, "deep_depth_cm": 140}, shape="oval")
    assert abs(water_volume_m3(oval, 10) - 3.14159 / 4 * 15 * 1.3) < 0.01
    # inclinada: profundidade média (100+140)/2 = 120, menos 10 -> 5*3*1,1
    sloped = PoolGeometry(**base, shape="inclinada")
    assert abs(water_volume_m3(sloped, 10) - 15 * 1.1) < 0.01
    # manual: ignora a altura livre
    manual = PoolGeometry(**base, shape="manual", manual_volume_m3=42.5)
    assert water_volume_m3(manual, 0) == water_volume_m3(manual, 20) == 42.5
    # retangular simples (sem área rasa nem escada) com profundidade uniforme
    simple = PoolGeometry(**{**base, "shallow_depth_cm": 140})
    assert abs(water_volume_m3(simple, 10) - 15 * 1.3) < 0.01
