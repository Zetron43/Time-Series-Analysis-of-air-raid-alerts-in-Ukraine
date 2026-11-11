from src.bot.raion_utils import is_same_raion, get_raion_variants, normalize_raion_name

def test_collision_prevention():
    # 1. Dnistrovskyi vs Bilhorod-Dnistrovskyi (The user's reported bug)
    assert not is_same_raion("Дністровський район", "Білгород-Дністровський район")
    assert not is_same_raion("дністровський", "білгород-дністровський")
    assert not is_same_raion("Білгород-Дністровський", "Дністровський район")

    # 2. Podilskyi vs Kamianets-Podilskyi vs Mohyliv-Podilskyi
    assert not is_same_raion("Подільський район", "Кам'янець-Подільський район")
    assert not is_same_raion("Подільський район", "Кам’янець-Подільський район")
    assert not is_same_raion("Подільський район", "Могилів-Подільський район")
    assert not is_same_raion("Кам'янець-Подільський район", "Могилів-Подільський район")

    # 3. Lutskyi vs Prylutskyi
    assert not is_same_raion("Луцький район", "Прилуцький район")
    assert not is_same_raion("луцький", "прилуцький")

    # 4. Donetskyi vs Sievierodonetskyi
    assert not is_same_raion("Донецький район", "Сєвєродонецький район")


def test_positive_matches():
    # Basic variants with and without "район"
    assert is_same_raion("Дністровський район", "Дністровський")
    assert is_same_raion("чернівецький район", "Чернівецький")

    # Apostrophe variants
    assert is_same_raion("Кам’янець-Подільський район", "Кам'янець-Подільський")
    assert is_same_raion("Камʼянець-Подільський район", "Кам`янець-Подільський район")

    # Renamed / de-communized aliases
    assert is_same_raion("Червоноградський район", "Шептицький район")
    assert is_same_raion("Шептицький", "червоноградський")
    assert is_same_raion("Новомосковський район", "Самарівський район")
    assert is_same_raion("Красноградський район", "Берестинський район")
    assert is_same_raion("Новоград-Волинський район", "Звягельський район")
    assert is_same_raion("Володимир-Волинський район", "Володимирський район")

    # In parentheses
    assert is_same_raion("Шептицький (Червоноградський) район", "Червоноградський")
    assert is_same_raion("Червоноградський", "Шептицький (Червоноградський)")


if __name__ == "__main__":
    test_collision_prevention()
    test_positive_matches()
    print("ALL TESTS IN test_raion_matching.py PASSED!")
