# -*- coding: utf-8 -*-

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from ss_circuit_rules import (
    CircuitRuleError, common_system_type, panel_load_names, remaining_connections,
)


class CircuitRulesTests(unittest.TestCase):
    def test_keeps_distinct_panel_names_in_order(self):
        self.assertEqual(panel_load_names(u"  Шлейф 2, Шлейф 1, Шлейф 2,  "),
                         [u"Шлейф 2", u"Шлейф 1"])
        self.assertEqual(panel_load_names(u"Шлейф,1"), [u"Шлейф,1"])
        self.assertEqual(panel_load_names(u"  "), [])

    def test_only_md_can_add_second_connection(self):
        self.assertEqual(remaining_connections(False, 0), 1)
        self.assertEqual(remaining_connections(False, 1), 0)
        self.assertEqual(remaining_connections(True, 0), 2)
        self.assertEqual(remaining_connections(True, 1), 1)
        self.assertEqual(remaining_connections(True, 2), 0)
        self.assertEqual(remaining_connections(True, 3), 0)

    def test_prefers_controls_only_if_all_devices_support_it(self):
        self.assertEqual(common_system_type([{"Controls", "Security"}, {"Controls"}],
                                            "Controls"), "Controls")
        self.assertEqual(common_system_type([{"Controls", "Security"}, {"Security"}],
                                            "Controls"), "Security")

    def test_does_not_pick_type_for_incompatible_or_ambiguous_group(self):
        with self.assertRaises(CircuitRuleError):
            common_system_type([{"Controls"}, {"Security"}], "Controls")
        with self.assertRaises(CircuitRuleError):
            common_system_type([{"Data", "Security"}, {"Data", "Security"}], "Controls")


if __name__ == "__main__":
    unittest.main()
