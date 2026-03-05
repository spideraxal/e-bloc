import logging
from datetime import datetime, timedelta
from aiohttp import ClientSession
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import (
    DOMAIN,
    URL_LOGIN,
    HEADERS_LOGIN,
    HEADERS_POST,
    URL_HOME,
    URL_INDEX,
    URL_RECEIPTS,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)

class EBlocDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordonator pentru actualizarea datelor în integrarea E-bloc."""

    def __init__(self, hass, config):
        """Inițializare coordonator."""
        super().__init__(
            hass,
            _LOGGER,
            name="EBlocDataUpdateCoordinator",
            update_interval=SCAN_INTERVAL,
        )
        self.hass = hass
        self.config = config
        self.session = None
        self.authenticated = False

    async def _async_update_data(self):
        """Actualizează datele pentru toate componentele."""
        try:
            if not self.session:
                self.session = ClientSession()
            if not self.authenticated:
                await self._authenticate()

            # Use current month for the index request
            current_month = datetime.now().strftime("%Y-%m")

            home_data = await self._fetch_data(URL_HOME, {"pIdAsoc": self.config["pIdAsoc"], "pIdAp": self.config["pIdAp"]})

            # Prefer luna_afisata from home data if available
            luna = current_month
            if isinstance(home_data, dict):
                home_info = next(iter(home_data.values()), None) if home_data else None
                if isinstance(home_info, dict) and home_info.get("luna_afisata"):
                    luna = home_info["luna_afisata"]

            return {
                "home": home_data,
                "index": await self._fetch_data(URL_INDEX, {"pIdAsoc": self.config["pIdAsoc"], "pLuna": luna, "pIdAp": "-1"}),
                "receipts": await self._fetch_data(URL_RECEIPTS, {"pIdAsoc": self.config["pIdAsoc"], "pIdAp": self.config["pIdAp"]}),
            }
        except Exception as e:
            raise UpdateFailed(f"Eroare la actualizarea datelor: {e}")

    async def _authenticate(self):
        """Autentificare pe server."""
        payload = {"pUser": self.config["pUser"], "pPass": self.config["pPass"]}
        try:
            async with self.session.post(URL_LOGIN, data=payload, headers=HEADERS_LOGIN) as response:
                if response.status == 200 and "Acces online proprietari" in await response.text():
                    _LOGGER.debug("Autentificare reușită.")
                    self.authenticated = True
                else:
                    raise UpdateFailed("Autentificare eșuată.")
        except Exception as e:
            raise UpdateFailed(f"Eroare la autentificare: {e}")

    async def _fetch_data(self, url, payload):
        """Execută cererea POST și returnează răspunsul JSON."""
        try:
            async with self.session.post(url, data=payload, headers=HEADERS_POST) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    # Handle null JSON responses and session expiry
                    if data is None:
                        _LOGGER.debug("Răspuns null de la %s", url)
                        return {}
                    # Detect session expiry (server returns {"1":{"status":"nologin"}})
                    if isinstance(data, dict):
                        first_val = next(iter(data.values()), None)
                        if isinstance(first_val, dict) and first_val.get("status") == "nologin":
                            _LOGGER.warning("Sesiune expirată, re-autentificare...")
                            self.authenticated = False
                            await self._authenticate()
                            return await self._fetch_data(url, payload)
                    return data
                else:
                    _LOGGER.error("Eroare la accesarea %s: Status %s", url, response.status)
                    return {}
        except Exception as e:
            _LOGGER.error("Eroare la conexiunea cu serverul: %s", e)
            return {}

    async def async_close(self):
        """Închide sesiunea HTTP."""
        if self.session and not self.session.closed:
            await self.session.close()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Setăm senzorii pentru integrarea E-bloc."""
    coordinator = EBlocDataUpdateCoordinator(hass, entry.data)
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator reference for cleanup on unload
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][f"{entry.entry_id}_coordinator"] = coordinator

    sensors = [
        EBlocHomeSensor(coordinator),
        EBlocPlatiChitanteSensor(coordinator),
    ]

    # Create one sensor per real meter (skip entries with id_contor == "0")
    index_data = (coordinator.data or {}).get("index") or {}
    for key, meter in index_data.items():
        if isinstance(meter, dict) and meter.get("id_contor") and meter["id_contor"] != "0":
            sensors.append(EBlocContorSensor(coordinator, key, meter))

    async_add_entities(sensors, update_before_add=True)


class EBlocSensorBase(SensorEntity):
    """Clasă de bază pentru senzorii E-bloc."""

    def __init__(self, coordinator, name):
        self._coordinator = coordinator
        self._attr_name = name
        self._attr_state = None
        self._attr_extra_state_attributes = {}

    async def async_update(self):
        """Actualizează datele pentru senzor."""
        await self._coordinator.async_request_refresh()


class EBlocHomeSensor(EBlocSensorBase):
    """Senzor pentru `AjaxGetHomeApInfo.php`."""

    def __init__(self, coordinator):
        super().__init__(coordinator, "Date client")

    async def async_update(self):
        """Actualizează datele pentru senzorul `home`."""
        coordinator_data = self._coordinator.data or {}
        home_data = coordinator_data.get("home") or {}
        # Find the first entry in home data (key may vary)
        data = {}
        if isinstance(home_data, dict) and home_data:
            data = next(iter(home_data.values()), {}) or {}

        self._attr_state = data.get("cod_client") or "Necunoscut"
        self._attr_extra_state_attributes = {
            "Cod client": data.get("cod_client") or "Necunoscut",
            "Apartament": data.get("ap") or "Necunoscut",
            "Persoane declarate": data.get("nr_pers_afisat") or "Necunoscut",
            "Restanță de plată": f"{int(data.get('datorie') or 0) / 100:.2f} RON",
            "Ultima zi de plată": data.get("ultima_zi_plata") or "Necunoscut",
            "Contor trimis": "Da"
            if data.get("contoare_citite") == "1"
            else "Nu",
            "Începere citire contoare": data.get("citire_contoare_start") or "Necunoscut",
            "Încheiere citire contoare": data.get("citire_contoare_end") or "Necunoscut",
            "Luna cu datoria cea mai veche": data.get("luna_veche") or "Necunoscut",
            "Luna afișată": data.get("luna_afisata") or "Necunoscut",
            "Nivel restanță": data.get("nivel_restanta") or "Necunoscut",
        }

    @property
    def unique_id(self):
        return f"{DOMAIN}_client"

    @property
    def name(self):
        return self._attr_name

    @property
    def state(self):
        return self._attr_state

    @property
    def extra_state_attributes(self):
        return self._attr_extra_state_attributes

    @property
    def icon(self):
        """Pictograma senzorului."""
        return "mdi:account-file"

    @property
    def device_info(self):
        """Returnează informațiile dispozitivului."""
        return {
            "identifiers": {(DOMAIN, "home")},
            "name": "Interfață UI pentru E-bloc.ro",
            "manufacturer": "E-bloc.ro",
            "model": "Interfață UI pentru E-bloc.ro",
            "entry_type": DeviceEntryType.SERVICE,
        }

class EBlocContorSensor(EBlocSensorBase):
    """Senzor individual pentru fiecare contor din `AjaxGetIndexContoare.php`."""

    def __init__(self, coordinator, key, meter_data):
        self._key = key
        self._contor_id = meter_data.get("id_contor", key)
        titlu = meter_data.get("titlu") or f"Contor {key}"
        super().__init__(coordinator, f"Index {titlu}")

    async def async_update(self):
        """Actualizează datele pentru acest contor."""
        coordinator_data = self._coordinator.data or {}
        index_data = coordinator_data.get("index") or {}
        data = (index_data.get(self._key) or {})

        index_vechi = (data.get("index_vechi") or "").strip()
        index_nou = (data.get("index_nou") or "").strip()

        # Valorile vin în mii (ex. 1481000 = 1481 mc)
        try:
            index_vechi_val = f"{int(float(index_vechi) // 1000)}" if index_vechi and index_vechi != "0" else "Necunoscut"
        except ValueError:
            index_vechi_val = "Necunoscut"

        try:
            index_nou_val = f"{int(float(index_nou) // 1000)}" if index_nou and index_nou != "0" else "Necunoscut"
        except ValueError:
            index_nou_val = "Necunoscut"

        # Starea senzorului este indexul nou (cel mai recent)
        if index_nou_val != "Necunoscut":
            self._attr_state = f"{index_nou_val} mc"
        elif index_vechi_val != "Necunoscut":
            self._attr_state = f"{index_vechi_val} mc"
        else:
            self._attr_state = "Necunoscut"

        # Atribute suplimentare
        self._attr_extra_state_attributes = {
            "Titlu": data.get("titlu") or "Necunoscut",
            "Index vechi": f"{index_vechi_val} mc" if index_vechi_val != "Necunoscut" else "Necunoscut",
            "Index nou": f"{index_nou_val} mc" if index_nou_val != "Necunoscut" else "Necunoscut",
            "Data citire": data.get("data") or "Necunoscut",
            "ID contor": data.get("id_contor") or "Necunoscut",
        }

    @property
    def unique_id(self):
        return f"{DOMAIN}_contor_{self._contor_id}"

    @property
    def name(self):
        return self._attr_name

    @property
    def state(self):
        return self._attr_state

    @property
    def extra_state_attributes(self):
        return self._attr_extra_state_attributes

    @property
    def icon(self):
        """Pictograma senzorului."""
        return "mdi:counter"

    @property
    def device_info(self):
        """Returnează informațiile dispozitivului."""
        return {
            "identifiers": {(DOMAIN, "home")},
            "name": "Interfață UI pentru E-bloc.ro",
            "manufacturer": "E-bloc.ro",
            "model": "Interfață UI pentru E-bloc.ro",
            "entry_type": DeviceEntryType.SERVICE,
        }

class EBlocPlatiChitanteSensor(EBlocSensorBase):
    """Senzor pentru `AjaxGetPlatiChitanteToti.php`."""

    def __init__(self, coordinator):
        super().__init__(coordinator, "Plăți și chitanțe")

    async def async_update(self):
        """Actualizează datele pentru senzorul `plati_chitante`."""
        coordinator_data = self._coordinator.data or {}
        data = coordinator_data.get("receipts") or {}
        numar_chitante = len(data)

        # Setăm starea senzorului pe baza numărului de chitanțe
        self._attr_state = numar_chitante

        # Creăm atribute suplimentare
        atribute = {"Număr total de chitanțe": numar_chitante}
        for idx, chitanta_data in data.items():
            numar = chitanta_data.get("numar", "Necunoscut")
            data_chitanta = chitanta_data.get("data", "Necunoscut")
            suma = chitanta_data.get("suma", "0")
            suma_formatata = f"{int(suma) / 100:.2f} RON"

            # Formatul exact al atributelor (fără "Chitanță X")
            atribute[f"Chitanță {idx}"] = numar
            atribute[f"Data {idx}"] = data_chitanta
            atribute[f"Sumă plătită {idx}"] = suma_formatata

        # Atribuim atributele suplimentare
        self._attr_extra_state_attributes = atribute

    @property
    def unique_id(self):
        return f"{DOMAIN}_plati_si_chitante"

    @property
    def name(self):
        return self._attr_name

    @property
    def state(self):
        return self._attr_state

    @property
    def extra_state_attributes(self):
        return self._attr_extra_state_attributes

    @property
    def icon(self):
        """Pictograma senzorului."""
        return "mdi:credit-card-check-outline"

    @property
    def device_info(self):
        """Returnează informațiile dispozitivului."""
        return {
            "identifiers": {(DOMAIN, "home")},
            "name": "Interfață UI pentru E-bloc.ro",
            "manufacturer": "E-bloc.ro",
            "model": "Interfață UI pentru E-bloc.ro",
            "entry_type": DeviceEntryType.SERVICE,
        }
