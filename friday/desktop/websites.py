"""Owner-specified destinations and aliases. No discovery, model or browser I/O."""
from types import MappingProxyType
import re
from urllib.parse import urlencode, urlsplit

WEBSITES = MappingProxyType({
    'youtube': 'https://www.youtube.com/',
    'linkedin': 'https://www.linkedin.com/in/sameti-thirumani-vigneshwar/',
    'whatsapp': 'https://web.whatsapp.com/',
    'github': 'https://github.com/Vigneshwar4053',
    'pw_study': 'https://www.pw.live/study-v2/study',
    'google': 'https://www.google.com/',
    'stackoverflow': 'https://stackoverflow.com/',
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
    'gatewall': 'pw_study',
    'gatewalla': 'pw_study',
    'my gatewall': 'pw_study',
    'my gatewalla': 'pw_study',
    'google': 'google',
    'stackoverflow': 'stackoverflow',
    'stack overflow': 'stackoverflow',
})
APPROVED_URLS = frozenset(WEBSITES.values())
SEARCH_PROVIDER = 'https://www.google.com/search'
MAX_QUERY_BYTES = 256
MAX_SEARCH_URL_BYTES = 2048
SEARCH_DOMAINS = frozenset(urlsplit(url).hostname for url in WEBSITES.values())


def approved_url(value):
    """Exact, case-sensitive bytes represented as str; no URL normalization."""
    return type(value) is str and value in APPROVED_URLS


def site_destination(name):
    key = SITE_ALIASES.get(name.casefold()) if type(name) is str else None
    return WEBSITES[key] if key is not None else None


def search_url(query):
    """One canonical HTTPS target; query text never becomes launcher arguments."""
    if (type(query) is not str or not query.strip() or
            len(query.encode('utf-8')) > MAX_QUERY_BYTES or
            any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in query)):
        raise ValueError('Search query is empty, oversized or contains controls.')
    # Explicit site operators are restricted to the same reviewed registry.
    for domain in re.findall(r'(?i)site:([^\s]+)', query):
        if domain not in SEARCH_DOMAINS:
            raise ValueError('Search domain is outside the reviewed registry.')
    url = SEARCH_PROVIDER + '?' + urlencode({'q': query})
    if len(url.encode('ascii')) > MAX_SEARCH_URL_BYTES:
        raise ValueError('Encoded search URL is oversized.')
    return url


def site_search_query(alias, query):
    destination = site_destination(alias)
    if destination is None:
        raise ValueError('Search site is not registered; an exact HTTPS URL is required.')
    value = 'site:' + urlsplit(destination).hostname + ' ' + query
    search_url(value)
    return value
