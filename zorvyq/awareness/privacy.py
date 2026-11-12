"""Data minimization before persistence. Never copy upstream data wholesale."""
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit, unquote

SENSITIVE=re.compile(r'password|passwd|token|secret|authorization|oauth|sign.?in|log.?in|auth|bank|health|medical|patient|clinic|hospital|vault|1password|bitwarden|lastpass|private browsing|incognito|search|query|reset|session|credential|api.?key|access.?key|verify|recover|account|payment|finance|credit|checkout',re.I)
NAMES={'code':'VS Code','firefox':'Firefox','gnome-terminal':'Terminal','org.gnome.nautilus':'File Manager'}
CATEGORIES={'code':'Programming','firefox':'Browsing','gnome-terminal':'Terminal','org.gnome.nautilus':'Files'}
WEBSITE_CATEGORIES={'github.com':'Programming','gitlab.com':'Programming',
    'stackoverflow.com':'Programming','docs.python.org':'Programming',
    'youtube.com':'Entertainment','youtu.be':'Entertainment','coursera.org':'Education',
    'edx.org':'Education','nptel.ac.in':'Education',
    'wikipedia.org':'Research','arxiv.org':'Research','reddit.com':'Social media',
    'instagram.com':'Social media','linkedin.com':'Work'}

def normalize_domain(value):
    if type(value) is not str or len(value)>253:raise ValueError('Invalid domain')
    value=value.lower().rstrip('.').encode('idna').decode('ascii')
    if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',value):
        raise ValueError('Use an exact website domain')
    return value

def safe_title(value):
    if type(value) is not str or len(value)>300 or SENSITIVE.search(value) or any(not c.isprintable() for c in value):return ''
    # Titles resembling credential assignments, URLs or bearer strings are omitted.
    if re.search(r'https?://|\b\w+\s*[=:]\s*\S+|[A-Za-z0-9_-]{32,}',value):return ''
    return value

def excluded(value,p):
    return any(s.casefold() in value.casefold() for s in p['exclusions'])

def browser_metadata(data,p):
    if not p['browser'] or data.get('incognito') is not False:return None
    if SENSITIVE.search(str(data.get('title',''))) or excluded(str(data.get('title','')),p):return None
    raw=data.get('url')
    if type(raw) is not str or len(raw)>4096:return None
    if SENSITIVE.search(unquote(raw)) or excluded(raw,p):return None
    try:
        u=urlsplit(raw);host=(u.hostname or '').encode('idna').decode().lower().rstrip('.')
        if u.scheme not in ('https','http') or not host or u.username or u.password or u.port not in (None,80,443):return None
        try:ipaddress.ip_address(host);return None
        except ValueError:pass
        # Owner approves domains as a positive scope, not just an incomplete deny list.
        if not any(host==d or host.endswith('.'+d) for d in p['domains']):return None
        if any(not c.isprintable() for c in raw) or re.search(r'[A-Za-z0-9_-]{32,}',unquote(u.path)):return None
        url=urlunsplit((u.scheme,host,u.path,'','')) if p['urls'] else ''
    except (ValueError,UnicodeError):return None
    return dict(domain=host,url=url,title=safe_title(data.get('title','')) if p['titles'] else '')
