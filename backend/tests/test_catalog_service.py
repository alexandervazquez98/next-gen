"""Focused tests for category icon handling in catalog_service."""

from unittest.mock import MagicMock, patch

from models.core import Category


def _mock_driver() -> tuple[MagicMock, MagicMock]:
    session = MagicMock()
    driver = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver, session


def test_create_category_accepts_pr_329_icon_keys():
    driver, session = _mock_driver()

    with patch("services.catalog_service.get_db", return_value=driver):
        from services.catalog_service import create_category

        create_category(Category(name="Radio", icon_key="radio_telecom"))

    _, kwargs = session.run.call_args
    assert kwargs["icon_key"] == "radio_telecom"


def test_update_category_preserves_pr_329_icon_keys():
    driver, session = _mock_driver()

    with patch("services.catalog_service.get_db", return_value=driver):
        from services.catalog_service import update_category

        update_category("Legacy", "Distribution CI", "distribution_ci")

    _, kwargs = session.run.call_args
    assert kwargs["icon_key"] == "distribution_ci"


def test_get_categories_infers_pr_329_default_icons_from_names():
    driver, session = _mock_driver()
    session.run.return_value = [
        {"name": "Troncal de Red", "icon_key": None},
        {"name": "Distribución", "icon_key": None},
    ]

    with patch("services.catalog_service.get_db", return_value=driver):
        from services.catalog_service import get_categories

        result = get_categories()

    assert result == [
        {"name": "Troncal de Red", "icon_key": "trunk_link"},
        {"name": "Distribución", "icon_key": "distribution_ci"},
    ]
