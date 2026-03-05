DOMAIN = "e-bloc"

# Interval implicit de actualizare (în secunde)
DEFAULT_SCAN_INTERVAL = 3600

# URL-uri
URL_LOGIN = "https://www.e-bloc.ro/index.php"
URL_HOME = "https://www.e-bloc.ro/ajax/AjaxGetHomeApInfo.php"
URL_INDEX = "https://www.e-bloc.ro/ajax/AjaxGetIndexContoare.php"
URL_RECEIPTS = "https://www.e-bloc.ro/ajax/AjaxGetPlatiChitanteToti.php"

# Payload-uri implicite pentru autentificare și cereri POST
DEFAULT_USER = ""
DEFAULT_PASS = ""
DEFAULT_ID_ASOC = ""
DEFAULT_ID_AP = ""

PAYLOAD_LOGIN = {
    "pUser": DEFAULT_USER,
    "pPass": DEFAULT_PASS,
    "pIdAsoc": DEFAULT_ID_ASOC,
    "pIdAp": DEFAULT_ID_AP,
}

# Anteturi pentru cererile HTTP
HEADERS_LOGIN = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Referer": URL_LOGIN,
}

HEADERS_POST = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.e-bloc.ro/index.php?page=19&t=1735328869",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
}