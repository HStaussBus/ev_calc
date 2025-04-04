import datetime
import streamlit as st
import folium
from streamlit_folium import st_folium # Ensure this is imported

# Assume zipcodes_df and zip_lookup are loaded globally before this function is called
# and passed as arguments.
# zip_lookup format: {'zip_string': {'latitude': lat, 'longitude': lon}}

def handle_map_route_input(st, folium, st_folium, zipcodes_df, zip_lookup):
    """
    Handles interactive route definition using a Folium map within Streamlit.
    Allows adding/selecting routes, adding stops via map click, setting bell times,
    deleting routes/stops, and includes button-triggered ZIP code centering.
    Map is displayed below controls. Defaults to centering on the last added stop.

    Args:
        st: The Streamlit module.
        folium: The Folium module.
        st_folium: The streamlit_folium component function.
        zipcodes_df: DataFrame related to zipcodes (used minimally now).
        zip_lookup: Dictionary mapping 5-digit zip string to {'latitude': lat, 'longitude': lon}.
    """
    import datetime # Ensure datetime is available inside the function

    # --- Initialize session state variables ---
    if "routes" not in st.session_state: st.session_state.routes = []
    if "selected_route_index" not in st.session_state: st.session_state.selected_route_index = 0
    if "last_processed_click" not in st.session_state: st.session_state.last_processed_click = None # To prevent double processing
    if "center_on_next_run" not in st.session_state: st.session_state.center_on_next_run = None # Stores [lat, lon] for ZIP jump

    # --- UI Elements ---
    st.subheader("Define Routes Interactively")
    st.write("Select/create route, choose marker type, click map to add stops.")

    # --- Add New Route Section ---
    with st.expander("Add New Route"):
        route_name_input = st.text_input("Enter New Route ID", key="map_input_new_route_name")
        if st.button("Create Route", key="map_input_create_route_button") and route_name_input:
            route_id_clean = route_name_input.strip()
            if any(r['route_id'] == route_id_clean for r in st.session_state.routes):
                st.warning(f"Route ID '{route_id_clean}' already exists.")
            else:
                new_route = {"route_id": route_id_clean, "depot": None, "pickups": [], "dropoffs": [], "map_source": True}
                st.session_state.routes.append(new_route)
                st.session_state.selected_route_index = len(st.session_state.routes) - 1
                st.session_state.last_processed_click = None
                st.session_state.center_on_next_run = None
                st.success(f"Route '{route_id_clean}' added!")
                st.rerun()

    # --- Route Selection and Main Interaction Area ---
    if not st.session_state.routes:
        st.info("No routes added yet. Create a new route above.")
        return # Stop if no routes exist

    # Route selection dropdown
    route_labels = [f"{r['route_id']}" for r in st.session_state.routes]
    if st.session_state.selected_route_index >= len(st.session_state.routes):
        st.session_state.selected_route_index = 0 # Reset index safely

    selected_route_label = st.selectbox(
        "Select Route to Edit:",
        options=route_labels,
        index=st.session_state.selected_route_index,
        key="map_input_route_selector"
    )
    current_index = route_labels.index(selected_route_label)
    # Check if selection changed vs previous state
    if st.session_state.selected_route_index != current_index:
        st.session_state.selected_route_index = current_index
        # Reset state when user manually changes route selection
        st.session_state.last_processed_click = None
        st.session_state.center_on_next_run = None
        st.rerun() # Rerun to load the newly selected route's map state
    # Get the currently selected route object AFTER potential rerun
    # Ensure index is still valid after potential deletion before accessing
    if st.session_state.selected_route_index >= len(st.session_state.routes):
         st.session_state.selected_route_index = 0 # Reset if index became invalid
         if not st.session_state.routes: return # Exit again if routes became empty
    current_route = st.session_state.routes[st.session_state.selected_route_index] # Use updated index


    # Delete route button
    if st.button(f"🗑️ Delete Route '{current_route['route_id']}'", key=f"map_input_delete_route_{current_index}"):
        route_id_deleted = current_route['route_id']
        del st.session_state.routes[current_index]
        st.session_state.selected_route_index = max(0, min(current_index, len(st.session_state.routes) - 1))
        # Reset state
        st.session_state.last_processed_click = None
        st.session_state.center_on_next_run = None
        st.warning(f"Route '{route_id_deleted}' deleted.")
        st.rerun()

    # --- Map Controls (Marker Type and ZIP Jump Button) ---
    controls_cols = st.columns([1, 1, 1]) # 3 columns for Marker | ZIP Input | Jump Button
    with controls_cols[0]:
        marker_type = st.radio(
            "Marker Type to Add:",
            ["Depot", "Pickup", "Dropoff"],
            key="map_input_marker_type",
            horizontal=False
        )
    with controls_cols[1]:
        # Text input needs a key so button can access its value via session state
        st.text_input(
            "Enter ZIP Code:",
            key="map_input_zip_text", # Key for text input widget state
            help="Enter a 5-digit NYC ZIP code"
        )
    with controls_cols[2]:
        st.write("") # Vertical alignment helpers
        st.write("")
        if st.button("Jump to ZIP", key="map_input_zip_button"):
            zip_input_value = st.session_state.get("map_input_zip_text", "").strip() # Get value safely
            # st.write(f"DEBUG [Button]: ZIP Button Clicked. Input Value: '{zip_input_value}'") # DEBUG
            if zip_input_value:
                try:
                    zip_code_str = zip_input_value.zfill(5)
                    # st.write(f"DEBUG [Button]: Padded ZIP: '{zip_code_str}'") # DEBUG
                    # st.write(f"DEBUG [Button]: Checking if '{zip_code_str}' in zip_lookup keys...") # DEBUG
                    if not isinstance(zip_lookup, dict) or not zip_lookup:
                         st.error("DEBUG [Button]: zip_lookup is invalid or empty!")
                    elif zip_code_str in zip_lookup:
                        # st.write(f"DEBUG [Button]: ZIP Found in lookup!") # DEBUG
                        zip_data = zip_lookup[zip_code_str]
                        lat = zip_data.get('latitude')
                        lon = zip_data.get('longitude')
                        if lat is not None and lon is not None:
                            # st.write(f"DEBUG [Button]: Setting center_on_next_run to: {[lat, lon]}") # DEBUG
                            st.session_state.center_on_next_run = [lat, lon]
                            st.session_state.last_processed_click = None # Clear click state when jumping
                            # st.write("DEBUG [Button]: Triggering rerun...") # DEBUG
                            st.rerun() # Rerun to apply centering
                        else: st.warning(f"Coords not found for ZIP {zip_code_str}.")
                    else: st.warning(f"ZIP {zip_code_str} not found.")
                except Exception as e: st.warning(f"Error processing ZIP: {e}")
            else: st.warning("Please enter a ZIP code.")
    # --- End Map Controls ---

    # Separator between controls and map
    st.markdown("---")

    # *** Use st.container for the map section to ensure layout ***
    map_container = st.container()
    with map_container:
        # --- Determine Map Center and Zoom ---
        default_center = [40.7128, -74.0060]
        center = default_center
        zoom_start = 11
        # centering_reason = "Default" # Keep for debug if needed

        # Logic based on stops/depot for the base map object
        dropoffs = current_route.get("dropoffs", [])
        pickups = current_route.get("pickups", [])
        depot = current_route.get("depot")
        if dropoffs:
            last_dropoff_loc = dropoffs[-1].get("location");
            if last_dropoff_loc: center = last_dropoff_loc; zoom_start = 15; # centering_reason = "Last Dropoff"
        elif pickups:
            last_pickup_loc = pickups[-1].get("location");
            if last_pickup_loc: center = last_pickup_loc; zoom_start = 15; # centering_reason = "Last Pickup"
        elif depot:
            center = depot; zoom_start = 13; # centering_reason = "Depot"

        # st.write(f"DEBUG: Base Map Center Reason: {centering_reason}, Center: {center}, Zoom: {zoom_start}")

        # Create the map using the determined default/stop-based center
        m = folium.Map(location=center, zoom_start=zoom_start, tiles="cartodbpositron", control_scale=True)

        # --- Add Markers ---
        marker_group = folium.FeatureGroup(name=f"Stops for Route {current_route['route_id']}")
        def create_map_marker(loc, tip, icon, color): # Simplified helper
            if not (isinstance(loc, (list, tuple)) and len(loc)==2): return None
            try: return folium.Marker(location=loc, tooltip=tip, icon=folium.Icon(color=color, icon=icon, prefix='fa'))
            except Exception: return None
        # Add markers safely
        if current_route.get("depot"): marker_group.add_child(create_map_marker(current_route["depot"], "Depot", "bus", "red"))
        for i, p_data in enumerate(current_route.get("pickups",[])): marker_group.add_child(create_map_marker(p_data.get("location"), f"Pickup {i+1}", "user-plus", "blue"))
        for i, d_data in enumerate(current_route.get("dropoffs",[])): marker_group.add_child(create_map_marker(d_data.get("location"), f"Dropoff {i+1}", "school", "green"))
        m.add_child(marker_group)

        # --- Prepare Overrides for st_folium based on ZIP Jump State ---
        # Check the temporary state variable JUST BEFORE calling st_folium
        map_center_override = None
        map_zoom_override = None
        if st.session_state.get("center_on_next_run"):
            map_center_override = st.session_state.center_on_next_run
            map_zoom_override = 14 # Zoom level for ZIP code
            # st.write(f"DEBUG [st_folium]: OVERRIDING center/zoom for ZIP jump: {map_center_override}") # Optional Debug
            # Clear the state variable AFTER reading it, before the component call
            if "center_on_next_run" in st.session_state:
                 del st.session_state.center_on_next_run
                 # st.write("DEBUG [st_folium]: DELETED center_on_next_run.") # Optional Debug

        # --- Display Map using st_folium with potential overrides ---
        # st.write("Map View:") # Optional Title
        map_key = f"route_map_{current_index}_p{len(current_route.get('pickups',[]))}_d{len(current_route.get('dropoffs',[]))}"
        map_data = st_folium(
            m,                          # The base Folium map object
            key=map_key,
            width='100%',
            height=500,
            center=map_center_override, # *** Pass override center ***
            zoom=map_zoom_override      # *** Pass override zoom ***
            # If overrides are None, st_folium uses the base map's settings
        )
        # --- End map display ---

    # --- End map_container --- # Make sure this 'with' block was closed if you used it before

    # --- Handle Map Click Event ---
    # ... (Click handling logic should remain outside the container, using map_data) ...
    # --- End map_container ---

    # --- Handle Map Click Event (Remains Outside Container) ---
    if map_data:
        clicked_data = map_data.get("last_clicked")
        if clicked_data:
            clicked_latlng = (clicked_data["lat"], clicked_data["lng"])
            # Use last_processed_click to ensure we only process a new click once
            if clicked_latlng != st.session_state.get("last_processed_click"):
                st.session_state.last_processed_click = clicked_latlng # Mark as processed
                new_stop_added = False
                if marker_type == "Depot":
                    if current_route.get("depot"): st.warning("Replacing existing Depot location.")
                    current_route["depot"] = clicked_latlng; st.success(f"Depot updated."); new_stop_added = True
                elif marker_type == "Pickup":
                    current_route.setdefault("pickups", []).append({"location": clicked_latlng}); st.success(f"Pickup {len(current_route['pickups'])} added."); new_stop_added = True
                elif marker_type == "Dropoff":
                    current_route.setdefault("dropoffs", []).append({"location": clicked_latlng, "bell_time": None}); st.success(f"Dropoff {len(current_route['dropoffs'])} added."); new_stop_added = True

                if new_stop_added:
                    # Ensure any pending ZIP jump request is cancelled if user adds stop via click
                    if "center_on_next_run" in st.session_state: del st.session_state.center_on_next_run
                    st.rerun()

    # --- Display Stops List & Actions Below Map (Remains Outside Container) ---
    st.markdown("---")
    st.subheader(f"Stops for Route: {current_route['route_id']}")

    # Display Depot & Remove Button
    st.markdown("**Depot:**")
    if current_route.get("depot"):
        depot_cols = st.columns([4, 1])
        depot_cols[0].write(f"📍 {current_route['depot']}")
        if depot_cols[1].button("Remove Depot", key=f"remove_depot_{current_index}", type="secondary"):
            current_route["depot"] = None; st.session_state.last_processed_click = None; st.session_state.center_on_next_run = None; st.rerun()
    else: st.caption("No depot added yet.")

    # Display Pickups & Remove Buttons
    st.markdown("**Pickups:**")
    pickups_list = current_route.get("pickups", [])
    if pickups_list:
        for i, pt_data in enumerate(pickups_list):
            pickup_loc = pt_data.get("location")
            pickup_cols = st.columns([4, 1])
            pickup_cols[0].write(f" P{i+1}: {pickup_loc}")
            if pickup_cols[1].button(f"Remove P{i+1}", key=f"remove_pickup_{current_index}_{i}", type="secondary"):
                current_route["pickups"].pop(i); st.session_state.last_processed_click = None; st.session_state.center_on_next_run = None; st.rerun()
    else: st.caption("No pickups added yet.")

    # Display Dropoffs & Remove Buttons
    st.markdown("**Dropoffs:**")
    dropoffs_list = current_route.get("dropoffs", [])
    if dropoffs_list:
        for i, pt_data in enumerate(dropoffs_list):
            dropoff_loc = pt_data.get("location")
            dropoff_cols = st.columns([4, 1])
            dropoff_cols[0].write(f" D{i+1}: {dropoff_loc}")
            if dropoff_cols[1].button(f"Remove D{i+1}", key=f"remove_dropoff_{current_index}_{i}", type="secondary"):
                current_route["dropoffs"].pop(i); st.session_state.last_processed_click = None; st.session_state.center_on_next_run = None; st.rerun()
    else: st.caption("No dropoffs added yet.")

    # Bell Time Input Section
    if dropoffs_list:
        st.markdown("---"); st.subheader("Set Bell Times (Optional)")
        for idx, dropoff in enumerate(dropoffs_list):
             current_bell_time = dropoff.get("bell_time"); default_widget_time = current_bell_time if current_bell_time else datetime.time(8, 0)
             bell_time_input = st.time_input(f"Bell Time Dropoff {idx+1}", value=default_widget_time, key=f"bell_time_{current_index}_{idx}", help=f"Est. bell time for D{idx+1}")
             current_route["dropoffs"][idx]["bell_time"] = bell_time_input

    # Final Info Message
    st.markdown("---"); st.info("Route data is managed in this session only.")