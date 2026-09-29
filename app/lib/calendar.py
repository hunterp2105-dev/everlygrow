"""Calendar (§16 steps 26-27): merges real posts/deliverables with the
holiday/awareness-day reference table into one event feed, for both the
customer (read-only, own data) and admin (cross-customer) views.

Posts/deliverables are computed from `generations`/`design_deliverables`
directly, not duplicated into the Phase 1 `calendar_events` shell table —
see migration 0010's note on why. Holidays recur annually, so their
occurrence date is computed per-query from month/day, not stored fixed.
"""

from datetime import date


def holidays_in_range(client, start: date, end: date, niche: str | None = None) -> list[dict]:
    rows = client.table("holidays").select("*").execute().data or []
    events = []
    for row in rows:
        if not row["is_general"] and (niche is None or niche not in (row.get("niche_tags") or [])):
            continue
        for year in range(start.year, end.year + 1):
            try:
                occurrence = date(year, row["month"], row["day"])
            except ValueError:
                continue  # e.g. Feb 29 on a non-leap year
            if start <= occurrence <= end:
                events.append(
                    {
                        "date": occurrence,
                        "type": "holiday",
                        "title": row["name"],
                        "content_idea_prompt": row.get("content_idea_prompt"),
                        "is_general": row["is_general"],
                    }
                )
    return events


def _posts_in_range(client, start: date, end: date, customer_id: str | None) -> list[dict]:
    query = (
        client.table("generations")
        .select("id, customer_id, template_description, post_caption, post_url, published_at, customers(name)")
        .eq("publish_status", "published")
        .gte("published_at", start.isoformat())
        .lte("published_at", f"{end.isoformat()}T23:59:59")
    )
    if customer_id:
        query = query.eq("customer_id", customer_id)
    rows = query.execute().data or []
    return [
        {
            "date": date.fromisoformat(row["published_at"][:10]),
            "type": "post",
            "title": row.get("template_description") or "Social post",
            "detail": row.get("post_caption"),
            "post_url": row.get("post_url"),
            "generation_id": row["id"],
            "customer_name": (row.get("customers") or {}).get("name"),
        }
        for row in rows
        if row.get("published_at")
    ]


def _deliverables_in_range(client, start: date, end: date, customer_id: str | None) -> list[dict]:
    query = (
        client.table("design_deliverables")
        .select("id, generation_id, type, occasion, delivered_at, customer_id, customers(name), generations(template_description)")
        .eq("status", "delivered")
        .gte("delivered_at", start.isoformat())
        .lte("delivered_at", f"{end.isoformat()}T23:59:59")
    )
    if customer_id:
        query = query.eq("customer_id", customer_id)
    rows = query.execute().data or []
    return [
        {
            "date": date.fromisoformat(row["delivered_at"][:10]),
            "type": "deliverable",
            "title": f"{row['type'].title()}: {row.get('occasion') or (row.get('generations') or {}).get('template_description') or ''}",
            "detail": None,
            "generation_id": row["generation_id"],
            "customer_name": (row.get("customers") or {}).get("name"),
        }
        for row in rows
        if row.get("delivered_at")
    ]


def customer_calendar(client, customer_id: str, start: date, end: date) -> list[dict]:
    customer = client.table("customers").select("niche").eq("id", customer_id).maybe_single().execute()
    niche = (customer.data or {}).get("niche") if customer else None

    events = (
        _posts_in_range(client, start, end, customer_id)
        + _deliverables_in_range(client, start, end, customer_id)
        + holidays_in_range(client, start, end, niche)
    )
    return sorted(events, key=lambda e: e["date"])


def admin_calendar(client, start: date, end: date, customer_id: str | None = None) -> list[dict]:
    events = (
        _posts_in_range(client, start, end, customer_id)
        + _deliverables_in_range(client, start, end, customer_id)
        + holidays_in_range(client, start, end, niche=None)  # general only, cross-customer view has no single niche
    )
    return sorted(events, key=lambda e: e["date"])
