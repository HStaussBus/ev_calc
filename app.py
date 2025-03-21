import streamlit as st
from streamlit_folium import st_folium
import folium
import requests
import pandas as pd
import datetime
import matplotlib.pyplot as plt

# ------------------------------
# Helper Functions
# ------------------------------

def get_route_distance(api_key, origin, waypoints, destination):
    """
    Uses the Google Maps Directions API to compute total driving distance.
    """
    base_url = "https://maps.googleapis.com/maps/api/directions/json"
    waypoints_str = "|".join([f"{wp[0]},{wp[1]}" for wp in waypoints]) if waypoints else ""
    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "waypoints": waypoints_str,
        "key": api_key,
        "mode": "driving",
        "traffic_model": "best_guess"
    }
    st.write("**[Debug] Requesting route from Google Maps with parameters:**", params)
    response = requests.get(base_url, params=params)
    data = response.json()
    if data["status"] == "OK":
        total_distance = 0
        for leg in data["routes"][0]["legs"]:
            total_distance += leg["distance"]["value"] / 1609.34  # meters to miles
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

st.sidebar.header("EV Fleet Input")
fleet_data = {
    "Bus Type": st.sidebar.selectbox("Select Bus Type", ["A", "C"]),
    "Battery Capacity (kWh)": st.sidebar.number_input("Battery Capacity (kWh)", min_value=1.0, value=200.0),
    "Number of Buses": st.sidebar.number_input("Number of Buses", min_value=1, value=5)
}

# ------------------------------
# Route Input (Single Map)
# ------------------------------

st.header("Route Input")
st.write("Manage routes using a single interactive map. Choose the route (or add a new one), select the marker type, and click on the map to add a marker.")

# Add new route button
if st.button("Add New Route"):
    new_route = {
        "route_id": len(st.session_state.routes) + 1,
        "depot": None,
        "pickups": [],         # list of (lat, lng)
        "dropoffs": []         # list of dicts: {"location": (lat, lng), "bell_time": None}
    }
    st.session_state.routes.append(new_route)
    st.session_state.selected_route_index = len(st.session_state.routes) - 1

# If routes exist, allow user to select one
if st.session_state.routes:
    route_labels = [f"Route {r['route_id']}" for r in st.session_state.routes]
    selected = st.selectbox("Select Route", options=route_labels, index=st.session_state.selected_route_index)
    current_index = route_labels.index(selected)
    st.session_state.selected_route_index = current_index
    current_route = st.session_state.routes[current_index]

    # Choose marker type to add
    marker_type = st.radio("Select Marker Type", options=["Depot", "Pickup", "Dropoff"])

    st.write(f"Click on the map below to add a **{marker_type}** marker.")

    # Create the base map
    # Default center: use depot if set, else NYC coordinates
    center = current_route["depot"] if current_route["depot"] else [40.7128, -74.0060]
    m = folium.Map(location=center, zoom_start=12)

    # Add existing markers to the map
    if current_route["depot"]:
        folium.Marker(
            location=current_route["depot"],
            tooltip="Depot",
            icon=folium.Icon(color="blue", icon="home")
        ).add_to(m)
    for idx, pickup in enumerate(current_route["pickups"]):
        folium.Marker(
            location=pickup,
            tooltip=f"Pickup {idx+1}",
            icon=folium.Icon(color="green", icon="arrow-up")
        ).add_to(m)
    for idx, dropoff in enumerate(current_route["dropoffs"]):
        if dropoff["location"]:
            folium.Marker(
                location=dropoff["location"],
                tooltip=f"Dropoff {idx+1}",
                icon=folium.Icon(color="red", icon="info-sign")
            ).add_to(m)

    # Display the single map
    map_data = st_folium(m, key="main_map", width=700, height=500)

    # Process click event from the map
    if map_data and map_data.get("last_clicked"):
        new_coord = (map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"])
        st.write(f"**New {marker_type} coordinate detected:** {new_coord}")
        # Clear last_clicked to avoid duplicate entries on re-run
        map_data["last_clicked"] = None
        if marker_type == "Depot":
            current_route["depot"] = new_coord
        elif marker_type == "Pickup":
            current_route["pickups"].append(new_coord)
        elif marker_type == "Dropoff":
            current_route["dropoffs"].append({"location": new_coord, "bell_time": None})
    
    # Allow user to input bell times for dropoffs
    if current_route["dropoffs"]:
        st.write("### Set Bell Times for Dropoffs")
        for idx, dropoff in enumerate(current_route["dropoffs"]):
            default_time = dropoff["bell_time"] if dropoff["bell_time"] else datetime.time(8, 0)
            bell_time = st.time_input(f"Bell Time for Dropoff {idx+1}", value=default_time, key=f"bell_time_{current_index}_{idx}")
            current_route["dropoffs"][idx]["bell_time"] = bell_time

    # Display current route details for debugging
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
