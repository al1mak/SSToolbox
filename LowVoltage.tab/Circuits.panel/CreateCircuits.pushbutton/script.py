# -*- coding: utf-8 -*-

from pyrevit import DB, EXEC_PARAMS, HOST_APP, forms, script

from ss_circuits import FALLBACK_TYPES, collect_tasks, create_circuits


TITLE = u"Создать цепи"
OPTIONS = (
    ("address_param", u"Параметр адреса панели", u"SMNX_Адрес устройства"),
    ("load_param", u"Параметр имени нагрузки", u"SMNX_Имя нагрузки"),
    ("kit_param", u"Параметр комплекта панели", u"SMNX_Комплект"),
    ("kit_filter", u"Фрагмент значения комплекта панели", u"СПА"),
    ("md_prefix", u"Префикс имени панели для режима двух цепей", u"MD."),
    ("fallback_type", u"Тип цепи, если Revit не определил тип коннектора", u"Controls"),
)


def _read_settings(config):
    values = {}
    for key, label, default in OPTIONS:
        value = config.get_option(key, default)
        values[key] = value.strip() if isinstance(value, (str, type(u""))) else u""
    return values


def _configure(config, values):
    for key, label, default in OPTIONS:
        if key == "fallback_type":
            value = forms.ask_for_one_item(FALLBACK_TYPES, default=values[key] or default,
                                           prompt=label, title=u"Настройки создания цепей")
        else:
            value = forms.ask_for_string(default=values[key] or default,
                                         prompt=label, title=u"Настройки создания цепей")
        if value is None:
            return
        if not value.strip():
            forms.alert(u"Заполните поле «{}». Настройки не сохранены.".format(label), title=TITLE)
            return
        values[key] = value.strip()
    for key, value in values.items():
        config.set_option(key, value)
    script.save_config()
    forms.alert(u"Настройки создания цепей сохранены.", title=TITLE)


def _escape(value):
    return value.replace(u"&", u"&amp;").replace(u"<", u"&lt;").replace(u">", u"&gt;")


def _report(output, view_name, element_count, tasks, created, issues):
    panels = set(panel.Id.Value for panel, _, _, _ in tasks)
    connected = set(eid.Value for _, _, _, ids in created for eid in ids)
    errors = sum(1 for kind, _, _, _, _ in issues if kind == u"Ошибка")
    print(u"Активный вид: {}".format(_escape(view_name)))
    print(u"Просмотрено экземпляров: {}. Панелей с совпадениями: {}. Групп «панель — нагрузка»: {}."
          .format(element_count, len(panels), len(tasks)))
    print(u"Создано цепей: {}. Подключено устройств: {}. Записей о пропусках: {}. Ошибок: {}."
          .format(len(created), len(connected), len(issues) - errors, errors))
    if created and issues:
        print(u"Цепи с ошибками не сохранены; созданные цепи остаются в модели." if errors
              else u"Подключены только устройства, прошедшие проверки.")
    if not created:
        print(u"Модель не изменена.")
    for circuit_id, panel_id, name, device_ids in created:
        print(u"Цепь {} | панель {} | нагрузка «{}» | устройств: {}".format(
            output.linkify(circuit_id), output.linkify(panel_id), _escape(name), len(device_ids)))
    for kind, panel_id, device_id, name, reason in issues:
        location = []
        if panel_id is not None:
            location.append(u"панель " + output.linkify(panel_id))
        if device_id is not None:
            location.append(u"устройство " + output.linkify(device_id))
        if name:
            location.append(u"нагрузка «{}»".format(_escape(name)))
        print(u"{} | {} | {}".format(kind, u", ".join(location), _escape(reason)))


def main():
    config = script.get_config()
    settings = _read_settings(config)
    if EXEC_PARAMS.config_mode:
        _configure(config, settings)
        return

    uidoc = HOST_APP.uidoc
    doc = uidoc.Document if uidoc else None
    if doc is None or doc.IsFamilyDocument or doc.IsReadOnly or doc.IsLinked:
        forms.alert(u"Откройте доступный для записи проект Revit.", title=TITLE)
        return
    view = uidoc.ActiveView
    if view is None or view.IsTemplate or not DB.FilteredElementCollector.IsViewValidForElementIteration(doc, view.Id):
        forms.alert(u"Откройте вид модели с панелями и устройствами.", title=TITLE)
        return
    missing = [label for key, label, _ in OPTIONS if not settings[key]]
    if missing:
        forms.alert(u"Заполните настройки через Shift+клик:\n" + u"\n".join(missing), title=TITLE)
        return
    if settings["fallback_type"] not in FALLBACK_TYPES:
        forms.alert(u"Выберите допустимый тип цепи через Shift+клик.", title=TITLE)
        return

    tasks, issues, element_count = collect_tasks(doc, view, settings)
    if tasks:
        message = u"Активный вид: {}\nГрупп «панель — нагрузка»: {}.\nСоздать цепи по найденным совпадениям?"
        if not forms.alert(message.format(view.Name, len(tasks)), title=TITLE, yes=True, no=True):
            return
    output = script.get_output()
    output.set_title(TITLE)
    created = create_circuits(doc, tasks, settings, issues) if tasks else []
    _report(output, view.Name, element_count, tasks, created, issues)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        script.get_logger().exception(u"Не удалось завершить команду создания цепей.")
        forms.alert(u"Команда прервана. Техническая причина указана в окне вывода pyRevit.",
                    title=TITLE, warn_icon=True)
