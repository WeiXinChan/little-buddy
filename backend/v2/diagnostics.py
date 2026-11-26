"""Content-free exception metadata; unknown values are never serialized."""
CONTRACT_FAILURES=frozenset({
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
