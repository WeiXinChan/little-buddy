"""Supplier constrained decoding supplements, never replaces, local trust gates."""
def obj(properties, *, required=None):
    return dict(type='object', properties=properties,
                required=list(properties) if required is None else required, additionalProperties=False)

def string(limit):
    return dict(type='string', maxLength=limit)

def enum(*items):
    return dict(type='string', enum=list(items))

IMAGE_TOOL = obj(dict(kind=enum('show_image','hide_image','generate_image','extend_image','reshow_image'),asset_id=string(64)),required=['kind'])

PLAN = obj(dict(
    action=enum('continue','change','leave','handoff','private','end'),
    mode=enum('chat','guess','story','adventure','association'),
    rules=string(2000),
    roles=dict(type='array',items=string(80),maxItems=8),
    secrets=dict(type='object',additionalProperties=string(1000),maxProperties=8),
    sentences=dict(type='array',items=dict(type='string',minLength=1,maxLength=120),minItems=1,maxItems=4),
    anchors=dict(type='object',additionalProperties=dict(type='integer',minimum=0,maximum=3),maxProperties=16),
    tools=dict(type='array',items=IMAGE_TOOL,maxItems=1)),
    required=['action','mode','rules','roles','secrets','sentences','anchors'])
FACT_ITEM = obj(dict(
    key=enum('nickname','preference','role','rule','clue','plot','promise'),
    value=dict(type='string',minLength=1,maxLength=256),
    dimension=enum('unspecified','animal','color','food','sport','activity','music','place','person','object','other')),
    required=['key','value'])
FACTS = obj(dict(facts=dict(type='array',maxItems=8,items=FACT_ITEM)))
SAFETY = obj(dict(allow=dict(type='boolean')))
ENDPOINT = obj(dict(completion=enum('complete','incomplete','thinking'),
                    meaning=enum('new_turn','stop','noise','backchannel','thinking','unknown','management','volume_up','volume_down')))
COMPACT = obj(dict(keep=dict(type='array',maxItems=24,items=dict(type='integer',minimum=0))))
