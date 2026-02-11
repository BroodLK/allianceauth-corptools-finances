"""App Configuration"""

# Django
from django.apps import AppConfig

# AA allianceauth-corptools-finances
from finances import __version__


class FinancesConfig(AppConfig):
    """App Config"""

    name = "finances"
    label = "finances"
    verbose_name = f"Finances v{__version__}"
