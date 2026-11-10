# -*- coding: utf-8 -*-


class CircuitRuleError(ValueError):
    pass


def panel_load_names(raw_value):
    """Разделитель графа Dynamo — запятая с пробелом."""
    names = []
    seen = set()
    for part in (raw_value or u"").split(u", "):
        name = part.strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def remaining_connections(is_md, existing_count):
    return max(0, (2 if is_md else 1) - existing_count)


def common_system_type(device_types, preferred):
    common = set(device_types[0])
    for types in device_types[1:]:
        common.intersection_update(types)
    if preferred in common:
        return preferred
    if len(common) == 1:
        return next(iter(common))
    if not common:
        raise CircuitRuleError(u"У устройств группы нет общего типа цепи.")
    raise CircuitRuleError(u"У устройств несколько общих типов цепи; выбор неоднозначен.")
