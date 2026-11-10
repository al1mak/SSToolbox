# -*- coding: utf-8 -*-

from collections import defaultdict

from Autodesk.Revit import DB
from Autodesk.Revit.DB.Electrical import ElectricalSystem, ElectricalSystemType
from Autodesk.Revit.Exceptions import (
    ArgumentException, InvalidOperationException, RegenerationFailedException,
)
from System.Collections.Generic import List

from ss_circuit_rules import (
    CircuitRuleError, common_system_type, panel_load_names, remaining_connections,
)


EQUIPMENT = DB.BuiltInCategory.OST_ElectricalEquipment
DEVICE_CATEGORIES = (
    EQUIPMENT,
    DB.BuiltInCategory.OST_LightingFixtures,
    DB.BuiltInCategory.OST_ElectricalFixtures,
    DB.BuiltInCategory.OST_SecurityDevices,
    DB.BuiltInCategory.OST_FireAlarmDevices,
    DB.BuiltInCategory.OST_NurseCallDevices,
)
PREFERRED_TYPE = ElectricalSystemType.Controls
FALLBACK_TYPES = (
    u"Controls", u"Security", u"Data", u"Communication", u"FireAlarm",
    u"NurseCall", u"Telephone", u"PowerCircuit",
)
TRANSACTION_NAME = u"Создать электрические цепи"


def _named_parameter(element, name):
    matches = element.GetParameters(name)
    if matches.Count > 1:
        raise CircuitRuleError(u"Найдено несколько параметров «{}».".format(name))
    return matches[0] if matches.Count else None


def _read_parameter(parameter, name):
    if parameter is None or not parameter.HasValue:
        return None
    storage = parameter.StorageType
    if storage == DB.StorageType.String:
        return (parameter.AsString() or u"").strip() or None
    if storage == DB.StorageType.Integer:
        return u"{}".format(parameter.AsInteger())
    if storage == DB.StorageType.Double:
        return u"{}".format(parameter.AsDouble())
    raise CircuitRuleError(u"Неподдерживаемый тип параметра «{}».".format(name))


def _read_named(element, name):
    return _read_parameter(_named_parameter(element, name), name)


def _issue(issues, kind, panel, device, name, reason):
    issues.append((kind, panel.Id if panel else None,
                   device.Id if device else None, name, reason))


def collect_tasks(doc, view, settings):
    categories = List[DB.BuiltInCategory]()
    for category in DEVICE_CATEGORIES:
        categories.Add(category)
    collector = (DB.FilteredElementCollector(doc, view.Id)
                 .WherePasses(DB.ElementMulticategoryFilter(categories))
                 .OfClass(DB.FamilyInstance)
                 .WhereElementIsNotElementType())

    panels = []
    devices = defaultdict(list)
    issues = []
    address_param = settings["address_param"]
    load_param = settings["load_param"]
    kit_param = settings["kit_param"]
    equipment_id = DB.ElementId(EQUIPMENT)
    elements = sorted(collector, key=lambda element: element.Id.Value)
    for element in elements:
        is_panel = False
        try:
            if element.Category.Id == equipment_id:
                address = _read_named(element, address_param)
                is_panel = address is not None
            if is_panel:
                kit = _read_named(element, kit_param)
                if not kit or settings["kit_filter"] not in kit:
                    _issue(issues, u"Пропуск", element, None, None,
                           u"«{}» не содержит «{}».".format(kit_param, settings["kit_filter"]))
                    continue
                names = panel_load_names(_read_named(element, load_param))
                if not names:
                    _issue(issues, u"Пропуск", element, None, None,
                           u"Параметр «{}» отсутствует или не заполнен.".format(load_param))
                    continue
                panel_name = _read_parameter(
                    element.get_Parameter(DB.BuiltInParameter.RBS_ELEC_PANEL_NAME),
                    u"Имя панели",
                )
                if element.MEPModel is None:
                    raise CircuitRuleError(u"У панели нет модели инженерных систем.")
                is_md = bool(panel_name and panel_name.startswith(settings["md_prefix"]))
                panels.append((element, names, is_md))
            else:
                name = _read_named(element, load_param)
                if name:
                    devices[name].append(element)
                else:
                    _issue(issues, u"Пропуск", None, element, None,
                           u"Параметр «{}» отсутствует или не заполнен.".format(load_param))
        except CircuitRuleError as error:
            _issue(issues, u"Ошибка", element if is_panel else None,
                   None if is_panel else element, None, u"{}".format(error))

    tasks = []
    matched_names = set()
    for panel, names, is_md in panels:
        for name in names:
            matching = devices.get(name)
            if matching:
                tasks.append((panel, name, is_md, matching))
                matched_names.add(name)
            else:
                _issue(issues, u"Пропуск", panel, None, name,
                       u"На активном виде нет устройств с таким именем нагрузки.")
    for name in sorted(devices):
        if name not in matched_names:
            for device in devices[name]:
                _issue(issues, u"Пропуск", None, device, name,
                       u"На активном виде нет подходящей панели.")
    return tasks, issues, len(elements)


def _available_connectors(device, panel, is_md, fallback_type):
    mep = device.MEPModel
    manager = mep.ConnectorManager if mep is not None else None
    if manager is None:
        return 0, [], u"У устройства нет менеджера коннекторов."
    existing_ids = set()
    for system in mep.GetElectricalSystems() or []:
        base = system.BaseEquipment
        if base is not None and base.Id == panel.Id:
            existing_ids.add(system.Id.Value)
    remaining = remaining_connections(is_md, len(existing_ids))
    if not remaining:
        return 0, [], u"Устройство уже подключено к панели: цепей {}.".format(len(existing_ids))
    connectors = []
    for connector in manager.UnusedConnectors:
        if (connector.Domain != DB.Domain.DomainElectrical
                or connector.ConnectorType == DB.ConnectorType.Logical):
            continue
        # Revit может возвращать UndefinedSystemType у свободного коннектора.
        try:
            system_type = connector.ElectricalSystemType
        except InvalidOperationException:
            system_type = ElectricalSystemType.UndefinedSystemType
        if system_type == ElectricalSystemType.UndefinedSystemType:
            system_type = fallback_type
        connectors.append((connector, system_type))
    connectors.sort(key=lambda pair: (pair[1] != PREFERRED_TYPE, pair[0].Id))
    reason = None if connectors else u"Нет свободного электрического коннектора."
    return remaining, connectors, reason


def _set_load_name(circuit, name, fallback_param):
    parameter = circuit.get_Parameter(DB.BuiltInParameter.RBS_ELEC_CIRCUIT_NAME)
    if _can_set_text(parameter):
        parameter.Set(name)
        if parameter.AsString() == name:
            return
    parameter = _named_parameter(circuit, fallback_param)
    if _can_set_text(parameter):
        parameter.Set(name)
        if parameter.AsString() == name:
            return
    raise CircuitRuleError(u"Не удалось записать имя нагрузки в параметр цепи.")


def _can_set_text(parameter):
    return (parameter is not None and not parameter.IsReadOnly
            and parameter.StorageType == DB.StorageType.String)


def _create_circuit(doc, panel, name, devices, system_type, fallback_param, connector=None):
    with DB.Transaction(doc, TRANSACTION_NAME) as transaction:
        if transaction.Start() != DB.TransactionStatus.Started:
            raise RuntimeError(u"Revit не смог начать транзакцию создания цепи.")
        options = transaction.GetFailureHandlingOptions()
        options.SetClearAfterRollback(True)
        options.SetForcedModalHandling(True)
        transaction.SetFailureHandlingOptions(options)
        ids = List[DB.ElementId]()
        for device in devices:
            ids.Add(device.Id)
        try:
            if connector is None:
                circuit = ElectricalSystem.Create(doc, ids, system_type)
            else:
                circuit = ElectricalSystem.Create(connector, system_type)
            if circuit is None:
                raise CircuitRuleError(u"Revit не создал цепь.")
            circuit.SelectPanel(panel)
            doc.Regenerate()
            base = circuit.BaseEquipment
            if base is None or base.Id != panel.Id:
                raise CircuitRuleError(u"Revit не назначил указанную панель.")
            if set(item.Id.Value for item in circuit.Elements) != set(eid.Value for eid in ids):
                raise CircuitRuleError(u"Revit не включил в цепь точно заданный состав устройств.")
            _set_load_name(circuit, name, fallback_param)
            circuit_id = circuit.Id
        except RegenerationFailedException:
            # После сбоя регенерации продолжать работу с документом нельзя.
            raise
        except (CircuitRuleError, ArgumentException, InvalidOperationException) as error:
            if transaction.RollBack() != DB.TransactionStatus.RolledBack:
                raise RuntimeError(u"Revit не подтвердил откат цепи.")
            return None, u"{}".format(error)
        status = transaction.Commit()
        if status == DB.TransactionStatus.RolledBack:
            return None, u"Revit отменил цепь при подтверждении транзакции."
        if status != DB.TransactionStatus.Committed:
            raise RuntimeError(u"Не удалось завершить транзакцию: {}.".format(status))
        return circuit_id, None


def _record(created, issues, panel, device, name, devices, result):
    circuit_id, error = result
    if error:
        _issue(issues, u"Ошибка", panel, device, name, error)
    else:
        created.append((circuit_id, panel.Id, name, [item.Id for item in devices]))


def _create_group(doc, panel, name, devices, fallback_param, fallback_type, created, issues):
    eligible, types = [], []
    for device in devices:
        _, connectors, reason = _available_connectors(device, panel, False, fallback_type)
        if not connectors:
            _issue(issues, u"Пропуск", panel, device, name, reason)
            continue
        eligible.append(device)
        types.append(set(system_type for _, system_type in connectors))
    if not eligible:
        return
    try:
        system_type = common_system_type(types, PREFERRED_TYPE)
    except CircuitRuleError as error:
        _issue(issues, u"Ошибка", panel, None, name, u"{}".format(error))
        return
    result = _create_circuit(doc, panel, name, eligible, system_type, fallback_param)
    _record(created, issues, panel, None, name, eligible, result)


def _create_md(doc, panel, name, devices, fallback_param, fallback_type, created, issues):
    for device in devices:
        tried = set()
        created_here = False
        while True:
            remaining, connectors, reason = _available_connectors(device, panel, True, fallback_type)
            if not remaining or not connectors:
                if not created_here or remaining:
                    _issue(issues, u"Пропуск", panel, device, name, reason)
                break
            # После изменения или отката заново получаем коннекторы из модели.
            choice = next((pair for pair in connectors if pair[0].Id not in tried), None)
            if choice is None:
                break
            connector, system_type = choice
            tried.add(connector.Id)
            result = _create_circuit(doc, panel, name, [device], system_type, fallback_param, connector)
            _record(created, issues, panel, device, name, [device], result)
            created_here = created_here or result[0] is not None


def create_circuits(doc, tasks, settings, issues):
    created = []
    fallback_type = getattr(ElectricalSystemType, settings["fallback_type"])
    with DB.TransactionGroup(doc, TRANSACTION_NAME) as group:
        if group.Start() != DB.TransactionStatus.Started:
            raise RuntimeError(u"Revit не смог начать операцию создания цепей.")
        try:
            for panel, name, is_md, devices in tasks:
                create = _create_md if is_md else _create_group
                create(doc, panel, name, devices, settings["load_param"], fallback_type, created, issues)
            status = group.Assimilate() if created else group.RollBack()
            expected = DB.TransactionStatus.Committed if created else DB.TransactionStatus.RolledBack
            if status != expected:
                raise RuntimeError(u"Revit не подтвердил завершение операции: {}.".format(status))
        except Exception:
            if group.GetStatus() == DB.TransactionStatus.Started:
                group.RollBack()
            raise
    return created
