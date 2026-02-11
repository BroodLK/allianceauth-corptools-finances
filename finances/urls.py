"""App URLs"""

# Django
from django.urls import path

# AA allianceauth-corptools-finances
from finances import views

app_name: str = "finances"  # pylint: disable=invalid-name

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
]
