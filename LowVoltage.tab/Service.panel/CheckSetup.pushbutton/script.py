# -*- coding: utf-8 -*-

import sys

from pyrevit import HOST_APP, forms


engine_name = u"IronPython" if sys.platform == "cli" else u"Python"
engine_version = u"{}.{}.{}".format(*sys.version_info[:3])

forms.alert(
    u"Расширение загружено.\nRevit {}\n{} {}".format(
        HOST_APP.version, engine_name, engine_version
    ),
    title=u"Проверка загрузки",
)
