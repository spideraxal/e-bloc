import logging
from datetime import datetime, timedelta
from aiohttp import ClientSession
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
    CoordinatorEntity,
)
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    URL_LOGIN,
    HEADERS_LOGIN,
    HEADERS_POST,
    URL_HOME,
    URL_INDEX,
    URL_RECEIPTS,
)

_LOGGER = logging.getLogger(__name__)

DEVICE_INFO = {
    "identifiers": {(DOMAIN, "home")},
    "name": "E-bloc.ro",
    "manufacturer": "E-bloc.ro",
    "model": "Interfață UI pentru E-bloc.ro",
    "entry_type": DeviceEntryType.SERVICE,
}


class EBlocDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordonator pentru actualizarea datelor în integrarea E-bloc."""

    def __init__(self, hass, config):
        """Inițializare coordonator."""
        scan_interval = int(config.get("scan_interval", DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name="EBlocDataUpdateCoordinator",
            update_interval=timedelta(seconds=scan_interval),
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

            result = {
                "home": home_data,
                "index": await self._fetch_data(URL_INDEX, {"pIdAsoc": self.config["pIdAsoc"], "pLuna": luna, "pIdAp": "-1"}),
                "receipts": await self._fetch_data(URL_RECEIPTS, {"pIdAsoc": self.config["pIdAsoc"], "pIdAp": self.config["pIdAp"]}),
            }
            _LOGGER.debug("Date actualizate cu succes: home=%s, index_keys=%s, receipts=%s",
                         bool(home_data), list((result.get("index") or {}).keys()), bool(result.get("receipts")))
            return result
        except Exception as e:
            raise UpdateFailed(f"Eroare la actualizarea datelor: {e}")

    async def _authenticate(self):
        """Autentificare pe server."""
        payload = {"pUser": self.config["pUser"], "pPass": self.config["pPass"]}
        try:
            async with self.session.post(URL_LOGIN, data=payload, headers=HEADERS_LOGIN) as response:
                response_text = await response.text()
                _LOGGER.debug("Răspuns autentificare: status=%s, contains_marker=%s",
                             response.status, "Acces online proprietari" in response_text)
                if response.status == 200 and "Acces online proprietari" in response_text:
                    _LOGGER.debug("Autentificare reușită.")
                    self.authenticated = True
                else:
                    raise UpdateFailed("Autentificare eșuată.")
        except UpdateFailed:
            raise
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

    _LOGGER.debug("Coordinator data after first refresh: %s", coordinator.data is not None)

    sensors = [
        EBlocHomeSensor(coordinator),
        EBlocPlatiChitanteSensor(coordinator),
    ]

    # Create one sensor per real meter (skip entries with id_contor == "0")
    index_data = (coordinator.data or {}).get("index") or {}
    for key, meter in index_data.items():
        if isinstance(meter, dict) and meter.get("id_contor") and meter["id_contor"] != "0":
            _LOGGER.debug("Adăugăm senzor contor: key=%s, titlu=%s", key, meter.get("titlu"))
            sensors.append(EBlocContorSensor(coordinator, key, meter))

    _LOGGER.debug("Total senzori creați: %d", len(sensors))
    async_add_entities(sensors)


class EBlocHomeSensor(CoordinatorEntity, SensorEntity):
    """Senzor pentru `AjaxGetHomeApInfo.php`."""

    _attr_icon = "mdi:account-file"

    def __init__(self, coordinator):
        """Inițializare senzor."""
        super().__init__(coordinator)
        self._attr_name = "Date client"
        self._attr_unique_id = f"{DOMAIN}_client"
        self._attr_suggested_object_id = "e_bloc_date_client"
        self._process_data()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Procesează datele noi de la coordonator."""
        self._process_data()
        self.async_write_ha_state()

    def _process_data(self):
        """Extrage datele din coordinator și setează starea."""
        try:
            coordinator_data = self.coordinator.data or {}
            home_data = coordinator_data.get("home") or {}

            data = {}
            if isinstance(home_data, dict) and home_data:
                data = next(iter(home_data.values()), {}) or {}

            _LOGGER.debug("Home sensor data: datorie=%s, cod_client=%s, ap=%s",
                          data.get("datorie"), data.get("cod_client"), data.get("ap"))

            # Use restanță as state since cod_client can be null
            datorie = data.get("datorie")
            if datorie is not None:
                try:
                    self._attr_native_value = f"{int(datorie) / 100:.2f} RON"
                except (ValueError, TypeError):
                    self._attr_native_value = "Necunoscut"
            else:
                self._attr_native_value = "Necunoscut"

            self._attr_extra_state_attributes = {
                "Cod client": data.get("cod_client") or "Necunoscut",
                "Apartament": data.get("ap") or "Necunoscut",
                "Persoane declarate": data.get("nr_pers_afisat") or "Necunoscut",
                "Restanță de plată": self._safe_money(data.get("datorie")),
                "Ultima zi de plată": data.get("ultima_zi_plata") or "Necunoscut",
                "Contor trimis": "Da" if data.get("contoare_citite") == "1" else "Nu",
                "Începere citire contoare": data.get("citire_contoare_start") or "Necunoscut",
                "Încheiere citire contoare": data.get("citire_contoare_end") or "Necunoscut",
                "Luna cu datoria cea mai veche": data.get("luna_veche") or "Necunoscut",
                "Luna afișată": data.get("luna_afisata") or "Necunoscut",
                "Nivel restanță": data.get("nivel_restanta") or "Necunoscut",
            }
        except Exception as e:
            _LOGGER.error("Eroare la procesarea datelor Home: %s", e)
            if not hasattr(self, '_attr_extra_state_attributes'):
                self._attr_extra_state_attributes = {}

    @staticmethod
    def _safe_money(value):
        """Formatează o valoare monetară (în bani) ca RON."""
        if value is None:
            return "Necunoscut"
        try:
            return f"{int(value) / 100:.2f} RON"
        except (ValueError, TypeError):
            return "Necunoscut"

    @property
    def device_info(self):
        return DEVICE_INFO


class EBlocContorSensor(CoordinatorEntity, SensorEntity):
    """Senzor individual pentru fiecare contor din `AjaxGetIndexContoare.php`."""

    _attr_icon = "mdi:counter"
    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    def __init__(self, coordinator, key, meter_data):
        """Inițializare senzor contor."""
        super().__init__(coordinator)
        self._key = key
        self._contor_id = meter_data.get("id_contor", key)
        titlu = meter_data.get("titlu") or f"Contor {key}"
        self._attr_name = f"Index {titlu}"
        self._attr_unique_id = f"{DOMAIN}_contor_{self._contor_id}"
        self._attr_suggested_object_id = f"e_bloc_index_{titlu.lower().replace(' ', '_').replace('.', '')}"
        self._process_data()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Procesează datele noi de la coordonator."""
        self._process_data()
        self.async_write_ha_state()

    def _process_data(self):
        """Extrage datele din coordinator și setează starea."""
        try:
            coordinator_data = self.coordinator.data or {}
            index_data = coordinator_data.get("index") or {}
            data = index_data.get(self._key) or {}

            index_vechi = (data.get("index_vechi") or "").strip()
            index_nou = (data.get("index_nou") or "").strip()

            # Valorile vin în mii (ex. 1481000 = 1481 mc)
            try:
                index_vechi_val = int(float(index_vechi) // 1000) if index_vechi and index_vechi != "0" else None
            except (ValueError, TypeError):
                index_vechi_val = None

            try:
                index_nou_val = int(float(index_nou) // 1000) if index_nou and index_nou != "0" else None
            except (ValueError, TypeError):
                index_nou_val = None

            # Starea senzorului este indexul nou (cel mai recent)
            if index_nou_val is not None:
                self._attr_native_value = index_nou_val
            elif index_vechi_val is not None:
                self._attr_native_value = index_vechi_val
            else:
                self._attr_native_value = None

            # Atribute suplimentare
            self._attr_extra_state_attributes = {
                "Titlu": data.get("titlu") or "Necunoscut",
                "Index vechi": f"{index_vechi_val} m\u00b3" if index_vechi_val is not None else "Necunoscut",
                "Index nou": f"{index_nou_val} m\u00b3" if index_nou_val is not None else "Necunoscut",
                "Data citire": data.get("data") or "Necunoscut",
                "ID contor": data.get("id_contor") or "Necunoscut",
            }
        except Exception as e:
            _LOGGER.error("Eroare la procesarea datelor contor %s: %s", self._key, e)
            if not hasattr(self, '_attr_extra_state_attributes'):
                self._attr_extra_state_attributes = {}

    @property
    def device_info(self):
        return DEVICE_INFO


class EBlocPlatiChitanteSensor(CoordinatorEntity, SensorEntity):
    """Senzor pentru `AjaxGetPlatiChitanteToti.php`."""

    _attr_icon = "mdi:credit-card-check-outline"

    def __init__(self, coordinator):
        """Inițializare senzor chitanțe."""
        super().__init__(coordinator)
        self._attr_name = "Plăți și chitanțe"
        self._attr_unique_id = f"{DOMAIN}_plati_si_chitante"
        self._attr_suggested_object_id = "e_bloc_plati_si_chitante"
        self._process_data()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Procesează datele noi de la coordonator."""
        self._process_data()
        self.async_write_ha_state()

    def _process_data(self):
        """Extrage datele din coordinator și setează starea."""
        try:
            coordinator_data = self.coordinator.data or {}
            data = coordinator_data.get("receipts") or {}
            numar_chitante = len(data)

            self._attr_native_value = numar_chitante

            atribute = {"Număr total de chitanțe": numar_chitante}
            for idx, chitanta_data in data.items():
                if not isinstance(chitanta_data, dict):
                    continue
                numar = chitanta_data.get("numar", "Necunoscut")
                data_chitanta = chitanta_data.get("data", "Necunoscut")
                suma = chitanta_data.get("suma", "0")
                try:
                    suma_formatata = f"{int(suma) / 100:.2f} RON"
                except (ValueError, TypeError):
                    suma_formatata = "Necunoscut"

                atribute[f"Chitanță {idx}"] = numar
                atribute[f"Data {idx}"] = data_chitanta
                atribute[f"Sumă plătită {idx}"] = suma_formatata

            self._attr_extra_state_attributes = atribute
        except Exception as e:
            _LOGGER.error("Eroare la procesarea datelor chitanțe: %s", e)
            if not hasattr(self, '_attr_extra_state_attributes'):
                self._attr_extra_state_attributes = {}

    @property
    def device_info(self):
        return DEVICE_INFO
