"""Portable reviewed research exports; PPTX uses the editable authored template."""
import copy
import html
import io
from pathlib import Path
import re
import textwrap
import xml.etree.ElementTree as ET
import zipfile
from legacy.server import DIMENSIONS, OPTIONS

ROOT=Path(__file__).resolve().parent.parent
A='http://schemas.openxmlformats.org/drawingml/2006/main'
P='http://schemas.openxmlformats.org/presentationml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL='http://schemas.openxmlformats.org/package/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'

def sections(b):
    accepted={c['id'] for c in b['publishedClaims']}
    yield 'Research context', [b['title'],b['status'],b['challenge'],f"Audience: {b['intake']['role']}",f"Goal: {b['intake']['goal']}",
        'Intake score is workshop routing guidance. Research readiness is separate.',
        f"Origin brief: {b.get('originBriefId') or 'Standalone project'}"]
    yield 'Intake preparation answers', [f"Question {i+3} | {name}: "+('Unknown' if b['intake']['answers'][i] is None else OPTIONS[i][b['intake']['answers'][i]]) for i,name in enumerate(DIMENSIONS)] + ['Questions 1 and 2 are the audience and goal shown in the research context. These eight answers guide workshop routing, not research verification.']
    yield 'Research readiness', [f"Pilot heuristic: {b['readiness']['score']}/100",b['readiness']['method'],
        *[f"{k}: {v['numerator']}/{v['denominator']}" for k,v in b['readiness']['metrics'].items()],
        *(b['readiness']['gaps'] or ['No configured gaps detected; facilitator review still required.'])]
    yield 'Assumptions and stakeholder plan', [*[f"{a['risk']} risk hypothesis: {a['text']}" for a in b['assumptions']],
        *[f"{s['label']}: target {s['target']} distinct interview participants" for s in b['stakeholders']]] or ['No assumptions or stakeholder targets recorded.']
    for view in ['Says','Thinks','Does','Feels','Pains','Gains','Persona','Journey']:
        cs=[c for c in b['claims'] if c['view']==view]
        if not cs:continue
        lines=[]
        for c in cs:
            status='REVIEWED PRIMARY SUPPORT' if c['id'] in accepted else 'UNVERIFIED HYPOTHESIS'
            lines += [f"{status} | {c.get('stage') or view}",c['text'],
                'Interpretation; inspect the original context.' if c['interpretation'] else 'Observation or reported experience; inspect the original context.',
                'Evidence IDs: '+(', '.join(c['evidenceIds']) or 'None')]
        yield view,lines
    yield 'Evidence appendix', [f"{e['id']} | source {e['sourceId']} | characters {e['start']}–{e['end']} | {e['review']} | {e['category']}\n{e['quote']}\nReview note: {e['reviewNote']}" for e in b['evidence']] or ['No evidence passages recorded.']
    yield 'Source register', [f"{s['id']} | {s['kind']} | {s['participant']} | {s['title']} | {s['locator']}\nSHA256 {s['hash']}" for s in b['sources']] or ['No sources recorded.']
    yield 'Interview guides', [f"Assumption {s['assumptionId']}\n"+'\n'.join(s['questions']) for s in b['scripts']] or ['No interview guides recorded.']
    baseline=b.get('baseline')
    yield 'Review and next steps', ([f"Baseline {baseline['number']} | {baseline['kind']}",baseline['note']] if baseline else ['Working draft. Lock a reviewed research or learning baseline when appropriate.']) + [
        'Synthetic practice and demonstration material do not count as primary research.',
        'Resolve uncovered stakeholder groups and assumptions before making wider claims.',
        'Define is not implemented. The JSON handoff is portable data for future integration.',
        'Pricing, scope and research recruitment require separate agreement.']

def pages(b):
    result=[]
    for title,paragraphs in sections(b):
        groups=[]
        for para in paragraphs:
            lines=[]
            for line in str(para).splitlines():
                lines.extend(textwrap.wrap(line,width=76,break_long_words=True,replace_whitespace=True) or [''])
            groups.append(lines)
        current=[];number=0
        for group in groups:
            if current and len(current)+len(group)+1>14:
                result.append((title+(' continued' if number else ''),'\n'.join(current).rstrip()));number+=1;current=[]
            while len(group)>14:
                result.append((title+(' continued' if number else ''),'\n'.join(group[:14])));number+=1;group=group[14:]
            current.extend(group+[''])
        if current:result.append((title+(' continued' if number else ''),'\n'.join(current).rstrip()))
    return result

def xml_bytes(root):
    raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    # OPC content type/relationship readers expect a default namespace here.
    if root.tag.startswith('{'+CT+'}') or root.tag.startswith('{'+REL+'}'):
        raw=raw.replace(b'xmlns:ns0=',b'xmlns=').replace(b'<ns0:',b'<').replace(b'</ns0:',b'</')
    return raw

def pptx_bytes(b):
    slides=pages(b)
    with zipfile.ZipFile(ROOT/'templates/research_template_v2.pptx') as src:
        files={f:src.read(f) for f in src.namelist()}
    slide=files['ppt/slides/slide1.xml']
    relpath='ppt/slides/_rels/slide1.xml.rels'
    slide_rels=files.get(relpath)
    # Retain layouts, theme and fonts; each content page has editable text objects.
    files={k:v for k,v in files.items() if not re.fullmatch(r'ppt/slides/slide\d+\.xml',k) and not re.fullmatch(r'ppt/slides/_rels/slide\d+\.xml.rels',k)}
    presentation=ET.fromstring(files['ppt/presentation.xml'])
    ids=presentation.find(f'{{{P}}}sldIdLst')
    if ids is None:ids=ET.SubElement(presentation,f'{{{P}}}sldIdLst')
    ids.clear()
    relationships=ET.fromstring(files['ppt/_rels/presentation.xml.rels'])
    for item in list(relationships):
        if item.get('Type','').endswith('/slide'):relationships.remove(item)
    types=ET.fromstring(files['[Content_Types].xml'])
    for item in list(types):
        if re.fullmatch(r'/ppt/slides/slide\d+\.xml',item.get('PartName','')):types.remove(item)
    for index,(title,body) in enumerate(slides,1):
        root=ET.fromstring(slide)
        mapping={'TITLE':title,'BODY':body,'FOOTER':f"Empathise AI | {b['status']} | {index}/{len(slides)}"}
        for t in root.findall(f'.//{{{A}}}t'):
            for k,v in mapping.items():t.text=(t.text or '').replace('{{'+k+'}}',v)
        files[f'ppt/slides/slide{index}.xml']=xml_bytes(root)
        if slide_rels:
            relationships_for_slide=ET.fromstring(slide_rels)
            if index>1:
                for rel in list(relationships_for_slide):
                    if rel.get('Type','').endswith('/notesSlide'):relationships_for_slide.remove(rel)
            files[f'ppt/slides/_rels/slide{index}.xml.rels']=xml_bytes(relationships_for_slide)
        rid=f'rIdEmpathise{index}'
        ET.SubElement(ids,f'{{{P}}}sldId',{'id':str(255+index),f'{{{R}}}id':rid})
        ET.SubElement(relationships,f'{{{REL}}}Relationship',{'Id':rid,'Type':R+'/slide','Target':f'slides/slide{index}.xml'})
        ET.SubElement(types,f'{{{CT}}}Override',{'PartName':f'/ppt/slides/slide{index}.xml','ContentType':'application/vnd.openxmlformats-officedocument.presentationml.slide+xml'})
    files['ppt/presentation.xml']=xml_bytes(presentation)
    files['ppt/_rels/presentation.xml.rels']=xml_bytes(relationships)
    files['[Content_Types].xml']=xml_bytes(types)
    if 'docProps/app.xml' in files:
        app=ET.fromstring(files['docProps/app.xml'])
        for el in app.iter():
            if el.tag.endswith('}Slides'):el.text=str(len(slides))
        files['docProps/app.xml']=xml_bytes(app)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as dst:
        for name,data in files.items():dst.writestr(name,data)
    return out.getvalue()

def report_html(b):
    e=html.escape
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>Empathise research</title><body><h1>'+e(b['title'])+'</h1>'+''.join('<section><h2>'+e(t)+'</h2>'+''.join('<p>'+e(str(p)).replace('\n','<br>')+'</p>' for p in paras)+'</section>' for t,paras in sections(b))+'</body></html>'

def pdf_bytes(b):
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    # Portable font shipped with ReportLab; project Unicode is preserved in JSON/PPTX.
    font=Path(__import__('reportlab').__file__).parent/'fonts'/'Vera.ttf'
    if 'EmpathiseVera' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('EmpathiseVera',str(font)))
    styles=getSampleStyleSheet()
    for name in ['Normal','Title','Heading1']:styles[name].fontName='EmpathiseVera'
    styles['Normal'].fontSize=10;styles['Normal'].leading=15
    out=io.BytesIO();story=[Paragraph(html.escape(b['title']),styles['Title'])]
    for title,paras in sections(b):
        story.extend([Spacer(1,12),Paragraph(html.escape(title),styles['Heading1'])])
        for p in paras:story.extend([Paragraph(html.escape(str(p)).replace('\n','<br/>'),styles['Normal']),Spacer(1,7)])
    SimpleDocTemplate(out,pagesize=A4,rightMargin=48,leftMargin=48,topMargin=42,bottomMargin=42).build(story)
    return out.getvalue()
