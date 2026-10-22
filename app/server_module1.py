"""Loopback-only pilot server. Project capability tokens are kept out of browser storage."""
import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import domain
from exports import pptx_bytes, report_html, pdf_bytes

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('EMPATHISE_DATA',str(ROOT.parent/'local-data')))
DATA.mkdir(parents=True,exist_ok=True)
TOKEN_PATH=DATA/'admin-token.txt'
if os.environ.get('EMPATHISE_ADMIN_TOKEN'):
    ADMIN=os.environ['EMPATHISE_ADMIN_TOKEN']
elif TOKEN_PATH.is_file(): ADMIN=TOKEN_PATH.read_text().strip()
else:
    ADMIN=secrets.token_urlsafe(24)
    TOKEN_PATH.write_text(ADMIN+'\n');TOKEN_PATH.chmod(0o600)
if len(ADMIN)<16: raise RuntimeError('Use an admin token of at least 16 characters.')
DB=DATA/'research.sqlite3'
LOCK=threading.RLock()

def connect():
    c=sqlite3.connect(DB,timeout=20)
    c.execute('CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS access(hash TEXT PRIMARY KEY, project_id TEXT NOT NULL, role TEXT NOT NULL)')
    return c

def digest(t): return hashlib.sha256(t.encode()).hexdigest()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,status,data,kind='application/json',filename=None):
        raw=json.dumps(data,ensure_ascii=False).encode() if kind=='application/json' else data.encode() if isinstance(data,str) else data
        self.send_response(status)
        for k,v in {'Content-Type':kind,'Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}.items(): self.send_header(k,v)
        if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        self.end_headers();self.wfile.write(raw)
    def principal(self):
        token=self.headers.get('Authorization','').removeprefix('Bearer ')
        if hmac.compare_digest(token.encode(),ADMIN.encode()):return ('owner',None)
        with connect() as c:row=c.execute('SELECT role,project_id FROM access WHERE hash=?',(digest(token),)).fetchone()
        if not row: raise PermissionError('Enter the Module 1 admin token or a project access key.')
        return tuple(row)
    def project(self,pid,write=False,review=False):
        role,allowed=self.principal()
        if role!='owner' and allowed!=pid:raise PermissionError('This key cannot access that project.')
        if write and role=='viewer':raise PermissionError('Viewer keys cannot change research.')
        if review and role not in ['owner','reviewer']:raise PermissionError('A reviewer or owner key is required.')
        with connect() as c:row=c.execute('SELECT payload FROM projects WHERE id=?',(pid,)).fetchone()
        if not row:raise ValueError('Project not found.')
        return json.loads(row[0]),role
    def do_GET(self):
        try:
            parsed=urlparse(self.path);path=parsed.path
            files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
            if path in files:
                name,kind=files[path];return self.send(200,(ROOT/'public'/name).read_bytes(),kind)
            if path=='/api/config':return self.send(200,{'roles':domain.ROLES,'goals':domain.GOALS,'dimensions':domain.DIMENSIONS,'options':domain.OPTIONS,'version':domain.VERSION,'ai':'Offline pilot; no AI provider configured.'})
            if path=='/api/projects':
                role,pid=self.principal()
                with connect() as c:rows=c.execute('SELECT payload FROM projects'+(' WHERE id=?' if role!='owner' else ''),(pid,) if role!='owner' else ()).fetchall()
                projects=[json.loads(r[0]) for r in rows]
                return self.send(200,{'role':role,'projects':[{'id':p['id'],'title':p['title'],'role':p['intake']['role'],'revision':p['revision']} for p in projects]})
            parts=path.strip('/').split('/')
            if len(parts)>=3 and parts[:2]==['api','projects']:
                p,role=self.project(parts[2])
                if len(parts)==3:
                    return self.send(200,{'project':p,'readiness':domain.readiness(p),'accessRole':role,'publishedIds':[c['id'] for c in domain.published(p)]})
                if len(parts)==4 and parts[3] in ['handoff.json','research.pptx','report.html','report.pdf']:
                    baseline=parse_qs(parsed.query).get('baseline',[None])[0]
                    bundle=domain.export_bundle(p,baseline)
                    if parts[3]=='handoff.json':return self.send(200,bundle,filename='Empathise_Handoff.json')
                    if parts[3]=='research.pptx':return self.send(200,pptx_bytes(bundle),'application/vnd.openxmlformats-officedocument.presentationml.presentation','Empathise_Research.pptx')
                    if parts[3]=='report.pdf':return self.send(200,pdf_bytes(bundle),'application/pdf','Empathise_Research.pdf')
                    return self.send(200,report_html(bundle),'text/html; charset=utf-8','Empathise_Research.html')
            return self.send(404,{'error':'Not found.'})
        except PermissionError as e:return self.send(401,{'error':str(e)})
        except ValueError as e:return self.send(400,{'error':str(e)})
        except Exception as e:
            print('Local GET failed:',type(e).__name__,flush=True)
            return self.send(500,{'error':'Local operation failed. Check dependencies and server terminal.'})
    def do_POST(self):
        try:
            origin=self.headers.get('Origin')
            if origin and origin!='http://'+self.headers.get('Host',''):return self.send(403,{'error':'Origin is not allowed.'})
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=1100000:raise ValueError('Request must be between 1 byte and 1.1 MB.')
            d=json.loads(self.rfile.read(n))
            if not isinstance(d,dict):raise ValueError('Expected an object.')
            path=urlparse(self.path).path
            role,_=self.principal()
            if path=='/api/questionnaire':
                if d.get('role') not in domain.ROLES or d.get('goal') not in domain.GOALS:raise ValueError('Choose a valid audience and goal.')
                return self.send(200,domain.make_session(d['role'],d['goal']))
            if path=='/api/lint':return self.send(200,domain.lint(d.get('question')))
            if path=='/api/projects':
                if role!='owner':raise PermissionError('An owner token is required to create projects.')
                p=domain.new_project(d)
                keys={r:secrets.token_urlsafe(24) for r in ['researcher','reviewer','viewer']}
                with LOCK,connect() as c:
                    c.execute('INSERT INTO projects VALUES (?,?)',(p['id'],json.dumps(p)))
                    for r,k in keys.items():c.execute('INSERT INTO access VALUES (?,?,?)',(digest(k),p['id'],r))
                return self.send(201,{'id':p['id'],'keys':keys,'note':'Save these project keys now. They are shown only once.'})
            parts=path.strip('/').split('/')
            if len(parts)==4 and parts[:2]==['api','projects']:
                action=parts[3]
                needs_review=action in ['review_evidence','review_claim','baseline','delete_source','delete_project']
                with LOCK:
                    p,role=self.project(parts[2],True,needs_review)
                    if type(d.get('revision')) is not int or d['revision']!=p['revision']:
                        return self.send(409,{'error':'This project changed in another window. Reload and retry.'})
                    if action=='delete_project':
                        if role!='owner':raise PermissionError('Only the owner can delete a project.')
                        with connect() as c:
                            c.execute('DELETE FROM access WHERE project_id=?',(p['id'],));c.execute('DELETE FROM projects WHERE id=?',(p['id'],))
                        return self.send(200,{'deleted':True})
                    if action=='import_csv':
                        # Strict text CSV, no formulas evaluated; every row remains a draft source.
                        raw=domain.text(d.get('csv'),'CSV',800000)
                        if d.get('permission') is not True:raise ValueError('Confirm source processing permission.')
                        reader=csv.DictReader(io.StringIO(raw))
                        needed={'title','participant','kind','body','stakeholderId','locator'}
                        if not needed.issubset(reader.fieldnames or []):raise ValueError('Use the supplied CSV headers.')
                        count=0
                        for row in reader:
                            count+=1
                            if count>100:raise ValueError('Import at most 100 rows per batch.')
                            domain.mutate(p,'source',{**row,'permission':True},role)
                        if not count:raise ValueError('The CSV contains no records.')
                        result={'imported':count}
                    else:result=domain.mutate(p,action,d,role)
                    with connect() as c:c.execute('UPDATE projects SET payload=? WHERE id=?',(json.dumps(p),p['id']))
                return self.send(200,{'result':result,'revision':p['revision']})
            return self.send(404,{'error':'Not found.'})
        except PermissionError as e:return self.send(401,{'error':str(e)})
        except (ValueError,TypeError,KeyError) as e:return self.send(400,{'error':str(e)})
        except Exception as e:
            print('Local POST failed:',type(e).__name__,flush=True)
            return self.send(500,{'error':'Local operation failed. See server terminal.'})

if __name__=='__main__':
    connect().close()
    port=int(os.environ.get('PORT','8082'))
    print(f'Empathise AI local pilot: http://localhost:{port}',flush=True)
    print(f'Owner token is saved at {TOKEN_PATH}. Keep it private.',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
