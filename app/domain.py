"""Local pilot research model. No external AI calls or automated verification."""
import copy
import hashlib
import math
import re
import secrets
import time

from legacy.server import ROLES, GOALS, DIMENSIONS, OPTIONS, BANK, make_session
from legacy.offerings import select_offering

VERSION = '1.0.0'
SOURCE_TYPES = ['PRIMARY_INTERVIEW', 'PRIMARY_OBSERVATION', 'SECONDARY', 'SYNTHETIC_PRACTICE', 'DEMO']
CATEGORIES = ['PAIN_POINT', 'WORKAROUND', 'EMOTIONAL_TRIGGER', 'CONTRADICTION', 'OBSERVATION']
VIEWS = ['Says', 'Thinks', 'Does', 'Feels', 'Pains', 'Gains', 'Persona', 'Journey']

def uid():
    return secrets.token_urlsafe(12)

def text(value, name, limit=2000, required=True):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'{name} must be text of 1–{limit} characters.' if required else f'Invalid {name}.')
    if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        raise ValueError(f'{name} contains unsupported control characters.')
    return value.strip()

def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer from {low} to {high}.')
    return value

def intake(data):
    if not isinstance(data, dict): raise ValueError('Intake must be an object.')
    role, goal, answers = data.get('role'), data.get('goal'), data.get('answers')
    if role not in ROLES or goal not in GOALS: raise ValueError('Choose an existing audience and goal.')
    if not isinstance(answers, list) or len(answers) != 6 or any(x is not None and (type(x) is not int or not 0 <= x <= 3) for x in answers):
        raise ValueError('Keep the six existing dimension answers from 0–3, or null for unknown.')
    planning = data.get('planning', {})
    if not isinstance(planning, dict): raise ValueError('Planning must be an object.')
    cleaned = {}
    for k, choices in {'stage':['Not sure yet','Exploring a broad topic','Have assumptions','Have some user insights','Have ideas','Have a prototype'], 'scope':['One team','Founder cohort','One venture'], 'format':['Open to recommendations','Online','In person','Hybrid']}.items():
        cleaned[k] = planning.get(k, choices[0])
        if cleaned[k] not in choices: raise ValueError('Invalid planning ' + k)
    for k in ['users_confirmed', 'narrow_test']:
        cleaned[k] = planning.get(k, False)
        if type(cleaned[k]) is not bool: raise ValueError('Invalid planning ' + k)
    for k in ['participants','available_hours','timing','budget']:
        cleaned[k] = text(planning.get(k,''), k, 200, False)
    return {'role':role, 'goal':goal, 'answers':answers, 'planning':cleaned}

def new_project(data):
    d = intake(data)
    if data.get('consent') is not True: raise ValueError('Confirm permission to store this project context locally.')
    title = text(data.get('title'), 'Project name', 120)
    challenge = text(data.get('challenge'), 'Challenge', 1500)
    reference = text(data.get('originBriefId',''), 'Origin brief reference', 120, False)
    return {'id':uid(), 'version':VERSION, 'created':time.time(), 'revision':1, 'title':title,
        'challenge':challenge, 'intake':d, 'originBriefId':reference,
        'offering':select_offering(d['role'],d['goal'],d['answers'],d['planning']),
        'mode':'Daily workspace', 'assumptions':[], 'stakeholders':[], 'scripts':[], 'practice':[],
        'sources':[], 'evidence':[], 'claims':[], 'baselines':[], 'baselineSequence':0, 'audit':[],
        'consent':{'projectContext':True,'at':time.time(),'version':'pilot-1'}}

def find(items, item_id):
    for item in items:
        if item['id'] == item_id: return item
    raise ValueError('Record does not exist in this project.')

def usable(p, evidence):
    s = find(p['sources'], evidence['sourceId'])
    return evidence['review'] == 'accepted' and s['kind'] in ['PRIMARY_INTERVIEW','PRIMARY_OBSERVATION'] and s['permission'] is True

def published(p):
    return [c for c in p['claims'] if c['review']=='accepted' and c['evidenceIds'] and all(usable(p,find(p['evidence'],i)) for i in c['evidenceIds'])]

def readiness(p):
    valid = [e for e in p['evidence'] if usable(p,e)]
    ids = {e['sourceId'] for e in valid}
    interviews = {s['participant'] for s in p['sources'] if s['id'] in ids and s['kind']=='PRIMARY_INTERVIEW'}
    represented = {s['stakeholderId'] for s in p['sources'] if s['id'] in ids}
    target = sum(s['target'] for s in p['stakeholders'])
    high = [a for a in p['assumptions'] if a['risk']=='High']
    covered = {i for e in valid for i in e['assumptionIds']}
    claims = published(p)
    draft_claims = len(p['claims'])
    metrics = {'interviewVolume':{'numerator':len(interviews),'denominator':target},
        'stakeholderCoverage':{'numerator':len(represented),'denominator':len(p['stakeholders'])},
        'criticalAssumptionCoverage':{'numerator':sum(a['id'] in covered for a in high),'denominator':len(high)},
        'evidenceDensity':{'numerator':len(claims),'denominator':draft_claims}}
    ratios = [min(1,m['numerator']/m['denominator']) if m['denominator'] else 0 for m in metrics.values()]
    score = round(100*sum(ratios)/4)
    gaps = []
    if not p['stakeholders']: gaps.append('Set stakeholder groups and interview targets.')
    for s in p['stakeholders']:
        actual = len({src['participant'] for src in p['sources'] if src['id'] in ids and src['stakeholderId']==s['id'] and src['kind']=='PRIMARY_INTERVIEW'})
        if actual < s['target']: gaps.append(f"{s['label']}: {actual}/{s['target']} interview participants with reviewed evidence.")
    if not high: gaps.append('Identify critical assumptions or document why none apply in the review note.')
    for a in high:
        if a['id'] not in covered: gaps.append('Critical assumption has no reviewed primary evidence: '+a['text'])
    if not claims: gaps.append('Accept at least one claim linked to reviewed primary evidence.')
    if len(claims) < draft_claims: gaps.append('Some synthesis cards remain hypotheses or have ineligible evidence.')
    return {'score':score, 'metrics':metrics, 'gaps':gaps, 'eligibleClaims':len(claims),
        'method':'pilot-1: equal 25% weights; missing denominators score zero; heuristic, not validated research quality.'}

def lint(question):
    q = text(question,'Interview question',2000)
    warnings = []
    if re.search(r'\b(would you|will you|could you imagine|do you think you|wouldn.t|don.t you|surely|obviously)\b',q,re.I): warnings.append('Potential leading or future hypothetical wording.')
    if q.lower().startswith(('do you','did you','is ','are ','have you','would ','will ','can you')): warnings.append('Closed opening; consider asking for a specific recent example.')
    return {'warnings':warnings, 'rewrite':'Walk me through the last time you dealt with this situation. What happened, what did you do, and what made it difficult?',
        'note':'Pattern checks only. Context and facilitator judgement are required.'}

def mutate(p, action, d, actor):
    if not isinstance(d,dict): raise ValueError('Action data must be an object.')
    result = {}
    if action=='assumption':
        risk = d.get('risk','High')
        if risk not in ['High','Low']: raise ValueError('Risk must be High or Low.')
        a={'id':uid(),'text':text(d.get('text'),'Assumption'),'risk':risk,'origin':'USER_HYPOTHESIS'}
        p['assumptions'].append(a); result=a
    elif action=='stakeholder':
        label=text(d.get('label'),'Stakeholder label',120)
        if any(s['label'].casefold()==label.casefold() for s in p['stakeholders']): raise ValueError('Stakeholder label already exists.')
        s={'id':uid(),'label':label,'target':integer(d.get('target',3),'Target',1,50)}
        p['stakeholders'].append(s);result=s
    elif action=='scripts':
        a=find(p['assumptions'],d.get('assumptionId'))
        questions=[f"Tell me about the last time you encountered the situation behind this assumption: {a['text']}", 'What did you do, and what tools or workarounds did you use?', 'What happened next, and what was the consequence?']
        s={'id':uid(),'assumptionId':a['id'],'questions':questions,'method':'Offline template suggestion; review before interviewing.'}
        p['scripts'].append(s);result=s
    elif action=='script_edit':
        s=find(p['scripts'],d.get('id'))
        qs=d.get('questions')
        if not isinstance(qs,list) or not 1<=len(qs)<=12: raise ValueError('Provide 1–12 questions.')
        s['questions']=[text(q,'Question',2000) for q in qs];result=s
    elif action=='practice':
        q=text(d.get('question'),'Practice question',2000)
        feedback=lint(q)
        response=('I cannot predict a future purchase. Ask about my last experience.' if feedback['warnings'] else 'In this fictional exercise, I last reconciled invoices on Friday. I compared paper bills with a spreadsheet and had to call a colleague about a mismatch.')
        turn={'id':uid(),'kind':'SYNTHETIC_PRACTICE','question':q,'response':response,'feedback':feedback,'method':'Scripted exercise; not a live AI persona or real participant.'}
        p['practice'].append(turn);result=turn
    elif action=='source':
        kind=d.get('kind')
        if kind not in SOURCE_TYPES: raise ValueError('Invalid source type.')
        if d.get('permission') is not True: raise ValueError('Confirm permission to store and analyse this source.')
        body=text(d.get('body'),'Source text',100000)
        sid=d.get('stakeholderId')
        if sid: find(p['stakeholders'],sid)
        if kind.startswith('PRIMARY') and not sid: raise ValueError('Choose a stakeholder group for primary evidence.')
        participant=text(d.get('participant'),'Participant pseudonym or source label',120)
        s={'id':uid(),'kind':kind,'title':text(d.get('title'),'Source title',160),'body':body,
            'participant':participant,'stakeholderId':sid or '', 'permission':True,
            'locator':text(d.get('locator',''),'Source location or timestamp',300,False),
            'hash':hashlib.sha256(body.encode()).hexdigest(),'created':time.time()}
        p['sources'].append(s);result=s
    elif action=='evidence':
        s=find(p['sources'],d.get('sourceId'))
        start=integer(d.get('start'),'Passage start',0,len(s['body'])-1)
        end=integer(d.get('end'),'Passage end',start+1,len(s['body']))
        if end-start>1500: raise ValueError('Select a passage of at most 1500 characters.')
        category=d.get('category')
        if category not in CATEGORIES: raise ValueError('Invalid evidence category.')
        aids=d.get('assumptionIds',[])
        if not isinstance(aids,list): raise ValueError('Assumption references must be a list.')
        for i in aids: find(p['assumptions'],i)
        e={'id':uid(),'sourceId':s['id'],'start':start,'end':end,'quote':s['body'][start:end], 'category':category,
            'assumptionIds':list(dict.fromkeys(aids)),'review':'draft','reviewer':'','reviewNote':''}
        p['evidence'].append(e);result=e
    elif action=='review_evidence':
        e=find(p['evidence'],d.get('id'))
        status=d.get('status')
        if status not in ['draft','accepted','rejected']: raise ValueError('Invalid review status.')
        e.update(review=status,reviewer=actor,reviewNote=text(d.get('note'),'Review note',1500));result=e
    elif action=='claim':
        view=d.get('view')
        if view not in VIEWS: raise ValueError('Invalid synthesis view.')
        ids=d.get('evidenceIds',[])
        if not isinstance(ids,list): raise ValueError('Evidence references must be a list.')
        for i in ids: find(p['evidence'],i)
        c={'id':uid(),'text':text(d.get('text'),'Claim',1500),'view':view,'evidenceIds':list(dict.fromkeys(ids)),
            'review':'draft','reviewNote':'','reviewer':'',
            'stage':text(d.get('stage',''),'Journey stage or persona name',120,False),
            'interpretation':view in ['Thinks','Feels','Gains','Persona'] or d.get('interpretation') is True}
        p['claims'].append(c);result=c
    elif action=='review_claim':
        c=find(p['claims'],d.get('id'))
        status=d.get('status')
        if status not in ['draft','accepted','rejected']: raise ValueError('Invalid review status.')
        if status=='accepted' and (not c['evidenceIds'] or any(not usable(p,find(p['evidence'],i)) for i in c['evidenceIds'])):
            raise ValueError('Accept claims only after every linked passage is accepted primary evidence. Practice, demo and secondary sources remain hypotheses.')
        c.update(review=status,reviewNote=text(d.get('note'),'Review note',1500),reviewer=actor);result=c
    elif action=='baseline':
        kind=d.get('kind','research')
        if kind not in ['research','learning']: raise ValueError('Choose research or learning baseline.')
        note=text(d.get('note'),'Facilitator rationale',1500)
        r=readiness(p)
        if kind=='research' and not published(p): raise ValueError('A research baseline requires at least one accepted claim with primary evidence.')
        if kind=='research' and r['gaps'] and d.get('override') is not True: raise ValueError('Resolve gaps or explicitly acknowledge them with a facilitator rationale.')
        snap=copy.deepcopy({k:v for k,v in p.items() if k not in ['baselines','audit']})
        p['baselineSequence']=p.get('baselineSequence',0)+1
        b={'id':uid(),'number':p['baselineSequence'],'kind':kind,'created':time.time(),'reviewer':actor,'note':note,
            'readiness':r,'snapshot':snap,'module2Implemented':False}
        p['baselines'].append(b);result={'id':b['id'],'number':b['number']}
    elif action=='mode':
        if d.get('mode') not in ['Live workshop','Daily workspace']: raise ValueError('Invalid mode.')
        p['mode']=d['mode']
    elif action=='delete_source':
        source=find(p['sources'],d.get('id'))
        eids={e['id'] for e in p['evidence'] if e['sourceId']==source['id']}
        p['sources']=[s for s in p['sources'] if s['id']!=source['id']]
        p['evidence']=[e for e in p['evidence'] if e['id'] not in eids]
        p['claims']=[c for c in p['claims'] if not eids.intersection(c['evidenceIds'])]
        # A withdrawn source must not survive inside a previously frozen snapshot.
        p['baselines']=[b for b in p['baselines'] if not any(s['id']==source['id'] for s in b['snapshot']['sources'])]
        result={'withdrawnSource':source['id'],'note':'Linked claims and affected baselines removed. Delete previously downloaded copies separately.'}
    else: raise ValueError('Unknown action.')
    if any(len(p[k])>500 for k in ['sources','evidence','claims','assumptions','practice']): raise ValueError('Pilot record limit reached. Split this research into smaller projects.')
    p['revision']+=1
    p['audit'].append({'at':time.time(),'action':action,'actor':actor})
    return result

def export_bundle(p, baseline_id=None):
    if baseline_id:
        b=find(p['baselines'],baseline_id)
        out=copy.deepcopy(b['snapshot'])
        baseline={k:v for k,v in b.items() if k!='snapshot'}
    else:
        out=copy.deepcopy({k:v for k,v in p.items() if k not in ['baselines','audit']})
        baseline=None
    out['readiness']=readiness(out)
    out['publishedClaims']=published(out)
    out['baseline']=baseline
    out['schemaVersion']='empathise-handoff-1.0'
    out['module2Implemented']=False
    out['status']='Reviewed research baseline' if baseline and baseline['kind']=='research' else 'Learning baseline' if baseline else 'Working research draft'
    return out
