import datetime
import streamlit as st
import folium

def handle_map_route_input(st, folium, st_folium, zipcodes_df, zip_lookup):
    import datetime

    st.header("Route Input")
    st.write("Choose the route, marker type, and click on the map to add stops instantly.")

    if st.button("Add New Route"):
        new_route = {
            "route_id": len(st.session_state.routes) + 1,
            "depot": None,
            "pickups": [],
            "dropoffs": []
        }
        st.session_state.routes.append(new_route)
        st.session_state.selected_route_index = len(st.session_state.routes) - 1

    if st.session_state.routes:
        route_labels = [f"Route {r['route_id']}" for r in st.session_state.routes]
        selected = st.selectbox("Select Route", options=route_labels, index=st.session_state.selected_route_index)
        current_index = route_labels.index(selected)
        st.session_state.selected_route_index = current_index
        current_route = st.session_state.routes[current_index]

        marker_type = st.radio("Marker Type", ["Depot", "Pickup", "Dropoff"])
        zip_input = st.text_input("Jump to ZIP Code (centers the map)")

        default_center = [40.7128, -74.0060]
        center = current_route["depot"] or default_center
        use_bounds = None

        if zip_input.isdigit() and int(zip_input) in zip_lookup:
            shape = zipcodes_df.loc[zipcodes_df["MODZCTA"] == int(zip_input), "geometry"].values[0]
            bounds = shape.bounds
            sw = [bounds[1], bounds[0]]
            ne = [bounds[3], bounds[2]]
            use_bounds = [sw, ne]
            center = [(sw[0] + ne[0]) / 2, (sw[1] + ne[1]) / 2]

        def create_simple_marker(location, label, color):
            return folium.Marker(location=location, tooltip=label, icon=folium.Icon(color=color))

        m = folium.Map(location=center, zoom_start=13)
        marker_group = folium.FeatureGroup(name="All Stops")

        if current_route["depot"]:
            marker_group.add_child(create_simple_marker(current_route["depot"], "Depot", "blue"))

        for idx, pickup in enumerate(current_route["pickups"]):
            pickup_location = pickup["location"] if isinstance(pickup, dict) else pickup
            marker_group.add_child(create_simple_marker(pickup_location, f"Pickup {idx+1}", "green"))

        for idx, dropoff in enumerate(current_route["dropoffs"]):
            marker_group.add_child(create_simple_marker(dropoff["location"], f"Dropoff {idx+1}", "red"))

        m.add_child(marker_group)

        if use_bounds:
            m.fit_bounds(use_bounds)

        map_key = f"main_map_route_{current_index}_v{len(current_route['pickups']) + len(current_route['dropoffs'])}"
        map_data = st_folium(m, key=map_key, width=700, height=500)

        clicked = map_data.get("last_clicked")
        if clicked:
            latlng = (clicked["lat"], clicked["lng"])
            if latlng != st.session_state.last_clicked_location:
                st.session_state.last_clicked_location = latlng

                if marker_type == "Depot":
                    current_route["depot"] = latlng
                elif marker_type == "Pickup":
                    current_route["pickups"].append({
                        "location": latlng,
                        "pickup_time": None
                    })
                elif marker_type == "Dropoff":
                    current_route["dropoffs"].append({"location": latlng, "bell_time": None})

                st.rerun()

        st.subheader("Pickups")
        for i, pt in enumerate(current_route["pickups"]):
            cols = st.columns([5, 1])
            pickup_location = pt["location"] if isinstance(pt, dict) else pt
            cols[0].write(f"📍 Pickup {i+1}: {pickup_location}")
            if cols[1].button("Remove", key=f"remove_pickup_{i}"):
                current_route["pickups"].pop(i)
                st.rerun()

        st.subheader("Dropoffs")
        for i, pt in enumerate(current_route["dropoffs"]):
            cols = st.columns([5, 1])
            cols[0].write(f"\U0001F3AF Dropoff {i+1}: {pt['location']}")
            if cols[1].button("Remove", key=f"remove_dropoff_{i}"):
                current_route["dropoffs"].pop(i)
                st.rerun()

        if current_route["dropoffs"]:
            st.write("### Set Bell Times for Dropoffs")
            for idx, dropoff in enumerate(current_route["dropoffs"]):
                default_time = dropoff["bell_time"] if dropoff["bell_time"] else datetime.time(8, 0)
                bell_time = st.time_input(f"Bell Time for Dropoff {idx+1}", value=default_time, key=f"bell_time_{current_index}_{idx}")
                current_route["dropoffs"][idx]["bell_time"] = bell_time

        if current_route["pickups"]:
            st.write("### Set First Pickup Time")
            # Replace tuple with dictionary to support metadata
            if isinstance(current_route["pickups"][0], tuple):
                current_route["pickups"][0] = {
                    "location": current_route["pickups"][0],
                    "pickup_time": None
                }
            first_pickup = current_route["pickups"][0]
            default_time = first_pickup["pickup_time"] if first_pickup["pickup_time"] else datetime.time(7, 0)
            pickup_time = st.time_input(f"First Pickup Time for Route {current_route['route_id']}", value=default_time, key=f"pickup_time_{current_index}")
            current_route["pickups"][0]["pickup_time"] = pickup_time

        st.info("\U0001F512 Route data is processed in memory only and is not stored or shared.")
        st.write("**Current Route Data:**", current_route)
    else:
        st.info("No routes added yet. Click 'Add New Route' to start.")