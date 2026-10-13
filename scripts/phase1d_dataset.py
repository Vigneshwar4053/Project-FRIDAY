"""Opt-in bounded official documentation collection; inert data, never indexing.

Run review first, inspect its pinned licenses and selection, then collect.
Only Python's standard library and the existing deterministic text chunker
are used. No downloaded code, embedded instruction, link or command is run.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import ssl
import stat
from time import monotonic
from urllib.parse import quote, urlsplit
import uuid
import unicodedata

from friday.intelligence.chunking import TextChunker
from friday.tools.grants import directory_descriptor

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'knowledge/cybersecurity'
MAX_TOTAL = 100_000_000
MAX_FILE = 20_000_000
MAX_DOCUMENTS = 100
TOPICS = ('networking','network_scanning','nmap','web_security','linux_security',
          'vulnerability_management','threat_intelligence','defensive_security')
REPOS = {'wstg': ('OWASP/wstg','LICENSE','CC-BY-SA-4.0','OWASP Foundation and WSTG contributors'),
         'cheatsheets': ('OWASP/CheatSheetSeries','LICENSE.md','CC-BY-SA-4.0','OWASP Foundation and Cheat Sheet Series contributors'),
         'mitre': ('mitre-attack/attack-stix-data','LICENSE.txt','LicenseRef-MITRE-ATTACK','The MITRE Corporation')}
EXTRA_REVIEWS = [
    {'source':'Nmap','url':'https://nmap.org/book/','decision':'deferred',
     'license':'CC-BY-3.0 for the Reference Guide only',
     'license_url':'https://nmap.org/book/man-legal.html',
     'reason':'Reference Guide permission verified; book-wide permission not inferred. Initial collection prioritizes Markdown/JSON. No Nmap book copied.'},
    {'source':'NIST SP 800-115','url':'https://csrc.nist.gov/pubs/sp/800/115/final','decision':'deferred',
     'publication_date':'2008-09','license_url':'https://www.nist.gov/copyrights-disclaimers',
     'reason':'Official final publication identified; government and third-party authors listed. Document-specific permission and PDF processing deferred; no substantial content copied.'},
    {'source':'CISA KEV','url':'https://www.cisa.gov/known-exploited-vulnerabilities-catalog','decision':'skipped',
     'license':None,'reason':'Official catalog/policy requests unavailable during review; catalog-specific license could not be verified. No catalog downloaded.'},
    {'source':'Wireshark','url':'https://www.wireshark.org/docs/','decision':'deferred',
     'license':'GPL-2.0 documentation grant',
     'license_url':'https://www.wireshark.org/docs/wsug_html_chunked/AppGPL.html',
     'reason':'User Guide explicitly includes a GPL v2 document license. Initial Markdown/JSON scope retained; HTML/source redistribution treatment deferred.'},
    {'source':'Zeek','url':'https://docs.zeek.org/','decision':'skipped',
     'reviewed_redirect':'https://docs.zeek.org/en/current/','license':None,
     'reason':'Official documentation identified; documentation-specific license not verified. Software/Spicy BSD licensing was not treated as a grant for the Book of Zeek.'},
]


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def approved_url(url):
    parsed=urlsplit(url)
    if (parsed.scheme!='https' or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None,443) or parsed.fragment or '\\' in url):
        raise ValueError('Unapproved HTTPS URL')
    if parsed.hostname=='api.github.com':
        valid=any(parsed.path.startswith('/repos/'+repo+'/') for repo,*_ in REPOS.values())
    elif parsed.hostname=='raw.githubusercontent.com':
        valid=any(parsed.path.startswith('/'+repo+'/') for repo,*_ in REPOS.values()) and not parsed.query
    else:valid=False
    if not valid:raise ValueError('Host or publisher path is outside the reviewed source list')
    return parsed


def safe_path(root, relative, *, must_exist=True):
    root_info=root.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise ValueError('Unsafe dataset root')
    path=PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(p in ('..','.') for p in path.parts) or '\\' in relative:
        raise ValueError('Dataset path escape')
    current=root
    for part in path.parts:
        current=current/part
        if not current.exists() and not current.is_symlink():
            if must_exist:raise ValueError('Missing dataset file')
            continue
        info=current.lstat()
        if stat.S_ISLNK(info.st_mode) or (not stat.S_ISDIR(info.st_mode) and
                (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1)):
            raise ValueError('Unsafe dataset file type or link')
    return current


def write_file(relative,data,*,replace=False):
    destination=safe_path(DATASET,relative,must_exist=False)
    with directory_descriptor(destination.parent,create=True) as fd:
        flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW
        temporary=destination.name+'.tmp-'+uuid.uuid4().hex if replace else destination.name
        out=os.open(temporary,flags,0o600,dir_fd=fd)
        with os.fdopen(out,'wb') as stream:
            stream.write(data)
        if replace:os.replace(temporary,destination.name,src_dir_fd=fd,dst_dir_fd=fd)


def write_json(relative,value,*,replace=False):
    write_file(relative,(json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode(),replace=replace)


def read_file(root,relative):
    path=safe_path(root,relative)
    with directory_descriptor(path.parent) as parent:
        fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=parent)
        try:
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>MAX_FILE:
                raise ValueError('Unsafe dataset file identity/size')
            data=bytearray()
            while len(data)<=MAX_FILE:
                block=os.read(fd,min(65536,MAX_FILE+1-len(data)))
                if not block:break
                data.extend(block)
            after=os.fstat(fd)
            entry=os.stat(path.name,dir_fd=parent,follow_symlinks=False)
            identity=lambda info:(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
            if len(data)>MAX_FILE or identity(before)!=identity(after) or identity(before)!=identity(entry):
                raise ValueError('Dataset file changed during validation')
            return bytes(data)
        finally:os.close(fd)


def load_json(relative):
    return json.loads(read_file(DATASET,relative))


def secret_findings(text):
    # Public examples can resemble secrets. Return categories only, never values.
    patterns={'private_key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
              'github_token':r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b',
              'aws_access_key':r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
              'slack_token':r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b',
              'credential_assignment':r'(?im)^\s*(?:password|api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*[\x22\x27]?[A-Za-z0-9/+_=.-]{16,}'}
    return [name for name,pattern in patterns.items() if re.search(pattern,text)]


def valid_content(data,extension,content_type):
    permitted={'.md':{'text/plain','text/markdown'},'.txt':{'text/plain'},
               '.json':{'text/plain','application/json'}}
    if extension not in permitted or content_type not in permitted[extension]:
        raise ValueError('Unsupported document type')
    text=data.decode('utf-8',errors='strict')
    if not text.strip() or any(ord(c)<32 and c not in '\t\r\n' for c in text):
        raise ValueError('Empty or binary document')
    if text.lstrip().lower().startswith(('<!doctype html','<html','#!/')):
        raise ValueError('HTML/login wall or script masquerading as a document')
    if extension=='.json':json.loads(text)
    if secret_findings(text):raise ValueError('Potential secret-like content; rejected without exposing values')
    return text


class Fetcher:
    def __init__(self):
        ledger=DATASET/'reports/download-ledger.json'
        self.ledger=load_json('reports/download-ledger.json') if ledger.exists() else {'downloaded_bytes':0,'requests':[]}

    def fetch(self,url,*,max_bytes=MAX_FILE,types=('application/json','text/plain')):
        parsed=approved_url(url)
        if len(self.ledger['requests'])>=MAX_DOCUMENTS:raise ValueError('Maximum network response count reached')
        remaining=MAX_TOTAL-self.ledger['downloaded_bytes']
        if remaining<=0:raise ValueError('Total download limit reached')
        bound=min(max_bytes,MAX_FILE,remaining)
        item={'url':url,'retrieved_at':now(),'bytes':0,'redirects_followed':0}
        self.ledger['requests'].append(item)
        connection=http.client.HTTPSConnection(parsed.hostname,timeout=30,context=ssl.create_default_context())
        try:
            started=monotonic()
            connection.request('GET',parsed.path+('?' + parsed.query if parsed.query else ''),
                               headers={'Accept':'application/json,text/plain','Accept-Encoding':'identity',
                                        'User-Agent':'FRIDAY-reviewed-document-collection/1D'})
            response=connection.getresponse();item['status']=response.status
            if response.status!=200:raise ValueError('Non-200 response; no redirects followed')
            content_type=response.getheader('Content-Type','').split(';')[0].strip().lower()
            item['content_type']=content_type;item['last_modified']=response.getheader('Last-Modified')
            if content_type not in types:raise ValueError('Unsupported response Content-Type')
            if response.getheader('Content-Encoding','identity')!='identity':raise ValueError('Compressed transfers refused')
            declared=response.getheader('Content-Length')
            if declared and int(declared)>bound:raise ValueError('Declared size exceeds download bound')
            data=bytearray()
            while len(data)<bound:
                if monotonic()-started>120:raise ValueError('Download deadline exceeded')
                block=response.read1(min(65536,bound-len(data)))
                if not block:break
                data.extend(block);item['bytes']+=len(block);self.ledger['downloaded_bytes']+=len(block)
                write_json('reports/download-ledger.json',self.ledger,replace=True)
            if len(data)==bound and (declared is None or int(declared)!=bound):
                raise ValueError('Response reached bound without verified end')
            if declared and int(declared)!=len(data):raise ValueError('Incomplete transfer')
            item['sha256']=sha(data)
            return bytes(data),dict(item)
        except Exception as error:
            item['rejected_reason']=str(error);raise
        finally:
            connection.close();write_json('reports/download-ledger.json',self.ledger,replace=True)


def raw_url(repo,commit,path):
    return 'https://raw.githubusercontent.com/'+repo+'/'+commit+'/'+quote(path,safe='/')


def review():
    fetcher=Fetcher();review={'reviewed_at':now(),'sources':{},'additional_sources':EXTRA_REVIEWS}
    for key,(repo,license_path,license_name,publisher) in REPOS.items():
        metadata,meta=fetcher.fetch('https://api.github.com/repos/'+repo+'/commits/master',max_bytes=1_000_000)
        commit=json.loads(metadata)['sha']
        if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('Invalid upstream commit')
        write_file('sources/'+key+'-commit.json',metadata)
        tree_bytes,tree_meta=fetcher.fetch('https://api.github.com/repos/'+repo+'/git/trees/'+commit+'?recursive=1',max_bytes=2_000_000)
        tree=json.loads(tree_bytes)
        if tree.get('truncated'):raise ValueError('Incomplete upstream tree')
        write_file('sources/'+key+'-tree.json',tree_bytes)
        license_url=raw_url(repo,commit,license_path)
        license_bytes,license_meta=fetcher.fetch(license_url,max_bytes=100_000,types=('text/plain',))
        license_text=valid_content(license_bytes,'.txt','text/plain')
        marker='Attribution-ShareAlike 4.0 International' if key!='mitre' else 'royalty-free license'
        if marker not in license_text:raise ValueError('License text does not match review')
        stored_license='sources/'+key+'-LICENSE.txt'
        write_file(stored_license,license_bytes)
        paths={entry['path']:entry for entry in tree['tree'] if entry['type']=='blob'}
        candidates=[]
        if key=='wstg':
            selections=[('2-Introduction',('web_security','vulnerability_management')),
                        ('3-The_OWASP_Testing_Framework',('web_security','vulnerability_management','defensive_security')),
                        ('01-Information_Gathering/01-',('web_security','network_scanning')),
                        ('01-Information_Gathering/02-',('web_security','network_scanning')),
                        ('02-Configuration_and_Deployment_Management/01-',('web_security','networking','network_scanning','defensive_security')),
                        ('02-Configuration_and_Deployment_Management/02-',('web_security','defensive_security')),
                        ('02-Configuration_and_Deployment_Management/09-',('web_security','linux_security','defensive_security')),
                        ('09-Weak_Cryptography/03-',('web_security','networking','defensive_security')),
                        ('05-Authorization/02-',('web_security','defensive_security')),
                        ('3-The_OWASP_Testing_Framework/1-',('web_security','vulnerability_management'))]
            for fragment,tags in selections:
                matching=sorted(path for path in paths if path.startswith('document/') and path.endswith('.md') and fragment in path)
                if matching:candidates.append({'path':matching[0],'topics':tags})
        elif key=='cheatsheets':
            chosen={'Authentication_Cheat_Sheet.md':('web_security','defensive_security'),
                    'Authorization_Cheat_Sheet.md':('web_security','defensive_security'),
                    'Input_Validation_Cheat_Sheet.md':('web_security','defensive_security'),
                    'SQL_Injection_Prevention_Cheat_Sheet.md':('web_security','defensive_security'),
                    'Logging_Cheat_Sheet.md':('web_security','defensive_security'),
                    'Transport_Layer_Security_Cheat_Sheet.md':('networking','web_security','defensive_security'),
                    'Docker_Security_Cheat_Sheet.md':('linux_security','defensive_security'),
                    'Vulnerable_Dependency_Management_Cheat_Sheet.md':('vulnerability_management','defensive_security'),
                    'Vulnerability_Disclosure_Cheat_Sheet.md':('vulnerability_management','defensive_security'),
                    'Network_Segmentation_Cheat_Sheet.md':('networking','defensive_security'),
                    'OS_Command_Injection_Defense_Cheat_Sheet.md':('web_security','linux_security','defensive_security')}
            for name,tags in chosen.items():
                path='cheatsheets/'+name
                if path in paths:candidates.append({'path':path,'topics':tags})
        else:
            # ICS bundles are substantially smaller than the Enterprise bundle.
            # Choose only a current pinned bundle declared below the per-file cap.
            candidates_json=[entry for path,entry in paths.items() if path=='ics-attack/ics-attack.json' and entry.get('size',MAX_FILE+1)<=MAX_FILE]
            if candidates_json:candidates.append({'path':candidates_json[0]['path'],
                'topics':('threat_intelligence','defensive_security','network_scanning','vulnerability_management'),
                'subset':True})
        review['sources'][key]={'repo':repo,'publisher':publisher,'commit':commit,
            'commit_date':json.loads(metadata)['commit']['committer']['date'],
            'license':license_name,'license_url':license_url,'license_path':stored_license,
            'license_sha256':sha(license_bytes),'license_retrieved_at':license_meta['retrieved_at'],
            'metadata_transfers':[meta,tree_meta],'candidates':candidates,
            'permission':'Public reproduction permitted subject to retained attribution/license; no endorsement implied.'}
    write_json('reports/source-review.json',review)
    print(json.dumps({key:{'commit':source['commit'],'license':source['license'],
                           'selected_paths':[c['path'] for c in source['candidates']]}
                      for key,source in review['sources'].items()},indent=2))


def mitre_subset(raw,license_text):
    bundle=json.loads(raw)
    if bundle.get('type')!='bundle' or not isinstance(bundle.get('objects'),list):
        raise ValueError('Unsupported ATT&CK bundle')
    active=[obj for obj in bundle['objects'] if not obj.get('revoked') and not obj.get('x_mitre_deprecated')]
    techniques=[obj for obj in active if obj.get('type')=='attack-pattern' and
                any(term in obj.get('name','').lower() for term in ('network','service','discovery','exploit','remote','account'))][:12]
    mitigations=[obj for obj in active if obj.get('type')=='course-of-action'][:8]
    selected=techniques+mitigations
    ids={obj['id'] for obj in selected}
    relations=[obj for obj in active if obj.get('type')=='relationship' and obj.get('source_ref') in ids and obj.get('target_ref') in ids]
    support=[obj for obj in active if obj.get('type') in {'identity','marking-definition'}]
    objects=support+selected+relations
    subset={'type':'bundle','id':'bundle--'+str(uuid.uuid5(uuid.NAMESPACE_URL,sha(raw)+'friday-bounded-ics-subset')),
            'objects':objects,'friday_provenance':{'upstream_bundle_id':bundle['id'],
            'upstream_sha256':sha(raw),'selection':'Up to 12 discovery/network/exploitation techniques, 8 mitigations and matching relationships; original identity/marking objects retained.',
            'license_and_copyright':license_text,'domain':'ics-attack','complete_coverage':False}}
    rendered=['# MITRE ATT&CK ICS — bounded defensive subset',license_text]
    for obj in selected:
        refs=[ref.get('external_id') for ref in obj.get('external_references',[]) if ref.get('source_name')=='mitre-attack']
        rendered.extend(['## '+obj.get('name',obj['id'])+' ('+', '.join(filter(None,refs))+')',
                         obj.get('description',''),'STIX ID: '+obj['id'],
                         'Version: '+str(obj.get('x_mitre_version','unknown')),
                         'Modified: '+obj.get('modified','unknown')])
    return subset,'\n\n'.join(rendered)+'\n',len(selected)


def collect():
    review=load_json('reports/source-review.json');fetcher=Fetcher();documents=[];rejections=[];seen=set()
    old=load_json('manifest.json') if (DATASET/'manifest.json').exists() else {'documents':[]}
    previous={doc['source_url']:doc for doc in old['documents']}
    for key,source in review['sources'].items():
        license_text=read_file(DATASET,source['license_path']).decode('utf-8')
        if sha(license_text.encode())!=source['license_sha256']:raise ValueError('Reviewed license changed')
        for choice in source['candidates']:
            url=raw_url(source['repo'],source['commit'],choice['path'])
            if url in previous:
                record=previous[url]
                data=read_file(DATASET,record['original_path'])
                if sha(data)!=record['sha256']:raise ValueError('Existing approved document changed')
                record['upstream_git_blob_sha1']=hashlib.sha1(('blob '+str(len(data))+'\0').encode()+data).hexdigest()
                seen.add(record['sha256']);documents.append(record);continue
            try:
                data,transfer=fetcher.fetch(url,types=('text/plain','application/json','text/markdown'))
                extension=Path(choice['path']).suffix
                text=valid_content(data,extension,transfer['content_type'])
                fingerprint=sha(data)
                tree=load_json('sources/'+key+'-tree.json')
                expected=next(entry['sha'] for entry in tree['tree'] if entry['path']==choice['path'])
                blob_sha=hashlib.sha1(('blob '+str(len(data))+'\0').encode()+data).hexdigest()
                if blob_sha!=expected:raise ValueError('Pinned Git blob integrity mismatch')
                if fingerprint in seen:raise ValueError('Duplicate document')
                seen.add(fingerprint)
                name=key+'-'+fingerprint[:16]
                original='sources/'+name+extension
                title=next((line.lstrip('# ').strip() for line in text.splitlines() if line.startswith('# ')),Path(choice['path']).stem.replace('_',' '))
                record={'id':name,'publisher':source['publisher'],'title':title,
                    'source_url':url,'repository_url':'https://github.com/'+source['repo'],
                    'upstream_path':choice['path'],'upstream_git_blob_sha1':blob_sha,'document_version':source['commit'],
                    'publication_date':None,'repository_commit_date':source['commit_date'],
                    'retrieved_at':transfer['retrieved_at'],'sha256':fingerprint,'size_bytes':len(data),
                    'content_type':transfer['content_type'],'original_path':original,'topics':list(choice['topics']),
                    'license':{'name':source['license'],'url':source['license_url'],
                        'path':source['license_path'],'sha256':source['license_sha256']},
                    'trust':'verified_official_publisher','untrusted_document_text':True,
                    'redirects_followed':0,'indexed':False,'embedded':False,
                    'attribution':source['publisher']+'; original source and license retained. No publisher endorsement.'}
                if choice.get('subset'):
                    subset,normalized,selected_count=mitre_subset(data,license_text)
                    valid_content(normalized.encode(),'.txt','text/plain')
                    write_json('processed/'+name+'-subset.json',subset)
                    record.update(title='MITRE ATT&CK ICS — bounded defensive subset',
                        selected_technique_and_mitigation_count=selected_count,domain='ics-attack',
                        dataset_version=next((obj.get('x_mitre_attack_spec_version') for obj in subset['objects'] if obj.get('x_mitre_attack_spec_version')),None),
                        subset_path='processed/'+name+'-subset.json',subset_sha256=sha((json.dumps(subset,indent=2,ensure_ascii=False)+'\n').encode()),
                        original_bundle_objects=len(json.loads(data)['objects']),
                        original_bundle_is_archival_only=True,
                        changes='Bounded STIX selection and text rendering; source objects and MITRE license retained.')
                else:
                    normalized=unicodedata.normalize('NFC',text.removeprefix('\ufeff').replace('\r\n','\n').replace('\r','\n'))
                    record['changes']='UTF-8 BOM/newlines/Unicode NFC normalized; attribution prepended; original bytes retained.'
                attribution='# Source attribution\n\n'+record['attribution']+'\nSource: '+url+'\nLicense: '+source['license']+' ('+source['license_url']+')\nVersion: '+source['commit']+'\nChanges: '+record['changes']+'\n\n'
                normalized=attribution+normalized
                valid_content(normalized.encode(),'.txt','text/plain')
                processed='processed/'+name+'.txt';write_file(original,data);write_file(processed,normalized.encode())
                record.update(processed_path=processed,processed_sha256=sha(normalized.encode()),
                    processed_size_bytes=len(normalized.encode()),
                    estimated_chunks=len(TextChunker().chunks('inventory',fingerprint,normalized)))
                documents.append(record)
                print('collected',key,title,len(data),flush=True)
            except (ValueError,UnicodeError) as error:
                rejections.append({'url':url,'reason':str(error)})
    active_urls={doc['source_url'] for doc in documents}
    excluded=old.get('excluded_documents',[])+[{**doc,'exclusion_reason':'Deprecated/moved-page stub replaced with substantive content from the same reviewed commit.'} for doc in old['documents'] if doc['source_url'] not in active_urls]
    manifest={'schema_version':1,'created_at':now(),'limits':{'max_download_bytes':MAX_TOTAL,'max_documents':MAX_DOCUMENTS,'max_document_bytes':MAX_FILE},
              'source_review_path':'reports/source-review.json','documents':documents,'rejected_documents':rejections,
              'excluded_documents':excluded,'downloaded_document_count':len(documents)+len(excluded),
              'additional_sources':review['additional_sources'],'document_count':len(documents),
              'original_document_bytes':sum(d['size_bytes'] for d in documents),
              'total_download_bytes_including_review_metadata':fetcher.ledger['downloaded_bytes'],
              'estimated_chunks':sum(d['estimated_chunks'] for d in documents),
              'chunk_policy':'utf8-paragraph-v1:1536:192; inventory estimate only; no ingestion/index/embedding',
              'topics':{topic:[d['id'] for d in documents if topic in d['topics']] for topic in TOPICS},
              'coverage_limits':['Networking is transport/TLS context, not a complete TCP/IP curriculum.',
                  'Linux security is container/command-injection context, not general Linux hardening.',
                  'ATT&CK selection is ICS, not a complete Enterprise ATT&CK corpus.',
                  'Nmap documentation remains deferred; no nmap topic documents in this initial subset.'],
              'security':{'documents_are_untrusted':True,'execute_contents':False,'follow_document_links':False,
                          'personal_memory_accessed':False,'embeddings_created':False,'indexed':False}}
    write_json('manifest.json',manifest,replace=True)
    write_file('reports/SHA256SUMS.txt',(''.join(d['sha256']+'  '+d['original_path']+'\n'+d['processed_sha256']+'  '+d['processed_path']+'\n' for d in documents+excluded)).encode(),replace=True)
    write_json('reports/inventory.json',{key:manifest[key] for key in ('document_count','downloaded_document_count','original_document_bytes','total_download_bytes_including_review_metadata','estimated_chunks','topics','coverage_limits')},replace=True)
    write_file('reports/ATTRIBUTION.txt',('\n\n'.join(d['title']+'\n'+d['attribution']+'\n'+d['source_url']+'\n'+d['license']['name']+'\n'+d['license']['url'] for d in documents+excluded)+'\n').encode(),replace=True)
    print(json.dumps(validate(DATASET),indent=2))


def validate(root):
    # This function has no transport, execution, model, SQLite or memory calls.
    manifest=json.loads(read_file(root,'manifest.json'))
    seen=set();total=0;processed_seen=set();required=('publisher','title','source_url','license','retrieved_at','publication_date','document_version','sha256','topics')
    documents=manifest['documents']
    if len(documents)>MAX_DOCUMENTS or manifest['document_count']!=len(documents):raise ValueError('Document count limit/inventory mismatch')
    for document in documents:
        if any(key not in document for key in required):raise ValueError('Missing provenance')
        approved_url(document['source_url'])
        if not re.fullmatch('[0-9a-f]{40}',document['document_version']):raise ValueError('Unpinned document version')
        if '/'+document['document_version']+'/' not in document['source_url']:raise ValueError('Source/version mismatch')
        if document['publisher'] not in [spec[3] for spec in REPOS.values()]:raise ValueError('Unknown official publisher')
        key=document['id'].split('-',1)[0]
        if key not in REPOS:raise ValueError('Unknown source identity')
        repo,license_path,license_name,publisher=REPOS[key]
        if (document['publisher']!=publisher or document['license']['name']!=license_name or
                document['source_url']!=raw_url(repo,document['document_version'],document['upstream_path']) or
                document['license']['url']!=raw_url(repo,document['document_version'],license_path)):
            raise ValueError('Publisher/source/license provenance mismatch')
        if document['redirects_followed'] or document['indexed'] or document['embedded']:raise ValueError('Unexpected redirect/index/embedding')
        if not set(document['topics'])<=set(TOPICS):raise ValueError('Unknown topic')
        datetime.fromisoformat(document['retrieved_at'])
        original=safe_path(root,document['original_path']);data=read_file(root,document['original_path'])
        if len(data)>MAX_FILE or len(data)!=document['size_bytes'] or sha(data)!=document['sha256']:raise ValueError('Original integrity/size failure')
        if sha(data) in seen:raise ValueError('Duplicate original document')
        seen.add(sha(data));total+=len(data)
        blob_sha=hashlib.sha1(('blob '+str(len(data))+'\0').encode()+data).hexdigest()
        if blob_sha!=document['upstream_git_blob_sha1']:raise ValueError('Upstream Git blob integrity failure')
        valid_content(data,original.suffix,document['content_type'])
        processed=read_file(root,document['processed_path'])
        valid_content(processed,'.txt','text/plain')
        if sha(processed)!=document['processed_sha256'] or len(processed)!=document['processed_size_bytes']:raise ValueError('Processed integrity failure')
        if sha(processed) in processed_seen:raise ValueError('Duplicate processed document')
        processed_seen.add(sha(processed))
        if document['source_url'] not in processed.decode() or document['license']['url'] not in processed.decode():raise ValueError('Missing processed attribution')
        license_bytes=read_file(root,document['license']['path'])
        if sha(license_bytes)!=document['license']['sha256']:raise ValueError('License integrity failure')
        if 'subset_path' in document:
            subset=read_file(root,document['subset_path'])
            if sha(subset)!=document['subset_sha256']:raise ValueError('Subset integrity failure')
            parsed=json.loads(subset)
            if parsed['friday_provenance']['upstream_sha256']!=document['sha256'] or license_bytes.decode() not in parsed['friday_provenance']['license_and_copyright']:raise ValueError('Subset provenance/license failure')
        estimate=len(TextChunker().chunks('inventory',document['sha256'],processed.decode()))
        if estimate!=document['estimated_chunks']:raise ValueError('Chunk inventory mismatch')
    for excluded in manifest.get('excluded_documents',[]):
        for key,hash_key in (('original_path','sha256'),('processed_path','processed_sha256')):
            data=read_file(root,excluded[key])
            if sha(data)!=excluded[hash_key]:raise ValueError('Excluded archive integrity failure')
    ledger=json.loads(read_file(root,'reports/download-ledger.json'))
    if total!=manifest['original_document_bytes'] or ledger['downloaded_bytes']!=manifest['total_download_bytes_including_review_metadata'] or ledger['downloaded_bytes']>MAX_TOTAL:raise ValueError('Total download/inventory mismatch')
    if sum(request['bytes'] for request in ledger['requests'])!=ledger['downloaded_bytes']:raise ValueError('Transfer ledger mismatch')
    for request in ledger['requests']:
        approved_url(request['url'])
        if request['redirects_followed'] or request['bytes']>MAX_FILE:raise ValueError('Transfer limit/redirect failure')
    if sum(d['estimated_chunks'] for d in documents)!=manifest['estimated_chunks']:raise ValueError('Total chunk inventory mismatch')
    for topic in TOPICS:
        if manifest['topics'][topic]!=[d['id'] for d in documents if topic in d['topics']]:raise ValueError('Topic inventory mismatch')
    for path in root.rglob('*'):
        safe_path(root,str(path.relative_to(root)))
        if path.is_file() and (path.stat().st_mode&0o111):raise ValueError('Executable dataset file')
        if path.is_file():
            valid_content(read_file(root,str(path.relative_to(root))),path.suffix,
                          'application/json' if path.suffix=='.json' else 'text/plain')
    return {'passed':True,'validated_at':now(),'documents':len(documents),'original_bytes':total,
            'total_download_bytes':ledger['downloaded_bytes'],'estimated_chunks':manifest['estimated_chunks'],
            'duplicates':0,'redirects_followed':0,'secret_pattern_matches':0,'indexing_performed':False,
            'secret_check_limits':'Known secret patterns and strict official-public-source selection; no claim of exhaustive secret detection.',
            'topics':{topic:len(manifest['topics'][topic]) for topic in TOPICS}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('review','collect','validate'))
    parser.add_argument('--phase1c-report',required=True)
    args=parser.parse_args()
    report_path=Path(args.phase1c_report)
    if report_path.parent.parent!=ROOT/'data/intelligence/phase1c-benchmarks':raise ValueError('Only the synthetic prerequisite report is allowed')
    report=json.loads(report_path.read_bytes())
    if not all(report.get(key) for key in ('synthetic_only','correctness_passed','ram_target_met','resource_safety_passed')):
        raise ValueError('Phase 1C correctness/resource prerequisite failed')
    with directory_descriptor(DATASET,create=True):pass
    for folder in ('sources','processed','reports'):
        with directory_descriptor(DATASET/folder,create=True):pass
    if args.action=='review':review()
    elif args.action=='collect':collect()
    else:
        report=validate(DATASET);write_json('reports/validation.json',report,replace=True);print(json.dumps(report,indent=2))


if __name__=='__main__':main()
