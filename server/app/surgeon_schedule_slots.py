"""AM/PM slot assembly for surgeon schedule views."""


def open_surgical_location(loc) -> bool:
    if not loc:
        return False
    lt = (loc.location_type or "").lower()
    if lt == "hospital":
        return True
    name = (loc.name or "").lower()
    return "adventhealth" in name or "hospital" in name


def compute_schedule_slots(ws: dict) -> dict:
    am, pm = [], []
    footer = []

    if ws["day_off"]:
        am.append({"text": "Day off", "neutral": True, "color": None, "hospital": False})

    for cs in ws["clinics"]:
        if (cs.assignment_type or "assigned") == "off":
            entry = {
                "text": "OFF",
                "neutral": True,
                "color": "#cbd5e1",
                "hospital": False,
            }
            sess = (cs.session or "full").lower()
            if sess == "am":
                am.append(entry)
            elif sess == "pm":
                pm.append(entry)
            else:
                am.append({**entry, "text": "OFF - Full day"})
            continue

        loc = cs.location
        if not loc:
            continue
        hosp = open_surgical_location(loc)
        sess = (cs.session or "full").lower()
        entry = {
            "text": loc.name,
            "neutral": False,
            "color": loc.color or "#0ea5e9",
            "hospital": hosp,
        }
        if sess == "am":
            am.append(entry)
        elif sess == "pm":
            pm.append(entry)
        else:
            am.append({**entry, "text": f"{loc.name} - Full day"})

    for m in ws["meetings"]:
        if m.start_time is None:
            footer.append({"kind": "meeting", "text": m.title})
            continue
        line = {"text": m.title, "neutral": True, "color": None, "hospital": False}
        if m.start_time.hour < 12:
            am.append(line)
        else:
            pm.append(line)

    for sc in ws["surgeries"]:
        st = sc.start_time
        h = st.hour if st else 8
        label = (sc.patient_name or sc.procedure or "Surgery").strip() or "Surgery"
        if len(label) > 42:
            label = label[:39] + "..."
        col = (sc.location.color if sc.location else None) or None
        line = {
            "text": f"Surgery - {label}",
            "neutral": col is None,
            "color": col,
            "hospital": False,
        }
        if h < 12:
            am.append(line)
        else:
            pm.append(line)

    for p in ws.get("personal_items") or []:
        footer.append({"kind": "personal", "text": p.title, "id": p.id})

    return {"am": am, "pm": pm, "footer": footer}
