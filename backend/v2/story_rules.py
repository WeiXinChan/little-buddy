"""Bounded explicit turn-count grammar, not general natural-language inference.

Current input > persisted rule > proposal on continue; explicit changes replace
old rules. Only unquoted imperative count forms are interpreted locally.
"""
import re

_COUNT=re.compile(r'(?:每[人次轮]|一[人次轮])(?:都)?(?:只)?(?:说|讲|接)?(?:只)?([一二两三四1-4])句(?:话)?|你一句我一句')
_NUM={'一':1,'1':1,'二':2,'两':2,'2':2,'三':3,'3':3,'四':4,'4':4}
_QUOTED=re.compile(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"|‘[^’]*’')
_NEGATED=re.compile(r'不要(?:再)?|不用(?:再)?|不再|别(?:再)?|取消|不按|不是')
_CANCEL=re.compile(r'(?:取消|不再限制|不限制|不限)(?:每轮)?句数(?:限制)?')

def explicit_count(text):
    """(found, count); None count means an explicit cancellation, not zero."""
    text=_QUOTED.sub('',text)
    found=False;count=None
    for clause in re.split(r'[，,。；;！？!?\n]|而是|改成|改为',text):
        events=[(m.start(),False,m) for m in _COUNT.finditer(clause)]+[(m.start(),True,m) for m in _CANCEL.finditer(clause)]
        for _,cancel,match in sorted(events,key=lambda event:event[0]):
            prefix=clause[:match.start()]
            if cancel and _NEGATED.search(prefix):continue
            count=None if cancel or _NEGATED.search(prefix) else _NUM.get(match.group(1),1)
            found=True
    return found,count

def turn_limit(text,context,plan):
    found,count=explicit_count(text or '')
    if found:return count
    game=context.get('game',{})
    # Owned by Session's final ACK, never accepted from the new model proposal.
    if 'turn_limit' in game and (game['turn_limit'] is None or type(game['turn_limit']) is int and 1<=game['turn_limit']<=4):
        return game['turn_limit']
    # Bootstrap legacy committed prose once, then retain the typed receipt.
    found,count=explicit_count(game.get('rules',''))
    if found:return count
    return explicit_count(plan['rules'])[1]

def constraint_proposal(text,context,plan):
    """(present, limit); explicit cancellation is a persistent None receipt."""
    if plan['mode']!='story' or plan['action'] not in {'continue','change'}:return False,None
    found,count=explicit_count(text or '')
    if found:return True,count
    game=context.get('game',{})
    if 'turn_limit' in game:return True,turn_limit(text,context,plan)
    found,count=explicit_count(game.get('rules',''))
    if found:return True,count
    return explicit_count(plan['rules'])

# Protect numbers and conventional abbreviations, never all alphabetic periods.
_ABBREVIATION=re.compile(r'\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr)\.|\b(?:[A-Za-z]\.){2,}',re.IGNORECASE)

def sentence_count(text):
    protected=_ABBREVIATION.sub(lambda match:match.group().replace('.','\u2024'),text)
    protected=re.sub(r'(?<=\d)\.(?=\d)','\u2024',protected)
    # Ellipsis is a pause within a contribution; an otherwise complete next
    # sentence still needs a delimiter. Quotes alone never count as a sentence.
    protected=re.sub(r'\.{2,}|…+',' ',protected)
    return len([part for part in re.split(r'[。！？!?.]+',protected)
                if part.strip(' \t\n\r“”‘’「」『』\"')])

def obeys_turn_limit(text,context,plan):
    if plan['mode']!='story' or plan['action'] not in {'continue','change'}:return True
    limit=turn_limit(text,context,plan)
    return limit is None or sum(sentence_count(s) for s in plan['sentences'])<=limit
