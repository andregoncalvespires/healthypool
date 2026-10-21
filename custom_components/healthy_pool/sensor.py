"""Sensores: volume, qualidade, correções e quantidades de produto."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util, slugify

from .const import DOMAIN
from .catalog import ROLE_ACID, ROLE_ALK_UP, ROLE_CHLORINE, ROLE_PH_UP
from .dosing import (
    OVERALL_OK,
    OVERALL_PENDING,
    OVERALL_TREAT,
    Recommendation,
)
from .entity import PoolEntity
from .pool import PoolManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: PoolManager = hass.data[DOMAIN][entry.entry_id]
    entities: list[PoolEntity] = [
        PoolVolumeSensor(manager),
        PoolStatusSensor(manager),
        CorrectionSensor(manager, "correction_alkalinity", "Correção alcalinidade", "alkalinity"),
        CorrectionSensor(manager, "correction_ph", "Correção pH", "ph"),
        CorrectionSensor(manager, "correction_chlorine", "Correção cloro", "chlorine"),
        DoseSensor(manager, "dose_ph_certo", ROLE_ALK_UP, "mdi:cup-water"),
        DoseSensor(manager, "dose_ph_mais", ROLE_PH_UP, "mdi:cup-water"),
        DoseSensor(manager, "dose_ph_menos", ROLE_ACID, "mdi:beaker-minus"),
        DoseSensor(manager, "dose_cloro", ROLE_CHLORINE, "mdi:water-plus"),
        LastTreatmentSensor(manager),
        RemeasureSensor(manager),
        MaintenanceSensor(manager, "algaecide", "Algicida", "algaecide", "mdi:bacteria-outline"),
        MaintenanceSensor(manager, "clarifier", "Clarificante", "clarifier", "mdi:water-opacity"),
        MaintenanceDoseSensor(manager, "dose_algicida", "Adicionar algicida", "algaecide"),
        MaintenanceDoseSensor(manager, "dose_clarificante", "Adicionar clarificante", "clarifier"),
        MaintenanceSensor(manager, "metals", "Removedor de metais", "metals", "mdi:flask-round-bottom-outline"),
        MaintenanceDoseSensor(manager, "dose_metais", "Adicionar removedor de metais", "metals"),
        InstructionsSensor(manager),
        CurrentStepSensor(manager),
        ResultSensor(manager),
        HistorySensor(manager),
    ]
    if manager.temperature_entity:
        entities.append(PoolTemperatureSensor(manager))
    async_add_entities(entities)


class PoolVolumeSensor(PoolEntity, SensorEntity):
    """Volume de água calculado pela geometria e pela altura livre."""

    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_icon = "mdi:pool"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "volume", "Volume de água")

    @property
    def native_value(self) -> float:
        return round(self.manager.volume_m3, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.manager.volume_info
        return {
            "litros": round(info["total_m3"] * 1000),
            "altura_livre_cm": self.manager.freeboard_cm,
            "parte_funda_m3": info["parte_funda_m3"],
            "area_rasa_m3": info["area_rasa_m3"],
            "escada_m3": info["escada_m3"],
        }


class PoolTemperatureSensor(PoolEntity, SensorEntity):
    """Temperatura da água (espelha o sensor configurado, em °C)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "temperature", "Temperatura da água")

    @property
    def native_value(self) -> float | None:
        return self.manager.temperature


class PoolStatusSensor(PoolEntity, SensorEntity):
    """Situação geral: Água OK / Tratar Água / ..."""

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "status", "Qualidade da água")

    @property
    def native_value(self) -> str:
        return self.manager.analysis.overall

    @property
    def icon(self) -> str:
        overall = self.manager.analysis.overall
        if overall == OVERALL_OK:
            return "mdi:water-check"
        if overall == OVERALL_TREAT:
            return "mdi:water-minus"
        if overall == OVERALL_PENDING:
            return "mdi:water-sync"
        return "mdi:water-alert"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        analysis = self.manager.analysis
        return {
            "proxima_acao": analysis.next_action,
            "recomendacoes": [r.message for r in analysis.recommendations],
            "correcao_alcalinidade": analysis.alkalinity.message,
            "correcao_ph": analysis.ph.message,
            "correcao_cloro": analysis.chlorine.message,
            "situacao_alcalinidade": analysis.alkalinity.status,
            "situacao_ph": analysis.ph.status,
            "situacao_cloro": analysis.chlorine.status,
            "data_medicao": self.manager.measured_at.isoformat()
            if self.manager.measured_at
            else None,
        }


class CorrectionSensor(PoolEntity, SensorEntity):
    """Texto de correção de um parâmetro (substitui sensor.piscina_correcao_*)."""

    def __init__(self, manager: PoolManager, key: str, name: str, which: str) -> None:
        super().__init__(manager, key, name)
        self._which = which

    @property
    def _rec(self) -> Recommendation:
        return getattr(self.manager.analysis, self._which)

    @property
    def native_value(self) -> str:
        return self._rec.message

    @property
    def icon(self) -> str:
        return "mdi:check-circle-outline" if self._rec.status == "ok" else "mdi:flask-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rec = self._rec
        return {
            "situacao": rec.status,
            "produto": rec.product,
            "quantidade_total": rec.amount,
            "unidade": rec.unit,
            "aplicacoes": rec.applications,
            "quantidade_por_aplicacao": round(rec.per_application),
            "observacao": rec.note,
        }


_DOSE_OBJECT_IDS = {
    ROLE_ALK_UP: "adicionar_ph_certo",
    ROLE_PH_UP: "adicionar_ph_mais",
    ROLE_ACID: "adicionar_ph_menos",
    ROLE_CHLORINE: "adicionar_cloro",
}


class DoseSensor(PoolEntity, SensorEntity):
    """Quantidade numérica (g ou mL) do produto escolhido para uma função."""

    def __init__(self, manager: PoolManager, key: str, role: str, icon: str) -> None:
        super().__init__(manager, key, f"Adicionar {manager.products[role].name}")
        # O entity_id não depende da marca escolhida: os cards continuam valendo se o produto mudar.
        self.entity_id = f"sensor.{slugify(manager.entry.title)}_{_DOSE_OBJECT_IDS[role]}"
        self._role = role
        self._attr_icon = icon
        self._attr_suggested_display_precision = 0

    @property
    def name(self) -> str:
        if self._role == ROLE_CHLORINE:
            return "Adicionar cloro"
        return f"Adicionar {self.manager.products[self._role].name}"

    @property
    def native_unit_of_measurement(self) -> str:
        return self.manager.products[self._role].unit

    @property
    def native_value(self) -> float:
        return self.manager.analysis.amount_for(self._role)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        product = self.manager.products[self._role]
        return {"produto": product.name, "marca": product.brand, "ficha": product.id}


class LastTreatmentSensor(PoolEntity, SensorEntity):
    """Quando o último tratamento foi registrado."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:history"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "last_treatment", "Último tratamento")

    @property
    def native_value(self) -> datetime | None:
        return self.manager.last_treatment

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"aplicado": self.manager.last_treatment_summary}


class RemeasureSensor(PoolEntity, SensorEntity):
    """Quando medir de novo depois de um tratamento."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:timer-sand"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "remeasure_at", "Remedir a partir de")

    @property
    def native_value(self) -> datetime | None:
        return self.manager.remeasure_at


class MaintenanceSensor(PoolEntity, SensorEntity):
    """Situação e instruções do algicida ou do clarificante."""

    def __init__(
        self, manager: PoolManager, key: str, name: str, attr: str, icon: str
    ) -> None:
        super().__init__(manager, key, name)
        self._attr = attr
        self._attr_icon = icon

    @property
    def _item(self):
        return getattr(self.manager, self._attr)

    @property
    def native_value(self) -> str:
        return self._item.message

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._item
        return {
            "situacao": item.status,
            "produto": item.name,
            "modo": item.mode,
            "dose_ml": item.amount_ml,
            "intervalo_dias": item.interval_days,
            "ultima_aplicacao": item.last_applied.isoformat() if item.last_applied else None,
            "proxima_aplicacao": item.next_due.isoformat() if item.next_due else None,
            "aguardar_ate": item.wait_until.isoformat() if item.wait_until else None,
            "observacoes": item.notes,
        }


class MaintenanceDoseSensor(PoolEntity, SensorEntity):
    """Quantidade (mL) de algicida ou clarificante a aplicar agora (0 se em dia)."""

    _attr_native_unit_of_measurement = "mL"
    _attr_suggested_display_precision = 0

    def __init__(self, manager: PoolManager, key: str, name: str, attr: str) -> None:
        super().__init__(manager, key, name)
        self._attr = attr
        self._attr_icon = "mdi:beaker-outline"

    @property
    def native_value(self) -> float:
        return getattr(self.manager, self._attr).amount_ml


class InstructionsSensor(PoolEntity, SensorEntity):
    """Ordem e modo de aplicação dos produtos pendentes (Markdown no atributo)."""

    _attr_icon = "mdi:clipboard-list-outline"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "instructions", "Instruções de aplicação")

    @property
    def native_value(self) -> str:
        count = self.manager.instructions[1]
        if count == 0:
            return "Nada a aplicar"
        return f"{count} aplicação pendente" if count == 1 else f"{count} aplicações pendentes"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"instrucoes": self.manager.instructions[0], "pendentes": self.manager.instructions[1]}


class CurrentStepSensor(PoolEntity, SensorEntity):
    """Etapa atual do tratamento: o que aplicar agora, o que aguardar ou medir de novo."""

    _attr_icon = "mdi:stairs"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "current_step", "Etapa atual")

    @property
    def native_value(self) -> str:
        return self.manager.step_text

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        step = self.manager.current_step
        waiting = self.manager.waiting_step
        remaining = [
            f"{int(round(c['amount']))} {c['unit']} de {c['name']}"
            for c in self.manager._step_candidates()
        ]
        return {
            "produto": step["name"] if step else None,
            "quantidade_sugerida": step["amount"] if step else None,
            "unidade": step["unit"] if step else None,
            "aguardando": waiting["name"] if waiting else None,
            "aguardar_ate": waiting["wait_until"].isoformat() if waiting else None,
            "medir_de_novo_a_partir_de": self.manager.remeasure_at.isoformat()
            if self.manager.remeasure_at
            else None,
            "proxima_acao_em": self.manager.next_action[0].isoformat() if self.manager.next_action else None,
            "proxima_acao_descricao": self.manager.next_action[1] if self.manager.next_action else None,
            "etapas_restantes": remaining,
            "aplicado_neste_tratamento": self.manager.last_treatment_summary
            if self.manager.cycle
            else [],
        }


class ResultSensor(PoolEntity, SensorEntity):
    """Efetividade do tratamento: esperado x medido, depois da nova medição."""

    _attr_icon = "mdi:chart-line-variant"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "treatment_result", "Resultado do tratamento")

    @property
    def native_value(self) -> str:
        text = self.manager.result_text
        return text if len(text) <= 255 else text[:252] + "..."

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        results, started = self.manager.latest_results
        return {"inicio": started, "resultados": results, "texto": self.manager.result_text}


class HistorySensor(PoolEntity, SensorEntity):
    """Últimos 20 tratamentos concluídos (mais o que está em andamento)."""

    _attr_icon = "mdi:history"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "treatment_history", "Histórico de tratamentos")

    @property
    def native_value(self) -> int:
        return len(self.manager.history)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        view = self.manager.history_view()
        lines = []
        for h in view[:10]:
            when = dt_util.as_local(dt_util.parse_datetime(h["inicio"])).strftime("%d/%m %H:%M")
            tag = " (em andamento)" if h["em_andamento"] else ""
            lines.append(f"- **{when}**{tag}: {', '.join(h['etapas'])}")
            if h["resultado"]:
                lines.append(f"  - {h['resultado']}")
        return {"historico": view, "resumo": "\n".join(lines) or "Nenhum tratamento registrado."}
