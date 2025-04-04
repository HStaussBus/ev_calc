import datetime
import streamlit as st
import folium
from streamlit_folium import st_folium # Ensure this is imported

def handle_map_route_input(st, folium, st_folium, zipcodes_df, zip_lookup):
    import datetime

    # --- Initialize session state variables ---
    if "routes" not in st.session_state: st.session_state.routes = []
    if "selected_route_index" not in st.session_state: st.session_state.selected_route_index = 0
    if "last_clicked_location" not in st.session_state: st.session_state.last_clicked_location = None # For map centering
    if "last_processed_click" not in st.session_state: st.session_state.last_processed_click = None # To prevent double processing

    # --- UI Elements ---
    st.subheader("Define Routes Interactively") # Changed header level
    st.write("Select/create route, choose marker type, click map.")

    # Expander for adding new routes
    with st.expander("Add New Route"):
        route_name_input = st.text_input("Enter New Route ID", key="map_input_new_route_name") # More specific key
        if st.button("Create Route", key="map_input_create_route_button") and route_name_input:
            route_id_clean = route_name_input.strip()
            if any(r['route_id'] == route_id_clean for r in st.session_state.routes):
                st.warning(f"Route ID '{route_id_clean}' already exists.")
            else:
                new_route = {"route_id": route_id_clean, "depot": None, "pickups": [], "dropoffs": [], "map_source": True}
                st.session_state.routes.append(new_route)
                st.session_state.selected_route_index = len(st.session_state.routes) - 1
                st.session_state.last_clicked_location = None # Reset click state
                st.session_state.last_processed_click = None
                st.success(f"Route '{route_id_clean}' added!")
                st.rerun()

    # Main interaction area if routes exist
    if not st.session_state.routes:
        st.info("No routes added yet. Create a new route above.")
        return

    # Route selection dropdown
    route_labels = [f"{r['route_id']}" for r in st.session_state.routes]
    if st.session_state.selected_route_index >= len(st.session_state.routes):
        st.session_state.selected_route_index = 0 # Reset index if out of bounds

    selected_route_label = st.selectbox("Select Route to Edit:", options=route_labels, index=st.session_state.selected_route_index, key="map_input_route_selector")
    current_index = route_labels.index(selected_route_label)
    if st.session_state.selected_route_index != current_index: # If selection changed
        st.session_state.selected_route_index = current_index
        st.session_state.last_clicked_location = None # Reset click state on route change
        st.session_state.last_processed_click = None
        st.rerun() # Rerun if route selection changes
    current_route = st.session_state.routes[current_index]


    # Delete route button
    if st.button(f"🗑️ Delete Route '{current_route['route_id']}'", key=f"map_input_delete_route_{current_index}"):
        route_id_deleted = current_route['route_id']
        del st.session_state.routes[current_index]
        st.session_state.selected_route_index = max(0, min(current_index, len(st.session_state.routes) - 1))
        st.session_state.last_clicked_location = None
        st.session_state.last_processed_click = None
        st.warning(f"Route '{route_id_deleted}' deleted.")
        st.rerun()

    # Map controls
    controls_cols = st.columns([1, 2])
    with controls_cols[0]:
        marker_type = st.radio("Marker Type to Add:", ["Depot", "Pickup", "Dropoff"], key="map_input_marker_type")
    with controls_cols[1]:
        zip_input = st.text_input("Jump to ZIP Code:", key="map_input_zip")
        if zip_input: # If user types in zip input, clear last click state
            st.session_state.last_clicked_location = None
            st.session_state.last_processed_click = None

    # --- Determine Map Center/Zoom ---
    default_center = [40.7128, -74.0060]
    center = default_center
    zoom_start = 11
    use_bounds = None

    # --- Debugging Write ---


    if st.session_state.last_clicked_location:
        center = st.session_state.last_clicked_location
        zoom_start = 15
        #st.write(f"DEBUG: Centering on last_clicked_location: {center}") # Debug
    elif zip_input.isdigit() and len(zip_input) == 5 and int(zip_input) in zip_lookup:
        try:
            shape = zipcodes_df.loc[zipcodes_df["MODZCTA"] == int(zip_input), "geometry"].iloc[0]
            bounds = shape.bounds
            sw, ne = [bounds[1], bounds[0]], [bounds[3], bounds[2]]
            use_bounds = [sw, ne]
            center = [(sw[0] + ne[0]) / 2, (sw[1] + ne[1]) / 2]
            #st.write(f"DEBUG: Centering on ZIP: {center}") # Debug
        except Exception as e:
            st.warning(f"ZIP lookup failed: {e}")
            center = default_center
    elif current_route.get("depot"):
        center = current_route["depot"]
        zoom_start = 13
        #st.write(f"DEBUG: Centering on Depot: {center}") # Debug
    #else:
        #st.write(f"DEBUG: Centering on Default: {center}") # Debug


    # --- Create Map ---
    m = folium.Map(location=center, zoom_start=zoom_start, tiles="cartodbpositron", control_scale=True)

    # --- Add Markers ---
    marker_group = folium.FeatureGroup(name=f"Stops for Route {current_route['route_id']}")
    def create_map_marker(loc, tip, icon, color): # Simplified helper
        if not (isinstance(loc, (list, tuple)) and len(loc)==2): return None
        try: return folium.Marker(location=loc, tooltip=tip, icon=folium.Icon(color=color, icon=icon, prefix='fa'))
        except Exception: return None

    if current_route.get("depot"): marker_group.add_child(create_map_marker(current_route["depot"], "Depot", "bus", "red"))
    for i, p in enumerate(current_route.get("pickups",[])): marker_group.add_child(create_map_marker(p.get("location") if isinstance(p,dict) else p, f"Pickup {i+1}", "user-plus", "blue"))
    for i, d in enumerate(current_route.get("dropoffs",[])): marker_group.add_child(create_map_marker(d.get("location"), f"Dropoff {i+1}", "school", "green"))
    m.add_child(marker_group)

    # Fit bounds if using ZIP
    if use_bounds:
        try: m.fit_bounds(use_bounds, padding=(0.01, 0.01))
        except Exception as e: st.warning(f"Fit bounds failed: {e}")

    # --- Display Map ---
    map_key = f"route_map_{current_index}_stops_{len(current_route.get('pickups',[]))}_{len(current_route.get('dropoffs',[]))}"
    map_data = st_folium(m, key=map_key, width='100%', height=500) # REMOVED returned_objects=[]

    # --- Handle Click ---
    if map_data:
        clicked_data = map_data.get("last_clicked")
        if clicked_data:
            clicked_latlng = (clicked_data["lat"], clicked_data["lng"])
            #st.write(f"DEBUG: Click Detected at {clicked_latlng}") # Debug

            # Use last_processed_click to ensure we only process a new click once
            if clicked_latlng != st.session_state.get("last_processed_click"):
                

                # Set state for next rerun's centering
                st.session_state.last_clicked_location = clicked_latlng
                # Set state to prevent re-processing this specific click
                st.session_state.last_processed_click = clicked_latlng

                new_stop_added = False
                if marker_type == "Depot":
                    current_route["depot"] = clicked_latlng
                    st.success("Depot updated.")
                    new_stop_added = True
                elif marker_type == "Pickup":
                    current_route.setdefault("pickups", []).append({"location": clicked_latlng})
                    st.success(f"Pickup {len(current_route['pickups'])} added.")
                    new_stop_added = True
                elif marker_type == "Dropoff":
                    current_route.setdefault("dropoffs", []).append({"location": clicked_latlng, "bell_time": None})
                    st.success(f"Dropoff {len(current_route['dropoffs'])} added.")
                    new_stop_added = True

                if new_stop_added:
                    st.rerun() # Rerun ONLY if a stop was added/updated
            # else: # Debugging for ignored click
                # st.write(f"DEBUG: Ignoring duplicate click event for {clicked_latlng}")

    # --- Display Stops List & Actions ---
    st.markdown("---")
    st.subheader(f"Stops for Route: {current_route['route_id']}")
    # ... (Rest of the code to display Depot, Pickups, Dropoffs, Bell Times - NO CHANGES NEEDED HERE) ...
    # Display Depot
    st.markdown("**Depot:**")
    if current_route.get("depot"):
        depot_cols = st.columns([4, 1])
        depot_cols[0].write(f"📍 {current_route['depot']}")
        if depot_cols[1].button("Remove Depot", key=f"remove_depot_{current_index}", type="secondary"):
            current_route["depot"] = None; st.session_state.last_clicked_location = None; st.session_state.last_processed_click = None; st.rerun()
    else: st.caption("No depot added yet.")
    # Display Pickups
    st.markdown("**Pickups:**")
    if current_route.get("pickups"):
        for i, pt_data in enumerate(current_route["pickups"]):
            pickup_loc = pt_data.get("location") if isinstance(pt_data, dict) else pt_data
            pickup_cols = st.columns([4, 1])
            pickup_cols[0].write(f" P{i+1}: {pickup_loc}")
            if pickup_cols[1].button(f"Remove P{i+1}", key=f"remove_pickup_{current_index}_{i}", type="secondary"):
                current_route["pickups"].pop(i); st.session_state.last_clicked_location = None; st.session_state.last_processed_click = None; st.rerun()
    else: st.caption("No pickups added yet.")
    # Display Dropoffs
    st.markdown("**Dropoffs:**")
    if current_route.get("dropoffs"):
        for i, pt_data in enumerate(current_route["dropoffs"]):
            dropoff_loc = pt_data["location"]
            dropoff_cols = st.columns([4, 1])
            dropoff_cols[0].write(f" D{i+1}: {dropoff_loc}")
            if dropoff_cols[1].button(f"Remove D{i+1}", key=f"remove_dropoff_{current_index}_{i}", type="secondary"):
                current_route["dropoffs"].pop(i); st.session_state.last_clicked_location = None; st.session_state.last_processed_click = None; st.rerun()
    else: st.caption("No dropoffs added yet.")
    # Bell Time Input Section
    if current_route.get("dropoffs"):
        st.markdown("---"); st.subheader("Set Bell Times (Optional)")
        for idx, dropoff in enumerate(current_route["dropoffs"]):
             current_bell_time = dropoff.get("bell_time")
             default_widget_time = current_bell_time if current_bell_time else datetime.time(8, 0)
             bell_time_input = st.time_input(f"Bell Time Dropoff {idx+1}", value=default_widget_time, key=f"bell_time_{current_index}_{idx}", help=f"Est. bell time for {dropoff['location']}")
             current_route["dropoffs"][idx]["bell_time"] = bell_time_input

    # --- Final Info Message ---
    st.markdown("---")
    st.info("Route data is managed in this session only and not saved permanently.")