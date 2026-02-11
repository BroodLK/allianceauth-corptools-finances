"""App Views"""

# Standard Library
from datetime import timedelta
from decimal import Decimal

# Django
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

# Corptools
from corptools.models import (
    CorporationWalletDivision,
    CorporationWalletJournalEntry,
)

WALLET_PERMISSIONS = (
    "corptools.own_corp_manager",
    "corptools.alliance_corp_manager",
    "corptools.state_corp_manager",
    "corptools.global_corp_manager",
    "corptools.holding_corp_wallets",
)


def _user_can_view_wallets(user) -> bool:
    return any(user.has_perm(perm) for perm in WALLET_PERMISSIONS)


def _parse_int_list(values):
    output = []
    for value in values:
        try:
            output.append(int(value))
        except (TypeError, ValueError):
            continue
    return output


def _format_ref_type(ref_type: str) -> str:
    return ref_type.replace("_", " ").title()


@login_required
def dashboard(request) -> HttpResponse:
    if not _user_can_view_wallets(request.user):
        raise PermissionDenied("No permission to view corporation wallet data.")

    days_options = [7, 30, 60, 90, 180, 365]
    try:
        days = int(request.GET.get("days", 30))
    except (TypeError, ValueError):
        days = 30

    if days not in days_options:
        days = 30

    start_date = timezone.now() - timedelta(days=days)

    all_divisions = (
        CorporationWalletDivision.get_visible(request.user)
        .select_related("corporation__corporation")
        .order_by("corporation__corporation__corporation_name", "division")
    )

    selected_divisions = _parse_int_list(request.GET.getlist("divisions"))
    if selected_divisions:
        selected_divisions_qs = all_divisions.filter(id__in=selected_divisions)
    else:
        selected_divisions_qs = all_divisions

    division_ids = list(selected_divisions_qs.values_list("id", flat=True))
    if not division_ids:
        selected_divisions_qs = all_divisions
        division_ids = list(all_divisions.values_list("id", flat=True))

    entries = CorporationWalletJournalEntry.get_visible(request.user).filter(
        date__gte=start_date,
        division_id__in=division_ids,
    )

    ref_type_options = list(
        entries.filter(amount__gt=0)
        .values_list("ref_type", flat=True)
        .distinct()
        .order_by("ref_type")
    )
    ref_type_choices = [
        {"value": ref_type, "label": _format_ref_type(ref_type)}
        for ref_type in ref_type_options
    ]

    selected_ref_types = request.GET.getlist("ref_types")
    if selected_ref_types:
        selected_ref_types = [ref for ref in selected_ref_types if ref in ref_type_options]
    if not selected_ref_types:
        selected_ref_types = ref_type_options

    income_entries = entries.filter(amount__gt=0)
    if selected_ref_types:
        income_entries = income_entries.filter(ref_type__in=selected_ref_types)

    expense_entries = entries.filter(amount__lt=0)

    income_total = income_entries.aggregate(
        total=Coalesce(Sum("amount"), Decimal("0.00"))
    )["total"]
    expense_total = expense_entries.aggregate(
        total=Coalesce(Sum("amount"), Decimal("0.00"))
    )["total"]

    income_by_ref = list(
        income_entries.values("ref_type")
        .annotate(total=Coalesce(Sum("amount"), Decimal("0.00")), count=Count("id"))
        .order_by("-total")
    )
    for row in income_by_ref:
        row["label"] = _format_ref_type(row["ref_type"])

    expense_by_ref = list(
        expense_entries.values("ref_type")
        .annotate(total=Coalesce(Sum("amount"), Decimal("0.00")), count=Count("id"))
        .order_by("total")
    )
    for row in expense_by_ref:
        row["label"] = _format_ref_type(row["ref_type"])
        row["total_abs"] = abs(row["total"])

    division_totals = {
        row["division_id"]: row
        for row in entries.values(
            "division_id",
            "division__division",
            "division__name",
            "division__corporation__corporation__corporation_name",
        ).annotate(
            income=Coalesce(
                Sum("amount", filter=Q(amount__gt=0, ref_type__in=selected_ref_types)),
                Decimal("0.00"),
            ),
            expenses=Coalesce(
                Sum("amount", filter=Q(amount__lt=0)),
                Decimal("0.00"),
            ),
        )
    }

    division_rows = []
    for division in selected_divisions_qs:
        totals = division_totals.get(division.id, {})
        income = totals.get("income", Decimal("0.00"))
        expenses = totals.get("expenses", Decimal("0.00"))
        division_rows.append(
            {
                "corp_name": division.corporation.corporation.corporation_name,
                "division": division.division,
                "name": division.name or "",
                "balance": division.balance,
                "income": income,
                "expenses": expenses,
                "net": income + expenses,
            }
        )

    context = {
        "days": days,
        "days_options": days_options,
        "start_date": start_date,
        "end_date": timezone.now(),
        "division_rows": division_rows,
        "division_ids": set(division_ids),
        "divisions": all_divisions,
        "ref_type_choices": ref_type_choices,
        "selected_ref_types": set(selected_ref_types),
        "summary": {
            "income_total": income_total,
            "expense_total": expense_total,
            "expense_total_abs": abs(expense_total),
            "net_total": income_total + expense_total,
            "entry_count": entries.count(),
            "income_count": income_entries.count(),
            "expense_count": expense_entries.count(),
        },
        "income_by_ref": income_by_ref,
        "expense_by_ref": expense_by_ref,
    }

    return render(request, "finances/index.html", context)
