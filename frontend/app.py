from datetime import date
from typing import Any

import streamlit as st

from services.api_client import (
    ApiError,
    login_user,
    get_current_user,
    create_trip,
    plan_trip,
    preview_budget,
    register_user,
    search_transport_options,
    select_hotel,
)
from utils.validation import (
    TRANSPORT_LABELS,
    extract_display_value,
    get_max_date,
    parse_preferences,
    validate_trip_input,
)

st.set_page_config(page_title="AI Travel Planner", page_icon="✈️", layout="centered")


# =========================================================
# SESSION STATE
# =========================================================

def init_session_state():
    defaults = {
        "authenticated": False,
        "access_token": None,
        "username": None,
        "trip_id": None,
        "itinerary_result": None,
        "hotel_selection_result": None,
        "is_planning": False,
        "is_searching_transport": False,
        "flash_error": None,
        "outbound_searched": False,
        "available_outbound_options": [],
        "selected_outbound_idx": None,
        "selected_outbound_class": None,
        "return_searched": False,
        "available_return_options": [],
        "selected_return_idx": None,
        "selected_return_class": None,
        "selected_hotel_id": None,
        "transport_search_generation": 0,
        "search_params": {},
        "trip_form_state": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


def _clear_transport_search_state(increment_generation: bool = True):
    """Clear every live transport selection/result before a new search."""
    st.session_state.outbound_searched = False
    st.session_state.available_outbound_options = []
    st.session_state.selected_outbound_idx = None
    st.session_state.selected_outbound_class = None
    st.session_state.return_searched = False
    st.session_state.available_return_options = []
    st.session_state.selected_return_idx = None
    st.session_state.selected_return_class = None

    if increment_generation:
        st.session_state.transport_search_generation = (
            int(st.session_state.get("transport_search_generation", 0)) + 1
        )


def do_logout(message: str = None):
    """Clears the authenticated session and all trip-specific UI state."""
    st.session_state.authenticated = False
    st.session_state.access_token = None
    st.session_state.username = None
    st.session_state.trip_id = None
    st.session_state.itinerary_result = None
    st.session_state.hotel_selection_result = None
    st.session_state.selected_hotel_id = None
    st.session_state.is_planning = False
    st.session_state.is_searching_transport = False
    _clear_transport_search_state(increment_generation=True)
    st.session_state.search_params = {}
    st.session_state.trip_form_state = {}
    if message:
        st.session_state.flash_error = message


def reset_transport_selection():
    """Reset transport results and selections for a genuinely new search."""
    _clear_transport_search_state(increment_generation=True)
    st.session_state.itinerary_result = None
    st.session_state.hotel_selection_result = None
    st.session_state.selected_hotel_id = None
    st.session_state.trip_form_state = {}


# =========================================================
# AUTH SECTION (LOGIN / REGISTER)
# =========================================================

def render_auth():
    if st.session_state.flash_error:
        st.error(st.session_state.flash_error)
        st.session_state.flash_error = None

    tab_login, tab_register = st.tabs(["Login", "Register"])

    with tab_login:
        st.caption("Login to start planning your trip.")

        with st.form("login_form"):
            email = st.text_input("Email", placeholder="Enter email")
            password = st.text_input("Password", type="password", placeholder="Enter password")
            submitted = st.form_submit_button("Login", type="primary", use_container_width=True)

        if submitted:
            if not email or not password:
                st.error("Please enter both email and password.")
            else:
                try:
                    with st.spinner("Logging in..."):
                        result = login_user(email, password)
                        token = result.get("token")

                        # Do not commit authenticated UI state until the
                        # protected profile endpoint also succeeds.
                        profile = get_current_user(token)

                    raw_username = profile.get("username")
                    username = (
                        str(raw_username).strip()
                        if raw_username is not None
                        else ""
                    )
                    if username.casefold() in {"", "none", "null", "undefined"}:
                        username = email.strip()

                    st.session_state.access_token = token
                    st.session_state.username = username
                    st.session_state.authenticated = True
                    st.rerun()
                except ApiError as e:
                    st.session_state.authenticated = False
                    st.session_state.access_token = None
                    st.session_state.username = None
                    st.error(e.message)

    with tab_register:
        st.caption("Create a new account to plan trips.")

        with st.form("register_form"):
            reg_username = st.text_input(
                "Username", placeholder="Choose a username", key="reg_username"
            )
            reg_email = st.text_input("Email", placeholder="Enter email", key="reg_email")
            reg_password = st.text_input(
                "Password", type="password", placeholder="Create password", key="reg_password"
            )
            reg_submitted = st.form_submit_button("Create Account", type="primary", use_container_width=True)

        if reg_submitted:
            if not reg_username or not reg_email or not reg_password:
                st.error("Please enter username, email, and password.")
            else:
                try:
                    with st.spinner("Creating account..."):
                        register_user(reg_username, reg_email, reg_password)
                    st.success("Account created! Switch to the Login tab to log in.")
                except ApiError as e:
                    st.error(e.message)


# =========================================================
# TRANSPORT SELECTION HELPERS
# =========================================================

def format_transport_option_label(option: dict) -> str:
    """Formats a transport option for radio/select display."""
    if not isinstance(option, dict):
        return "Unknown Option"

    t_type = str(option.get("type", "")).lower()
    is_flight = "flight" in t_type or bool(option.get("airline") or option.get("flight_number") or option.get("flight_name"))
    icon = "✈️" if is_flight else "🚆"

    name = option.get("train_name") or option.get("flight_name") or option.get("name") or option.get("airline") or "Transport"
    num = str(option.get("train_number") or option.get("flight_number") or "").strip()
    name_str = f"{name} ({num})" if (num and num not in str(name)) else str(name)

    orig = option.get("from_station_code") or option.get("from_code") or option.get("actual_train_origin") or "Origin"
    dest = option.get("to_station_code") or option.get("to_code") or option.get("actual_train_destination") or "Destination"

    dep = extract_display_value(
        option.get("departure") or option.get("departure_time")
    )
    arr = extract_display_value(
        option.get("arrival") or option.get("arrival_time")
    )
    dur = extract_display_value(option.get("duration"))

    time_str = f" | {dep} → {arr}" if dep and arr else ""
    dur_str = f" ({dur})" if dur else ""

    return f"{icon} {name_str} | {orig} → {dest}{time_str}{dur_str}"


def _safe_float(value):
    """Return a finite float or None, never fabricate zero for missing data."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def get_option_classes(option: dict) -> list[dict]:
    """Extract only provider-supplied travel classes with valid fares."""
    if not isinstance(option, dict):
        return []

    classes = option.get("available_classes")
    if isinstance(classes, list) and classes:
        result = []
        for cls in classes:
            if not isinstance(cls, dict):
                continue
            code = str(cls.get("code") or "").strip()
            if not code:
                continue
            fare = _safe_float(cls.get("fare"))
            if fare is None or fare < 0:
                continue
            result.append({
                "code": code,
                "name": str(cls.get("name") or code).strip(),
                "fare": fare,
            })
        if result:
            return result

    fares = option.get("fares")
    if isinstance(fares, list) and fares:
        result = []
        for fare_item in fares:
            if not isinstance(fare_item, dict):
                continue
            code = str(fare_item.get("class_code") or "").strip()
            fare = _safe_float(fare_item.get("amount"))
            if not code or fare is None or fare < 0:
                continue
            result.append({
                "code": code,
                "name": str(
                    fare_item.get("class_name") or f"Class {code}"
                ).strip(),
                "fare": fare,
            })
        if result:
            return result

    # A selected class is a valid fallback only when the backend explicitly
    # supplied both the class and its fare. Never invent STD/Standard/₹0.
    c_code = str(option.get("selected_class") or "").strip()
    c_name = str(
        option.get("selected_class_name")
        or option.get("class_name")
        or ""
    ).strip()
    fare = _safe_float(
        option.get("fare")
        if option.get("fare") is not None
        else option.get("price")
    )

    if c_code and fare is not None and fare >= 0:
        return [{
            "code": c_code,
            "name": c_name or c_code,
            "fare": fare,
        }]

    return []


def format_class_label(cls_dict: dict) -> str:
    """Format a validated travel class."""
    if not isinstance(cls_dict, dict):
        return "Travel Class"

    name = str(cls_dict.get("name") or cls_dict.get("code") or "Travel Class")
    code = str(cls_dict.get("code") or "")
    fare = _safe_float(cls_dict.get("fare"))

    if fare is None:
        return f"{name} ({code})" if code and code not in name else name

    if code and code not in name:
        return f"{name} ({code}) — ₹{fare:,.0f} / person"
    return f"{name} — ₹{fare:,.0f} / person"


# =========================================================
# TRIP PLANNER FORM & SELECTION FLOW
# =========================================================

def _clamp_trip_dates_to_new_max():
    """on_change callback for transport preference selectbox."""
    new_preference = st.session_state.get("trip_transport_preference", "train")
    new_max = get_max_date(new_preference, date.today())

    for date_key in ("trip_start_date", "trip_end_date"):
        current_value = st.session_state.get(date_key)
        if isinstance(current_value, date) and current_value > new_max:
            st.session_state[date_key] = new_max


def handle_search_outbound_transport(origin, destination, start_date, end_date, adults, children, budget, transport_preference, preferences_raw):
    """Searches live outbound transport options only."""
    if not st.session_state.access_token:
        st.error("Please login first.")
        return

    # A new search is a new UI state. Clear old results even when validation
    # fails, so the previous route can never remain selectable accidentally.
    _clear_transport_search_state(increment_generation=True)
    st.session_state.itinerary_result = None
    st.session_state.hotel_selection_result = None
    st.session_state.selected_hotel_id = None

    errors = validate_trip_input(
        origin=origin,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        adults=adults,
        children=children,
        budget=budget,
        transport_preference=transport_preference,
    )

    if errors:
        for message in errors:
            st.error(message)
        return

    st.session_state.is_searching_transport = True

    try:
        with st.spinner(f"Searching available outbound {transport_preference}s for {start_date.strftime('%d %b %Y')}..."):
            outbound_req = {
                "origin": origin.strip(),
                "destination": destination.strip(),
                "travel_date": start_date.isoformat(),
                "mode": transport_preference,
                "leg": "outbound",
                "adults": int(adults),
                "children": int(children),
                "budget": float(budget) if budget is not None else None,
            }
            outbound_res = search_transport_options(st.session_state.access_token, outbound_req)
            outbound_opts = outbound_res.get("options") or []

            # The state was already cleared before the request. Only the
            # current response is allowed to populate the selection state.
            st.session_state.available_outbound_options = (
                outbound_opts if isinstance(outbound_opts, list) else []
            )
            st.session_state.outbound_searched = True
            st.session_state.search_params = {
                "origin": origin.strip(),
                "destination": destination.strip(),
                "start_date": start_date,
                "end_date": end_date,
                "adults": int(adults),
                "children": int(children),
                "budget": float(budget) if budget is not None else None,
                "transport_preference": transport_preference,
                "preferences_raw": preferences_raw,
            }
            st.rerun()

    except ApiError as e:
        if e.status_code == 401:
            do_logout("Session expired. Please login again.")
            st.rerun()
        st.error(e.message)
    finally:
        st.session_state.is_searching_transport = False


def _restore_trip_form_state():
    """Restore the user's last confirmed trip inputs after Streamlit reruns."""
    saved = st.session_state.get("trip_form_state") or {}
    if not isinstance(saved, dict) or not saved:
        return

    # Only restore values that belong to the saved planning session.
    # This runs after hotel selection / final itinerary reruns so the form
    # does not fall back to today's date or default numeric values.
    for key in (
        "trip_origin",
        "trip_destination",
        "trip_transport_preference",
        "trip_start_date",
        "trip_end_date",
        "trip_adults",
        "trip_children",
        "trip_budget",
        "trip_preferences",
    ):
        if key in saved and saved[key] is not None:
            st.session_state[key] = saved[key]


def _save_trip_form_state(
    origin, destination, start_date, end_date, adults, children,
    budget, transport_preference, preferences_raw
):
    """Persist the exact user-entered planner values across st.rerun()."""
    st.session_state.trip_form_state = {
        "trip_origin": str(origin or "").strip(),
        "trip_destination": str(destination or "").strip(),
        "trip_transport_preference": str(transport_preference or "train"),
        "trip_start_date": start_date,
        "trip_end_date": end_date,
        "trip_adults": int(adults),
        "trip_children": int(children),
        "trip_budget": int(budget) if budget is not None else 0,
        "trip_preferences": str(preferences_raw or ""),
    }


def _visible_sightseeing_activities(activities):
    """Hide internal hotel transit events from the user-facing itinerary."""
    return [
        a for a in (activities or [])
        if isinstance(a, dict)
        and a.get("type") != "hotel_transit"
        and a.get("category") != "transit"
    ]


def render_planner():
    _restore_trip_form_state()
    st.header("Plan Your Trip")
    st.caption("Enter your travel details below, select your preferred transport & travel class, and confirm before generating your complete itinerary.")

    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            origin = st.text_input("Origin City", placeholder="e.g. Mumbai, Delhi", key="trip_origin")
        with col2:
            destination = st.text_input("Destination City", placeholder="e.g. Manali, Goa, Jaipur", key="trip_destination")

        today = date.today()
        transport_preference = st.session_state.get("trip_transport_preference", "train")
        max_date = get_max_date(transport_preference, today)

        tcol1, tcol2, tcol3 = st.columns(3)
        with tcol1:
            transport_preference = st.selectbox(
                "Transport Mode",
                options=["train", "flight"],
                format_func=lambda v: TRANSPORT_LABELS.get(v, v.title()),
                key="trip_transport_preference",
                on_change=_clamp_trip_dates_to_new_max,
            )
        with tcol2:
            start_date = st.date_input(
                "Start Date",min_value=today, max_value=max_date, key="trip_start_date"
            )
        with tcol3:
            end_date = st.date_input(
                "End Date", min_value=today, max_value=max_date, key="trip_end_date"
            )

        if transport_preference == "train":
            st.caption(f"🚆 Trains can be booked up to {max_date.strftime('%d %b %Y')} (2 months out).")
        elif transport_preference == "flight":
            st.caption(f"✈️ Flights can be booked up to {max_date.strftime('%d %b %Y')} (1 year out).")

        pcol1, pcol2, pcol3 = st.columns(3)
        with pcol1:
            adults = st.number_input("Adults", min_value=1,step=1, key="trip_adults")
        with pcol2:
            children = st.number_input("Children", min_value=0,step=1, key="trip_children")
        with pcol3:
            budget = st.number_input("Budget (₹)", min_value=0,step=1000, key="trip_budget")

        preferences_raw = st.text_input(
            "Travel Preferences & Interests",
            placeholder="e.g. adventure, temples, mountain view, local food, sightseeing",
            help="Separate multiple preferences with commas.",
            key="trip_preferences",
        )

        bcol1, bcol2 = st.columns([2, 1])
        with bcol1:
            search_clicked = st.button(
                "🔍 Search Available Transport",
                type="primary",
                disabled=st.session_state.is_searching_transport or st.session_state.is_planning,
                use_container_width=True,
            )
        with bcol2:
            if st.session_state.outbound_searched:
                if st.button("Reset / New Search", use_container_width=True):
                    reset_transport_selection()
                    st.rerun()

    if search_clicked:
        handle_search_outbound_transport(
            origin=origin,
            destination=destination,
            start_date=start_date,
            end_date=end_date,
            adults=adults,
            children=children,
            budget=budget,
            transport_preference=transport_preference,
            preferences_raw=preferences_raw,
        )

    # -----------------------------------------------------------------
    # STEP 4-9: GATED SEQUENTIAL TRANSPORT SELECTION FLOW
    # -----------------------------------------------------------------
    if st.session_state.outbound_searched and not st.session_state.itinerary_result:
        render_transport_selection_and_confirmation(
            origin=origin,
            destination=destination,
            start_date=start_date,
            end_date=end_date,
            adults=adults,
            children=children,
            budget=budget,
            transport_preference=transport_preference,
            preferences_raw=preferences_raw,
        )


def render_transport_selection_and_confirmation(
    origin, destination, start_date, end_date, adults, children, budget, transport_preference, preferences_raw
):
    pax = max(1, int(adults) + int(children))
    nights = max(1, (end_date - start_date).days)
    mode_title = "Train" if transport_preference == "train" else "Flight"
    mode_icon = "🚆" if transport_preference == "train" else "✈️"

    outbound_opts = st.session_state.available_outbound_options
    if not outbound_opts:
        st.error(f"No verified outbound {transport_preference}s found from {origin} to {destination} for {start_date.strftime('%d %b %Y')}. Please modify your travel dates or switch transport mode.")
        return

    st.subheader(f"Select Your {mode_title} & Travel Class")

    # =========================================================
    # STEP 4: OUTBOUND TRANSPORT SELECTION (NO AUTO-SELECTION)
    # =========================================================
    st.markdown(f"### {mode_icon} 1. Select Outbound {mode_title}")
    out_labels = [format_transport_option_label(opt) for opt in outbound_opts]

    # Streamlit selectbox with index=None forces explicit selection
    selected_out_idx = st.selectbox(
        f"Choose Outbound {mode_title}:",
        range(len(outbound_opts)),
        index=st.session_state.selected_outbound_idx,
        placeholder=f"Select an outbound {transport_preference}...",
        format_func=lambda i: out_labels[i],
        key=f"ui_outbound_select_{st.session_state.transport_search_generation}",
    )

    if selected_out_idx != st.session_state.selected_outbound_idx:
        st.session_state.selected_outbound_idx = selected_out_idx
        st.session_state.selected_outbound_class = None
        st.session_state.return_searched = False
        st.session_state.available_return_options = []
        st.session_state.selected_return_idx = None
        st.session_state.selected_return_class = None
        st.rerun()

    if selected_out_idx is None:
        st.info(f"👆 Please select an outbound {transport_preference} from the dropdown above to view available travel classes.")
        return

    if not isinstance(selected_out_idx, int) or not (0 <= selected_out_idx < len(outbound_opts)):
        st.session_state.selected_outbound_idx = None
        st.session_state.selected_outbound_class = None
        st.info("Please select a valid outbound transport.")
        return

    selected_out_opt = outbound_opts[selected_out_idx]

    # Display clean route/transfer info if available
    out_first_mile = selected_out_opt.get("first_mile_transfer")
    out_last_mile = selected_out_opt.get("last_mile_transfer")
    if out_first_mile:
        _render_transfer_card(out_first_mile, title="🚗 Transfer to Boarding Station/Airport")
    if out_last_mile:
        _render_transfer_card(out_last_mile, title=f"🚗 Transfer to {destination}")

    # =========================================================
    # STEP 5: OUTBOUND CLASS SELECTION (NO AUTO-SELECTION)
    # =========================================================
    out_classes = get_option_classes(selected_out_opt)
    if not out_classes:
        st.error("No travel classes available for this option.")
        return

    st.markdown(f"### 🎫 2. Select Outbound Class / Cabin")
    out_cls_codes = [c["code"] for c in out_classes]
    current_out_cls_idx = out_cls_codes.index(st.session_state.selected_outbound_class) if st.session_state.selected_outbound_class in out_cls_codes else None

    selected_out_cls_idx = st.radio(
        "Outbound Travel Class",
        range(len(out_classes)),
        index=current_out_cls_idx,
        format_func=lambda i: format_class_label(out_classes[i]),
        key=f"ui_out_cls_radio_{st.session_state.transport_search_generation}_{selected_out_idx}",
    )

    if selected_out_cls_idx is not None:
        chosen_code = out_classes[selected_out_cls_idx]["code"]
        if chosen_code != st.session_state.selected_outbound_class:
            st.session_state.selected_outbound_class = chosen_code
            st.session_state.return_searched = False
            st.session_state.available_return_options = []
            st.session_state.selected_return_idx = None
            st.session_state.selected_return_class = None
            st.rerun()

    if st.session_state.selected_outbound_class is None:
        st.info("👆 Please select an outbound travel class above to search return journeys.")
        return

    if st.session_state.selected_outbound_class not in out_cls_codes:
        st.session_state.selected_outbound_class = None
        st.info("Please select an outbound travel class.")
        return

    selected_out_cls_obj = out_classes[
        out_cls_codes.index(st.session_state.selected_outbound_class)
    ]

    # =========================================================
    # STEP 6: RETURN TRANSPORT SEARCH (TRIGGERED ONLY AFTER OUTBOUND IS SELECTED)
    # =========================================================
    if not st.session_state.return_searched:
        out_orig_code = selected_out_opt.get("from_station_code") or selected_out_opt.get("from_code")
        out_dest_code = selected_out_opt.get("to_station_code") or selected_out_opt.get("to_code")

        with st.spinner(f"Searching verified return {transport_preference}s for {end_date.strftime('%d %b %Y')}..."):
            return_req = {
                "origin": destination.strip(),
                "destination": origin.strip(),
                "travel_date": end_date.isoformat(),
                "mode": transport_preference,
                "leg": "return",
                "adults": int(adults),
                "children": int(children),
                "budget": float(budget) if budget is not None else None,
                "outbound_origin_code": out_orig_code,
                "outbound_destination_code": out_dest_code,
            }
            try:
                return_res = search_transport_options(st.session_state.access_token, return_req)
                return_opts = return_res.get("options") or []
                st.session_state.available_return_options = return_opts
                st.session_state.return_searched = True
                st.session_state.selected_return_idx = None
                st.session_state.selected_return_class = None
                st.rerun()
            except ApiError as e:
                st.session_state.return_searched = False
                st.session_state.available_return_options = []
                st.session_state.selected_return_idx = None
                st.session_state.selected_return_class = None
                if e.status_code == 401:
                    do_logout("Session expired. Please login again.")
                    st.rerun()
                st.error(e.message)
                return

    # =========================================================
    # STEP 7: RETURN TRANSPORT SELECTION (NO AUTO-SELECTION)
    # =========================================================
    st.divider()
    return_opts = st.session_state.available_return_options
    if not return_opts:
        st.error(f"No verified return transport is currently available for the selected date ({end_date.strftime('%d %b %Y')}). Please modify your travel dates or switch transport mode.")
        return

    st.markdown(f"### 🔄 3. Select Return {mode_title}")
    ret_labels = [format_transport_option_label(opt) for opt in return_opts]

    selected_ret_idx = st.selectbox(
        f"Choose Return {mode_title}:",
        range(len(return_opts)),
        index=st.session_state.selected_return_idx,
        placeholder=f"Select a return {transport_preference}...",
        format_func=lambda i: ret_labels[i],
        key=f"ui_return_select_{st.session_state.transport_search_generation}",
    )

    if selected_ret_idx != st.session_state.selected_return_idx:
        st.session_state.selected_return_idx = selected_ret_idx
        st.session_state.selected_return_class = None
        st.rerun()

    if selected_ret_idx is None:
        st.info(f"👆 Please select a return {transport_preference} from the dropdown above to view available travel classes.")
        return

    if not isinstance(selected_ret_idx, int) or not (0 <= selected_ret_idx < len(return_opts)):
        st.session_state.selected_return_idx = None
        st.session_state.selected_return_class = None
        st.info("Please select a valid return transport.")
        return

    selected_ret_opt = return_opts[selected_ret_idx]

    # Display return transfer info if available
    ret_first_mile = selected_ret_opt.get("first_mile_transfer") or selected_ret_opt.get("return_first_mile_transfer")
    ret_last_mile = selected_ret_opt.get("last_mile_transfer") or selected_ret_opt.get("return_last_mile_transfer")
    if ret_first_mile:
        _render_transfer_card(ret_first_mile, title="🚗 Transfer to Return Boarding Station/Airport")
    if ret_last_mile:
        _render_transfer_card(ret_last_mile, title=f"🚗 Transfer to {origin}")

    # =========================================================
    # STEP 8: RETURN CLASS SELECTION (NO AUTO-SELECTION)
    # =========================================================
    ret_classes = get_option_classes(selected_ret_opt)
    if not ret_classes:
        st.error("No return travel classes available for this option.")
        return

    st.markdown(f"### 🎫 4. Select Return Class / Cabin")
    ret_cls_codes = [c["code"] for c in ret_classes]
    current_ret_cls_idx = ret_cls_codes.index(st.session_state.selected_return_class) if st.session_state.selected_return_class in ret_cls_codes else None

    selected_ret_cls_idx = st.radio(
        "Return Travel Class",
        range(len(ret_classes)),
        index=current_ret_cls_idx,
        format_func=lambda i: format_class_label(ret_classes[i]),
        key=f"ui_ret_cls_radio_{st.session_state.transport_search_generation}_{selected_ret_idx}",
    )

    if selected_ret_cls_idx is not None:
        chosen_ret_code = ret_classes[selected_ret_cls_idx]["code"]
        if chosen_ret_code != st.session_state.selected_return_class:
            st.session_state.selected_return_class = chosen_ret_code
            st.rerun()

    if st.session_state.selected_return_class is None:
        st.info("👆 Please select a return travel class above to review transport confirmation.")
        return

    if st.session_state.selected_return_class not in ret_cls_codes:
        st.session_state.selected_return_class = None
        st.info("Please select a return travel class.")
        return

    selected_ret_cls_obj = ret_classes[
        ret_cls_codes.index(st.session_state.selected_return_class)
    ]

    # =========================================================
    # STEP 9: TRANSPORT CONFIRMATION SUMMARY & CONFIRM BUTTON
    # =========================================================
    st.divider()
    st.subheader("Transport Confirmation")

    out_fare = _safe_float(selected_out_cls_obj.get("fare"))
    ret_fare = _safe_float(selected_ret_cls_obj.get("fare"))
    if out_fare is None or out_fare < 0:
        st.error("Outbound fare is invalid. Please select another transport option.")
        return
    if ret_fare is None or ret_fare < 0:
        st.error("Return fare is invalid. Please select another transport option.")
        return

    out_total = out_fare * pax
    ret_total = ret_fare * pax
    transport_total = out_total + ret_total

    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            out_name = selected_out_opt.get("train_name") or selected_out_opt.get("flight_name") or selected_out_opt.get("name") or "Outbound Transport"
            out_cls_name = selected_out_cls_obj.get("name") or selected_out_cls_obj.get("code")
            st.markdown(f"**{mode_icon} Outbound:** {out_name}")
            st.write(f"**Class:** {out_cls_name}")
            if pax > 1:
                st.caption(f"₹{out_fare:,.0f} / person × {pax} travelers = ₹{out_total:,.0f}")
            else:
                st.caption(f"₹{out_fare:,.0f} / person")

        with col2:
            ret_name = selected_ret_opt.get("train_name") or selected_ret_opt.get("flight_name") or selected_ret_opt.get("name") or "Return Transport"
            ret_cls_name = selected_ret_cls_obj.get("name") or selected_ret_cls_obj.get("code")
            st.markdown(f"**🔄 Return:** {ret_name}")
            st.write(f"**Class:** {ret_cls_name}")
            if pax > 1:
                st.caption(f"₹{ret_fare:,.0f} / person × {pax} travelers = ₹{ret_total:,.0f}")
            else:
                st.caption(f"₹{ret_fare:,.0f} / person")

        st.divider()
        st.markdown(f"**Total Transport Cost ({pax} Travelers):** ₹{transport_total:,.0f}")
        st.caption("ℹ️ *Hotel accommodations at destination, sightseeing activities, and final budget breakdown will be generated in the complete itinerary.*")

    confirm_clicked = st.button(
        "✅ Confirm Transport & Continue to Hotel Selection",
        type="primary",
        disabled=st.session_state.is_planning,
        use_container_width=True,
    )

    if confirm_clicked:
        handle_confirm_and_plan(
            origin=origin,
            destination=destination,
            start_date=start_date,
            end_date=end_date,
            adults=adults,
            children=children,
            budget=budget,
            transport_preference=transport_preference,
            preferences_raw=preferences_raw,
            selected_out_opt=selected_out_opt,
            selected_out_cls_obj=selected_out_cls_obj,
            selected_ret_opt=selected_ret_opt,
            selected_ret_cls_obj=selected_ret_cls_obj,
            out_fare=out_fare,
            ret_fare=ret_fare,
        )


def handle_confirm_and_plan(
    origin,
    destination,
    start_date,
    end_date,
    adults,
    children,
    budget,
    transport_preference,
    preferences_raw,
    selected_out_opt,
    selected_out_cls_obj,
    selected_ret_opt,
    selected_ret_cls_obj,
    out_fare,
    ret_fare,
):
    """Submits confirmed transport and opens the Phase 1 hotel selection step."""
    if not st.session_state.access_token:
        st.error("Please login first.")
        return

    if not selected_out_opt or not selected_out_cls_obj:
        st.error("Please select an outbound transport option and travel class.")
        return

    if not selected_ret_opt or not selected_ret_cls_obj:
        st.error("Please select a return transport option and travel class.")
        return

    # Deep copy / enrich transport option with explicit selected class & fare
    outbound_payload = None
    if selected_out_opt:
        outbound_payload = dict(selected_out_opt)
        if selected_out_cls_obj:
            outbound_payload["selected_class"] = selected_out_cls_obj["code"]
            outbound_payload["selected_class_name"] = selected_out_cls_obj["name"]
            outbound_payload["price"] = out_fare
            outbound_payload["fare"] = out_fare

    return_payload = None
    if selected_ret_opt:
        return_payload = dict(selected_ret_opt)
        if selected_ret_cls_obj:
            return_payload["selected_class"] = selected_ret_cls_obj["code"]
            return_payload["selected_class_name"] = selected_ret_cls_obj["name"]
            return_payload["price"] = ret_fare
            return_payload["fare"] = ret_fare

    plan_payload = {
        "origin": origin.strip(),
        "destination": destination.strip(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "adults": int(adults),
        "children": int(children),
        "budget": float(budget) if budget is not None else None,
        "transport_preference": transport_preference,
        "preferences": parse_preferences(preferences_raw),
        "selected_outbound_transport": outbound_payload,
        "selected_return_transport": return_payload,
        "selected_outbound_option": outbound_payload,
        "selected_return_option": return_payload,
        "selected_outbound_class": selected_out_cls_obj["code"] if selected_out_cls_obj else None,
        "selected_return_class": selected_ret_cls_obj["code"] if selected_ret_cls_obj else None,
        "selected_outbound_fare": out_fare if selected_out_opt else None,
        "selected_return_fare": ret_fare if selected_ret_opt else None,
    }

    _save_trip_form_state(
        origin=origin,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        adults=adults,
        children=children,
        budget=budget,
        transport_preference=transport_preference,
        preferences_raw=preferences_raw,
    )

    st.session_state.is_planning = True
    st.session_state.itinerary_result = None
    st.session_state.hotel_selection_result = None

    # =====================================================
    # CREATE MASTER TRIP RECORD
    # =====================================================

    trip_payload = {
        "source_city": origin.strip(),
        "destination_city": destination.strip(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "adults": int(adults),
        "children": int(children),
        "travellers": int(adults) + int(children),
        "trip_type": "leisure",
        "budget": float(budget) if budget is not None else None,
        "transport_pref": transport_preference,
        "preferences": parse_preferences(preferences_raw),
    }

    try:
        with st.spinner("Creating your trip..."):
            trip_record = create_trip(
                st.session_state.access_token,
                trip_payload,
            )

        if not isinstance(trip_record, dict):
            st.error("Invalid response received while creating the trip.")
            return

        trip_id = trip_record.get("id")

        if trip_id is None:
            st.error("Trip was created but no trip ID was returned by the backend.")
            return

        try:
            trip_id = int(trip_id)
        except (TypeError, ValueError):
            st.error("Backend returned an invalid trip ID.")
            return

        st.session_state.trip_id = trip_id
        plan_payload["trip_id"] = trip_id

        # =====================================================
        # EXISTING AI PLANNING FLOW
        # =====================================================

        with st.spinner("Preparing hotel options..."):
            result = plan_trip(st.session_state.access_token, plan_payload)

        if not isinstance(result, dict):
            st.error("Invalid response received from the planning API.")
            return

        if result.get("status") == "AWAITING_HOTEL_SELECTION":
            st.session_state.hotel_selection_result = result
        else:
            st.error("Unexpected planning response. Hotel selection was not opened.")
            return
        st.rerun()
    except ApiError as e:
        if e.status_code == 401:
            do_logout("Session expired. Please login again.")
            st.rerun()
        st.error(e.message)
    finally:
        st.session_state.is_planning = False


# =========================================================
# HOTEL SELECTION (PHASE 1 CHECKPOINT)
# =========================================================

def render_hotel_selection():
    data = st.session_state.hotel_selection_result or {}
    hotels = data.get("hotel_options") or []
    planning_id = str(data.get("planning_id") or "").strip()

    st.divider()
    st.header("🏨 Select Your Base Hotel")
    st.caption("Choose one hotel. Your selected hotel will be the base for transfers and sightseeing.")

    if not hotels:
        st.error("No hotel options were returned. Please restart the trip search.")
        return

    selected_id = st.session_state.get("selected_hotel_id")
    for hotel_index, hotel in enumerate(hotels[:3]):
        if not isinstance(hotel, dict):
            continue
        hotel_id = hotel.get("hotel_id") or hotel.get("id")
        role = str(hotel.get("selection_role") or hotel.get("tier") or "RECOMMENDED").replace("_", " ").title()
        name = hotel.get("hotel_name") or hotel.get("name") or "Hotel"
        address = hotel.get("address") or hotel.get("location") or "Location unavailable"
        rating = _safe_float(hotel.get("rating"))
        total_price = _safe_float(hotel.get("price"))
        price_per_night = _safe_float(hotel.get("price_per_night"))
        stay_nights_raw = hotel.get("stay_nights")
        try:
            stay_nights = int(stay_nights_raw) if stay_nights_raw is not None else 0
        except (TypeError, ValueError):
            stay_nights = 0
        budget_fit = hotel.get("budget_fit")

        with st.container(border=True):
            st.markdown(f"### {role}")
            st.markdown(f"**{extract_display_value(name)}**")
            st.write(f"📍 {extract_display_value(address)}")
            if rating is not None:
                st.write(f"⭐ {min(5.0, max(0.0, rating)):.1f}/5")
            if price_per_night is not None and price_per_night > 0:
                st.write(f"💰 ₹{price_per_night:,.0f} / night")
            if total_price is not None and total_price > 0:
                night_label = f"{stay_nights} nights" if stay_nights else "full stay"
                st.write(f"🏨 ₹{total_price:,.0f} total ({night_label})")
            if budget_fit is True:
                st.caption("✅ Fits your trip budget")
            elif budget_fit is False:
                st.caption("⚠️ Above your trip budget")

            if st.button(
                f"Select {role}",
                key=f"select_hotel_{hotel_id}_{hotel_index}",
                use_container_width=True,
            ):
                if not planning_id:
                    st.error("Planning session expired. Please start a new trip search.")
                    return

                if hotel_id is None or not str(hotel_id).strip():
                    st.error("This hotel cannot be selected because its hotel ID is missing.")
                    continue

                selected_id = hotel_id
                st.session_state.selected_hotel_id = hotel_id
                st.session_state.is_planning = True
                try:
                    with st.spinner("Generating your itinerary around the selected hotel..."):
                        result = select_hotel(
                            st.session_state.access_token,
                            planning_id,
                            hotel_id,
                        )
                    if not isinstance(result, dict):
                        raise ApiError(
                            "Invalid response received from the hotel selection API."
                        )
                    st.session_state.itinerary_result = result
                    st.session_state.hotel_selection_result = None
                    # Keep trip_form_state intact. The planner form is rendered
                    # again after rerun and restored from this snapshot.
                    st.session_state.selected_hotel_id = None
                    st.rerun()
                except ApiError as e:
                    if e.status_code == 401:
                        do_logout("Session expired. Please login again.")
                        st.rerun()
                    st.error(e.message)
                finally:
                    st.session_state.is_planning = False


# =========================================================
# ITINERARY RENDERING HELPERS
# =========================================================

def get_itinerary_days(data: dict) -> list:
    itinerary = data.get("itinerary") or data.get("final_itinerary") or data.get("trip_itinerary")

    if isinstance(itinerary, list):
        return itinerary
    if isinstance(itinerary, dict) and isinstance(itinerary.get("days"), list):
        return itinerary["days"]
    if isinstance(data.get("days"), list):
        return data["days"]
    return []


def is_valid_verified_transport(t: Any) -> bool:
    """Check whether a transport object is a real verified transport leg."""
    if not isinstance(t, dict) or not t:
        return False
    if t.get("status") == "unavailable" or t.get("transport_unavailable") is True:
        return False
    ver = t.get("verification")
    if isinstance(ver, dict) and ver.get("status") not in ["verified", "available", "evidence_found"]:
        return False
    name = str(t.get("train_name") or t.get("flight_name") or t.get("name") or "").strip().lower()
    num = str(t.get("train_number") or t.get("flight_number") or "").strip()
    if not num and (
        not name
        or name in ("unknown", "n/a", "none", "transport", "flight", "train", "null", "")
        or "superfast express" in name
        or "return express" in name
    ):
        return False
    return True


def get_transport_info(data: dict) -> dict:
    if not isinstance(data, dict):
        return {}

    candidates = [
        data.get("outbound_transport"),
        data.get("selected_transport"),
        data.get("transport", {}).get("selected") if isinstance(data.get("transport"), dict) else None,
        data.get("itinerary", {}).get("transport") if isinstance(data.get("itinerary"), dict) else None,
        data.get("optimization", {}).get("best_outbound_transport") if isinstance(data.get("optimization"), dict) else None,
        data.get("optimization", {}).get("best_transport") if isinstance(data.get("optimization"), dict) else None,
    ]
    for cand in candidates:
        if is_valid_verified_transport(cand):
            return cand

    return {}


def get_return_transport_info(data: dict, outbound_transport: dict = None) -> dict:
    if not isinstance(data, dict):
        return {}

    candidates = [
        data.get("return_transport"),
        outbound_transport.get("return_trip") if isinstance(outbound_transport, dict) else None,
        data.get("itinerary", {}).get("return_transport") if isinstance(data.get("itinerary"), dict) else None,
        data.get("optimization", {}).get("best_return_transport") if isinstance(data.get("optimization"), dict) else None,
    ]
    for cand in candidates:
        if is_valid_verified_transport(cand):
            return cand

    return {}


def get_hotel_info(data: dict) -> dict:
    hotels = data.get("hotels")
    if isinstance(hotels, dict) and isinstance(hotels.get("selected"), dict):
        return hotels["selected"]

    itinerary = data.get("itinerary")
    if isinstance(itinerary, dict) and isinstance(itinerary.get("hotel"), dict):
        return itinerary["hotel"]

    hotel = data.get("hotel")
    return hotel if isinstance(hotel, dict) else {}


def _format_transfer_banner(transfer_dict: Any) -> str:
    """Safely format first/last-mile transfer banner without internal debug tokens or LLM tags."""
    if not transfer_dict:
        return ""

    if isinstance(transfer_dict, str):
        raw_str = str(transfer_dict).strip()
        if raw_str.lower() in ("none", "null", "n/a", "unknown", ""):
            return ""
        import re
        clean_text = re.sub(r"\[.*?\]", "", raw_str)
        clean_text = re.sub(r"(?i)\b(source|verified|verification|circuit breaker|railcore|railradar|http \d+)\b:?", "", clean_text)
        return clean_text.strip(" ,.-•")

    if not isinstance(transfer_dict, dict):
        return ""

    def _clean(val):
        if val is None or str(val).strip().lower() in ("none", "null", "n/a", "unknown", "transfer hub", "first_mile", "last_mile", "first-mile", "last-mile", ""):
            return None
        return str(val).strip()

    from_pt = _clean(transfer_dict.get("from")) or _clean(transfer_dict.get("transfer_from")) or _clean(transfer_dict.get("origin"))
    to_pt = _clean(transfer_dict.get("to")) or _clean(transfer_dict.get("transfer_to")) or _clean(transfer_dict.get("destination"))
    dist = _clean(transfer_dict.get("distance_km") or transfer_dict.get("road_distance_km") or transfer_dict.get("estimated_distance_km") or transfer_dict.get("distance"))
    dur = _clean(transfer_dict.get("duration") or transfer_dict.get("estimated_transfer_time") or transfer_dict.get("estimated_duration") or transfer_dict.get("estimated_time") or transfer_dict.get("time"))
    hub = _clean(transfer_dict.get("hub_name") or transfer_dict.get("transfer_point"))

    if from_pt and to_pt and from_pt.lower() == to_pt.lower():
        return ""
    if not from_pt and not to_pt and not dist and not dur:
        return ""

    parts = []
    if from_pt and to_pt:
        parts.append(f"**{from_pt} → {to_pt}**")
    elif hub:
        parts.append(f"via **{hub}**")

    if dist:
        clean_dist = str(dist).replace("~", "").strip()
        parts.append(f"~{clean_dist} km")
    if dur:
        clean_dur = str(dur).replace("~", "").strip()
        parts.append(f"~{clean_dur}")

    return " • ".join(parts)


def _render_transfer_card(transfer_dict: dict, title: str = "🚗 Road Transfer"):
    """Render a clean, native Streamlit transfer card with road transfer details."""
    if not isinstance(transfer_dict, dict) or not transfer_dict:
        return

    def _clean(val):
        if val is None or str(val).strip().lower() in ("none", "null", "n/a", "unknown", "transfer hub", "first_mile", "last_mile", "first-mile", "last-mile", ""):
            return None
        return str(val).strip()

    from_pt = _clean(transfer_dict.get("from")) or _clean(transfer_dict.get("transfer_from")) or _clean(transfer_dict.get("origin"))
    to_pt = _clean(transfer_dict.get("to")) or _clean(transfer_dict.get("transfer_to")) or _clean(transfer_dict.get("destination"))
    dist = _clean(transfer_dict.get("distance_km") or transfer_dict.get("road_distance_km") or transfer_dict.get("estimated_distance_km") or transfer_dict.get("distance"))
    dur = _clean(transfer_dict.get("duration") or transfer_dict.get("estimated_transfer_time") or transfer_dict.get("estimated_duration") or transfer_dict.get("estimated_time") or transfer_dict.get("time"))

    if from_pt and to_pt and from_pt.lower() == to_pt.lower():
        return
    if not from_pt and not to_pt and not dist and not dur:
        return

    with st.container(border=True):
        st.markdown(f"**{title}**")
        if from_pt and to_pt:
            st.write(f"{from_pt} → {to_pt}")
        details = []
        if dist:
            clean_dist = str(dist).replace("~", "").strip()
            details.append(f"~{clean_dist} km")
        if dur:
            clean_dur = str(dur).replace("~", "").strip()
            details.append(f"~{clean_dur}")
        if details:
            st.caption(" • ".join(details))


def render_transport(transport: dict, data: dict = None):
    origin_name = "Origin"
    destination_name = "Destination"

    if data and isinstance(data, dict):
        trip = data.get("trip") or {}
        origin_name = extract_display_value(trip.get("origin")) or "Origin"
        destination_name = extract_display_value(trip.get("destination")) or "Destination"

    has_real_outbound = is_valid_verified_transport(transport)
    return_trip = get_return_transport_info(data, transport) if isinstance(data, dict) else (transport.get("return_trip") if isinstance(transport, dict) else None)
    has_real_return = is_valid_verified_transport(return_trip)

    st.subheader("Transport Details")
    with st.container(border=True):
        # ----------------------------------------------------
        # OUTBOUND SECTION
        # ----------------------------------------------------
        if not has_real_outbound:
            st.markdown(f"### 🚆 Outbound Journey")
            st.markdown(f"**Route:** {origin_name} → {destination_name}")
            st.info("Outbound transport could not be verified online.")
        else:
            t_type = str(transport.get("type", "")).lower()
            f_airline = str(transport.get("airline") or "").strip()
            f_number = str(transport.get("flight_number") or "").strip()
            f_label = f"{f_airline} {f_number}".strip() if (f_airline or f_number) else ""

            is_flight = (
                "flight" in t_type
                or bool(transport.get("airline") or transport.get("flight_number") or transport.get("flight_name"))
            )
            mode = "Flight" if is_flight else "Train"
            mode_icon = "✈️" if is_flight else "🚆"

            name = (
                transport.get("flight_name")
                or transport.get("train_name")
                or transport.get("name")
                or f_label
            )
            t_number = str(transport.get("train_number") or transport.get("flight_number") or "").strip()
            name_display = f"{extract_display_value(name)} ({t_number})" if (t_number and t_number not in str(name)) else extract_display_value(name)

            departure = transport.get("departure") or transport.get("departure_time")
            arrival = transport.get("arrival") or transport.get("arrival_time")
            duration = transport.get("duration")
            price = transport.get("price")
            outbound_class = (
                transport.get("selected_class_name")
                or transport.get("class_name")
                or (f"Class {transport['selected_class']}" if transport.get("selected_class") else None)
                or transport.get("cabin_class")
            )

            out_transfer = (
                transport.get("outbound_transfer")
                or transport.get("transfer")
                or (data.get("outbound_transfer") if isinstance(data, dict) else None)
                or (data.get("transfer") if isinstance(data, dict) else None)
            )
            first_mile_t = transport.get("first_mile_transfer") or (data.get("first_mile_transfer") if isinstance(data, dict) else None)
            last_mile_t = transport.get("last_mile_transfer") or (data.get("last_mile_transfer") if isinstance(data, dict) else None)

            orig_st_name = transport.get("actual_train_origin") or transport.get("from_station_name") or transport.get("origin_station_name")
            orig_st_code = transport.get("from_station_code") or transport.get("from_code")
            dest_st_name = transport.get("actual_train_destination") or transport.get("to_station_name") or transport.get("destination_station_name")
            dest_st_code = transport.get("to_station_code") or transport.get("to_code")

            if orig_st_name and orig_st_code and orig_st_code not in orig_st_name:
                out_orig_label = f"{orig_st_name} ({orig_st_code})"
            elif orig_st_name:
                out_orig_label = orig_st_name
            elif orig_st_code:
                out_orig_label = orig_st_code
            else:
                out_orig_label = origin_name

            if dest_st_name and dest_st_code and dest_st_code not in dest_st_name:
                out_dest_label = f"{dest_st_name} ({dest_st_code})"
            elif dest_st_name:
                out_dest_label = dest_st_name
            elif dest_st_code:
                out_dest_label = dest_st_code
            elif last_mile_t and last_mile_t.get("from"):
                out_dest_label = str(last_mile_t.get("from"))
            else:
                out_dest_label = destination_name

            # Canonical 4-Concept Route Banner
            clean_u_orig = origin_name
            clean_a_orig = orig_st_name or out_orig_label
            clean_a_dest = dest_st_name or out_dest_label
            clean_u_dest = destination_name

            if clean_a_orig.lower() != clean_u_orig.lower() and clean_a_dest.lower() != clean_u_dest.lower():
                canonical_route_banner = f"{clean_u_orig} → {clean_a_orig} → {clean_a_dest} → {clean_u_dest}"
            elif clean_a_orig.lower() != clean_u_orig.lower():
                canonical_route_banner = f"{clean_u_orig} → {clean_a_orig} → {clean_u_dest}"
            elif clean_a_dest.lower() != clean_u_dest.lower():
                canonical_route_banner = f"{clean_u_orig} → {clean_a_dest} → {clean_u_dest}"
            else:
                canonical_route_banner = f"{clean_u_orig} → {clean_u_dest}"

            st.markdown(f"### {mode_icon} Outbound Journey")
            st.markdown(f"**Route:** {canonical_route_banner}")

            if clean_a_orig.lower() != clean_u_orig.lower() and first_mile_t:
                _render_transfer_card(first_mile_t, title=f"🚗 Transfer to Boarding Station ({out_orig_label})")

            if name_display:
                st.write(f"**{mode}:** {name_display}")
            st.write(f"**Boarding Station:** {out_orig_label}")
            if orig_st_code and dest_st_code:
                st.write(f"**{mode} Route:** {orig_st_code} → {dest_st_code}")
            if outbound_class:
                st.write(f"**Travel Class:** {outbound_class}")

            col1, col2 = st.columns(2)
            with col1:
                if departure:
                    st.write(f"**Departure:** {departure}")
            with col2:
                if arrival:
                    st.write(f"**Arrival:** {arrival}")
            if duration:
                st.write(f"**Duration:** {duration}")

            if clean_a_dest.lower() != clean_u_dest.lower():
                target_last_mile = last_mile_t or out_transfer
                if target_last_mile:
                    _render_transfer_card(target_last_mile, title=f"🚗 Transfer to {clean_u_dest}")

            # Outbound Fare
            trip_data = data.get("trip", {}) if isinstance(data, dict) and isinstance(data.get("trip"), dict) else {}
            travelers_dict = trip_data.get("travelers", {}) if isinstance(trip_data.get("travelers"), dict) else {}
            adults = travelers_dict.get("adults", trip_data.get("adults", 1))
            children = travelers_dict.get("children", trip_data.get("children", 0))
            try:
                pax = max(1, int(adults or 1) + int(children or 0))
            except (TypeError, ValueError):
                pax = 1

            if price is not None:
                class_tag = f" [{outbound_class}]" if outbound_class else ""
                if isinstance(price, (int, float)):
                    if pax > 1:
                        st.write(f"**Outbound Fare:** ₹{price:,.0f} / person (₹{price * pax:,.0f} for {pax} travelers){class_tag}")
                    else:
                        st.write(f"**Outbound Fare:** ₹{price:,.0f} / person{class_tag}")
                else:
                    st.write(f"**Outbound Fare:** ₹{price}{class_tag}")

        # ----------------------------------------------------
        # RETURN SECTION
        # ----------------------------------------------------
        st.divider()
        if not has_real_return:
            st.markdown(f"### 🔄 Return Journey")
            st.markdown(f"**Route:** {destination_name} → {origin_name}")
            st.info("Return transport could not be verified online.")
        else:
            ret_type = str(return_trip.get("type", "")).lower()
            is_ret_flight = (
                "flight" in ret_type
                or bool(return_trip.get("airline") or return_trip.get("flight_number") or return_trip.get("flight_name"))
            )
            ret_mode = "Flight" if is_ret_flight else "Train"
            ret_mode_icon = "✈️" if is_ret_flight else "🚆"

            r_airline = str(return_trip.get("airline") or "").strip()
            r_number = str(return_trip.get("flight_number") or "").strip()
            r_label = f"{r_airline} {r_number}".strip() if (r_airline or r_number) else ""

            ret_name = (
                return_trip.get("flight_name")
                or return_trip.get("train_name")
                or return_trip.get("name")
                or r_label
            )
            r_t_number = str(return_trip.get("train_number") or return_trip.get("flight_number") or "").strip()
            ret_name_display = f"{extract_display_value(ret_name)} ({r_t_number})" if (r_t_number and r_t_number not in str(ret_name)) else extract_display_value(ret_name)

            ret_dep = return_trip.get("departure") or return_trip.get("departure_time")
            ret_arr = return_trip.get("arrival") or return_trip.get("arrival_time")
            ret_dur = return_trip.get("duration")
            ret_price = return_trip.get("price")
            ret_class = (
                return_trip.get("selected_class_name")
                or return_trip.get("class_name")
                or (f"Class {return_trip['selected_class']}" if return_trip.get("selected_class") else None)
                or return_trip.get("cabin_class")
            )

            ret_transfer = (
                return_trip.get("return_transfer")
                or return_trip.get("transfer")
                or (data.get("return_transfer") if isinstance(data, dict) else None)
            )
            ret_first_mile_t = return_trip.get("first_mile_transfer") or return_trip.get("return_first_mile_transfer") or (data.get("return_first_mile_transfer") if isinstance(data, dict) else None)
            ret_last_mile_t = return_trip.get("last_mile_transfer") or return_trip.get("return_last_mile_transfer") or (data.get("return_last_mile_transfer") if isinstance(data, dict) else None)

            r_orig_st_name = return_trip.get("actual_train_origin") or return_trip.get("from_station_name") or return_trip.get("origin_station_name")
            r_orig_st_code = return_trip.get("from_station_code") or return_trip.get("from_code")
            r_dest_st_name = return_trip.get("actual_train_destination") or return_trip.get("to_station_name") or return_trip.get("destination_station_name")
            r_dest_st_code = return_trip.get("to_station_code") or return_trip.get("to_code")

            if r_orig_st_name and r_orig_st_code and r_orig_st_code not in r_orig_st_name:
                ret_orig_label = f"{r_orig_st_name} ({r_orig_st_code})"
            elif r_orig_st_name:
                ret_orig_label = r_orig_st_name
            elif r_orig_st_code:
                ret_orig_label = r_orig_st_code
            else:
                ret_orig_label = destination_name

            if r_dest_st_name and r_dest_st_code and r_dest_st_code not in r_dest_st_name:
                ret_dest_label = f"{r_dest_st_name} ({r_dest_st_code})"
            elif r_dest_st_name:
                ret_dest_label = r_dest_st_name
            elif r_dest_st_code:
                ret_dest_label = r_dest_st_code
            elif ret_last_mile_t and ret_last_mile_t.get("to"):
                ret_dest_label = str(ret_last_mile_t.get("to"))
            else:
                ret_dest_label = origin_name

            # Canonical 4-Concept Return Route Banner
            clean_r_u_orig = destination_name
            clean_r_a_orig = r_orig_st_name or ret_orig_label
            clean_r_a_dest = r_dest_st_name or ret_dest_label
            clean_r_u_dest = origin_name

            if clean_r_a_orig.lower() != clean_r_u_orig.lower() and clean_r_a_dest.lower() != clean_r_u_dest.lower():
                canonical_ret_banner = f"{clean_r_u_orig} → {clean_r_a_orig} → {clean_r_a_dest} → {clean_r_u_dest}"
            elif clean_r_a_orig.lower() != clean_r_u_orig.lower():
                canonical_ret_banner = f"{clean_r_u_orig} → {clean_r_a_orig} → {clean_r_u_dest}"
            elif clean_r_a_dest.lower() != clean_r_u_dest.lower():
                canonical_ret_banner = f"{clean_r_u_orig} → {clean_r_a_dest} → {clean_r_u_dest}"
            else:
                canonical_ret_banner = f"{clean_r_u_orig} → {clean_r_u_dest}"

            st.markdown(f"### {ret_mode_icon} Return Journey")
            st.markdown(f"**Route:** {canonical_ret_banner}")

            if clean_r_a_orig.lower() != clean_r_u_orig.lower():
                target_ret_first = ret_first_mile_t or ret_transfer
                if target_ret_first:
                    _render_transfer_card(target_ret_first, title=f"🚗 Transfer to Boarding Station ({ret_orig_label})")

            if ret_name_display:
                st.write(f"**{ret_mode}:** {ret_name_display}")
            st.write(f"**Boarding Station:** {ret_orig_label}")
            if r_orig_st_code and r_dest_st_code:
                st.write(f"**{ret_mode} Route:** {r_orig_st_code} → {r_dest_st_code}")
            if ret_class:
                st.write(f"**Travel Class:** {ret_class}")

            rcol1, rcol2 = st.columns(2)
            with rcol1:
                if ret_dep:
                    st.write(f"**Departure:** {ret_dep}")
            with rcol2:
                if ret_arr:
                    st.write(f"**Arrival:** {ret_arr}")
            if ret_dur:
                st.write(f"**Duration:** {ret_dur}")

            if clean_r_a_dest.lower() != clean_r_u_dest.lower() and ret_last_mile_t:
                _render_transfer_card(ret_last_mile_t, title=f"🚗 Transfer to {clean_r_u_dest}")

            if ret_price is not None:
                ret_class_tag = f" [{ret_class}]" if ret_class else ""
                if isinstance(ret_price, (int, float)):
                    if pax > 1:
                        st.write(f"**Return Fare:** ₹{ret_price:,.0f} / person (₹{ret_price * pax:,.0f} for {pax} travelers){ret_class_tag}")
                    else:
                        st.write(f"**Return Fare:** ₹{ret_price:,.0f} / person{ret_class_tag}")
                else:
                    st.write(f"**Return Fare:** ₹{ret_price}{ret_class_tag}")


def render_hotel(hotel: dict, budget_summary: dict = None, total_nights: int = 7):
    if not hotel or not isinstance(hotel, dict):
        return

    name = hotel.get("hotel_name") or hotel.get("name")
    rating = hotel.get("rating")
    location = hotel.get("address") or hotel.get("location")

    nights_raw = (
        (budget_summary.get("hotel_nights") if budget_summary else None)
        or hotel.get("nights")
        or total_nights
        or 7
    )
    try:
        nights = max(1, int(nights_raw))
    except (TypeError, ValueError):
        nights = 1

    raw_price = None

    if budget_summary and budget_summary.get("estimated_hotel") is not None:
        total_stay = _safe_float(budget_summary.get("estimated_hotel"))
        if total_stay is not None:
            nightly_value = _safe_float(budget_summary.get("hotel_price_per_night"))
            rate_night = nightly_value if nightly_value is not None else (
                total_stay / nights if nights > 0 else total_stay
            )
        else:
            rate_night = None
    else:
        raw_price = hotel.get("price") if hotel.get("price") is not None else hotel.get("cost")
        is_per_night = bool(hotel.get("is_per_night") or hotel.get("rate_type") == "nightly")
        if raw_price is not None:
            try:
                p_val = float(raw_price)
                if is_per_night:
                    rate_night = p_val
                    total_stay = p_val * nights
                else:
                    rate_night = p_val / nights if nights > 0 else p_val
                    total_stay = p_val
            except (TypeError, ValueError):
                rate_night = raw_price
                total_stay = raw_price
        else:
            rate_night = None
            total_stay = None

    st.subheader("Selected Base Hotel")
    with st.container(border=True):
        if name and str(name).strip() and str(name).strip().lower() not in ("none", "null", "unknown"):
            st.markdown(f"**Hotel Name:** {extract_display_value(name)}")
        else:
            st.markdown("**Hotel Name:** Not available")

        if location:
            st.write(f"**Location:** {extract_display_value(location)}")

        if rating is not None:
            try:
                r_val = float(rating)
                if r_val > 5.0:
                    r_val = r_val / 2.0
                norm_rating = round(min(5.0, max(0.0, r_val)), 1)
                st.write(f"**Rating:** {norm_rating} / 5.0")
            except (TypeError, ValueError):
                pass

        if rate_night is not None and total_stay is not None:
            st.write(f"**Rate:** ₹{rate_night:,.0f} / night")
            st.write(f"**Stay:** {nights} nights")
            st.write(f"**Total:** ₹{total_stay:,.0f}")
        elif raw_price is not None:
            st.write(f"**Price:** ₹{raw_price:,.0f}" if isinstance(raw_price, (int, float)) else f"**Price:** ₹{raw_price}")


def render_weather(weather: dict, destination_name: str = "Destination"):
    st.subheader(f"Weather Forecast ({destination_name})")
    if not weather or not isinstance(weather, dict) or not weather.get("forecast"):
        with st.container(border=True):
            st.info("Weather data unavailable for this date.")
        return

    forecast = weather.get("forecast") or []
    if isinstance(forecast, list):
        def _parse_ui_date(item):
            from datetime import datetime
            if not isinstance(item, dict):
                return date.min
            d = item.get("date")
            if isinstance(d, date):
                return d
            if hasattr(d, "date") and callable(d.date):
                return d.date()
            if d:
                d_str = str(d).strip()[:10]
                try:
                    return date.fromisoformat(d_str)
                except Exception:
                    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                        try:
                            return datetime.strptime(d_str, fmt).date()
                        except Exception:
                            continue
            return date.min

        forecast = sorted(forecast, key=_parse_ui_date)

    forecast_type = weather.get("forecast_type")
    with st.container(border=True):
        if forecast_type == "seasonal_climate_estimate":
            st.caption("Based on destination seasonal climate averages & historical weather trends for these dates.")

        num_cols = 4
        items_to_show = forecast[:8]
        for i in range(0, len(items_to_show), num_cols):
            chunk = items_to_show[i:i + num_cols]
            cols = st.columns(len(chunk))
            for col, day in zip(cols, chunk):
                with col:
                    d_str = day.get("date", "")
                    cond = day.get("weather", "Mainly clear")
                    temps = day.get("temperature", {})
                    min_t = temps.get("min_c") if isinstance(temps, dict) else None
                    max_t = temps.get("max_c") if isinstance(temps, dict) else None
                    rain_p = day.get("rain_probability")

                    st.markdown(f"**{d_str}**")
                    st.write(cond)
                    min_num = _safe_float(min_t)
                    max_num = _safe_float(max_t)
                    rain_num = _safe_float(rain_p)

                    if min_num is not None and max_num is not None:
                        st.write(f"{min_num:.0f}°C - {max_num:.0f}°C")
                    if rain_num is not None and rain_num > 0:
                        st.caption(f"Rain: {rain_num:g}%")


def render_budget(budget_summary: dict, data: dict = None):
    if not budget_summary:
        return

    st.subheader("Budget Breakdown")
    with st.container(border=True):
        def fmt(value):
            numeric = _safe_float(value)
            return f"₹{numeric:,.0f}" if numeric is not None else str(value)

        # Resolve the user's original trip budget first.
        # The final budget_summary can contain a stale/default 0, so prefer
        # the persisted trip/state budget when it is available.
        trip_data = data.get("trip", {}) if isinstance(data, dict) and isinstance(data.get("trip"), dict) else {}

        user_budget = None

        # 1. Final budget summary, when it contains a real value.
        for key in ("total_budget", "budget_limit"):
            value = budget_summary.get(key)
            if value is not None:
                try:
                    user_budget = float(value)
                    break
                except (TypeError, ValueError):
                    pass

        # 2. Recover the original budget from the final API response.
        # TripState exposes budget as an object such as {"amount": 20000}.
        budget_sources = [
            data.get("budget") if isinstance(data, dict) else None,
            trip_data.get("budget") if isinstance(trip_data, dict) else None,
        ]

        for source in budget_sources:
            if source is None:
                continue

            candidate = source
            if isinstance(source, dict):
                candidate = source.get("amount")
                if candidate is None:
                    candidate = source.get("total_budget")
                if candidate is None:
                    candidate = source.get("budget_limit")

            if candidate is not None:
                try:
                    candidate = float(candidate)
                    # A positive persisted budget is authoritative over a
                    # stale/default zero in budget_summary.
                    if candidate > 0 or user_budget is None:
                        user_budget = candidate
                        break
                except (TypeError, ValueError):
                    continue

        # Keep integer-looking budgets clean in the UI.
        if user_budget is not None and float(user_budget).is_integer():
            user_budget = int(user_budget)

        remaining = budget_summary.get("remaining_budget")

        # Recalculate remaining budget from the same two values shown below.
        # This prevents a stale remaining_budget (for example one calculated
        # against ₹0) from contradicting the displayed user budget.
        estimated_total = budget_summary.get("estimated_total")
        if estimated_total is None:
            estimated_total = (
                budget_summary.get("estimated_cost")
                or budget_summary.get("calculated_cost")
            )

        if user_budget is not None and estimated_total is not None:
            total_num = _safe_float(estimated_total)
            if total_num is not None:
                estimated_total = total_num
                remaining = float(user_budget) - total_num

        if remaining is not None and remaining < 0:
            excess = abs(remaining)
            st.error(
                f"Budget Exceeded by {fmt(excess)}. "
                f"The estimated trip cost exceeds your budget of {fmt(user_budget)}."
            )

        travelers_dict = trip_data.get("travelers", {}) if isinstance(trip_data.get("travelers"), dict) else {}
        adults = travelers_dict.get("adults", trip_data.get("adults", 1))
        children = travelers_dict.get("children", trip_data.get("children", 0))
        calc_pax = max(1, (adults or 1) + (children or 0))

        pax = budget_summary.get("travelers_count") or calc_pax

        t_class = (
            budget_summary.get("transport_class")
            or (get_transport_info(data).get("selected_class_name") if data else None)
            or (get_transport_info(data).get("class_name") if data else None)
        )
        class_suffix = f" • {t_class}" if t_class else ""

        rows = []
        if user_budget is not None:
            rows.append(("Total Trip Budget", fmt(user_budget)))

        # Transport
        if budget_summary.get("estimated_transport") is not None:
            t_label = f"Transport (Roundtrip{class_suffix} for {pax} Travelers)" if pax and pax > 1 else f"Transport (Roundtrip{class_suffix})"
            rows.append((t_label, fmt(budget_summary["estimated_transport"])))
            out_p = _safe_float(budget_summary.get("outbound_transport_price"))
            ret_p = _safe_float(budget_summary.get("return_transport_price"))
            if out_p is not None and ret_p is not None and (out_p > 0 or ret_p > 0):
                out_c = budget_summary.get("transport_class") or "Selected Class"
                ret_c = budget_summary.get("return_transport_class") or out_c
                if pax > 1:
                    rows.append((f"  ↳ Outbound ({out_c})", f"{fmt(out_p)} / person = {fmt(out_p * pax)}"))
                    rows.append((f"  ↳ Return ({ret_c})", f"{fmt(ret_p)} / person = {fmt(ret_p * pax)}"))
                else:
                    rows.append((f"  ↳ Outbound ({out_c})", fmt(out_p)))
                    rows.append((f"  ↳ Return ({ret_c})", fmt(ret_p)))
        else:
            rows.append(("Transport", "Not available"))

        # Hotel
        if budget_summary.get("estimated_hotel") is not None:
            h_nights = budget_summary.get("hotel_nights")
            label = f"Hotel Stay ({h_nights} Nights)" if h_nights and h_nights > 1 else "Hotel Stay"
            rows.append((label, fmt(budget_summary["estimated_hotel"])))
        else:
            rows.append(("Hotel Stay", "Not available"))

        # Activities
        rows.append(("Activities & Sightseeing", "Not included"))

        # Food & Local Transport
        rows.append(("Food / Local Transport", "Not included (Self-managed)"))

        # Total Trip Cost
        if estimated_total is not None:
            rows.append(("Calculated Trip Cost (Transport + Hotel)", fmt(estimated_total)))

        # Remaining Budget
        if remaining is not None:
            rows.append(("Remaining Budget", fmt(remaining)))

        for label, val_str in rows:
            col_l, col_v = st.columns([3, 2])
            with col_l:
                st.write(f"**{label}**")
            with col_v:
                st.write(val_str)


def render_itinerary(data: dict):
    st.divider()
    st.header("Trip Itinerary")

    trip = data.get("trip") or {}
    origin_name = extract_display_value(trip.get("origin")) or "Origin"
    destination_name = extract_display_value(trip.get("destination")) or "Destination"

    travelers_dict = trip.get("travelers", {}) if isinstance(trip.get("travelers"), dict) else {}
    adults = travelers_dict.get("adults", trip.get("adults", 1))
    children = travelers_dict.get("children", trip.get("children", 0))

    if origin_name or destination_name:
        st.subheader(f"{origin_name} → {destination_name}")
        st.markdown(f"👥 **Travelers:** {adults} Adults, {children} Children")

    days = get_itinerary_days(data)

    if not days:
        st.success("Trip Planned — the planning pipeline completed, but no itinerary days were returned.")
    else:
        transport_data = get_transport_info(data) or {}
        return_transport_data = transport_data.get("return_trip") if isinstance(transport_data.get("return_trip"), dict) else {}
        transfer_info = transport_data.get("transfer") or (data.get("transfer") if isinstance(data, dict) else None)

        for index, day in enumerate(days):
            day_number = day.get("day") or (index + 1)
            day_date = day.get("date") or ""
            day_status = day.get("status") or ""
            activities = day.get("activities") or []
            t_info = day.get("transport")
            constraint_text = day.get("travel_constraint")

            with st.container(border=True):
                header = f"Day {day_number}"
                if day_date:
                    header += f" - {day_date}"
                st.markdown(f"### {header}")

                # Outbound Travel Day (Day 1)
                if day_status == "outbound_travel" or (t_info and t_info.get("type") == "outbound") or (index == 0 and len(days) > 1 and day_status not in ["return_arrival", "departure_day"]):
                    has_real_outbound = bool(
                        transport_data
                        and not transport_data.get("transport_unavailable")
                        and transport_data.get("status") != "unavailable"
                        and (
                            transport_data.get("train_number")
                            or transport_data.get("flight_number")
                            or transport_data.get("airline")
                            or (transport_data.get("train_name") and "superfast" not in str(transport_data.get("train_name")).lower())
                            or (t_info and t_info.get("name") and "superfast" not in str(t_info.get("name")).lower())
                        )
                    )

                    if has_real_outbound:
                        t_mode_raw = str((t_info.get("mode") if t_info else None) or transport_data.get("type") or "").lower()
                        pref_raw = str(trip.get("transport_preference") or (data.get("transport_preference") if isinstance(data, dict) else "") or "").lower()
                        is_flight = (
                            "flight" in t_mode_raw
                            or bool(transport_data.get("airline") or transport_data.get("flight_number") or transport_data.get("flight_name"))
                            or (pref_raw == "flight" and not transport_data.get("train_number"))
                        )
                        t_mode = "Flight" if is_flight else "Train"

                        if is_flight:
                            f_airline = str(transport_data.get("airline") or "").strip()
                            f_number = str(transport_data.get("flight_number") or "").strip()
                            f_label = f"{f_airline} {f_number}".strip() if (f_airline or f_number) else ""
                            raw_name = (t_info.get("name") if t_info else None) or transport_data.get("flight_name") or transport_data.get("name") or f_label
                            t_name = raw_name if raw_name and str(raw_name).strip().lower() not in ("flight", "none", "unknown", "null", "") else (f_label or f"{origin_name} - {destination_name} Flight")
                        else:
                            t_name = (t_info.get("name") if t_info else None) or transport_data.get("train_name") or transport_data.get("name")

                        t_class = (t_info.get("class_name") if t_info else None) or transport_data.get("selected_class_name") or transport_data.get("class_name")
                        t_dep = (t_info.get("departure") if t_info else None) or transport_data.get("departure") or transport_data.get("departure_time")
                        t_arr = (t_info.get("arrival") if t_info else None) or transport_data.get("arrival") or transport_data.get("arrival_time")

                        orig_st_code = (t_info.get("origin_station_code") if t_info else None) or transport_data.get("from_station_code") or transport_data.get("from_code")
                        dest_st_code = (t_info.get("destination_station_code") if t_info else None) or transport_data.get("to_station_code") or transport_data.get("to_code")

                        if orig_st_code and dest_st_code:
                            out_journey_label = f"{origin_name} → {orig_st_code} → {dest_st_code} → {destination_name}"
                        elif dest_st_code:
                            out_journey_label = f"{origin_name} → {dest_st_code} → {destination_name}"
                        else:
                            out_journey_label = f"{origin_name} → {destination_name}"

                        st.markdown(f"**Outbound Journey:** {out_journey_label}")

                        day_first_mile = (
                            (t_info.get("first_mile_transfer") if isinstance(t_info, dict) else None)
                            or transport_data.get("first_mile_transfer")
                            or (data.get("first_mile_transfer") if isinstance(data, dict) else None)
                        )
                        fm_banner = _format_transfer_banner(day_first_mile)
                        if fm_banner:
                            st.info(f"🚗 **Transfer to Station:** {fm_banner}")

                        day_out_transfer = (
                            (t_info.get("transfer") if isinstance(t_info, dict) else None)
                            or (t_info.get("last_mile_transfer") if isinstance(t_info, dict) else None)
                            or (t_info.get("outbound_transfer") if isinstance(t_info, dict) else None)
                            or transport_data.get("last_mile_transfer")
                            or transport_data.get("outbound_transfer")
                            or transport_data.get("transfer")
                            or (data.get("outbound_transfer") if isinstance(data, dict) else None)
                            or (data.get("transfer") if isinstance(data, dict) else None)
                        )
                        is_out_overnight = bool(t_info.get("is_overnight")) if (t_info and isinstance(t_info, dict)) else False
                        out_banner = _format_transfer_banner(day_out_transfer)
                        if out_banner and not is_out_overnight:
                            st.info(f"🚗 **Transfer:** {out_banner}")

                        if t_name:
                            st.write(f"**{t_mode} Name:** {extract_display_value(t_name)}")
                        if t_class:
                            st.write(f"**Travel Class:** {t_class}")
                        if t_dep:
                            st.write(f"**Departure:** {t_dep}")

                        if is_out_overnight:
                            if t_arr:
                                st.write(f"**Arrival:** {t_arr} (Next Day)")
                            st.caption("🌙 Overnight journey in transit. Arrival is scheduled for tomorrow.")
                        else:
                            if t_arr:
                                st.write(f"**Arrival:** {t_arr}")
                    else:
                        st.markdown(f"**Outbound Journey:** {origin_name} → {destination_name}")
                        st.info("Outbound transport could not be verified online for this route. Please check booking portals for current availability.")

                    if constraint_text:
                        st.caption(f"ℹ️ {constraint_text}")

                # Outbound Arrival Day (Overnight Journey Arrival)
                elif day_status == "arrival_day" and (t_info and t_info.get("type") == "outbound_arrival"):
                    t_mode_raw = str((t_info.get("mode") if t_info else None) or transport_data.get("type") or "").lower()
                    pref_raw = str(trip.get("transport_preference") or (data.get("transport_preference") if isinstance(data, dict) else "") or "").lower()
                    is_flight = (
                        "flight" in t_mode_raw
                        or bool(transport_data.get("airline") or transport_data.get("flight_number") or transport_data.get("flight_name"))
                        or (pref_raw == "flight" and not transport_data.get("train_number"))
                    )
                    t_mode = "Flight" if is_flight else "Train"

                    t_name = (t_info.get("name") if t_info else None) or transport_data.get("train_name") or transport_data.get("name")
                    t_arr = (t_info.get("arrival") if t_info else None) or transport_data.get("arrival") or transport_data.get("arrival_time")
                    t_dest_arr = t_info.get("destination_arrival")
                    dest_st_name = t_info.get("destination_station") or transport_data.get("to_station_name")
                    dest_st_code = t_info.get("destination_station_code") or transport_data.get("to_station_code") or transport_data.get("to_code")
                    dest_st_label = f"{dest_st_name} ({dest_st_code})" if dest_st_name and dest_st_code and dest_st_code not in dest_st_name else (dest_st_name or dest_st_code or destination_name)

                    st.markdown(f"**Arrival:** {dest_st_label}")
                    if t_arr:
                        st.write(f"**Station/Airport Arrival:** {t_arr}")
                    if t_dest_arr and t_dest_arr != t_arr:
                        st.write(f"**Destination Arrival:** {t_dest_arr}")

                    day_out_transfer = (
                        (t_info.get("transfer") if isinstance(t_info, dict) else None)
                        or (t_info.get("outbound_transfer") if isinstance(t_info, dict) else None)
                        or transport_data.get("last_mile_transfer")
                        or transport_data.get("outbound_transfer")
                        or transport_data.get("transfer")
                    )
                    out_banner = _format_transfer_banner(day_out_transfer)
                    if out_banner:
                        st.info(f"🚗 **Transfer to Selected Hotel:** {out_banner}")
                    st.write("🏨 **Hotel Check-in**")
                    st.write("🛌 **Rest and settle in**")

                    if constraint_text:
                        st.caption(f"ℹ️ {constraint_text}")

                    visible_activities = _visible_sightseeing_activities(activities)
                    if visible_activities:
                        st.markdown("---")
                        st.markdown("**Sightseeing Activities:**")
                        for activity in visible_activities:
                            name = (
                                activity.get("name")
                                or activity.get("place_name")
                                or activity.get("place")
                                or activity.get("title")
                                or "Activity"
                            )
                            st.markdown(f"• **{extract_display_value(name)}**")

                # Return Travel Day (Departure Day)
                elif day_status == "departure_day" or (t_info and t_info.get("type") == "return"):
                    has_real_return = bool(
                        (return_transport_data or transport_data)
                        and not (return_transport_data or transport_data).get("transport_unavailable")
                        and (return_transport_data or transport_data).get("status") != "unavailable"
                        and (
                            (return_transport_data or transport_data).get("train_number")
                            or (return_transport_data or transport_data).get("flight_number")
                            or (return_transport_data or transport_data).get("airline")
                            or ((return_transport_data or transport_data).get("train_name") and "return express" not in str((return_transport_data or transport_data).get("train_name")).lower())
                            or (t_info and t_info.get("name") and "return express" not in str(t_info.get("name")).lower())
                        )
                    )

                    if has_real_return:
                        ret_mode_raw = str((t_info.get("mode") if t_info else None) or return_transport_data.get("type") or transport_data.get("type") or "").lower()
                        is_ret_flight = (
                            "flight" in ret_mode_raw
                            or bool(return_transport_data.get("airline") or return_transport_data.get("flight_number") or return_transport_data.get("flight_name"))
                        )
                        ret_mode = "Flight" if is_ret_flight else "Train"

                        if is_ret_flight:
                            r_airline = str(return_transport_data.get("airline") or transport_data.get("airline") or "").strip()
                            r_number = str(return_transport_data.get("flight_number") or "").strip()
                            r_label = f"{r_airline} {r_number}".strip() if (r_airline or r_number) else ""
                            raw_ret = (t_info.get("name") if t_info else None) or return_transport_data.get("flight_name") or return_transport_data.get("name") or r_label
                            ret_name = raw_ret if raw_ret and str(raw_ret).strip().lower() not in ("flight", "none", "unknown", "null", "") else (r_label or f"{destination_name} - {origin_name} Return Flight")
                        else:
                            ret_name = (t_info.get("name") if t_info else None) or return_transport_data.get("train_name") or return_transport_data.get("name")

                        ret_class = (t_info.get("class_name") if t_info else None) or return_transport_data.get("selected_class_name") or return_transport_data.get("class_name") or transport_data.get("selected_class_name") or transport_data.get("class_name")
                        ret_dep = (t_info.get("departure") if t_info else None) or return_transport_data.get("departure") or return_transport_data.get("departure_time")
                        ret_arr = (t_info.get("arrival") if t_info else None) or return_transport_data.get("arrival") or return_transport_data.get("arrival_time")

                        ret_orig_code = (t_info.get("origin_station_code") if t_info else None) or return_transport_data.get("from_station_code") or return_transport_data.get("from_code")
                        ret_dest_code = (t_info.get("destination_station_code") if t_info else None) or return_transport_data.get("to_station_code") or return_transport_data.get("to_code") or transport_data.get("from_station_code") or transport_data.get("from_code")

                        if ret_orig_code and ret_dest_code:
                            ret_journey_label = f"{destination_name} → {ret_orig_code} → {ret_dest_code} → {origin_name}"
                        elif ret_orig_code:
                            ret_journey_label = f"{destination_name} → {ret_orig_code} → {origin_name}"
                        else:
                            ret_journey_label = f"{destination_name} → {origin_name}"

                        st.markdown(f"**Return Journey:** {ret_journey_label}")

                        day_ret_transfer = (
                            (t_info.get("transfer") if isinstance(t_info, dict) else None)
                            or (t_info.get("return_transfer") if isinstance(t_info, dict) else None)
                            or return_transport_data.get("first_mile_transfer")
                            or return_transport_data.get("return_first_mile_transfer")
                            or return_transport_data.get("return_transfer")
                            or return_transport_data.get("transfer")
                            or transport_data.get("return_transfer")
                            or (data.get("return_transfer") if isinstance(data, dict) else None)
                        )
                        st.write("🏨 **Hotel Check-out**")
                        ret_banner = _format_transfer_banner(day_ret_transfer)
                        if ret_banner:
                            st.info(f"🚗 **Transfer to Boarding Station/Airport:** {ret_banner}")

                        if ret_name:
                            st.write(f"**{ret_mode} Name:** {extract_display_value(ret_name)}")
                        if ret_class:
                            st.write(f"**Travel Class:** {ret_class}")
                        if ret_dep:
                            st.write(f"**Departure:** {ret_dep}")

                        is_overnight = bool(t_info.get("is_overnight")) if (t_info and isinstance(t_info, dict)) else False
                        if is_overnight:
                            if ret_arr:
                                st.write(f"**Arrival:** {ret_arr} (Next Day)")
                            st.caption("🌙 Overnight return journey in transit. Arrival is scheduled for tomorrow.")
                        else:
                            if ret_arr:
                                st.write(f"**Arrival:** {ret_arr}")
                            day_last_mile = (
                                (t_info.get("last_mile_transfer") if isinstance(t_info, dict) else None)
                                or return_transport_data.get("return_last_mile_transfer")
                                or return_transport_data.get("last_mile_transfer")
                            )
                            if day_last_mile:
                                lm_banner = _format_transfer_banner(day_last_mile)
                                if lm_banner:
                                    st.info(f"🚗 **Transfer:** {lm_banner}")
                    else:
                        st.markdown(f"**Return Journey:** {destination_name} → {origin_name}")
                        st.info("Return transport could not be verified online for this route. Please check booking portals for current availability.")

                    if constraint_text:
                        st.caption(f"ℹ️ {constraint_text}")

                # Return Travel Overnight Arrival Day (Final Day for Overnight Return)
                elif day_status == "return_arrival" or (t_info and t_info.get("type") == "return_arrival"):
                    ret_mode_raw = str((t_info.get("mode") if t_info else None) or return_transport_data.get("type") or transport_data.get("type") or "").lower()
                    is_ret_flight = "flight" in ret_mode_raw or bool(return_transport_data.get("airline") or return_transport_data.get("flight_number") or return_transport_data.get("flight_name"))
                    ret_mode = "Flight" if is_ret_flight else "Train"

                    ret_name = (t_info.get("name") if t_info else None) or return_transport_data.get("train_name") or return_transport_data.get("flight_name") or return_transport_data.get("name")
                    ret_arr = (t_info.get("arrival") if t_info else None) or return_transport_data.get("arrival") or return_transport_data.get("arrival_time")

                    dest_st_name = (t_info.get("destination_station") if t_info else None) or return_transport_data.get("to_station_name") or return_transport_data.get("destination_station_name")
                    dest_st_code = (t_info.get("destination_station_code") if t_info else None) or return_transport_data.get("to_station_code") or return_transport_data.get("to_code") or transport_data.get("from_station_code") or transport_data.get("from_code")

                    if dest_st_name and dest_st_code and dest_st_code not in dest_st_name:
                        dest_st_label = f"{dest_st_name} ({dest_st_code})"
                    elif dest_st_name:
                        dest_st_label = dest_st_name
                    elif dest_st_code:
                        dest_st_label = dest_st_code
                    else:
                        dest_st_label = origin_name

                    st.markdown("**Final Arrival**")
                    if ret_arr:
                        st.write(f"**Arrival at {dest_st_label}:** {ret_arr}")
                    ret_final_arr = t_info.get("origin_final_arrival") if isinstance(t_info, dict) else None
                    if ret_final_arr and ret_final_arr != ret_arr:
                        st.write(f"**Final Arrival at {origin_name}:** {ret_final_arr}")
                    st.success("Journey completed.")

                    if constraint_text:
                        st.caption(f"ℹ️ {constraint_text}")

                # In Transit Day
                elif day_status == "in_transit" or (t_info and t_info.get("type") == "in_transit"):
                    st.markdown("🚆 **In Transit**")
                    if constraint_text:
                        st.caption(f"ℹ️ {constraint_text}")
                    else:
                        st.caption("Journey in progress. Traveling towards destination.")

                # Sightseeing Activities & Leisure Days
                else:
                    if constraint_text:
                        st.caption(f"ℹ️ {constraint_text}")
                    visible_activities = _visible_sightseeing_activities(activities)
                    if visible_activities:
                        for activity in visible_activities:
                            name = (
                                activity.get("name")
                                or activity.get("place_name")
                                or activity.get("place")
                                or activity.get("title")
                                or "Activity"
                            )
                            st.markdown(f"• **{extract_display_value(name)}**")
                    else:
                        st.markdown("• **Free Day / Leisure**")
                        st.caption("No scheduled activities for this day. Enjoy free time, relaxation, or local exploration at your own pace.")

    budget_summary = data.get("budget_summary") or {}
    total_nights = (
        data.get("total_nights")
        or (data.get("itinerary", {}).get("total_nights") if isinstance(data.get("itinerary"), dict) else None)
        or (budget_summary.get("hotel_nights") if isinstance(budget_summary, dict) else None)
        or (len(days) - 1 if len(days) > 1 else 1)
    )
    render_transport(get_transport_info(data), data=data)
    render_hotel(get_hotel_info(data), budget_summary, total_nights=total_nights)
    render_weather(data.get("weather"), destination_name=destination_name)
    render_budget(budget_summary, data=data)


# =========================================================
# HEADER
# =========================================================

header_col1, header_col2 = st.columns([3, 1])

with header_col1:
    st.title("AI Travel Planner")
    st.caption("Plan your complete travel itinerary with verified transport, hotels, and activities.")

with header_col2:
    if st.session_state.authenticated:
        st.write(f"User: **{st.session_state.username}**")
        if st.button("Logout", use_container_width=True):
            do_logout()
            st.rerun()

st.divider()


# =========================================================
# MAIN FLOW
# =========================================================

if not st.session_state.authenticated:
    render_auth()
else:
    if st.session_state.hotel_selection_result and not st.session_state.itinerary_result:
        render_hotel_selection()
    else:
        render_planner()
        if st.session_state.itinerary_result:
            render_itinerary(st.session_state.itinerary_result)