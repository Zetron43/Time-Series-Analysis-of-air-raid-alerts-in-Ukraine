"""End-to-end integration test verifying early warning neighbor matching.

Ensures:
1. Alert in 'Білгород-Дністровський район' DOES NOT falsely trigger 'Дністровський район'
   as an alert neighbor for 'Чернівецький район'.
2. Real alert in 'Дністровський район' DOES trigger as an alert neighbor for 'Чернівецький район'.
3. Real alert in 'Коломийський район' (cross-oblast from Ivano-Frankivsk) DOES trigger
   as an alert neighbor for 'Чернівецький район'.
"""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.bot.interactive_bot import ThreatAnalyzer
from src.bot.raion_utils import is_same_raion


def test_neighbor_alert_discrimination():
    bot = ThreatAnalyzer()

    # Case 1: Mock all_raions_status where ONLY Bilhorod-Dnistrovskyi is on alert (Odesa oblast)
    mock_all_raions_only_bilhorod = {
        "Білгород-Дністровський район": {
            "name": "Білгород-Дністровський район",
            "region_name": "Одеська область",
            "active": True,
            "level": "YELLOW",
            "type": "YELLOW",
            "started_at": "2026-11-11T23:40:00Z"
        },
        "Чернівецький район": {
            "name": "Чернівецький район",
            "region_name": "Чернівецька область",
            "active": False,
            "level": "CLEAR",
            "type": "CLEAR"
        },
        "Дністровський район": {
            "name": "Дністровський район",
            "region_name": "Чернівецька область",
            "active": False,
            "level": "CLEAR",
            "type": "CLEAR"
        }
    }

    # Patch live_client and threat_syncer to return this mock state
    class MockThreatSyncer:
        class State:
            is_warm = True
            def get_snapshot(self):
                return {
                    "alerts_raions": mock_all_raions_only_bilhorod,
                    "raw_threats": []
                }
        state = State()
        def get_raion_status(self, r_name):
            for k, v in mock_all_raions_only_bilhorod.items():
                if is_same_raion(r_name, k):
                    return v
            return {"active": False, "level": "CLEAR"}

    bot.threat_syncer = MockThreatSyncer()

    # Run analysis for Chernivtsi raion
    res = bot.analyze_threats_for_region("chernivtsi", "15m", raion_name="Чернівецький район")
    nb_alarms = res.get("neighbors_alarms", [])

    print("Test 1 (Bilhorod-Dnistrovskyi alert active):")
    print("  Neighbors alarms detected for Чернівецький район:", nb_alarms)
    assert len(nb_alarms) == 0, f"Expected 0 neighbor alarms, got: {nb_alarms}"
    print("  -> PASSED! No false positive for Дністровський район.")

    # Case 2: Now add real alert in Dnistrovskyi raion
    mock_all_raions_real_dnistrovskyi = dict(mock_all_raions_only_bilhorod)
    mock_all_raions_real_dnistrovskyi["Дністровський район"] = {
        "name": "Дністровський район",
        "region_name": "Чернівецька область",
        "active": True,
        "level": "YELLOW",
        "type": "YELLOW",
        "started_at": "2026-11-11T23:42:00Z"
    }

    class MockThreatSyncerReal:
        class State:
            is_warm = True
            def get_snapshot(self):
                return {
                    "alerts_raions": mock_all_raions_real_dnistrovskyi,
                    "raw_threats": []
                }
        state = State()
        def get_raion_status(self, r_name):
            for k, v in mock_all_raions_real_dnistrovskyi.items():
                if is_same_raion(r_name, k):
                    return v
            return {"active": False, "level": "CLEAR"}

    bot.threat_syncer = MockThreatSyncerReal()
    res2 = bot.analyze_threats_for_region("chernivtsi", "15m", raion_name="Чернівецький район")
    nb_alarms2 = res2.get("neighbors_alarms", [])

    print("\nTest 2 (Real Дністровський район alert active):")
    print("  Neighbors alarms detected for Чернівецький район:", nb_alarms2)
    assert len(nb_alarms2) == 1, f"Expected 1 neighbor alarm, got: {nb_alarms2}"
    assert nb_alarms2[0][0] == "Дністровський район"
    print("  -> PASSED! Legitimate alert in Дністровський район successfully detected.")

    # Case 3: Cross-oblast neighbor Kolomyiskyi raion (Ivano-Frankivsk oblast)
    mock_all_raions_cross_oblast = dict(mock_all_raions_only_bilhorod)
    mock_all_raions_cross_oblast["Коломийський район"] = {
        "name": "Коломийський район",
        "region_name": "Івано-Франківська область",
        "active": True,
        "level": "RED",
        "type": "RED",
        "started_at": "2026-11-11T23:45:00Z"
    }

    class MockThreatSyncerCross:
        class State:
            is_warm = True
            def get_snapshot(self):
                return {
                    "alerts_raions": mock_all_raions_cross_oblast,
                    "raw_threats": []
                }
        state = State()
        def get_raion_status(self, r_name):
            for k, v in mock_all_raions_cross_oblast.items():
                if is_same_raion(r_name, k):
                    return v
            return {"active": False, "level": "CLEAR"}

    bot.threat_syncer = MockThreatSyncerCross()
    res3 = bot.analyze_threats_for_region("chernivtsi", "15m", raion_name="Чернівецький район")
    nb_alarms3 = res3.get("neighbors_alarms", [])

    print("\nTest 3 (Cross-oblast Коломийський район alert active):")
    print("  Neighbors alarms detected for Чернівецький район:", nb_alarms3)
    assert len(nb_alarms3) == 1, f"Expected 1 cross-oblast neighbor alarm, got: {nb_alarms3}"
    assert nb_alarms3[0][0] == "Коломийський район"
    print("  -> PASSED! Cross-oblast neighbor detected without collision.")


if __name__ == "__main__":
    test_neighbor_alert_discrimination()
    print("\nALL NEIGHBOR ALERT TESTS PASSED!")
