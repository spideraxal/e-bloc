import logging
from aiohttp import ClientSession
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from .const import DOMAIN, PAYLOAD_LOGIN, HEADERS_LOGIN, URL_LOGIN
import voluptuous as vol

_LOGGER = logging.getLogger(__name__)


def mask_value(value):
    """Maschează valoarea, afișând doar primele 3 caractere."""
    if not value or len(value) <= 3:
        return value
    return value[:3] + '*' * (len(value) - 3)


class EBlocConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestionarea fluxului de configurare pentru integrarea E-bloc."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Primul pas pentru configurarea utilizatorului."""
        errors = {}

        if user_input is not None:
            # Maschează datele pentru debug
            masked_input = {key: mask_value(value) for key, value in user_input.items()}
            _LOGGER.debug("Validăm datele introduse pentru autentificare: %s", masked_input)

            # Validează datele introduse
            is_valid = await self._validate_credentials(user_input["pUser"], user_input["pPass"])
            if is_valid:
                _LOGGER.debug("Datele sunt valide. Salvăm configurația.")
                return self.async_create_entry(title="E-bloc.ro", data=user_input)
            else:
                _LOGGER.debug("Datele de autentificare sunt invalide.")
                errors["base"] = "invalid_auth"

        # Afișează formularul
        _LOGGER.debug("Afișăm formularul de configurare utilizator.")
        return self.async_show_form(
            step_id="user",
            data_schema=self._get_form_schema(),
            errors=errors,
        )

    async def _validate_credentials(self, username, password):
        """Verifică dacă acreditările sunt valide prin codul de status."""
        async with ClientSession() as session:
            payload = PAYLOAD_LOGIN.copy()
            payload["pUser"] = username
            payload["pPass"] = password

            try:
                async with session.post(URL_LOGIN, data=payload, headers=HEADERS_LOGIN) as response:
                    _LOGGER.debug("Răspuns primit de la server: Status %s", response.status)
                    return response.status == 200
            except Exception as e:
                _LOGGER.error("Eroare la conectarea cu serverul: %s", e)
                return False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Returnează opțiunile configurabile."""
        return EBlocOptionsFlow(config_entry)

    def _get_form_schema(self):
        """Schema formularului de configurare."""
        return vol.Schema(
            {
                vol.Required("pUser"): str,
                vol.Required("pPass"): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Required("pIdAsoc"): str,
                vol.Required("pIdAp"): str,
            }
        )


class EBlocOptionsFlow(config_entries.OptionsFlow):
    """Gestionarea opțiunilor configurabile."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Gestionarea opțiunilor."""
        errors = {}

        if user_input is not None:
            # Maschează datele pentru debug
            masked_input = {key: mask_value(value) for key, value in user_input.items()}
            _LOGGER.debug("Salvăm opțiunile actualizate: %s", masked_input)

            self.hass.config_entries.async_update_entry(self.config_entry, data=user_input)
            return self.async_create_entry(title="", data=user_input)

        # Preluăm datele curente din configurația inițială
        current_data = self.config_entry.data
        masked_data = {key: mask_value(value) for key, value in current_data.items()}
        _LOGGER.debug("Date curente preluate pentru opțiuni: %s", masked_data)

        # Afișăm formularul pentru configurare
        return self.async_show_form(
            step_id="init",
            data_schema=self._get_options_schema(current_data),
            errors=errors,
        )

    def _get_options_schema(self, current_data):
        """Schema formularului de opțiuni."""
        return vol.Schema(
            {
                vol.Optional("pUser", default=current_data.get("pUser", "")): str,
                vol.Optional("pPass", default=current_data.get("pPass", "")): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional("pIdAsoc", default=current_data.get("pIdAsoc", "")): str,
                vol.Optional("pIdAp", default=current_data.get("pIdAp", "")): str,
            }
        )