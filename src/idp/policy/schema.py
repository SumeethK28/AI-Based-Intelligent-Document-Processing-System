"""Strict policy configuration. Safety requirements cannot be switched off."""
import copy
from decimal import Decimal, InvalidOperation
import re

from idp.agents.validation_agent import ValidationAgent
from idp.agents.routing_agent import WorkflowRoutingAgent

DEFAULT = {
    'mandatory_fields': copy.deepcopy(ValidationAgent.REQUIRED_FIELDS),
    'high_value_thresholds': {'INR':'100000','USD':'100000','EUR':'100000','GBP':'100000'},
    'unknown_currency_threshold':'100000',
    'po_tolerance':'0.02',
    'arithmetic_tolerance':'0.02',
    'require_po_reference':False,
    'duplicate_identifiers':'review',
    'require_contract_expiration':False,
    'escalate_all':False,
    'departments':copy.deepcopy(WorkflowRoutingAgent.DEPARTMENT_MAP),
}
DESCRIPTION = {
    'mandatory_fields':'Required information by document type. Protected base fields cannot be removed.',
    'high_value_thresholds':'Review amounts above the threshold in each currency; no currency conversion.',
    'unknown_currency_threshold':'Conservative nominal threshold for unspecified or unconfigured currencies.',
    'po_tolerance':'Maximum absolute invoice/PO amount difference in the same currency (0–1 nominal unit).',
    'arithmetic_tolerance':'Maximum subtotal plus tax difference (0–0.02 nominal unit).',
    'require_po_reference':'Require a PO reference on every invoice; referenced POs must always reconcile.',
    'duplicate_identifiers':'Review distinct sources sharing the same type, identifier and business party.',
    'require_contract_expiration':'Require a supported expiration date in addition to protected contract checks.',
    'escalate_all':'Send all supported documents for additional review without relaxing any safety check.',
    'departments':'Destination after all preliminary checks pass. Queued work is not an authorized transaction.',
}


def validate_config(config):
    from idp.llm.schemas import AIExtractionResult
    from idp.review.service import TEAMS
    if not isinstance(config,dict) or set(config)!=set(DEFAULT):
        raise ValueError('Provide exactly the supported policy categories; safety overrides are not supported.')
    result=copy.deepcopy(config)
    for key in ('require_po_reference','require_contract_expiration','escalate_all'):
        if type(result[key]) is not bool:
            raise ValueError(key+' must be true or false.')
    if result['duplicate_identifiers']!='review':
        raise ValueError('Duplicate business identifiers must remain subject to review.')
    mandatory=result['mandatory_fields']
    if not isinstance(mandatory,dict) or set(mandatory)!=set(DEFAULT['mandatory_fields']):
        raise ValueError('Mandatory fields must cover all four supported document types.')
    for kind,base in DEFAULT['mandatory_fields'].items():
        fields=mandatory[kind]
        allowed=set(base+ValidationAgent.OPTIONAL_FIELDS[kind])
        if not isinstance(fields,list) or any(not isinstance(f,str) for f in fields) or len(fields)!=len(set(fields)) or not set(base)<=set(fields) or not set(fields)<=allowed or not set(fields)<=set(AIExtractionResult.model_fields):
            raise ValueError('Mandatory fields cannot remove protected fields or add unsupported fields: '+kind)
    def number(value,maximum):
        if not isinstance(value,(str,int,float)) or isinstance(value,bool):
            raise ValueError('Thresholds and tolerances must be finite numbers.')
        try:
            amount=Decimal(str(value))
        except InvalidOperation:
            raise ValueError('Invalid numeric policy value.') from None
        if not amount.is_finite() or amount<0 or amount>maximum:
            raise ValueError('Numeric policy value is outside the safe supported range.')
        return str(amount)
    result['po_tolerance']=number(result['po_tolerance'],Decimal('1'))
    result['arithmetic_tolerance']=number(result['arithmetic_tolerance'],Decimal('.02'))
    thresholds=result['high_value_thresholds']
    if not isinstance(thresholds,dict) or not thresholds or len(thresholds)>100 or any(not isinstance(code,str) or not re.fullmatch('[A-Z]{3}',code) for code in thresholds):
        raise ValueError('Thresholds require uppercase three-letter currency codes.')
    for code,value in thresholds.items():
        thresholds[code]=number(value,Decimal('1000000000000'))
        if Decimal(thresholds[code])<=0:
            raise ValueError('High-value thresholds must be positive.')
    result['unknown_currency_threshold']=number(result['unknown_currency_threshold'],Decimal('100000'))
    if Decimal(result['unknown_currency_threshold'])<=0:
        raise ValueError('Unknown-currency threshold must be positive and cannot exceed the baseline.')
    if not isinstance(result['departments'],dict) or set(result['departments'])!=set(DEFAULT['departments']) or any(team not in TEAMS[:4] for team in result['departments'].values()):
        raise ValueError('Select a supported business department for every document type.')
    return result
