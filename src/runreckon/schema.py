"""A small, dependency-free JSON Schema validator.

Implements the subset of JSON Schema that task specs realistically use to
describe tool arguments: type, required, properties, additionalProperties,
items, enum, const, pattern, minLength/maxLength, minimum/maximum,
exclusiveMinimum/exclusiveMaximum, minItems/maxItems, and anyOf/oneOf.

Deliberate strictness: JSON booleans are not integers (``True`` does not
satisfy ``{"type": "integer"}``), and a numeric string does not satisfy a
numeric type. Argument validity is where agents most often get silent
credit for malformed calls, so the validator does not coerce.
"""

from __future__ import annotations

import re


def _type_name(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return type(value).__name__


def _matches_type(value, expected: str) -> bool:
    actual = _type_name(value)
    if expected == "number":
        return actual in ("integer", "number")
    return actual == expected


def validate(value, schema, path: str = "$") -> list[str]:
    """Return a list of violation strings (empty when valid)."""
    if not isinstance(schema, dict):
        return []
    errors: list[str] = []

    if "anyOf" in schema:
        if not any(not validate(value, sub, path) for sub in schema["anyOf"]):
            errors.append(f"{path}: matches none of the anyOf schemas")
        return errors
    if "oneOf" in schema:
        hits = sum(1 for sub in schema["oneOf"] if not validate(value, sub, path))
        if hits != 1:
            errors.append(f"{path}: matches {hits} of the oneOf schemas (need exactly 1)")
        return errors

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']!r}")

    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, t) for t in types):
            errors.append(
                f"{path}: expected type {'/'.join(types)}, got {_type_name(value)}")
            return errors  # deeper checks would be noise on a wrong type

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property '{key}'")
        props = schema.get("properties", {})
        for key, subschema in props.items():
            if key in value:
                errors.extend(validate(value[key], subschema, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path}: unexpected property '{key}'")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: has {len(value)} items, minimum is {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: has {len(value)} items, maximum is {schema['maxItems']}")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                errors.extend(validate(item, schema["items"], f"{path}[{i}]"))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} is below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} is above maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: {value} is not above {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: {value} is not below {schema['exclusiveMaximum']}")
    return errors
