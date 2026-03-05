import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def mask_value(value):
    """Maschează valoarea, afișând doar primele 3 caractere."""
    if not value or len(value) <= 3:
        return value
    return value[:3] + '*' * (len(value) - 3)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Configurează integrarea utilizând Config Entry.
    """
    _LOGGER.debug("Inițializăm integrarea pentru E-bloc. ID intrare: %s", entry.entry_id)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Maschează datele pentru loguri
    masked_data = {key: mask_value(value) for key, value in entry.data.items()}
    _LOGGER.debug("Configurația curentă a fost adăugată: %s", masked_data)

    # Configurăm platformele folosind metoda corectă
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Curăță integrarea atunci când este eliminată.
    """
    _LOGGER.debug("Încercăm să eliminăm integrarea pentru E-bloc. ID intrare: %s", entry.entry_id)

    # Close the coordinator's HTTP session
    coordinator = hass.data[DOMAIN].get(f"{entry.entry_id}_coordinator")
    if coordinator and hasattr(coordinator, "async_close"):
        await coordinator.async_close()

    # Eliminăm datele specifice acestei intrări
    if entry.entry_id in hass.data[DOMAIN]:
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_coordinator", None)
        _LOGGER.debug("Intrarea a fost eliminată cu succes.")
        # Descărcăm platformele asociate
        return await hass.config_entries.async_unload_platforms(entry, ["sensor"])

    _LOGGER.warning("Intrarea cu ID %s nu a fost găsită în datele curente.", entry.entry_id)
    return False
