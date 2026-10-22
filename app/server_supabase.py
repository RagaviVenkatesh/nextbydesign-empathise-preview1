"""ASGI adapter for the unchanged research model, Supabase Auth and Postgres."""
import csv
import io
import json
import os
from pathlib import Path
from urllib.parse import urlparse

# Optional private local configuration; production hosts supply environment variables.
ROOT=Path(__file__).resolve().parent
for line in (ROOT.parent/'.env').read_text().splitlines() if (ROOT.parent/'.env').is_file() else []:
    if line and not line.startswith('#') and '=' in line:
        key,value=line.split('=',1);os.environ.setdefault(key,value)

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
import domain
from exports import pptx_bytes,pdf_bytes,report_html
from supabase_store import SupabaseStore,StoreError

store=SupabaseStore()
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
REVIEW={'review_evidence','review_claim','baseline','delete_source'}

@app.middleware('http')
async def boundary(request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        expected=os.getenv('PUBLIC_ORIGIN',str(request.base_url).rstrip('/'))
        if origin and origin!=expected:return JSONResponse({'error':'Origin is not allowed.'},403)
        try:
            limit=12000000 if request.url.path.endswith('/create') else 1100000
            if int(request.headers.get('content-length','0'))>limit:return JSONResponse({'error':'Request is too large.'},413)
            body=await request.body()
            if len(body)>limit:return JSONResponse({'error':'Request is too large.'},413)
        except ValueError:return JSONResponse({'error':'Invalid request length.'},400)
    response=await call_next(request)
    response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
    return response

@app.exception_handler(StoreError)
async def storage_error(req,e):return JSONResponse({'error':str(e)},e.status)
@app.exception_handler(ValueError)
async def value_error(req,e):return JSONResponse({'error':str(e)},400)
@app.exception_handler(RequestValidationError)
async def input_error(req,e):return JSONResponse({'error':'Invalid request.'},400)

def user(request):
    token=request.headers.get('authorization','').removeprefix('Bearer ')
    return store.identity(token)['id']

def writable(role,action):
    if role=='viewer':raise StoreError(403,'Viewer accounts cannot change research.')
    if action in REVIEW and role not in ('owner','reviewer'):raise StoreError(403,'A reviewer or owner is required.')
    if action=='delete_project' and role!='owner':raise StoreError(403,'Only the owner can delete a project.')

def mutate_document(p,role,uid,action,d):
    writable(role,action)
    if type(d.get('revision')) is not int or d['revision']!=p['revision']:raise StoreError(409,'This project changed. Reload and retry.')
    if action=='delete_project':return {'deleted':True}
    if action=='import_csv':
        raw=domain.text(d.get('csv'),'CSV',800000)
        if d.get('permission') is not True:raise ValueError('Confirm source processing permission.')
        reader=csv.DictReader(io.StringIO(raw))
        if not {'title','participant','kind','body','stakeholderId','locator'}.issubset(reader.fieldnames or []):raise ValueError('Use the supplied CSV headers.')
        count=0
        for row in reader:
            count+=1
            if count>100:raise ValueError('Import at most 100 rows per batch.')
            domain.mutate(p,'source',{**row,'permission':True},uid)
        if not count:raise ValueError('The CSV contains no records.')
        # One HTTP mutation is one revision, even for multi-row imports.
        p['revision']=d['revision']+1
        return {'imported':count}
    return domain.mutate(p,action,d,uid)

@app.get('/api/config')
def config():return {'roles':domain.ROLES,'goals':domain.GOALS,'dimensions':domain.DIMENSIONS,'options':domain.OPTIONS,'version':domain.VERSION,'database':'Supabase','configured':bool(store.secret),'ai':'Template suggestions and scripted practice; no external AI configured.'}

@app.post('/api/login')
def login(d:dict):
    email=domain.text(d.get('email'),'Email',254)
    password=d.get('password')
    if not isinstance(password,str) or not 1<=len(password)<=4096:raise ValueError('Enter a valid password.')
    try:return store.login(email,password)
    except Exception as e:
        if isinstance(e,StoreError):raise
        raise StoreError(503,'Could not reach the sign-in service.')

@app.post('/api/logout')
def logout(request:Request):
    token=request.headers.get('authorization','').removeprefix('Bearer ')
    if token:store.request('/auth/v1/logout','POST',token=token)
    return {'signedOut':True}

@app.get('/api/projects')
def projects(request:Request):return store.listing(user(request))

@app.get('/api/briefs')
def saved_briefs(request:Request):
    uid=user(request)
    if not store.team(uid):raise StoreError(403,'Team membership is required to import questionnaire briefs.')
    rows=store.rows('submissions',{'select':'id,role,goal,answers,planning,challenge,recommendation,completed_at',
        'contact_consent':'eq.true','order':'completed_at.desc','limit':'200'})
    # Contact names/emails are intentionally excluded from research intake.
    return {'briefs':[{'id':r['id'],'role':r['role'],'goal':r['goal'],'answers':r['answers'],
        'planning':(r.get('recommendation') or {}).get('offering',{}).get('planning') or r.get('planning') or {},
        'challenge':r.get('challenge') or '', 'completed_at':r['completed_at']} for r in rows]}

@app.post('/api/questionnaire')
def questionnaire(request:Request,d:dict):
    user(request)
    if d.get('role') not in domain.ROLES or d.get('goal') not in domain.GOALS:raise ValueError('Choose a valid audience and goal.')
    return domain.make_session(d['role'],d['goal'])

@app.post('/api/lint')
def lint(request:Request,d:dict):
    user(request);return domain.lint(d.get('question'))

@app.post('/api/projects',status_code=201)
def create(request:Request,d:dict):
    uid=user(request)
    if not store.team(uid):raise StoreError(403,'Team membership is required to create research projects.')
    p=domain.new_project(d)
    p['consent']['version']='supabase-1';p['createdBy']=uid
    store.rpc('ntd_research_create',{'actor':uid,'document':p})
    return {'id':p['id'],'note':'Project saved in Supabase. Use project membership to grant access.'}

@app.get('/api/projects/{pid}')
def read_project(request:Request,pid:str):
    p,role=store.project(pid,user(request))
    return {'project':p,'readiness':domain.readiness(p),'accessRole':role,'publishedIds':[c['id'] for c in domain.published(p)]}

@app.get('/api/projects/{pid}/{format}')
def export(request:Request,pid:str,format:str,baseline:str=None):
    p,role=store.project(pid,user(request))
    bundle=domain.export_bundle(p,baseline)
    if format=='handoff.json':data=json.dumps(bundle,ensure_ascii=False).encode();kind='application/json';name='Empathise_Handoff.json'
    elif format=='research.pptx':data=pptx_bytes(bundle);kind='application/vnd.openxmlformats-officedocument.presentationml.presentation';name='Empathise_Research.pptx'
    elif format=='report.pdf':data=pdf_bytes(bundle);kind='application/pdf';name='Empathise_Research.pdf'
    elif format=='report.html':data=report_html(bundle);kind='text/html';name='Empathise_Research.html'
    else:raise StoreError(404,'Export not found.')
    return Response(data,media_type=kind,headers={'Content-Disposition':f'attachment; filename="{name}"'})

@app.post('/api/projects/{pid}/{action}')
def mutation(request:Request,pid:str,action:str,d:dict):
    uid=user(request);p,role=store.project(pid,uid)
    if action=='members':
        if role!='owner':raise StoreError(403,'Only the project owner can manage members.')
        email=domain.text(d.get('email'),'Member email',254)
        member_role=d.get('role')
        if member_role not in ('researcher','reviewer','viewer','revoke'):raise ValueError('Invalid member role.')
        store.rpc('ntd_research_member',{'actor':uid,'pid':pid,'member_email':email,'member_role':member_role})
        return {'saved':True}
    expected=p['revision']
    result=mutate_document(p,role,uid,action,d)
    ok=store.rpc('ntd_research_commit',{'actor':uid,'pid':pid,'expected_revision':expected,'document':p,'operation':action})
    if not ok:raise StoreError(409,'This project changed in another window. Reload and retry.')
    return {'result':result,'revision':p['revision']}

@app.get('/')
def index():return FileResponse(ROOT/'public/index.html')
app.mount('/',StaticFiles(directory=ROOT/'public'),name='static')
