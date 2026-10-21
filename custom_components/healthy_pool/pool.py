"""Gerenciador de estado da piscina: medições, aplicações, persistência e análise."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ALGAECIDE_DAYS,
    CONF_ALK_MAX,
    CONF_ALK_MIN,
    CONF_ALK_TARGET,
    CONF_CL_MAX,
    CONF_CL_MIN,
    CONF_CL_TARGET,
    CONF_CLARIFIER_DAYS,
    CONF_DEEP_DEPTH,
    CONF_FREEBOARD,
    CONF_LENGTH,
    CONF_PH_MAX,
    CONF_PH_MIN,
    CONF_PH_TARGET,
    CONF_PH_UP_FACTOR,
    CONF_SHALLOW_DEPTH,
    CONF_SHALLOW_LENGTH,
    CONF_STAIR_STEPS,
    CONF_STAIR_TREAD,
    CONF_STAIR_WIDTH,
    CONF_SHAPE,
    CONF_MANUAL_VOLUME,
    CONF_TEMP_ENTITY,
    CONF_WIDTH,
    DEFAULTS,
    DOMAIN,
    STORAGE_VERSION,
    USER_PRODUCTS_DIRNAME,
)
from .catalog import (
    BUILTIN_DIR,
    CONF_PRODUCT_PREFIX,
    ROLE_ORDER,
    ROLE_PH_UP,
    Product,
    ProductSet,
    load_products,
)
from .dosing import (
    STATUS_LOW,
    STATUS_OK,
    Analysis,
    Targets,
    analyze,
    cap_chlorine,
    overall_status,
    ph_up_g_per_m3,
    round_amount,
)
from .maintenance import (
    ASPECT_CLEAR,
    ASPECT_CLOUDY,
    ASPECTS,
    ITEM_DUE,
    ITEM_WAIT,
    KEY_ALGAECIDE,
    KEY_CHLORINE,
    KEY_CLARIFIER,
    KEY_METALS,
    LEGACY_ASPECTS,
    METAL_ASPECTS,
    MaintenanceItem,
    build_instructions,
    evaluate_algaecide,
    evaluate_clarifier,
    evaluate_metals,
    chlorine_gap_hours,
    fmt_dt,
    metals_max_chlorine,
    metals_window_end,
    ph_window,
)
from .treatment import (
    HISTORY_LIMIT,
    LEGACY_KEYS,
    PARAM_ALK,
    PARAM_ASPECT,
    PARAM_CL,
    PARAM_PH,
    PARAMS,
    evaluate_cycle,
    infer_param,
    summarize_results,
)
from .volume import PoolGeometry, volume_breakdown

_UNSET: Any = object()

class PoolManager:
    """Guarda as medições da piscina e calcula as recomendações."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.alkalinity: float | None = None
        self.ph: float | None = None
        self.chlorine: float | None = None
        self.measured_at: datetime | None = None
        self.last_treatment: datetime | None = None
        self.last_treatment_summary: list[str] = []
        self.cycle: dict[str, Any] | None = None  # tratamento em andamento
        self.history: list[dict[str, Any]] = []  # últimos tratamentos concluídos
        self.selected_product: str | None = None  # None = segue a etapa sugerida
        self.selected_amount: float | None = None
        self.metals_ppm: float = 0.0
        self.aspect: str = ASPECT_CLEAR
        self.freeboard_cm: float = float(DEFAULTS[CONF_FREEBOARD])
        self.last_applied: dict[str, datetime] = {}
        self.temperature: float | None = None
        self.catalog: dict[str, Product] = {}
        self._products: ProductSet | None = None
        self._cache: dict[str, Any] = {}
        self._unsub_temp = None
        self._unsub_timer = None
        self._unsub_stop = None

    # ------------------------------------------------------------------ config
    @property
    def signal(self) -> str:
        return f"{DOMAIN}_{self.entry.entry_id}_update"

    @property
    def cfg(self) -> dict[str, Any]:
        return {**DEFAULTS, **self.entry.data, **self.entry.options}

    @property
    def products(self) -> ProductSet:
        """Produto escolhido para cada função (carregado em async_load)."""
        if self._products is None:
            self._products = ProductSet.from_choices(self.catalog, self._choices())
        return self._products

    def _choices(self) -> dict[str, str | None]:
        return {role: self.cfg.get(f"{CONF_PRODUCT_PREFIX}{role}") for role in ROLE_ORDER}

    @property
    def user_products_dir(self) -> str:
        return self.hass.config.path(USER_PRODUCTS_DIRNAME)

    def product_for(self, key: str) -> Product:
        return self.products[key]

    def resolve_product(self, value: str | None) -> str | None:
        """Aceita a função (alk_up), a chave antiga (ph_certo), o nome ou "Marca Nome" do produto."""
        if not value:
            return None
        value = value.strip()
        if value in ROLE_ORDER:
            return value
        if value in LEGACY_KEYS:
            return LEGACY_KEYS[value]
        wanted = value.casefold()
        for role in ROLE_ORDER:
            product = self.products[role]
            if wanted in (product.name.casefold(), product.label.casefold(), product.id.casefold()):
                return role
        return None

    @property
    def geometry(self) -> PoolGeometry:
        c = self.cfg
        return PoolGeometry(
            length_cm=float(c[CONF_LENGTH]),
            width_cm=float(c[CONF_WIDTH]),
            shallow_length_cm=float(c[CONF_SHALLOW_LENGTH]),
            shallow_depth_cm=float(c[CONF_SHALLOW_DEPTH]),
            deep_depth_cm=float(c[CONF_DEEP_DEPTH]),
            stair_steps=int(c[CONF_STAIR_STEPS]),
            stair_tread_cm=float(c[CONF_STAIR_TREAD]),
            stair_width_cm=float(c[CONF_STAIR_WIDTH]),
            shape=str(c[CONF_SHAPE]),
            manual_volume_m3=float(c[CONF_MANUAL_VOLUME]),
        )

    @property
    def targets(self) -> Targets:
        c = self.cfg
        return Targets(
            alk_min=float(c[CONF_ALK_MIN]),
            alk_target=float(c[CONF_ALK_TARGET]),
            alk_max=float(c[CONF_ALK_MAX]),
            ph_min=float(c[CONF_PH_MIN]),
            ph_target=float(c[CONF_PH_TARGET]),
            ph_max=float(c[CONF_PH_MAX]),
            cl_min=float(c[CONF_CL_MIN]),
            cl_target=float(c[CONF_CL_TARGET]),
            cl_max=float(c[CONF_CL_MAX]),
            ph_up_factor=float(c[CONF_PH_UP_FACTOR]),
        )

    @property
    def temperature_entity(self) -> str | None:
        return self.cfg.get(CONF_TEMP_ENTITY) or None

    # ------------------------------------------------------------------ cálculo
    @property
    def volume_info(self) -> dict[str, float]:
        return volume_breakdown(self.geometry, self.freeboard_cm)

    @property
    def volume_m3(self) -> float:
        return self.volume_info["total_m3"]

    @property
    def cycle_steps(self) -> list[dict[str, Any]]:
        return list(self.cycle["steps"]) if self.cycle else []

    @property
    def pending_params(self) -> set[str]:
        """Parâmetros já tratados neste ciclo que ainda esperam uma nova medição."""
        if not self.cycle:
            return set()
        done = set(self.cycle["after"])
        return {
            s["param"]
            for s in self.cycle["steps"]
            if not s.get("skipped") and s.get("param") in PARAMS and s["param"] not in done
        }

    @property
    def treatment_pending(self) -> bool:
        return bool(self.pending_params)

    def _wait_hours(self, step: dict[str, Any]) -> float:
        if step.get("wait_hours") is not None:
            return float(step["wait_hours"])
        product = self.products.get(step["key"])
        return float(product.remeasure_hours) if product else 0.0

    @property
    def remeasure_at(self) -> datetime | None:
        """Quando medir de novo: o maior prazo dos rótulos entre as etapas que aguardam medição."""
        pending = self.pending_params
        times = [
            dt_util.parse_datetime(s["at"]) + timedelta(hours=self._wait_hours(s))
            for s in self.cycle_steps
            if not s.get("skipped") and s.get("param") in pending
        ]
        return max(times) if times else None

    @property
    def analysis(self) -> Analysis:
        if "analysis" not in self._cache:
            analysis = analyze(
                self.volume_m3,
                self.alkalinity,
                self.ph,
                self.chlorine,
                self.targets,
                self.temperature,
                self.pending_params,
                self.products,
            )
            if self.metals_cloro_limited:
                cap_chlorine(
                    analysis,
                    self.chlorine,
                    metals_max_chlorine(self.products.metals),
                    self.products.metals.item_name,
                )
            self._require_ph_window(analysis)
            self._apply_algaecide_gap(analysis)
            self._cache["analysis"] = analysis
        return self._cache["analysis"]

    @property
    def metals_cloro_limited(self) -> bool:
        """Cloro limitado a 1 ppm (e sem choque): aspecto de metais ou 7 dias após o Genquest."""
        return self.aspect in METAL_ASPECTS or (
            metals_window_end(self.last_applied.get(KEY_METALS), dt_util.now(), self.products.metals)
            is not None
        )

    def _eval_algaecide(self) -> MaintenanceItem:
        """Algicida sem consultar a análise (evita ciclo com a janela de pH)."""
        return evaluate_algaecide(
            self.volume_m3,
            self.aspect,
            self.last_applied.get(KEY_ALGAECIDE),
            self.last_applied.get(KEY_CHLORINE),
            self.ph,
            self.chlorine,
            dt_util.now(),
            float(self.cfg[CONF_ALGAECIDE_DAYS]),
            chlorine_limited=self.metals_cloro_limited,
            product=self.products.algaecide,
            acid=self.products.acid,
            metals=self.products.metals,
        )

    def _eval_metals(self) -> MaintenanceItem:
        t = self.targets
        return evaluate_metals(
            self.volume_m3,
            self.aspect,
            self.last_applied.get(KEY_METALS),
            self.alkalinity,
            self.ph,
            self.chlorine,
            self.metals_ppm,
            dt_util.now(),
            t.alk_min,
            t.alk_max,
            product=self.products.metals,
            acid=self.products.acid,
        )

    def _require_ph_window(self, analysis: Analysis) -> None:
        """pH 7,2 a 7,4 passa pela regra do pH, mas algicida e removedor de metais exigem 7,4 a 7,6.

        Nesse caso a correção de pH mostra a dose de pH Mais pela tabela do rótulo.
        Acima de 7,6 não há dose no rótulo (a tabela do pH Menos começa em 7,8), então
        nada é inventado: só a mensagem de bloqueio do produto.
        """
        rec = analysis.ph
        t = self.targets
        if (
            rec.status != STATUS_OK
            or self.ph is None
            or self.alkalinity is None
            or self.ph >= ph_window(self.products.algaecide)[0]
            or not t.alk_min <= self.alkalinity <= t.alk_max
        ):
            return
        blocked = [i for i in (self._eval_algaecide(), self._eval_metals()) if i.blocked_by == "ph"]
        if not blocked:
            return
        total = round_amount(
            ph_up_g_per_m3(
                self.alkalinity, self.ph, t.ph_target, self.temperature or 25.0, self.products.ph_up
            )
            * t.ph_up_factor
            * self.volume_m3
        )
        if total <= 0:
            return
        names = " e ".join(i.name.lower() for i in blocked)
        rec.status = STATUS_LOW
        up = self.products.ph_up
        low, high = ph_window(self.products.algaecide)
        rec.product = up.name
        rec.role = ROLE_PH_UP
        rec.amount = total
        rec.unit = up.unit
        rec.applications = 1
        rec.message = f"Adicionar {int(round(total))} {up.unit} de {up.text_name}"
        rec.note = (
            f"Para chegar a {f'{low:g}'.replace('.', ',')} a {f'{high:g}'.replace('.', ',')}, "
            f"faixa exigida pelo {names}."
        )
        analysis.overall = overall_status(r.status for r in analysis.recommendations)

    def _apply_algaecide_gap(self, analysis: Analysis) -> None:
        """Cloro não pode ser aplicado junto com algicida (12 h entre eles)."""
        last = self.last_applied.get(KEY_ALGAECIDE)
        rec = analysis.chlorine
        if last is None or rec.status != STATUS_LOW:
            return
        gap = chlorine_gap_hours(self.products.algaecide)
        gap_end = last + timedelta(hours=gap)
        now = dt_util.now()
        if now < gap_end:
            rec.message = (
                f"Aguardar até {fmt_dt(gap_end, now)} para adicionar "
                f"{int(round(rec.amount))} {rec.unit} de cloro ({gap:g} h após o algicida)"
            )
            rec.note = f"O rótulo do algicida pede {gap:g} h entre ele e o cloro."

    @property
    def algaecide(self) -> MaintenanceItem:
        if "algaecide" not in self._cache:
            item = self._eval_algaecide()
            # Se ainda falta cloro, ele vem primeiro e o algicida fica 12 h depois.
            if item.status == ITEM_DUE and self.analysis.chlorine.status == STATUS_LOW:
                item.status = ITEM_WAIT
                item.message = (
                    f"Aplicar {int(item.amount_ml)} mL de {item.name.lower()} "
                    f"{chlorine_gap_hours(self.products.algaecide):g} h depois de adicionar o cloro"
                )
            self._cache["algaecide"] = item
        return self._cache["algaecide"]

    @property
    def clarifier(self) -> MaintenanceItem:
        if "clarifier" not in self._cache:
            self._cache["clarifier"] = evaluate_clarifier(
                self.volume_m3,
                self.aspect,
                self.last_applied.get(KEY_CLARIFIER),
                dt_util.now(),
                float(self.cfg[CONF_CLARIFIER_DAYS]),
            )
        return self._cache["clarifier"]

    @property
    def metals(self) -> MaintenanceItem:
        if "metals" not in self._cache:
            self._cache["metals"] = self._eval_metals()
        return self._cache["metals"]

    @property
    def instructions(self) -> tuple[str, int]:
        if "instructions" not in self._cache:
            self._cache["instructions"] = build_instructions(
                self.analysis,
                self.algaecide,
                self.clarifier,
                self.metals,
                dt_util.now(),
                self.products,
            )
        return self._cache["instructions"]

    # --------------------------------------------------------------- persistência
    async def async_load(self) -> None:
        self.catalog = await self.hass.async_add_executor_job(
            load_products, [BUILTIN_DIR, self.user_products_dir]
        )
        self._products = None
        data = await self._store.async_load() or {}
        self.alkalinity = data.get("alkalinity")
        self.ph = data.get("ph")
        self.chlorine = data.get("chlorine")
        self.measured_at = _parse(data.get("measured_at"))
        self.last_treatment = _parse(data.get("last_treatment"))
        self.last_treatment_summary = list(data.get("last_treatment_summary") or [])
        self.cycle = data.get("cycle") or None
        self.history = list(data.get("history") or [])[:HISTORY_LIMIT]
        self._migrate_legacy_keys()
        self.metals_ppm = float(data.get("metals_ppm") or 0.0)
        # Altura livre agora é uma entidade; instalações antigas partem do valor da configuração.
        self.freeboard_cm = float(
            data.get("freeboard_cm", self.cfg.get(CONF_FREEBOARD, DEFAULTS[CONF_FREEBOARD]))
        )
        aspect = LEGACY_ASPECTS.get(data.get("aspect"), data.get("aspect"))
        self.aspect = aspect if aspect in ASPECTS else ASPECT_CLEAR
        self.last_applied = {
            LEGACY_KEYS.get(key, key): parsed
            for key, value in (data.get("last_applied") or {}).items()
            if (parsed := _parse(value)) is not None
        }

    def _migrate_legacy_keys(self) -> None:
        """Versões anteriores guardavam o nome do produto Genco como chave; agora é a função."""
        steps = list(self.cycle["steps"]) if self.cycle else []
        for entry in self.history:
            steps.extend(entry.get("etapas", []))
        for step in steps:
            step["key"] = LEGACY_KEYS.get(step.get("key"), step.get("key"))

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self._as_dict, 1)

    @callback
    def _as_dict(self) -> dict[str, Any]:
        return {
            "alkalinity": self.alkalinity,
            "ph": self.ph,
            "chlorine": self.chlorine,
            "measured_at": self.measured_at.isoformat() if self.measured_at else None,
            "last_treatment": self.last_treatment.isoformat()
            if self.last_treatment
            else None,
            "last_treatment_summary": self.last_treatment_summary,
            "cycle": self.cycle,
            "history": self.history,
            "metals_ppm": self.metals_ppm,
            "aspect": self.aspect,
            "freeboard_cm": self.freeboard_cm,
            "last_applied": {k: v.isoformat() for k, v in self.last_applied.items()},
        }

    # ------------------------------------------------------- acompanhamentos
    @callback
    def async_start(self) -> None:
        """Acompanha a temperatura e reavalia prazos a cada 5 minutos."""
        entity_id = self.temperature_entity
        if entity_id:
            self._update_temperature(self.hass.states.get(entity_id))
            self._unsub_temp = async_track_state_change_event(
                self.hass, [entity_id], self._temperature_changed
            )
        self._unsub_timer = async_track_time_interval(
            self.hass, self._tick, timedelta(minutes=5)
        )
        self._unsub_stop = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._on_stop
        )

    @callback
    def async_stop(self) -> None:
        for attr in ("_unsub_temp", "_unsub_timer", "_unsub_stop"):
            unsub = getattr(self, attr)
            if unsub:
                unsub()
                setattr(self, attr, None)

    @callback
    def _on_stop(self, _event: Event) -> None:
        self._unsub_stop = None
        self.async_stop()

    @callback
    def _tick(self, _now: datetime) -> None:
        self._changed(save=False)

    @callback
    def _temperature_changed(self, event: Event) -> None:
        self._update_temperature(event.data.get("new_state"))
        self._changed(save=False)

    def _update_temperature(self, state: State | None) -> None:
        self.temperature = None
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        try:
            value = float(state.state)
        except ValueError:
            return
        if state.attributes.get("unit_of_measurement") == "°F":
            value = (value - 32.0) * 5.0 / 9.0
        self.temperature = round(value, 1)

    # ----------------------------------------------------------------- operações
    @callback
    def _changed(self, save: bool = True) -> None:
        self._cache.clear()
        if save:
            self._save()
        async_dispatcher_send(self.hass, self.signal)

    @callback
    def set_measurement(
        self,
        alkalinity: Any = _UNSET,
        ph: Any = _UNSET,
        chlorine: Any = _UNSET,
        measured_at: Any = _UNSET,
    ) -> None:
        """Registra medições. A data passa a ser "agora" se não for informada."""
        if alkalinity is not _UNSET:
            self.alkalinity = None if alkalinity is None else float(alkalinity)
        if ph is not _UNSET:
            self.ph = None if ph is None else float(ph)
        if chlorine is not _UNSET:
            self.chlorine = None if chlorine is None else float(chlorine)
        self.measured_at = dt_util.now() if measured_at is _UNSET else measured_at
        self._note_after(
            {
                PARAM_ALK: None if alkalinity is _UNSET else self.alkalinity,
                PARAM_PH: None if ph is _UNSET else self.ph,
                PARAM_CL: None if chlorine is _UNSET else self.chlorine,
            }
        )
        self.selected_product = None
        self.selected_amount = None
        self._changed()

    @callback
    def set_measured_at(self, value: datetime | None) -> None:
        self.measured_at = value
        self._changed()

    @callback
    def set_freeboard(self, value: float) -> None:
        """Altura livre (cm) entre a água e a borda; recalcula o volume."""
        self.freeboard_cm = max(float(value), 0.0)
        self._changed()

    @callback
    def set_metals_ppm(self, value: float) -> None:
        """Metais dissolvidos (ppm) de um teste; 0 = não medido."""
        self.metals_ppm = max(float(value), 0.0)
        self._changed()

    @callback
    def set_aspect(self, aspect: str) -> None:
        if aspect in ASPECTS:
            self.aspect = aspect
            self._note_after({PARAM_ASPECT: aspect})
            self.selected_product = None
            self.selected_amount = None
            self._changed()

    # --------------------------------------------------------- tratamento por etapas
    @property
    def _targets_by_param(self) -> dict[str, float]:
        t = self.targets
        return {PARAM_ALK: t.alk_target, PARAM_PH: t.ph_target, PARAM_CL: t.cl_target}

    def _step_candidates(self) -> list[dict[str, Any]]:
        """Etapas que a análise pede agora, na ordem de aplicação."""
        if "candidates" in self._cache:
            return self._cache["candidates"]
        now = dt_util.now()
        skipped = set()
        if self.cycle and not self.cycle["after"]:
            skipped = {s["key"] for s in self.cycle["steps"] if s.get("skipped")}
        out: list[dict[str, Any]] = []
        for param, rec in zip(PARAMS, self.analysis.recommendations):
            key = rec.role
            if not (rec.actionable and key and rec.amount > 0) or key in skipped:
                continue
            cand = {
                "key": key,
                "name": self.products[key].name,
                "unit": self.products[key].unit,
                "param": param,
                "amount": round_amount(rec.per_application),
                "message": rec.message,
                "applications": rec.applications,
                "wait_until": None,
            }
            if key == KEY_CHLORINE:
                last = self.last_applied.get(KEY_ALGAECIDE)
                gap = timedelta(hours=chlorine_gap_hours(self.products.algaecide))
                if last and now < last + gap:
                    cand["wait_until"] = last + gap
            out.append(cand)
        # Produtos de manutenção dependem da química já corrigida: com alcalinidade ou pH
        # em correção, esperam a nova medição (prazo do rótulo) antes de entrar.
        chem_pending = self.pending_params & {PARAM_ALK, PARAM_PH}
        hold_until = self.remeasure_at if chem_pending else None
        for item in (self.metals, self.algaecide, self.clarifier):
            if item.status == ITEM_WAIT and item.wait_until and item.amount_ml > 0 and item.key not in skipped:
                out.append(
                    {
                        "key": item.key,
                        "name": self.products[item.key].name,
                        "unit": "mL",
                        "param": None,
                        "amount": round_amount(item.amount_ml),
                        "message": item.message,
                        "applications": 1,
                        "wait_until": item.wait_until,
                    }
                )
            elif item.status == ITEM_DUE and item.amount_ml > 0 and item.key not in skipped:
                out.append(
                    {
                        "key": item.key,
                        "name": self.products[item.key].name,
                        "unit": "mL",
                        "param": None,
                        "amount": round_amount(item.amount_ml),
                        "message": item.message,
                        "wait_until": hold_until or (dt_util.now() if chem_pending else None),
                        "reason": "medicao" if chem_pending else None,
                    }
                )
        self._cache["candidates"] = out
        return out

    @property
    def series_hold(self) -> dict[str, Any] | None:
        """Última correção aplicada que ainda espera nova medição.

        Enquanto ela espera, as próximas etapas ficam seguras: o que vem depois depende
        do resultado (e, nas correções divididas em vários dias, a dose seguinte também).
        """
        pending = self.pending_params
        held = [
            s for s in self.cycle_steps if not s.get("skipped") and s.get("param") in pending
        ]
        return held[-1] if held else None

    @property
    def current_step(self) -> dict[str, Any] | None:
        """Primeira etapa liberada para aplicar agora."""
        if self.series_hold:
            return None
        return next((c for c in self._step_candidates() if c["wait_until"] is None), None)

    @property
    def waiting_step(self) -> dict[str, Any] | None:
        return next((c for c in self._step_candidates() if c["wait_until"] is not None), None)

    @property
    def step_text(self) -> str:
        now = dt_util.now()
        held = self.series_hold
        if held:
            at = self.remeasure_at
            when = f"Aguardar até {fmt_dt(at, now)} para" if at and at > now else "Chegou a hora de"
            total = int(held.get("applications") or 1)
            if total > 1:
                done = sum(
                    1
                    for s in self.cycle_steps
                    if not s.get("skipped") and s["key"] == held["key"] and s.get("param") == held["param"]
                )
                return (
                    f"{when} medir de novo e aplicar a próxima dose de {held['name']} "
                    f"({done} de {max(total, done)} aplicações feitas)"
                )
            return f"{when} medir de novo antes da próxima etapa ({held['name']} aplicado)"
        step = self.current_step
        if step:
            text = f"Aplicar {int(round(step['amount']))} {step['unit']} de {step['name']}"
            later = self.waiting_step
            if later:
                text += f" ({later['name']} só a partir de {fmt_dt(later['wait_until'], now)})"
            return text
        waiting = self.waiting_step
        if waiting and waiting.get("reason") != "medicao":
            return f"Aguardar até {fmt_dt(waiting['wait_until'], now)} para {waiting['name']}"
        at = self.remeasure_at
        if self.treatment_pending:
            if at and at > now:
                return f"Aguardando até {fmt_dt(at, now)} para medir de novo"
            return "Medir de novo"
        return "Nenhuma etapa pendente"

    @property
    def next_action(self) -> tuple[datetime, str] | None:
        """Próximo momento em que algo libera, com o texto da ação (para notificações).

        Mantém o horário por 10 minutos depois de passar, para uma automação com gatilho de
        template não perder o instante entre duas reavaliações.
        """
        now = dt_util.now()
        options: list[tuple[datetime, str]] = []
        at = self.remeasure_at
        if at is not None:
            held = self.series_hold
            if held and int(held.get("applications") or 1) > 1:
                options.append((at, f"Medir de novo e aplicar a próxima dose de {held['name']}"))
            else:
                options.append((at, "Medir de novo"))
        for cand in self._step_candidates():
            if cand["wait_until"] is not None:
                options.append(
                    (cand["wait_until"], f"Aplicar {int(round(cand['amount']))} {cand['unit']} de {cand['name']}")
                )
        options = [o for o in options if o[0] > now - timedelta(minutes=10)]
        return min(options, key=lambda o: o[0]) if options else None

    @property
    def effective_product(self) -> str | None:
        """Produto que será registrado: o escolhido ou o da etapa sugerida."""
        if self.selected_product:
            return self.selected_product
        step = self.current_step
        return step["key"] if step else None

    @property
    def effective_amount(self) -> float:
        if self.selected_amount is not None:
            return self.selected_amount
        step = self.current_step
        if step and step["key"] == self.effective_product:
            return float(step["amount"])
        return 0.0

    @callback
    def select_product(self, key: str | None) -> None:
        self.selected_product = key
        self.selected_amount = None
        self._changed(save=False)

    @callback
    def select_amount(self, value: float) -> None:
        self.selected_amount = max(float(value), 0.0)
        self._changed(save=False)

    def _snapshot(self) -> dict[str, Any]:
        return {
            PARAM_ALK: self.alkalinity,
            PARAM_PH: self.ph,
            PARAM_CL: self.chlorine,
            PARAM_ASPECT: self.aspect,
        }

    def _real_steps(self, cycle: dict[str, Any]) -> list[dict[str, Any]]:
        return [s for s in cycle["steps"] if not s.get("skipped")]

    def _treated(self, cycle: dict[str, Any]) -> set[str]:
        return {s.get("param") or PARAM_ASPECT for s in self._real_steps(cycle)}

    def _archive(self, cycle: dict[str, Any]) -> None:
        steps = self._real_steps(cycle)
        if not steps:
            return
        self.history.insert(
            0,
            {
                "inicio": cycle["started_at"],
                "fim": max([*cycle["after_at"].values(), *(s["at"] for s in steps)]),
                "antes": cycle["before"],
                "depois": cycle["after"],
                "etapas": steps,
                "resultados": evaluate_cycle(cycle, self.volume_m3, self._targets_by_param, self.products),
            },
        )
        del self.history[HISTORY_LIMIT:]

    def _ensure_cycle(self, new_param: str | None) -> dict[str, Any]:
        """Devolve o ciclo em andamento ou arquiva o anterior e começa outro."""
        now = dt_util.now()
        cycle = self.cycle
        if cycle:
            steps = self._real_steps(cycle)
            treated = self._treated(cycle)
            done = set(cycle["after"])
            last_at = max((dt_util.parse_datetime(s["at"]) for s in steps), default=now)
            key = new_param or PARAM_ASPECT
            finished = bool(steps) and (
                treated <= done
                or (key in done and key in treated)
                or now - last_at > timedelta(hours=48)
            )
            if finished or (not steps and done):
                self._archive(cycle)
                cycle = None
        if cycle is None:
            cycle = {
                "started_at": now.isoformat(),
                "before": self._snapshot(),
                "after": {},
                "after_at": {},
                "steps": [],
            }
        self.cycle = cycle
        return cycle

    @callback
    def register_step(self, key: str | None = None, amount: float | None = None) -> None:
        """Registra uma aplicação: produto e quantidade realmente colocados na água."""
        key = self.resolve_product(key) if key else self.effective_product
        if key not in ROLE_ORDER:
            raise ServiceValidationError("Escolha o produto aplicado.")
        if amount is None:
            amount = self.effective_amount if key == self.effective_product else 0.0
        amount = float(amount)
        if amount <= 0:
            raise ServiceValidationError("Informe a quantidade aplicada.")

        info = self.products[key]
        suggested = self.current_step if self.current_step and self.current_step["key"] == key else None
        param = infer_param(
            key, suggested["param"] if suggested else None, self.alkalinity, self.targets.alk_max
        )
        now = dt_util.now()
        cycle = self._ensure_cycle(param)
        cycle["steps"].append(
            {
                "at": now.isoformat(),
                "key": key,
                "name": info.name,
                "amount": amount,
                "unit": info.unit,
                "wait_hours": info.remeasure_hours,
                "planned_amount": suggested["amount"] if suggested else None,
                "applications": suggested.get("applications", 1) if suggested else 1,
                "param": param,
                "skipped": False,
            }
        )
        self.last_applied[key] = now
        if param in PARAMS:
            self.last_treatment = now
        self.last_treatment_summary = [
            f"{s['name']} {int(round(s['amount']))} {s['unit']}" for s in self._real_steps(cycle)
        ]
        if key == KEY_CLARIFIER and self.aspect == ASPECT_CLOUDY:
            self.aspect = ASPECT_CLEAR
        self.selected_product = None
        self.selected_amount = None
        self._changed()

    @callback
    def skip_step(self) -> None:
        """Pula a etapa sugerida (não aplicou): a próxima etapa passa a ser a atual."""
        step = self.current_step
        if step is None:
            raise ServiceValidationError("Não há etapa para pular.")
        cycle = self._ensure_cycle(step["param"])
        cycle["steps"].append(
            {
                "at": dt_util.now().isoformat(),
                "key": step["key"],
                "name": step["name"],
                "amount": 0,
                "unit": step["unit"],
                "planned_amount": step["amount"],
                "param": step["param"],
                "skipped": True,
            }
        )
        self.selected_product = None
        self.selected_amount = None
        self._changed()

    def _note_after(self, values: dict[str, Any]) -> None:
        """Guarda o que foi medido depois da aplicação, para comparar com o esperado."""
        if not self.cycle or not self._real_steps(self.cycle):
            return
        now = dt_util.now().isoformat()
        for param, value in values.items():
            if value is None:
                continue
            self.cycle["after"][param] = value
            self.cycle["after_at"][param] = now

    # ----------------------------------------------------------- resultado e histórico
    @property
    def latest_results(self) -> tuple[list[dict[str, Any]], str | None]:
        """Resultado do ciclo atual (se já houve medição depois) ou do último concluído."""
        if self.cycle and self._real_steps(self.cycle):
            results = evaluate_cycle(self.cycle, self.volume_m3, self._targets_by_param, self.products)
            if results:
                return results, self.cycle["started_at"]
        if self.history:
            return self.history[0]["resultados"], self.history[0]["inicio"]
        return [], None

    @property
    def result_text(self) -> str:
        return summarize_results(self.latest_results[0]) if self.latest_results[1] else "Nenhum tratamento registrado"

    def history_view(self) -> list[dict[str, Any]]:
        def entry(h: dict[str, Any], current: bool = False) -> dict[str, Any]:
            return {
                "inicio": h["inicio"] if "inicio" in h else h["started_at"],
                "em_andamento": current,
                "etapas": [
                    f"{s['name']} {int(round(s['amount']))} {s['unit']}" + (" (pulada)" if s.get("skipped") else "")
                    for s in h["etapas" if "etapas" in h else "steps"]
                ],
                "resultado": summarize_results(h["resultados"]) if "resultados" in h else "",
            }

        out: list[dict[str, Any]] = []
        if self.cycle and self._real_steps(self.cycle):
            current = entry(self.cycle, True)
            current["resultado"] = summarize_results(
                evaluate_cycle(self.cycle, self.volume_m3, self._targets_by_param, self.products)
            )
            out.append(current)
        out.extend(entry(h) for h in self.history)
        return out

def _parse(value: str | None) -> datetime | None:
    return dt_util.parse_datetime(value) if value else None
