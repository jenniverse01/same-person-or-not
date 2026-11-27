"""Small checks that the copied name, date, and country tools still behave."""
from spon.countries import canonical_country, countries_in_text
from spon.helpers import (
    birth_years_from_age,
    names_agree,
    parse_date,
    set_data_dir,
)


def test_dates_and_countries_need_no_dataset():
    assert parse_date("05/03/1968", "DMY") == (1968, 3, 5)
    assert parse_date("March 5, 1968") == (1968, 3, 5)
    assert parse_date("1968") == (1968, None, None)
    assert parse_date("05/03/1968", "AUTO") == (1968, None, None)
    assert birth_years_from_age(45, 2019) == [1973, 1974]
    assert canonical_country("GB") == "United Kingdom"
    assert canonical_country("British") == "United Kingdom"
    assert canonical_country("UK") == "United Kingdom"
    assert canonical_country("International") is None
    assert countries_in_text("a Portugal passport and time in France") == ["Portugal", "France"]


def test_name_variants_follow_the_data_folder(data_dir):
    set_data_dir(str(data_dir))
    agree, matched = names_agree("Mohammed Ali", "Mohamed Ali")
    assert agree is True and matched >= 2
    agree, _matched = names_agree("Northwind Trading Limited", "Northwind Trading GmbH", company=True)
    assert agree is True
    agree, _matched = names_agree("Amara Boateng", "Okonkwo, Lina")
    assert agree is False
