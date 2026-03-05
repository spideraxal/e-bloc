import logging
from aiohttp import ClientSession
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from .const import DOMAIN, HEADERS_LOGIN, URL_LOGIN
import voluptuous as vol

_LOGGER = logging.getLogger(__name__)


def _mask_value(value):
    """Maschează valoarea, afișând doar primele 3 caractere."""
    if not isinstance(value, str):
        return value
    if len(value) <= 3:
        return value
    return value[:3] + '*' * (len(value) - 3)


def _get_form_schema(defaults=None):
    """Schema formularului de configurare."""
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required("pUser", default=d.get("pUser", "")): str,
            vol.Required("pPass", default=d.get("pPass", "")): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required("pIdAsoc", default=d.get("pIdAsoc", "")): str,
            vol.Required("pIdAp", default=d.get("pIdAp", "")): str,
        }
    )


async def _validate_credentials(username, password):
    """Verifică dacă acreditările sunt valide prin codul de status."""
    async with ClientSession() as session:
        payload = {"pUser": username, "pPass": password}
        try:
            async with session.post(URL_LOGIN, data=payload, headers=HEADERS_LOGIN) as response:
                _LOGGER.debug("Răspuns primit de la server: Status %s", response.status)
                return response.status == 200
        except Exception as e:
            _LOGGER.error("Eroare la conectarea cu serverul: %s", e)
            return False


class EBlocConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestionarea fluxului de configurare pentru integrarea E-bloc."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Primul pas pentru configurarea utilizatorului."""
        errors = {}

        if user_input is not None:
            masked_input = {k: _mask_value(v) for k, v in user_input.items()}
            _LOGGER.debug("Validăm datele introduse: %s", masked_input)

            if await _validate_credentials(user_input["pUser"], user_input["pPass"]):
                return self.async_create_entry(title="E-bloc.ro", data=user_input)
            errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="user",
            data_schema=_get_form_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Reconfigurarea integrării existente."""
        errors = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            masked_input = {k: _mask_value(v) for k, v in user_input.items()}
            _LOGGER.debug("Reconfigurare – validăm datele: %s", masked_input)

            if await _validate_credentials(user_input["pUser"], user_input["pPass"]):
                return self.async_update_reload_and_abort(
                    entry,
                    data=user_input,
                )
            errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_get_form_schema(dict(entry.data)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Returnează opțiunile configurabile."""
        return EBlocOptionsFlow()


class EBlocOptionsFlow(config_entries.OptionsFlow):
    """Gestionarea opțiunilor configurabile."""

    async def async_step_init(self, user_input=None):
        """Gestionarea opțiunilor."""
        errors = {}

        if user_input is not None:
            masked_input = {k: _mask_value(v) for k, v in user_input.items()}
            _LOGGER.debug("Salvăm opțiunile actualizate: %s", masked_input)

            self.hass.config_entries.async_update_entry(self.config_entry, data=user_input)
            return self.async_create_entry(title="", data=user_input)

        current_data = dict(self.config_entry.data)
        masked_data = {k: _mask_value(v) for k, v in current_data.items()}
        _LOGGER.debug("Date curente: %s", masked_data)

        return self.async_show_form(
            step_id="init",
            data_schema=_get_form_schema(current_data),
            errors=errors,
        )