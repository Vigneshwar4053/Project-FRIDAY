"""Activity-only Ollama transport: numeric loopback, no proxy, no redirects."""
from urllib.parse import urlsplit
import urllib.request
from zorvyq.services import DesktopProvider


def validate_endpoint(endpoint):
    parsed=urlsplit(endpoint)
    if (parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.port not in (None,11434)
            or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment):
        raise ValueError('Activity summaries require numeric loopback Ollama on port 11434')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Activity model redirects are refused')


class ActivityProvider(DesktopProvider):
    def _open_request(self,request,timeout):
        if request.full_url!='http://127.0.0.1:11434/api/chat':
            raise ValueError('Activity model endpoint refused')
        return urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(request,timeout=timeout)
