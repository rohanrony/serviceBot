"""Pure, narrowly scoped tool revision proposals; this module performs no I/O."""
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

from .core import SimulationError


def _body(tool, deployment_url):
    try:
        schema = tool['api_schema']
        target, deployed = urlsplit(schema['url']), urlsplit(deployment_url)
        query = parse_qs(target.query, keep_blank_values=True)
        if (tool['type'] != 'webhook' or tool['name'] != 'cancel_appointment'
                or schema['method'] != 'POST' or deployed.scheme != 'https'
                or deployed.username or deployed.password or deployed.query or deployed.fragment
                or deployed.path not in ('', '/') or not deployed.hostname
                or target.scheme != 'https' or target.netloc != deployed.netloc
                or target.username or target.password or target.fragment
                or target.path != '/api/v1/voice/tools'
                or query not in ({}, {'name':['cancel_appointment']})):
            raise ValueError
        body = schema['request_body_schema']
        properties = body['properties']
        if (body['type'] != 'object' or not isinstance(properties, dict)
                or properties['phone']['type'] != 'string'
                or properties['appointment_id']['type'] != 'integer'
                or not isinstance(body['required'], list) or 'phone' not in body['required']):
            raise ValueError
        return body
    except (KeyError, TypeError, AttributeError, ValueError):
        raise SimulationError('Selective tool requires the exact native cancel webhook scope') from None


def selective_cancel_tool(source, template, deployment_url):
    """Copy native authentication/settings, adding only reviewed selective scope."""
    source_body = _body(source, deployment_url)
    desired_body = _body(template, deployment_url)
    field = desired_body['properties'].get('service_name')
    if (not isinstance(field, dict) or set(field) != {'type', 'description'}
            or field.get('type') != 'string' or not isinstance(field.get('description'), str)
            or not field['description'].strip() or 'service_name' in desired_body['required']
            or not isinstance(template.get('description'), str) or not template['description'].strip()
            or ('service_name' in source_body['properties']
                and source_body['properties']['service_name'] != field)
            or 'service_name' in source_body['required']):
        raise SimulationError('Selective tool property differs from the reviewed optional revision')
    result = deepcopy(source)
    result['description'] = template['description']
    result['api_schema']['request_body_schema']['properties']['service_name'] = deepcopy(field)
    return result


def cancel_reference_patch(agent, source_tool_id, replacement_tool_id):
    """Prepare one reference replacement without sending materialized tool bodies."""
    try:
        ids = agent['conversation_config']['agent']['prompt']['tool_ids']
        if (not isinstance(ids, list) or not ids
                or any(not isinstance(value, str) or not value or value != value.strip() for value in ids)
                or len(set(ids)) != len(ids) or ids.count(source_tool_id) != 1
                or not isinstance(replacement_tool_id, str) or not replacement_tool_id
                or replacement_tool_id != replacement_tool_id.strip() or replacement_tool_id in ids):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise SimulationError('Selective tool reference requires one exact owned replacement') from None
    updated = [replacement_tool_id if value == source_tool_id else value for value in ids]
    return {'conversation_config': {'agent': {'prompt': {'tool_ids': updated}}}}
