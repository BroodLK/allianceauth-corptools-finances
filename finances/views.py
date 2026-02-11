"""App Views"""

# Standard Library
from datetime import date, datetime, time, timedelta
from decimal import Decimal

# Django
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.http import urlencode

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


def _parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _clean_query_params(request, remove_keys):
    params = request.GET.copy()
    for key in remove_keys:
        params.pop(key, None)
    return params.urlencode()


def _series_stats(values, start_day):
    if not values:
        return {
            "total": Decimal("0.00"),
            "avg": Decimal("0.00"),
            "max": Decimal("0.00"),
            "max_date": None,
            "active_days": 0,
            "days": 0,
        }

    total = sum(values, Decimal("0.00"))
    days = len(values)
    avg = total / days if days else Decimal("0.00")
    max_value = max(values)
    max_index = values.index(max_value)
    max_date = start_day + timedelta(days=max_index) if max_value > 0 else None
    active_days = sum(1 for value in values if value > 0)

    return {
        "total": total,
        "avg": avg,
        "max": max_value,
        "max_date": max_date,
        "active_days": active_days,
        "days": days,
    }


def _build_daily_series(entries, start_date, end_date, abs_values=False):
    series = list(
        entries.annotate(day=TruncDate("date"))
        .values("day")
        .annotate(total=Coalesce(Sum("amount"), Decimal("0.00")))
        .order_by("day")
    )
    totals_by_day = {row["day"]: row["total"] for row in series}

    days_count = (end_date.date() - start_date.date()).days
    values = []
    points = []
    for offset in range(days_count + 1):
        day = start_date.date() + timedelta(days=offset)
        total = totals_by_day.get(day, Decimal("0.00"))
        if abs_values:
            total = abs(total)
        values.append(total)
        points.append(
            {
                "date": day.isoformat(),
                "total": float(total),
            }
        )

    stats = _series_stats(values, start_date.date())

    return points, stats


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

    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)
    custom_start = _parse_date(request.GET.get("start_date"))
    custom_end = _parse_date(request.GET.get("end_date"))
    if custom_start or custom_end:
        if not custom_start:
            custom_start = custom_end
        if not custom_end:
            custom_end = custom_start
        if custom_start > custom_end:
            custom_start, custom_end = custom_end, custom_start
        tz = timezone.get_current_timezone()
        start_date = timezone.make_aware(datetime.combine(custom_start, time.min), tz)
        end_date = timezone.make_aware(datetime.combine(custom_end, time.max), tz)
        now = timezone.now()
        if end_date > now:
            end_date = now

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
        date__lte=end_date,
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

    expense_ref_type_options = list(
        entries.filter(amount__lt=0)
        .values_list("ref_type", flat=True)
        .distinct()
        .order_by("ref_type")
    )
    expense_ref_type_choices = [
        {"value": ref_type, "label": _format_ref_type(ref_type)}
        for ref_type in expense_ref_type_options
    ]

    selected_expense_ref_types = request.GET.getlist("expense_ref_types")
    if selected_expense_ref_types:
        selected_expense_ref_types = [
            ref for ref in selected_expense_ref_types if ref in expense_ref_type_options
        ]
    if not selected_expense_ref_types:
        selected_expense_ref_types = expense_ref_type_options

    income_entries = entries.filter(amount__gt=0)
    if selected_ref_types:
        income_entries = income_entries.filter(ref_type__in=selected_ref_types)

    expense_entries = entries.filter(amount__lt=0)
    if selected_expense_ref_types:
        expense_entries = expense_entries.filter(ref_type__in=selected_expense_ref_types)

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

    income_series_points, income_stats = _build_daily_series(
        income_entries, start_date, end_date
    )
    expense_series_points, expense_stats = _build_daily_series(
        expense_entries, start_date, end_date, abs_values=True
    )

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
                Sum("amount", filter=Q(amount__lt=0, ref_type__in=selected_expense_ref_types)),
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
                "division_id": division.id,
            }
        )

    drilldown = None
    drill_type = request.GET.get("drill")
    if drill_type:
        drill_qs = (
            entries.select_related(
                "division",
                "division__corporation__corporation",
                "first_party_name",
                "second_party_name",
            )
            .order_by("-date")
        )
        drill_title = ""

        if drill_type == "income_ref":
            ref_type = request.GET.get("ref_type", "")
            if ref_type in selected_ref_types:
                drill_qs = drill_qs.filter(amount__gt=0, ref_type=ref_type)
                drill_title = f"Income: {_format_ref_type(ref_type)}"
            else:
                drill_qs = drill_qs.none()
        elif drill_type == "expense_ref":
            ref_type = request.GET.get("ref_type", "")
            if ref_type in selected_expense_ref_types:
                drill_qs = drill_qs.filter(amount__lt=0, ref_type=ref_type)
                drill_title = f"Expenses: {_format_ref_type(ref_type)}"
            else:
                drill_qs = drill_qs.none()
        elif drill_type == "division":
            try:
                division_id = int(request.GET.get("division_id", ""))
            except (TypeError, ValueError):
                division_id = None

            if division_id and division_id in division_ids:
                drill_qs = drill_qs.filter(division_id=division_id).filter(
                    Q(amount__gt=0, ref_type__in=selected_ref_types)
                    | Q(amount__lt=0, ref_type__in=selected_expense_ref_types)
                )
                division_match = next(
                    (row for row in division_rows if row["division_id"] == division_id),
                    None,
                )
                if division_match:
                    division_label = f"{division_match['corp_name']} - {division_match['division']}"
                    if division_match["name"]:
                        division_label = f"{division_label} {division_match['name']}"
                    drill_title = f"Division: {division_label}"
                else:
                    drill_title = "Division"
            else:
                drill_qs = drill_qs.none()

        drill_rows = []
        for entry in drill_qs:
            drill_rows.append(
                {
                    "date": entry.date,
                    "entry_id": entry.entry_id,
                    "division": entry.division.division,
                    "division_name": entry.division.name or "",
                    "corp_name": entry.division.corporation.corporation.corporation_name,
                    "ref_type": entry.ref_type,
                    "amount": entry.amount,
                    "balance": entry.balance,
                    "first_party_id": entry.first_party_id,
                    "first_party_name": getattr(entry.first_party_name, "name", ""),
                    "first_party_category": getattr(entry.first_party_name, "category", ""),
                    "second_party_id": entry.second_party_id,
                    "second_party_name": getattr(entry.second_party_name, "name", ""),
                    "second_party_category": getattr(entry.second_party_name, "category", ""),
                    "context_id": entry.context_id,
                    "context_id_type": entry.context_id_type,
                    "description": entry.description,
                    "reason": entry.reason,
                    "tax": entry.tax,
                    "tax_receiver_id": entry.tax_receiver_id,
                    "processed": entry.processed,
                }
            )

        clear_query = _clean_query_params(
            request,
            [
                "drill",
                "ref_type",
                "division_id",
            ],
        )

        drilldown = {
            "title": drill_title,
            "rows": drill_rows,
            "count": len(drill_rows),
            "clear_query": clear_query,
        }

    context = {
        "days": days,
        "days_options": days_options,
        "start_date": start_date,
        "end_date": end_date,
        "custom_start_value": custom_start.isoformat() if custom_start else "",
        "custom_end_value": custom_end.isoformat() if custom_end else "",
        "division_rows": division_rows,
        "division_ids": set(division_ids),
        "divisions": all_divisions,
        "ref_type_choices": ref_type_choices,
        "selected_ref_types": set(selected_ref_types),
        "expense_ref_type_choices": expense_ref_type_choices,
        "selected_expense_ref_types": set(selected_expense_ref_types),
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
        "income_series": income_series_points,
        "expense_series": expense_series_points,
        "income_stats": income_stats,
        "expense_stats": expense_stats,
        "drilldown": drilldown,
    }

    return render(request, "finances/index.html", context)
