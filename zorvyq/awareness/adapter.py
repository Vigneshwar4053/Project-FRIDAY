"""Narrow read-only ActivityWatch API. Numeric loopback, no proxies/redirects."""
from datetime import timedelta
import http.client
import json
import math
from urllib.parse import quote, urlencode, urlsplit
from .store import utc, stamp

class Unavailable(Exception):
    """Fixed-category failure, with no event or response contents."""

class ActivityWatch:
    def __init__(self, endpoint='http://127.0.0.1:5600', timeout=2):
        parsed=urlsplit(endpoint)
        if (parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.port!=5600
                or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment):
            raise ValueError('Only http://127.0.0.1:5600 is supported')
        if not 0 < timeout <= 5:raise ValueError('Finite timeout required')
        self.timeout=timeout

    def _get(self,path):
        conn=http.client.HTTPConnection('127.0.0.1',5600,timeout=self.timeout)
        try:
            conn.request('GET','/api/0/'+path,headers={'Accept':'application/json','Host':'127.0.0.1:5600'})
            response=conn.getresponse()
            if response.status!=200:raise Unavailable('activitywatch_unavailable')
            raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise Unavailable('activitywatch_response_limit')
            return json.loads(raw)
        except (OSError,ValueError,http.client.HTTPException):
            raise Unavailable('activitywatch_unavailable') from None
        finally:conn.close()

    def buckets(self):
        value=self._get('buckets/')
        if type(value) is not dict or len(value)>100:raise Unavailable('activitywatch_schema')
        for key,row in value.items():
            if (type(key) is not str or not 1<=len(key)<=200 or type(row) is not dict
                    or row.get('type') not in ('currentwindow','afkstatus','web.tab.current')):
                # Unrelated buckets are ignored, never exposed as arbitrary endpoints.
                continue
        return {k:v for k,v in value.items() if isinstance(k,str) and len(k)<=200 and isinstance(v,dict)
                and v.get('type') in ('currentwindow','afkstatus','web.tab.current')}

    def events(self,bucket,start,end):
        if not isinstance(bucket,str) or not 1<=len(bucket)<=200:raise ValueError('Invalid bucket')
        value=self._get('buckets/'+quote(bucket,safe='')+'/events?'+urlencode(dict(start=stamp(start),end=stamp(end),limit=512)))
        if type(value) is not list or len(value)>=512:raise Unavailable('activitywatch_event_limit')
        result=[]
        try:
            for r in value:
                if (type(r) is not dict or type(r.get('id')) is not int or type(r.get('data')) is not dict
                        or type(r.get('duration')) not in (int,float) or not math.isfinite(r['duration'])
                        or not 0<=r['duration']<=86400*31):raise ValueError()
                at=utc(r['timestamp']);finish=at+timedelta(seconds=r['duration'])
                if finish>utc(end)+timedelta(seconds=5):raise ValueError()
                result.append(dict(id=r['id'],start=at,end=finish,data=r['data']))
        except (ValueError,KeyError,TypeError,OverflowError):raise Unavailable('activitywatch_schema') from None
        return sorted(result,key=lambda r:(r['start'],r['id']))
