"""Quote-bound primary candidate mining and explicit single-pass review triage.

Every supplied chunk is scanned, but selecting a primary span is not exhaustive
claim extraction. Five logical rubric outputs in one inference are not five
independent reviews. No model output can verify truth or approve publication.
"""
from collections import Counter
import math
import re
from im19.contracts import KnowledgeUnit, KNOWLEDGE_TYPES, digest, stable_id
from im19.knowledge_mining.classifier import TAXONOMY
from im19.knowledge_mining.mining_engine import injection_signal

PROTOCOL = 'primary-extractive-triage-v1'
LABELS = {category + '/' + sub: (category, sub) for category, subs in TAXONOMY.items() for sub in subs}
RUBRICS = {
 'A': ['QUOTE_TRACEABLE', 'EXTRACTION_WARNING', 'FRAGMENT_OR_INCOMPLETE'],
 'B': ['CLEAR_WITH_LIMITED_EVIDENCE', 'NEEDS_CONTEXT', 'AUTHOR_PREFERENCE_OR_ASSUMPTION', 'NO_KNOWLEDGE'],
 'C': ['CHECKABLE_BUT_UNVERIFIED', 'OPINION_OR_ASSUMPTION', 'NOT_A_FACTUAL_CLAIM', 'INSUFFICIENT_EVIDENCE'],
 'D': ['DUPLICATE', 'COMPLEMENTARY', 'DIRECT_CONTRADICTION', 'DEFINITION_DIFFERENCE', 'CONTEXT_DIFFERENCE', 'PERIOD_DIFFERENCE', 'METHODOLOGY_DIFFERENCE', 'INSUFFICIENT_COMPARISON'],
 'E': ['HUMAN_REVIEW_REQUIRED', 'QUARANTINE_RECOMMENDED'],
}
TYPE_CODES=sorted(KNOWLEDGE_TYPES)
LABEL_CODES=sorted(LABELS)

def compact_schema(source_spans, comparison_spans):
    fields={'s':{'type':'string','enum':['NONE',*source_spans]},'t':{'type':'integer','enum':list(range(len(TYPE_CODES)))},'c':{'type':'string','minLength':1,'maxLength':64},'l':{'type':'array','items':{'type':'integer','enum':list(range(len(LABEL_CODES)))},'maxItems':2},**{k:{'type':'integer','enum':list(range(len(v)))} for k,v in RUBRICS.items()},'j':{'type':'string','enum':['NONE',*comparison_spans]},'q':{'type':'array','items':{'type':['integer','null'],'minimum':0,'maximum':100},'minItems':4,'maxItems':4}}
    if not comparison_spans:fields['D']['enum']=[RUBRICS['D'].index('INSUFFICIENT_COMPARISON')]
    return {'type':'object','additionalProperties':False,'properties':fields,'required':list(fields)}

def expand_compact(raw):
    if set(raw)!={'s','t','c','l','A','B','C','D','E','j','q'}:
        raise ValueError('COMPACT_SCHEMA')
    def select(values,index):
        if type(index) is not int or not 0<=index<len(values):raise ValueError('COMPACT_CODE_UNKNOWN')
        return values[index]
    return {'span':raw['s'],'kind':select(TYPE_CODES,raw['t']),'concept':raw['c'],'labels':[select(LABEL_CODES,x) for x in raw['l']],**{k:select(values,raw[k]) for k,values in RUBRICS.items()},'comparison_span':raw['j'],'scores':raw['q']}
STOP = set('the and that this with from have has for are was were will would should can could not but into your you their they its our pada dari yang dan untuk dalam dengan adalah akan atau tidak ini itu sebagai karena oleh suatu dapat lebih juga saya anda kita'.split())

def spans(text):
    result = {}
    for m in re.finditer(r'.+?(?:[.!?](?=\s|$)|\Z)', text, re.S):
        value = m.group().strip()
        if len(value) >= 25 and len(re.findall(r'\w+', value)) >= 4:
            result['s' + str(len(result))] = value
    return result

def terms(text):
    return Counter(x for x in re.findall(r'[^\W\d_]{3,}', text.casefold()) if x not in STOP)

def comparison_map(chunks):
    """Top one TF-IDF cosine candidate from another document, not verification."""
    counts = [terms(c['text']) for c in chunks]
    df = Counter(t for c in counts for t in c)
    vectors = [{t: (1 + math.log(n)) * math.log(1 + len(chunks) / df[t]) for t, n in c.items()} for c in counts]
    norms = [math.sqrt(sum(x*x for x in v.values())) or 1 for v in vectors]
    result = {}
    for i, chunk in enumerate(chunks):
        best, best_score = None, 0.12
        for j, other in enumerate(chunks):
            if other['document_id'] == chunk['document_id']:
                continue
            shared = vectors[i].keys() & vectors[j].keys()
            if len(shared) < 3:
                continue
            score = sum(vectors[i][t] * vectors[j][t] for t in shared) / (norms[i] * norms[j])
            if score > best_score:
                best, best_score = other['chunk_id'], score
        result[chunk['chunk_id']] = {'chunk_id': best, 'cosine': best_score if best else None}
    return result

def response_schema(source_spans, comparison_spans):
    properties = {
      'span': {'type':'string', 'enum':['NONE', *source_spans]},
      'kind': {'type':'string', 'enum':sorted(KNOWLEDGE_TYPES)},
      'concept': {'type':'string', 'minLength':1, 'maxLength':64},
      'labels': {'type':'array', 'items':{'type':'string', 'enum':sorted(LABELS)}, 'maxItems':2},
      **{key:{'type':'string','enum':values} for key, values in RUBRICS.items()},
      'comparison_span': {'type':'string','enum':['NONE', *comparison_spans]},
      'scores': {'type':'array', 'items':{'type':['integer','null'], 'minimum':0,'maximum':100}, 'minItems':4,'maxItems':4},
    }
    if not comparison_spans:
        properties['D']['enum'] = ['INSUFFICIENT_COMPARISON']
    return {'type':'object','additionalProperties':False,'properties':properties,'required':list(properties)}

def bind_result(raw, chunk, source_spans, comparison, comparison_spans, model_version):
    if chunk['content_hash'] != digest(chunk['text']):
        raise ValueError('SOURCE_HASH_MISMATCH')
    if comparison and (comparison['document_id']==chunk['document_id'] or comparison['content_hash']!=digest(comparison['text'])):
        raise ValueError('COMPARISON_PROVENANCE_INVALID')
    required = {'span','kind','concept','labels','A','B','C','D','E','comparison_span','scores'}
    if set(raw) != required or raw['kind'] not in KNOWLEDGE_TYPES:
        raise ValueError('TRIAGE_SCHEMA')
    if any(raw[k] not in values for k,values in RUBRICS.items()):
        raise ValueError('TRIAGE_RUBRIC')
    if not isinstance(raw['concept'],str) or not 1 <= len(raw['concept'].strip()) <= 64:
        raise ValueError('TRIAGE_CONCEPT')
    if not isinstance(raw['labels'],list) or len(raw['labels'])>2 or any(x not in LABELS for x in raw['labels']):
        raise ValueError('TRIAGE_LABELS')
    if not isinstance(raw['scores'],list) or len(raw['scores']) != 4 or any(x is not None and (type(x) is not int or not 0<=x<=100) for x in raw['scores']):
        raise ValueError('TRIAGE_SCORES')
    if raw['span'] != 'NONE' and raw['span'] not in source_spans:
        raise ValueError('SOURCE_SPAN_UNKNOWN')
    if raw['comparison_span'] != 'NONE' and raw['comparison_span'] not in comparison_spans:
        raise ValueError('COMPARISON_SPAN_UNKNOWN')
    if not comparison and (raw['D']!='INSUFFICIENT_COMPARISON' or raw['comparison_span']!='NONE'):
        raise ValueError('COMPARISON_NOT_SUPPLIED')
    labels = [dict(zip(('category','subcategory'),LABELS[x])) for x in raw['labels']]
    unit = None
    if raw['span']!='NONE':
        quote=source_spans[raw['span']]
        if quote not in chunk['text']:
            raise ValueError('SOURCE_EVIDENCE_MISMATCH')
        category,sub=LABELS[raw['labels'][0]] if raw['labels'] else ('Lainnya','Unclassified')
        unit=KnowledgeUnit(stable_id(chunk['document_id'],chunk['locator'],digest(quote),model_version,PROTOCOL),chunk['document_id'],raw['concept'].strip(),category,sub,raw['kind'],quote,quote,chunk['page_start'],chunk['page_end'],[chunk['chunk_id']],chunk['locator'],model_version,digest(quote)).to_dict()
        unit.update(verification_status='NOT_EXTERNALLY_VERIFIED',review_status='SINGLE_PASS_TRIAGED_NEEDS_HUMAN_REVIEW',human_approval_required=True,production_published=False,mining_method=PROTOCOL,extraction_completeness='PRIMARY_SPAN_ONLY_NOT_EXHAUSTIVE')
    relation=None
    if unit and comparison and raw['comparison_span']!='NONE' and raw['D']!='INSUFFICIENT_COMPARISON':
        evidence=comparison_spans[raw['comparison_span']]
        if evidence not in comparison['text']:
            raise ValueError('COMPARISON_EVIDENCE_MISMATCH')
        relation={'relation_id':stable_id(unit['knowledge_id'],comparison['chunk_id'],digest(evidence),raw['D'],model_version,PROTOCOL),'source_knowledge_id':unit['knowledge_id'],'source_chunk_id':chunk['chunk_id'],'source_document_id':chunk['document_id'],'source_locator':chunk['locator'],'source_evidence_text':unit['evidence_text'],'target_chunk_id':comparison['chunk_id'],'target_document_id':comparison['document_id'],'target_locator':comparison['locator'],'target_evidence_text':evidence,'kind':raw['D'],'model_version':model_version,'review_status':'PROPOSED_NEEDS_HUMAN_REVIEW','verified':False}
    warnings=list(chunk.get('warnings',[]))
    if injection_signal(chunk['text']):warnings.append('POSSIBLE_PROMPT_INJECTION')
    return {'unit':unit,'labels':labels,'classification_status':'NEEDS_REVIEW' if not labels or any(x['category']=='Lainnya' for x in labels) else 'PROVISIONAL_CONTENT_CLASSIFIED','rubrics':{k:raw[k] for k in RUBRICS},'dimensions':dict(zip(['extraction_integrity','provenance','evidence_strength','consistency'],raw['scores']))|{'source_credibility':None,'freshness':None},'quality':{'score':None,'status':'NEEDS_REVIEW','calibrated':False},'relation':relation,'warnings':warnings,'human_approval_required':True,'verification_status':'NOT_EXTERNALLY_VERIFIED','independent_reviewers':False,'review_execution_mode':'SINGLE_MODEL_PASS_FIVE_LOGICAL_RUBRICS','comparison_scope':'top-one lexical candidate among currently supplied staged chunks; not exhaustive','claim_extraction_scope':'at most one primary verbatim knowledge statement per source chunk; not exhaustive'}
