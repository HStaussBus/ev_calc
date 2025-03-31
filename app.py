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
from geopy.geocoders import Nominatim
import time


zipcodes_df = pd.read_csv(".data/Modified_Zip_Code_Tabulation_Areas__MODZCTA_.csv")

# Convert geometry to shapely objects and compute centroids
zipcodes_df["geometry"] = zipcodes_df["the_geom"].apply(wkt.loads)
zipcodes_df["centroid_lat"] = zipcodes_df["geometry"].apply(lambda g: g.centroid.y)
zipcodes_df["centroid_lng"] = zipcodes_df["geometry"].apply(lambda g: g.centroid.x)

# Build lookup: MODZCTA → (lat, lng)
zip_lookup = zipcodes_df.set_index("MODZCTA")[["centroid_lat", "centroid_lng"]].to_dict("index")

#Session State
if "routes" not in st.session_state:
    st.session_state.routes = []  # Each route is a dict
if "selected_route_index" not in st.session_state:
    st.session_state.selected_route_index = 0
if "fleet" not in st.session_state:
    st.session_state.fleet = [{}]  # Each bus is a dict
if "last_clicked_location" not in st.session_state:
    st.session_state.last_clicked_location = None

#Route Input Mode Selection
st.title("EV Bus Route Designer")
st.session_state.input_mode = st.radio("How would you like to define routes?", ["Interactive Map", "Upload CSV"], horizontal=True)

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

#Interactive Map Input Mode
if st.session_state.input_mode == "Interactive Map":
    from interactive_map_logic import handle_map_route_input
    handle_map_route_input(st, folium, st_folium, zipcodes_df, zip_lookup)

# ------------------------------
# CSV Upload Route Input
# ------------------------------
elif st.session_state.input_mode == "Upload CSV":
    st.subheader("Upload Your Route CSV")
    uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])
    st.markdown("""
    **CSV Format Required:**
    - Columns: `Route`, `Location Type`, `Address`, 'Time', 'Sequence Number'
    - Location Types: `Depot`, `Pickup`, `Dropoff`
    - Time: First Pickup Time (at sequence 1), and Bell Time (at dropoff locations) HH:MM
    """)

    st.info("🔒 Uploaded files are processed in memory only and are not stored or shared.")

    
    st.markdown("""
    **CSV Format Required:**

    | Route | Location Type | Address                          | Time     | Sequence Number |
    |-------|----------------|----------------------------------|----------|------------------|
    | A123  | Depot          | 123 Main St, Bronx, NY 10451     |          | 0                |
    | A123  | Pickup         | 456 1st Ave, Bronx, NY 10455     | 07:15 AM | 1                |
    | A123  | Pickup         | 789 3rd Ave, Bronx, NY 10457     |          | 2                |
    | A123  | Dropoff        | 101 School Rd, Bronx, NY 10460   | 08:00 AM | 3                |
    | B321  | Depot          | 12 Depot Ln, Queens, NY 11368    |          | 0                |
    | B321  | Pickup         | 200 Park Ave, Queens, NY 11369   | 07:25 AM | 1                |
    | B321  | Dropoff        | 400 Academy St, Queens, NY 11370 | 08:10 AM | 2                |
    """)

    if uploaded_file:
        try:
            df = pd.read_csv(uploaded_file)
            st.dataframe(df)

            if st.button("Process CSV"):
                google_maps_api_key = st.secrets.get("google_maps_api_key")
                if not google_maps_api_key:
                    st.error("Google Maps API key not found in secrets.")
                else:
                    route_dict = {}

                    for _, row in df.iterrows():
                        route_id = row['Route']
                        location_type = row['Location Type']
                        address = row['Address']
                        time_str = row.get('Time', '')
                        sequence = row.get('Sequence Number', None)

                        try:
                            response = requests.get(
                                "https://maps.googleapis.com/maps/api/geocode/json",
                                params={"address": address, "key": google_maps_api_key}
                            )
                            time.sleep(0.2)
                            data = response.json()
                            if data["status"] == "OK":
                                location = data["results"][0]["geometry"]["location"]
                                coords = (location["lat"], location["lng"])

                                if route_id not in route_dict:
                                    route_dict[route_id] = {
                                        "route_id": route_id,
                                        "depot": None,
                                        "pickups": [],
                                        "dropoffs": []
                                    }

                                parsed_time = None
                                if pd.notna(time_str) and isinstance(time_str, str):
                                    try:
                                        parsed_time = datetime.datetime.strptime(time_str.strip(), "%I:%M %p").time()
                                    except ValueError:
                                        st.warning(f"Invalid time format for {address}: {time_str}")

                                if location_type == "Depot":
                                    route_dict[route_id]["depot"] = coords
                                elif location_type == "Pickup":
                                    route_dict[route_id]["pickups"].append({"location": coords, "pickup_time": parsed_time})
                                elif location_type == "Dropoff":
                                    route_dict[route_id]["dropoffs"].append({"location": coords, "bell_time": parsed_time})
                            else:
                                st.warning(f"Geocoding failed for {address}: {data['status']}")

                        except Exception as geocode_error:
                            st.warning(f"Failed to geocode: {address} - {geocode_error}")

                    st.session_state.routes = list(route_dict.values())
                    st.success("CSV processed successfully. Displaying parsed routes:")
                    for r in st.session_state.routes:
                        st.write(r)

        except Exception as e:
            st.error(f"Error reading CSV: {e}")

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
# Route Input
# ------------------------------

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
