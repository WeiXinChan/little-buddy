"""Lossless cold evidence and extractive retrieval; no model-authored summaries."""
import base64
import json
import re
import zlib

MAX_SOURCE_BYTES = 1024 * 1024
# Query-only grammatical/utterance particles, never removed from source evidence.
# Single Han topics are added only for short (<=4 content-character) queries.
QUERY_PARTICLES = frozenset('的了着呢啊呀吧吗么嘛哦喔嗯呐啦哎诶和与及或也就都还我你他她它们这那是有')


def query_terms(query):
    words=set(re.findall(r'[a-z0-9]+',query))
    grams={query[i:i+2] for i in range(max(0,len(query)-1))
           if any(c.isalnum() and c not in QUERY_PARTICLES for c in query[i:i+2])}
    han=[c for c in query if '\u4e00'<=c<='\u9fff' and c not in QUERY_PARTICLES]
    topics=set(han) if 0<len(han)<=4 else set()
    return words,grams,topics


def unpack(encoded):
    if not encoded:return {}
    decoder=zlib.decompressobj()
    raw=decoder.decompress(base64.b64decode(encoded,validate=True),MAX_SOURCE_BYTES+1)
    if len(raw)>MAX_SOURCE_BYTES or decoder.unconsumed_tail or not decoder.eof:
        raise ValueError('source archive capacity')
    return json.loads(raw)


def partition(facts, archive):
    cold=unpack(archive)
    # One exact source per source_id, even when a repeated statement moves
    # between the latest alias and a history alias in the same turn.
    latest={v['source_id'] for k,v in facts.items() if ':history:' not in k and 'source_id' in v}
    clean={k:v for k,v in facts.items() if ':history:' not in k or v['source_id'] not in latest}
    for k,v in clean.items():
        if 'source_id' in v:cold.pop(v['source_id'],None)
    history=[k for k in clean if ':history:' in k]
    # Keep all sources hot for small conversations, then move the old history
    # verbatim to a single compressed archive; current facts/played anchors stay hot.
    if len(json.dumps(clean,ensure_ascii=False).encode())>12000 or archive:
        for key in history[:-4]:
            value=clean.pop(key);cold[value['source_id']]=[key,value]
    raw=json.dumps(cold,ensure_ascii=False,separators=(',',':')).encode()
    if len(raw)>MAX_SOURCE_BYTES:raise BufferError('source archive capacity')
    packed=base64.b64encode(zlib.compress(raw,9)).decode() if cold else ''
    return clean,packed


def retrieve(facts, archive, query, private):
    visible={k:v for k,v in facts.items() if private or not v['private']}
    cold=[(k,v) for k,v in unpack(archive).values() if private or not v['private']]
    # Lexical relevance only: complete source evidence is returned, never a
    # rewritten/merged claim. Latest facts stay separate from historical evidence.
    query=query.casefold()
    words,grams,topics=query_terms(query)
    def relevance(value):
        text=value.get('source_text',value['value']).casefold()
        return sum(3 for w in words if w in text)+sum(1 for g in grams if g in text)+sum(1 for c in topics if c in text)
    def score(item):
        return (relevance(item[1]),item[1]['turn'])
    ranked=sorted(cold,key=score,reverse=True)
    selected=ranked[:12] if words or grams or topics else ranked[:4]
    for k,v in selected:visible[k]=v
    # Projection is bounded too, including unusually long full source_text.
    # Omitted evidence remains in owner memory and is declared, not rewritten.
    def priority(item):
        k,v=item
        return (relevance(v),':played:' in k,':history:' not in k,v['turn'])
    bounded={};used=2
    for k,v in sorted(visible.items(),key=priority,reverse=True):
        cost=len(json.dumps({k:v},ensure_ascii=False).encode())
        if used+cost<=18000:bounded[k]=v;used+=cost
    cold_keys={k for k,v in cold}
    fetched=len(cold_keys & bounded.keys())
    return bounded,dict(archived_sources=len(cold),retrieved_sources=fetched,
                        omitted_sources=len(cold)-fetched+len(set(visible)-cold_keys-set(bounded)),
                        mode='exact_evidence')
