"""Server-only Supabase transport. Secrets never enter page configuration."""
import os
import httpx

class StoreError(Exception):
    def __init__(self,status,message):self.status=status;super().__init__(message)

class SupabaseStore:
    def __init__(self):
        self.url=os.getenv('SUPABASE_URL','https://rlnpziwjrforgsbxljwi.supabase.co').rstrip('/')
        self.public=os.getenv('SUPABASE_PUBLISHABLE_KEY','sb_publishable_C2AlHEtuI2ykJh9IgqtGrQ_k3lv-P3a')
        self.secret=os.getenv('SUPABASE_SECRET_KEY','')
        self.client=httpx.Client(timeout=25)
    def request(self,path,method='GET',body=None,token=None,params=None):
        key=self.public if token else self.secret
        if not key:raise StoreError(503,'Complete the database setup and run Configure Supabase.command first.')
        headers={'apikey':key,'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        elif key.startswith('eyJ'):headers['Authorization']='Bearer '+key
        try:r=self.client.request(method,self.url+path,headers=headers,json=body,params=params)
        except httpx.HTTPError:raise StoreError(503,'Could not reach Supabase. Check your connection.')
        if not r.is_success:
            if r.status_code in (401,403):raise StoreError(401 if token else 403,'Sign in again or check your project access.')
            try:code=r.json().get('code')
            except ValueError:code=None
            if code=='42501':raise StoreError(403,'You no longer have permission for this operation.')
            if code=='P0001' and path.endswith('ntd_research_member'):
                raise StoreError(400,r.json().get('message','Check the member account.'))
            raise StoreError(503,'Supabase operation failed. Check the Module 1 database migration and server configuration.')
        return r.json() if r.content else None
    def identity(self,token):
        if not token:raise StoreError(401,'Sign in with your team email and password.')
        return self.request('/auth/v1/user',token=token)
    def login(self,email,password):
        # Passwords and refresh tokens are never written to disk or logs.
        r=self.client.post(self.url+'/auth/v1/token',params={'grant_type':'password'},headers={'apikey':self.public},json={'email':email,'password':password})
        if not r.is_success:raise StoreError(401,'Sign-in failed. Check your email and password.')
        d=r.json();return {'access_token':d['access_token'],'expires_in':d['expires_in']}
    def rows(self,table,params):return self.request('/rest/v1/'+table,params=params)
    def team(self,uid):return bool(self.rows('team_members',{'user_id':'eq.'+uid,'select':'user_id'}))
    def project(self,pid,uid):
        rows=self.rows('ntd_research_members',{'project_id':'eq.'+pid,'user_id':'eq.'+uid,'select':'role'})
        if not rows:raise StoreError(403,'This account does not have access to that project.')
        projects=self.rows('ntd_research_projects',{'id':'eq.'+pid,'select':'payload'})
        if not projects:raise StoreError(404,'Project not found.')
        return projects[0]['payload'],rows[0]['role']
    def listing(self,uid):
        # Paginate memberships as well as projects; Supabase caps each response.
        memberships=[]
        for offset in range(0,100000,500):
            batch=self.rows('ntd_research_members',{'user_id':'eq.'+uid,'select':'project_id,role','order':'project_id','limit':'500','offset':str(offset)})
            memberships.extend(batch)
            if len(batch)<500:break
        projects=[]
        for m in memberships:
            p,_=self.project(m['project_id'],uid)
            projects.append({'id':p['id'],'title':p['title'],'role':p['intake']['role'],'revision':p['revision']})
        return {'role':'owner' if self.team(uid) else 'member','projects':projects}
    def rpc(self,name,body):return self.request('/rest/v1/rpc/'+name,'POST',body)
