"""Hook into Alliance Auth"""

# Django
from django.utils.translation import gettext_lazy as _

# Alliance Auth
from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

# AA allianceauth-corptools-finances
from finances import urls


class FinancesMenuItem(MenuItemHook):
    """This class ensures only authorized users will see the menu entry"""

    def __init__(self):
        # setup menu entry for sidebar
        MenuItemHook.__init__(
            self,
            _("Corp Finances"),
            "fas fa-chart-line fa-fw",
            "finances:dashboard",
            navactive=["finances:"],
        )

    def render(self, request):
        """Render the menu item"""

        if any(
            request.user.has_perm(perm)
            for perm in [
                "corptools.own_corp_manager",
                "corptools.alliance_corp_manager",
                "corptools.state_corp_manager",
                "corptools.global_corp_manager",
                "corptools.holding_corp_wallets",
            ]
        ):
            return MenuItemHook.render(self, request)

        return ""


@hooks.register("menu_item_hook")
def register_menu():
    """Register the menu item"""

    return FinancesMenuItem()


@hooks.register("url_hook")
def register_urls():
    """Register app urls"""

    return UrlHook(urls, "finances", r"^finances/")
