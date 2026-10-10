"""Owner-specified destinations and aliases. No discovery, model or browser I/O."""
from types import MappingProxyType

WEBSITES = MappingProxyType({
    'youtube': 'https://www.youtube.com/',
    'linkedin': 'https://www.linkedin.com/in/sameti-thirumani-vigneshwar/',
    'whatsapp': 'https://web.whatsapp.com/',
    'github': 'https://github.com/Vigneshwar4053',
    'pw_study': 'https://www.pw.live/study-v2/study',
})
SITE_ALIASES = MappingProxyType({
    'youtube': 'youtube',
    'linkedin': 'linkedin',
    'my linkedin': 'linkedin',
    'whatsapp': 'whatsapp',
    'whatsapp web': 'whatsapp',
    'github': 'github',
    'my github': 'github',
    'pw study': 'pw_study',
    'physics wallah': 'pw_study',
    'pw_study': 'pw_study',
})
APPROVED_URLS = frozenset(WEBSITES.values())


def approved_url(value):
    """Exact, case-sensitive bytes represented as str; no URL normalization."""
    return type(value) is str and value in APPROVED_URLS


def site_destination(name):
    key = SITE_ALIASES.get(name.casefold()) if type(name) is str else None
    return WEBSITES[key] if key is not None else None
