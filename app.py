import streamlit as st
from streamlit_folium import st_folium
import folium
from folium import FeatureGroup
import requests
import pandas as pd
import datetime
from shapely import wkt
import matplotlib.pyplot as plt
import streamlit.components.v1 as components


zipcodes_df = pd.read_csv(".data/Modified_Zip_Code_Tabulation_Areas__MODZCTA_.csv")

# Convert geometry to shapely objects and compute centroids
zipcodes_df["geometry"] = zipcodes_df["the_geom"].apply(wkt.loads)
zipcodes_df["centroid_lat"] = zipcodes_df["geometry"].apply(lambda g: g.centroid.y)
zipcodes_df["centroid_lng"] = zipcodes_df["geometry"].apply(lambda g: g.centroid.x)

# Build lookup: MODZCTA → (lat, lng)
zip_lookup = zipcodes_df.set_index("MODZCTA")[["centroid_lat", "centroid_lng"]].to_dict("index")

# ------------------------------
# Helper Functions
# ------------------------------

def get_route_distance(api_key, origin, waypoints, destination):
    """
    Uses the Google Maps Directions API to compute total driving distance.
    """
    base_url = "https://maps.googleapis.com/maps/api/directions/json"
    # Create the waypoints string if waypoints exist
    waypoints_str = "|".join([f"{wp[0]},{wp[1]}" for wp in waypoints]) if waypoints else ""
    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "waypoints": waypoints_str,
        "key": api_key,
        "mode": "driving",
        "traffic_model": "best_guess",
        "departure_time": "now"  # Added parameter to satisfy API requirements
    }
    st.write("**[Debug] Requesting route from Google Maps with parameters:**", params)
    response = requests.get(base_url, params=params)
    data = response.json()
    if data["status"] == "OK":
        total_distance = 0
        for leg in data["routes"][0]["legs"]:
            total_distance += leg["distance"]["value"] / 1609.34  # convert meters to miles
        return total_distance
    else:
        st.write("**[Error] Google Maps API response:**", data.get("error_message", data["status"]))
        return None

def get_min_temperature(location):
    """
    Placeholder for weather API. For demo purposes, if the depot's latitude is below 40, 
    simulate a min temp of 35°F; otherwise, 45°F.
    """
    lat = location[0]
    return 35 if lat < 40 else 45

# ------------------------------
# Initialize Session State
# ------------------------------

if "routes" not in st.session_state:
    st.session_state.routes = []  # Each route is a dict
if "selected_route_index" not in st.session_state:
    st.session_state.selected_route_index = 0

# ------------------------------
# EV Fleet Input
# ------------------------------


st.sidebar.header("Fleet Configuration")

if "fleet" not in st.session_state:
    st.session_state.fleet = [{}]  # Start with one empty bus input

# Add button to append more buses (max 20)
if len(st.session_state.fleet) < 20:
    if st.sidebar.button("Add Another Bus"):
        st.session_state.fleet.append({})

# Iterate through each bus input block
for i, bus in enumerate(st.session_state.fleet):
    with st.sidebar.expander(f"Bus {i + 1}", expanded=True):
        powertrain = st.selectbox(f"Powertrain", ["EV", "Gas"], key=f"powertrain_{i}")
        bus_type = st.selectbox(f"Type", ["A", "C"], key=f"type_{i}")
        make = st.text_input(f"Make", key=f"make_{i}")
        quantity = st.number_input(f"Quantity", min_value=1, value=1, step=1, key=f"quantity_{i}")
        battery_size = None
        if powertrain == "EV":
            battery_size = st.number_input(f"Battery Capacity (kWh)", min_value=1.0, value=200.0, key=f"battery_{i}")
        
        # Save to session state
        st.session_state.fleet[i] = {
            "Powertrain": powertrain,
            "Type": bus_type,
            "Quantity": quantity,
            "Battery Capacity (kWh)": battery_size if powertrain == "EV" else None
        }

    fleet_data = pd.DataFrame(st.session_state.fleet)

    # ------------------------------
# Route Input (Optimized Map - No Popups)
# ------------------------------


    st.header("Route Input")
    st.write("Choose the route, marker type, and click on the map to add stops instantly.")

    if "routes" not in st.session_state:
        st.session_state.routes = []
    if "selected_route_index" not in st.session_state:
        st.session_state.selected_route_index = 0

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

        if "last_clicked_location" not in st.session_state:
            st.session_state.last_clicked_location = None

        # Map center logic
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
            return folium.Marker(
                location=location,
                tooltip=label,
                icon=folium.Icon(color=color)
            )

        m = folium.Map(location=center, zoom_start=13)
        marker_group = folium.FeatureGroup(name="All Stops")

        if current_route["depot"]:
            marker_group.add_child(create_simple_marker(current_route["depot"], "Depot", "blue"))

        for idx, pickup in enumerate(current_route["pickups"]):
            marker_group.add_child(create_simple_marker(pickup, f"Pickup {idx+1}", "green"))

        for idx, dropoff in enumerate(current_route["dropoffs"]):
            marker_group.add_child(create_simple_marker(dropoff["location"], f"Dropoff {idx+1}", "red"))

        m.add_child(marker_group)

        if use_bounds:
            m.fit_bounds(use_bounds)

        map_key = f"main_map_route_{current_index}_v{len(current_route['pickups']) + len(current_route['dropoffs'])}"
        map_data = st_folium(m, key=map_key, width=700, height=500)

        # Handle new click
        clicked = map_data.get("last_clicked")
        if clicked:
            latlng = (clicked["lat"], clicked["lng"])
            if latlng != st.session_state.last_clicked_location:
                st.session_state.last_clicked_location = latlng

                if marker_type == "Depot":
                    current_route["depot"] = latlng
                elif marker_type == "Pickup":
                    current_route["pickups"].append(latlng)
                elif marker_type == "Dropoff":
                    current_route["dropoffs"].append({"location": latlng, "bell_time": None})

                st.rerun()

        # Sidebar-style UI for editing pickups and dropoffs
        st.subheader("Pickups")
        for i, pt in enumerate(current_route["pickups"]):
            cols = st.columns([5, 1])
            cols[0].write(f"📍 Pickup {i+1}: {pt}")
            if cols[1].button("Remove", key=f"remove_pickup_{i}"):
                current_route["pickups"].pop(i)
                st.rerun()

        st.subheader("Dropoffs")
        for i, pt in enumerate(current_route["dropoffs"]):
            cols = st.columns([5, 1])
            cols[0].write(f"🎯 Dropoff {i+1}: {pt['location']}")
            if cols[1].button("Remove", key=f"remove_dropoff_{i}"):
                current_route["dropoffs"].pop(i)
                st.rerun()

        if current_route["dropoffs"]:
            st.write("### Set Bell Times for Dropoffs")
            for idx, dropoff in enumerate(current_route["dropoffs"]):
                default_time = dropoff["bell_time"] if dropoff["bell_time"] else datetime.time(8, 0)
                bell_time = st.time_input(f"Bell Time for Dropoff {idx+1}", value=default_time, key=f"bell_time_{current_index}_{idx}")
                current_route["dropoffs"][idx]["bell_time"] = bell_time

        st.write("**Current Route Data:**", current_route)
    else:
        st.info("No routes added yet. Click 'Add New Route' to start.")


# ------------------------------
# Route Calculation and Feasibility Check
# ------------------------------

st.header("Calculation")

# Retrieve API key from Streamlit's secrets
try:
    google_maps_api_key = st.secrets["google_maps_api_key"]
except KeyError:
    st.error("Google Maps API key not found in secrets. Please add it to your Streamlit secrets.")
    google_maps_api_key = None

if st.button("Calculate Route Feasibility") and google_maps_api_key:
    results = []  # store feasibility results for each route
    efficiency = 2.5  # assumed miles per kWh

    for route in st.session_state.routes:
        st.write(f"**[Debug] Processing Route {route['route_id']}**")
        if not route["depot"]:
            st.write(f"Route {route['route_id']}: Depot not set.")
            continue
        if not route["dropoffs"]:
            st.write(f"Route {route['route_id']}: No school dropoffs set.")
            continue

        # Use the first dropoff as final destination (for demo purposes)
        destination = route["dropoffs"][0]["location"] if route["dropoffs"][0]["location"] else route["depot"]
        waypoints = []
        if route["pickups"]:
            waypoints.extend(route["pickups"])
        if len(route["dropoffs"]) > 1:
            for d in route["dropoffs"][1:]:
                if d["location"]:
                    waypoints.append(d["location"])
        
        st.write(f"**[Debug] Route {route['route_id']} waypoints:**", waypoints)
        total_distance = get_route_distance(google_maps_api_key, route["depot"], waypoints, destination)
        if total_distance is None:
            st.write(f"Route {route['route_id']}: Failed to calculate route distance.")
            continue
        st.write(f"**Route {route['route_id']} total distance:** {total_distance:.2f} miles")
        
        effective_range = fleet_data["Battery Capacity (kWh)"] * 0.6 * efficiency
        
        min_temp = get_min_temperature(route["depot"])
        st.write(f"**Route {route['route_id']} depot min temperature:** {min_temp}°F")
        if min_temp < 40:
            effective_range *= 0.8
            st.write("**[Info] Temperature below 40°F: Effective range reduced by 20%.**")
        
        feasible = total_distance <= effective_range
        results.append({
            "Route ID": route["route_id"],
            "Total Distance (miles)": round(total_distance, 2),
            "Effective Range (miles)": round(effective_range, 2),
            "Feasible": "Yes" if feasible else "No"
        })
    
    if results:
        results_df = pd.DataFrame(results)
        st.subheader("Route Feasibility Results")
        st.table(results_df)

        # Plot a simulated range curve
        temps = list(range(20, 81, 5))
        ranges = [fleet_data["Battery Capacity (kWh)"] * 0.6 * efficiency * (0.8 if t < 40 else 1.0) for t in temps]
        fig, ax = plt.subplots()
        ax.plot(temps, ranges)
        ax.set_xlabel("Temperature (°F)")
        ax.set_ylabel("Effective Range (miles)")
        ax.set_title("EV Effective Range vs. Temperature")
        st.pyplot(fig)
