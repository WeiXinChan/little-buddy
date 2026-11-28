"""Content-free exception metadata; unknown values are never serialized."""
CONTRACT_FAILURES=frozenset({
    'plan_structure','plan_action','plan_mode','plan_rules','plan_roles',
    'plan_secrets','plan_guess_answer_changed','plan_guess_role','plan_sentences','plan_anchors','plan_tool_schema','plan_sentence_limit',
    'json_type','json_capacity','json_encoding','json_syntax','json_duplicate',
    'upstream_capacity','upstream_json','upstream_structure','upstream_unknown',
    'facts_structure','facts_list_type','facts_count','fact_structure',
    'fact_key','fact_key_type','fact_value_type','fact_value_length',
    'fact_source_mismatch','fact_dimension','fact_dimension_type',
})

def mark_contract(error,code):
    if code in CONTRACT_FAILURES:error.contract_diagnostic=code
    return error

def contract_code(error):
    code=getattr(error,'contract_diagnostic',None)
    return code if isinstance(code,str) and code in CONTRACT_FAILURES else 'unknown'

CONTRACT_DETAILS=frozenset({'anchors_container','anchors_count','anchor_name','anchor_index_type','anchor_index_range','quality_whole','quality_segment'})
def mark_contract_detail(error,detail):
    if detail in CONTRACT_DETAILS:error.contract_detail=detail
    return error

def contract_detail(error):
    detail=getattr(error,'contract_detail',None)
    return detail if isinstance(detail,str) and detail in CONTRACT_DETAILS else 'unknown'
