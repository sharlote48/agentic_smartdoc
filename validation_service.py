import re
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Any, Dict, Literal
from dateutil import parser

router = APIRouter(tags=["validation"])

class ValidationRule(BaseModel):
    field_name: str
    rule_type: Literal["enum", "regex", "range", "date", "type_check"]
    criteria: Any  # Could be a list [USD, EUR], a regex string, or {"min": 0}

class ValidationRequest(BaseModel):
    data: Dict[str, Any]
    rules: List[ValidationRule]

@router.post("/validate")
async def validate_any_data(payload: ValidationRequest):
    errors = []
    data = payload.data

    for rule in payload.rules:
        val = data.get(rule.field_name)
        
        # 1. Handle Missing Data
        if val is None:
            errors.append(f"Field '{rule.field_name}' is missing.")
            continue

        # 2. Rule Logic
        try:
            if rule.rule_type == "enum":
                if str(val).upper() not in [str(c).upper() for c in rule.criteria]:
                    errors.append(f"'{rule.field_name}' value '{val}' not in allowed list: {rule.criteria}")
            
            elif rule.rule_type == "date":
                parser.parse(str(val))
            
            elif rule.rule_type == "regex":
                if not re.match(rule.criteria, str(val)):
                    errors.append(f"'{rule.field_name}' does not match pattern: {rule.criteria}")
            
            elif rule.rule_type == "range":
                num = float(val)
                if "min" in rule.criteria and num < rule.criteria["min"]:
                    errors.append(f"'{rule.field_name}' is below minimum {rule.criteria['min']}")
                if "max" in rule.criteria and num > rule.criteria["max"]:
                    errors.append(f"'{rule.field_name}' is above maximum {rule.criteria['max']}")

        except Exception:
            errors.append(f"Field '{rule.field_name}' failed {rule.rule_type} validation.")

    if not errors:
        return {"status": "valid", "feedback": "All rules passed."}
    
    return {"status": "invalid", "feedback": " | ".join(errors)}

