"""Versioned offering rules. Durations are proposal standards, not assessment facts."""
import json
from pathlib import Path
RULE_VERSION="2.0"
CATALOG=json.loads((Path(__file__).parent/"catalog.json").read_text())
def select_offering(role,goal,scores,context=None):
 context=context or {}
 known=[x for x in scores if x is not None]
 total=sum(known) if len(known)==6 else None
 reasons=[];gaps=[]
 learning=goal=="Build innovation skills"
 if learning: code="capability";reasons.append("The primary goal is methods learning, so capability training takes priority over the total.")
 elif scores[0] is None or total is None:code="clarify";reasons.append("Missing preparation information requires clarification before final routing.")
 elif scores[0]<2 or total<=5:code="explore";reasons.append("The challenge needs exploration before solution development.")
 elif total<=10:code="frame";reasons.append("Available preparation supports problem framing and concept selection.")
 elif total<=14:code="sprint";reasons.append("The team can develop a focused concept and rough prototype with preparation.")
 else:code="feedback";reasons.append("Preparation supports a prototype and feedback sprint, subject to confirmed user access.")
 profile=CATALOG["audiences"][role]
 offer=dict(CATALOG["formats"][code]);offer["code"]=code
 if code=="capability" and role=="Student":offer.update(days=3,hours=18)
 # An available prototype permits a focused feedback workshop only after readiness checks.
 if not learning and total is not None and scores[0]>=2 and scores[3]>=2 and scores[4]==3 and context.get("users_confirmed") is True and context.get("stage")=="Have a prototype" and context.get("narrow_test") is True:
  offer=dict(CATALOG["formats"]["existing_feedback"]);offer["code"]="existing_feedback";reasons.append("A prepared prototype and narrow test question allow a focused feedback workshop.")
 access=scores[4]==3 and context.get("users_confirmed") is True
 if not learning and code=="feedback" and offer["code"]=="feedback" and not access:
  offer=dict(CATALOG["formats"]["sprint"]);offer["code"]="sprint"
  reasons.append("Live feedback is not confirmed. Start with a prototype sprint and feedback preparation.")
 if scores[0] is None or scores[0]<2:gaps.append("Confirm one focused challenge and its boundaries.")
 if scores[3] is None or scores[3]<2:gaps.append("Confirm participants and relevant perspectives.")
 if not access:gaps.append("Confirm feedback contributors and recruitment before scheduling live testing.")
 if scores[5] is None or scores[5]<2:gaps.append("Identify an owner and capacity for a next experiment.")
 if context.get("scope")=="Founder cohort":gaps.append("Confirm shared learning versus separate venture tracks. Quote venture sprints separately.")
 schedule=f'{offer["days"]} days / {offer["hours"]} facilitated hours'
 if context.get("format")=="Online":schedule=f'{offer["hours"]//3} sessions of 3 hours / {offer["hours"]} hours'
 outcome=list(offer["outputs"])
 if learning:agenda=["Understand people and practise interviewing","Define a focused practice challenge","Generate concepts and build a practice prototype","Reflect and create an application plan"]
 elif offer["code"] in ["explore","clarify"]:agenda=["Identify affected people","Examine real examples and evidence gaps","Agree a challenge statement","Plan the next preparation step"]
 else:agenda=["Review user evidence and define the problem","Explore options and select a concept","Build a prototype or storyboard","Gather confirmed user feedback" if access else "Plan feedback access and the next experiment"]
 return {"ruleVersion":RULE_VERSION,"audience":role,"audienceContext":profile["context"],"audienceStartingFormat":profile["starting"],"goal":goal,"title":offer["title"],"code":offer["code"],"days":offer["days"],"hours":offer["hours"],"schedule":schedule,"total":total,"scores":scores,"unknownDimensions":[i for i,x in enumerate(scores) if x is None],"rationale":reasons,"preparation":gaps,"agenda":agenda,"outputs":outcome,"userTestingIncluded":access and offer["code"] in ["feedback","existing_feedback"],"planning":context,"scopingHours":"1–1.5 hours separately","followUpHours":2,"status":"Initial recommendation. Team review required before a proposal.","ai":"Optional synthesis and prototype drafting. No external AI service configured."}
