import os,json,sqlite3,secrets,time,hashlib,hmac
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
ROOT=Path(__file__).parent
DB=os.environ.get('NTD_DATABASE',str(ROOT/'submissions.sqlite3'))
TOKEN=os.environ.get('NTD_ADMIN_TOKEN','')
ROLES=['Corporate professional','Student','Startup founder/team','Investor/incubator','HR/L&D','Corporate management','Institution management']
GOALS=['Build innovation skills','Understand a problem','Improve an experience','Explore new ideas','Test a concept','Align a team']
DIMENSIONS=['Challenge focus','Understanding of people','Desired outcome','Participant involvement','Access to feedback','Follow-through capacity']
OPTIONS=[['No challenge chosen','Broad topic','Specific situation','Focused challenge with boundaries'],['People affected unclear','Group identified','Examples or observations available','Direct user insights available'],['Unsure','General aspiration','Clear session output','Output linked to a next decision'],['Participants unknown','One perspective available','Relevant team identified','Diverse perspectives and an owner'],['No access identified','Access uncertain','Existing feedback or potential access','Users available for feedback'],['No next step identified','Interest in continuing','Owner or resources likely','Owner and capacity for an experiment']]
BANK={
'Corporate professional':['How clearly can you describe the experience your team wants to improve?','What do you know about the customers or employees affected?','Who can contribute to the session?'],
'Student':['How focused is your course, project or venture challenge?','What have you learned from people affected by your challenge?','Who will work with you on this challenge?'],
'Startup founder/team':['How clearly have you defined the user problem behind your idea?','What evidence do you have about your intended users?','Who will help develop and test your ideas?'],
'Investor/incubator':['How focused is the challenge for your venture or founder cohort?','What user insights can participating founders bring?','Who from the ventures or investment team will participate?'],
'HR/L&D':['How focused is the employee experience or learning challenge?','What have you heard directly from employees?','Which employee perspectives can participate?'],
'Corporate management':['How focused is the challenge your teams need to explore?','What evidence is available from frontline people or customers?','Which functions and decision-makers can participate?'],
'Institution management':['How focused is the student, faculty or staff challenge?','What have you learned from the people affected?','Which institutional perspectives can participate?']}
ALT=['Choose the statement that best reflects your current position.','Thinking about your next session, which statement fits best?']
def connection():
 c=sqlite3.connect(DB);c.execute('CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY, created REAL, payload TEXT)');return c
def make_session(role,goal):
 seed=secrets.randbelow(2)
 variants=[f'For your {role.lower()} context, how focused is the challenge you want to bring?', 'How much have you learned about the needs and experiences of the people affected?', 'How clearly have you defined the outcome you want from this session?', 'How ready is your participant group to contribute different perspectives?']
 prompts=[BANK[role][0] if seed==0 else variants[0],BANK[role][1] if seed==0 else variants[1],'What would make this session valuable?' if seed==0 else variants[2],BANK[role][2] if seed==0 else variants[3], 'Can you access people who can give feedback on ideas?' if goal!='Build innovation skills' else 'Can participants bring feedback or examples from real people?', 'Who can support a small next step after the session?']
 return {'id':secrets.token_urlsafe(18),'role':role,'goal':goal,'questions':[{'id':str(i),'dimension':DIMENSIONS[i],'prompt':p,'hint':ALT[seed],'options':OPTIONS[i]} for i,p in enumerate(prompts)]}
def recommend(scores,goal):
 total=sum(scores)
 title=('Design Thinking capability workshop' if goal==GOALS[0] else 'Challenge exploration workshop' if scores[0]<2 or total<=5 else 'Problem framing and ideation workshop' if total<=10 else 'Focused Design Thinking sprint' if total<=14 else 'Prototype and user-feedback sprint')
 flags=[]
 if scores[0]<2:flags.append('Start by choosing and framing one focused challenge.')
 if scores[3]<2:flags.append('Confirm participants and include relevant perspectives before scheduling.')
 if scores[4]<2:flags.append('Arrange user access before promising user testing; otherwise plan an internal prototype review.')
 if scores[5]<2:flags.append('Identify an owner for follow-through and a realistic next experiment.')
 learning=goal==GOALS[0]
 steps=['Prepare a real challenge, relevant examples and a participant group.','Practise understanding people and framing a useful problem.' if learning else 'Explore the people affected and agree on a focused problem.','Practise ideation and build a rough prototype.' if learning else 'Generate ideas, select one concept and create a rough prototype.','Reflect on learning and choose where to apply the methods.' if learning else ('Gather user feedback and agree on the next experiment.' if scores[4]>=2 else 'Plan how to obtain user feedback and agree on the next experiment.')]
 return {'title':title,'total':total,'dimensions':dict(zip(DIMENSIONS,scores)),'preparation':flags,'roadmap':steps,'outputs':['Shared methods and a practice prototype','Personal application plan'] if learning else ['Focused problem statement','Prioritised concept','Prototype or prototype plan','Next experiment and owner'],'ai':'Optional AI support: synthesise non-sensitive notes, explore ideas or draft rough prototypes. People guide the decisions.','note':'Initial routing guidance, not an audit or a validated organisational assessment. Your team will refine the scope before proposing a session.'}
SESSIONS={};LIMITS={}
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,status,data,kind='application/json'):
  raw=json.dumps(data).encode() if kind=='application/json' else data
  self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','SAMEORIGIN' if self.path.startswith('/api') else '');self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  if self.path=='/api/config':return self.send(200,{'roles':ROLES,'goals':GOALS})
  if self.path=='/api/admin/submissions':
   supplied=self.headers.get('Authorization','').removeprefix('Bearer ')
   if not TOKEN or not hmac.compare_digest(supplied,TOKEN):return self.send(401,{'error':'Authorised team access required.'})
   with connection() as c: rows=c.execute('SELECT id,created,payload FROM submissions ORDER BY created DESC LIMIT 200').fetchall()
   return self.send(200,[{'id':r[0],'created':r[1],**json.loads(r[2])} for r in rows])
  files={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/style.css':'style.css','/admin':'admin.html'}
  if self.path not in files:return self.send(404,{'error':'Not found'})
  f=ROOT/'public'/files[self.path];return self.send(200,f.read_bytes(),{'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css'}[f.suffix])
 def do_POST(self):
  try:
   size=int(self.headers.get('Content-Length','0'))
   if size<1 or size>16000:raise ValueError('Request size is invalid.')
   origin=self.headers.get('Origin');expected=os.environ.get('NTD_PUBLIC_ORIGIN')
   if origin and origin!=(expected or 'http://'+self.headers.get('Host','')):return self.send(403,{'error':'Origin is not allowed.'})
   key=self.client_address[0];now=time.time();LIMITS[key]=[t for t in LIMITS.get(key,[]) if now-t<60]
   if len(LIMITS[key])>=30:return self.send(429,{'error':'Please wait a minute before trying again.'})
   LIMITS[key].append(now)
   data=json.loads(self.rfile.read(size))
   if self.path=='/api/session':
    if data.get('role') not in ROLES or data.get('goal') not in GOALS:raise ValueError('Choose your role and goal.')
    for sid,(s,t) in list(SESSIONS.items()):
     if now-t>7200:del SESSIONS[sid]
    s=make_session(data['role'],data['goal']);SESSIONS[s['id']]=(s,now);return self.send(200,s)
   if self.path!='/api/recommendation':return self.send(404,{'error':'Not found'})
   entry=SESSIONS.get(data.get('sessionId',''))
   if not entry or now-entry[1]>7200:raise ValueError('Your session expired. Please start again.')
   s=entry[0];scores=data.get('answers')
   if not isinstance(scores,list) or len(scores)!=6 or any(type(v)!=int or not 0<=v<=3 for v in scores):raise ValueError('Please answer every question.')
   result=recommend(scores,s['goal']);response={'recommendation':result}
   if data.get('save'):
    if data.get('consent') is not True:raise ValueError('Consent is required to share your brief.')
    contact=data.get('contact',{});email=contact.get('email','').strip();name=contact.get('name','').strip()
    if not name or len(name)>120 or '@' not in email or len(email)>254:raise ValueError('Enter your name and a valid email address.')
    clean={k:str(contact.get(k,'')).strip()[:1500] for k in ['name','email','organisation','challenge','timing','format']}
    sid=s['id'];payload={'role':s['role'],'goal':s['goal'],'answers':scores,'contact':clean,'recommendation':result,'consent':{'accepted':True,'version':'1.0','at':now}}
    with connection() as c:c.execute('INSERT OR IGNORE INTO submissions VALUES (?,?,?)',(sid,now,json.dumps(payload)))
    response['submissionId']=sid
   return self.send(200,response)
  except (ValueError,TypeError,json.JSONDecodeError) as e:return self.send(400,{'error':str(e)})
  except Exception:return self.send(500,{'error':'We could not process this request. Please try again.'})
if __name__=='__main__':
 connection().close();print('NextToDesign questionnaire: http://localhost:'+os.environ.get('PORT','8080'),flush=True);ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','8080'))),Handler).serve_forever()
