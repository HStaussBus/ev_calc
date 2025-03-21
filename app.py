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
    Parameters:
      - origin: tuple (lat, lng)
      - waypoints: list of tuples (lat, lng) (if any)
      - destination: tuple (lat, lng)
    Returns:
      - total distance in miles (float) or None on error.
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
        "traffic_model": "best_guess"
    }
    st.write("**[Debug] Requesting route from Google Maps with parameters:**", params)
    response = requests.get(base_url, params=params)
    data = response.json()
    if data["status"] == "OK":
        route = data["routes"][0]
        total_distance = 0
        for leg in route["legs"]:
            # Convert distance from meters to miles (1 mile = 1609.34 meters)
            total_distance += leg["distance"]["value"] / 1609.34
        return total_distance
    else:
        st.write("**[Error] Google Maps API response:**", data.get("error_message", data["status"]))
        return None

def get_min_temperature(location):
    """
    Placeholder for a weather API.
    For demo purposes, if the depot's latitude is below 40, we simulate a min temp of 35°F; otherwise 45°F.
    """
    lat = location[0]
    return 35 if lat < 40 else 45

# ------------------------------
# Streamlit App Layout
# ------------------------------

st.title("EV Route Feasibility for School Buses")

# --- EV Fleet Input ---
st.sidebar.header("EV Fleet Input")
fleet_data = {
    "Bus Type": st.sidebar.selectbox("Select Bus Type", ["A", "C"]),
    "Battery Capacity (kWh)": st.sidebar.number_input("Battery Capacity (kWh)", min_value=1.0, value=200.0),
    "Number of Buses": st.sidebar.number_input("Number of Buses", min_value=1, value=5)
}

# --- Route Input ---
st.header("Route Input")
st.write("Create one or more routes by defining three types of coordinates on a map:")

# Use session state to store multiple routes
if "routes" not in st.session_state:
    st.session_state.routes = []

# Button to add a new route
if st.button("Add New Route"):
    new_route = {
        "route_id": len(st.session_state.routes) + 1,
        "depot": None,
        "pickups": [],         # list of (lat, lng) tuples
        "dropoffs": []         # list of dicts: {"location": (lat, lng), "bell_time": <time>}
    }
    st.session_state.routes.append(new_route)

# Display each route in an expandable section
for idx, route in enumerate(st.session_state.routes):
    with st.expander(f"Route {route['route_id']}"):
        # --- Depot Input ---
        st.write("#### Depot Pullout")
        depot_map = folium.Map(location=[40.7128, -74.0060], zoom_start=12)
        if route["depot"]:
            folium.Marker(
                location=route["depot"],
                tooltip="Depot",
                icon=folium.Icon(color="blue", icon="home")
            ).add_to(depot_map)
        depot_data = st_folium(depot_map, key=f"depot_map_{idx}", width=500, height=300)
        if depot_data and depot_data.get("last_clicked"):
            depot_location = (depot_data["last_clicked"]["lat"], depot_data["last_clicked"]["lng"])
            route["depot"] = depot_location
            st.write(f"**Depot set at:** {depot_location}")

        # --- Pickups Input ---
        st.write("#### Pickups")
        if st.button(f"Add Pickup for Route {route['route_id']}", key=f"add_pickup_{idx}"):
            route["pickups"].append(None)
        for i, pickup in enumerate(route["pickups"]):
            st.write(f"**Pickup {i+1}**")
            pickup_map = folium.Map(location=route["depot"] if route["depot"] else [40.7128, -74.0060], zoom_start=12)
            if pickup:
                folium.Marker(
                    location=pickup,
                    tooltip=f"Pickup {i+1}",
                    icon=folium.Icon(color="green", icon="arrow-up")
                ).add_to(pickup_map)
            pickup_data = st_folium(pickup_map, key=f"pickup_map_{idx}_{i}", width=500, height=300)
            if pickup_data and pickup_data.get("last_clicked"):
                pickup_location = (pickup_data["last_clicked"]["lat"], pickup_data["last_clicked"]["lng"])
                route["pickups"][i] = pickup_location
                st.write(f"**Pickup {i+1} set at:** {pickup_location}")

        # --- School Dropoffs Input ---
        st.write("#### School Dropoffs")
        if st.button(f"Add School Dropoff for Route {route['route_id']}", key=f"add_dropoff_{idx}"):
            route["dropoffs"].append({"location": None, "bell_time": None})
        for j, dropoff in enumerate(route["dropoffs"]):
            st.write(f"**School Dropoff {j+1}**")
            dropoff_map = folium.Map(location=route["depot"] if route["depot"] else [40.7128, -74.0060], zoom_start=12)
            if dropoff["location"]:
                folium.Marker(
                    location=dropoff["location"],
                    tooltip=f"Dropoff {j+1}",
                    icon=folium.Icon(color="red", icon="info-sign")
                ).add_to(dropoff_map)
            dropoff_data = st_folium(dropoff_map, key=f"dropoff_map_{idx}_{j}", width=500, height=300)
            if dropoff_data and dropoff_data.get("last_clicked"):
                dropoff_location = (dropoff_data["last_clicked"]["lat"], dropoff_data["last_clicked"]["lng"])
                route["dropoffs"][j]["location"] = dropoff_location
                st.write(f"**Dropoff {j+1} set at:** {dropoff_location}")
            # Bell Time Input for dropoff
            bell_time = st.time_input(f"Bell Time for School {j+1}", key=f"bell_time_{idx}_{j}")
            route["dropoffs"][j]["bell_time"] = bell_time

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
    results = []  # to store feasibility results for each route
    efficiency = 2.5  # assumed miles per kWh
    
    # Loop through each route and process calculations
    for route in st.session_state.routes:
        st.write(f"**[Debug] Processing Route {route['route_id']}**")
        if not route["depot"]:
            st.write(f"Route {route['route_id']}: Depot not set.")
            continue
        if not route["dropoffs"]:
            st.write(f"Route {route['route_id']}: No school dropoffs set.")
            continue
        
        # For this demo, assume the first dropoff is the final destination.
        destination = route["dropoffs"][0]["location"] if route["dropoffs"][0]["location"] else route["depot"]
        waypoints = []
        # Combine all pickups
        if route["pickups"]:
            waypoints.extend(route["pickups"])
        # Add additional dropoffs (if any) as waypoints (exclude destination)
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
        
        # Calculate effective range using 60% of battery capacity
        effective_range = fleet_data["Battery Capacity (kWh)"] * 0.6 * efficiency
        
        # Adjust range based on weather at the depot location
        min_temp = get_min_temperature(route["depot"])
        st.write(f"**Route {route['route_id']} depot min temperature:** {min_temp}°F")
        if min_temp < 40:
            effective_range *= 0.8
            st.write("**[Info] Temperature below 40°F: Effective range reduced by 20%.**")
        
        # Check feasibility (distance must be within effective range)
        feasible = total_distance <= effective_range
        results.append({
            "Route ID": route["route_id"],
            "Total Distance (miles)": round(total_distance, 2),
            "Effective Range (miles)": round(effective_range, 2),
            "Feasible": "Yes" if feasible else "No"
        })
    
    # Display the results in a table
    if results:
        results_df = pd.DataFrame(results)
        st.subheader("Route Feasibility Results")
        st.table(results_df)

        # --- Plot a Range Curve ---
        # For demonstration, we simulate how effective range might vary with temperature.
        temps = list(range(20, 81, 5))
        # Effective range is reduced by 20% for temps below 40°F.
        ranges = [fleet_data["Battery Capacity (kWh)"] * 0.6 * efficiency * (0.8 if t < 40 else 1.0) for t in temps]
        fig, ax = plt.subplots()
        ax.plot(temps, ranges)
        ax.set_xlabel("Temperature (°F)")
        ax.set_ylabel("Effective Range (miles)")
        ax.set_title("EV Effective Range vs. Temperature")
        st.pyplot(fig)
