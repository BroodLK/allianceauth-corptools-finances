from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from finances.views import _build_subsidy_section


class _UserStub:
    def __init__(self, has_access=True):
        self._has_access = has_access

    def has_perm(self, perm):
        return self._has_access if perm == "aasubsidy.basic_access" else False


class TestSubsidyIntegration(SimpleTestCase):
    def setUp(self):
        self.end_date = timezone.now()
        self.start_date = self.end_date - timedelta(days=30)

    @patch("finances.views.apps.is_installed", return_value=False)
    def test_subsidy_section_returns_none_when_app_not_installed(self, mock_is_installed):
        result = _build_subsidy_section(
            _UserStub(has_access=True),
            self.start_date,
            self.end_date,
            [],
        )

        self.assertIsNone(result)
        mock_is_installed.assert_called_once_with("aasubsidy")

    @patch("finances.views.apps.is_installed", return_value=True)
    def test_subsidy_section_returns_none_without_permission(self, mock_is_installed):
        with patch("finances.views.apps.get_model") as mock_get_model:
            result = _build_subsidy_section(
                _UserStub(has_access=False),
                self.start_date,
                self.end_date,
                [],
            )

        self.assertIsNone(result)
        mock_is_installed.assert_called_once_with("aasubsidy")
        mock_get_model.assert_not_called()
