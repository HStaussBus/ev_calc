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
from shapely.geometry import LineString, MultiPolygon, Polygon, Point
import polyline
import geopandas as gpd
from shapely import wkt
import os

def switch_view(mode):
    st.session_state.view_mode = mode
    st.rerun()

if "view_mode" not in st.session_state:
    st.session_state.view_mode = "Main"

if st.session_state.view_mode == "EV Route Planning":
    st.subheader("🔧 Assign Bus Type to Each Route")
    st.markdown('Select which type of bus your route operates on. Then, click "Show Me the Plan!" to see the bus assignment summary, based on routes that can be completed without midday charging.')
    st.markdown(' ')
    st.markdown(f"*Route feasibility is calculated assuming a 20\\% buffer for battery health. These estimates do not include any driving done outside of the locations provided, nor a return to the depot midday.*")


    if "route_bus_types" not in st.session_state:
        st.session_state.route_bus_types = {}

    for route in st.session_state.routes:
        route_id = route["route_id"]
        selected_type = st.selectbox(
            f"Select Bus Type for Route {route_id}",
            ["A", "C"],
            key=f"route_bus_type_{route_id}"
        )
        st.session_state.route_bus_types[route_id] = selected_type

    # Back button
    if st.button("⬅ Back to Main"):
        switch_view("Main")

    st.markdown("---")

    if st.button("Show Me the Plan!"):
        if "ev_fleet" not in st.session_state:
            st.warning("No fleet data found. Please configure your EV fleet first.")
        else:
            ev_fleet = st.session_state.ev_fleet
            plan_results = []

            for route in st.session_state.routes:
                route_id = route["route_id"]
                feasibility = route.get("feasibility", {})
                if not feasibility:
                    continue

                selected_type = st.session_state.route_bus_types.get(route_id, "A")
                suggested_time = feasibility.get("Suggested Depot Departure Time", "N/A")
                percent_in_dac = feasibility.get("Percent in DAC", 0.0)
                total_duration = feasibility.get("Total Duration (min)", 0.0)
                time_in_dac = round((percent_in_dac / 100.0) * total_duration, 1)
                am_miles = feasibility.get("AM Distance (miles)", 0)
                pm_miles = feasibility.get("PM Distance (miles)", 0)
                round_trip = am_miles + pm_miles

                matching_fleet = ev_fleet[ev_fleet["Type"] == selected_type]

                def get_eligible_names(df, col):
                    return ", ".join(df[df[col] >= round_trip]["Name"].dropna().unique())

                cold_buses = get_eligible_names(matching_fleet, "Cold Weather Range")
                avg_buses = get_eligible_names(matching_fleet, "Average Weather Range")
                warm_buses = get_eligible_names(matching_fleet, "Warm Weather Range")

                plan_results.append({
                    "Route ID": route_id,
                    "Type Required": selected_type,
                    "Round Trip (mi)": round(round_trip, 2),
                    "Eligible Buses < 50°F": cold_buses,
                    "Eligible Buses 50–70°F": avg_buses,
                    "Eligible Buses 70°F+": warm_buses,
                    "Percent in DAC": percent_in_dac,
                    "Suggested Departure Time": suggested_time
                })

            if plan_results:
                st.subheader("🚌 EV Route Summary")
                st.dataframe(pd.DataFrame(plan_results))
                st.subheader("🚌 EV Bus Range Summary")
                st.dataframe(st.session_state.ev_fleet)
            else:
                st.info("No eligible routes with feasibility data found.")



zipcodes_df = pd.read_csv(".data/Modified_Zip_Code_Tabulation_Areas__MODZCTA_.csv")
dac_locs = pd.read_csv(".data/dac_file.csv")
dac_locs = dac_locs[dac_locs['DAC_Designation'] == 'Designated as DAC']
cols = ['the_geom', 'GEOID']
dac_locs = dac_locs[cols]
dac_locs['multipolygon'] = dac_locs['the_geom'].apply(wkt.loads)
dac_locs = gpd.GeoDataFrame(dac_locs, geometry='multipolygon')


# Convert geometry to shapely objects and compute centroids
zipcodes_df["geometry"] = zipcodes_df["the_geom"].apply(wkt.loads)
zipcodes_df["centroid_lat"] = zipcodes_df["geometry"].apply(lambda g: g.centroid.y)
zipcodes_df["centroid_lng"] = zipcodes_df["geometry"].apply(lambda g: g.centroid.x)

# Build lookup: MODZCTA → (lat, lng)
zip_lookup = zipcodes_df.set_index("MODZCTA")[["centroid_lat", "centroid_lng"]].to_dict("index")
# ------------------------ HELPER FUNCTIONS ---------------------
# --------------------------------------------------------------
def process_fleet_data(fleet_df):
    ev_fleet = fleet_df[fleet_df["Powertrain"] == "EV"].copy()

    def calc_ranges(row):
        kWh = row["Battery Capacity (kWh)"]
        if row["Type"] == "A":
            return pd.Series({
                "Cold Weather Range": round((kWh * 0.8) / 2, 1),
                "Average Weather Range": round((kWh * 0.8) / 1.5, 1),
                "Warm Weather Range": round((kWh * 0.8) / 1.0, 1),
            })
        elif row["Type"] == "C":
            return pd.Series({
                "Cold Weather Range": round((kWh * 0.8) / 2.5, 1),
                "Average Weather Range": round((kWh * 0.8) / 1.8, 1),
                "Warm Weather Range": round((kWh * 0.8) / 1.5, 1),
            })
        else:
            return pd.Series({col: None for col in ["Cold Weather Range", "Average Weather Range", "Warm Weather Range"]})

    ev_fleet[["Cold Weather Range", "Average Weather Range", "Warm Weather Range"]] = ev_fleet.apply(calc_ranges, axis=1)

    return ev_fleet[[
        "Name", "Type", "Quantity", "Battery Capacity (kWh)",
        "Cold Weather Range", "Average Weather Range", "Warm Weather Range"
    ]]

def get_route_distance(api_key, origin, waypoints, destination, departure_time=None):
        """
        Uses the Google Maps Directions API to compute total driving distance, duration, and leg details.
        """
        import datetime

        def normalize_location(point):
            return point["location"] if isinstance(point, dict) else point

        base_url = "https://maps.googleapis.com/maps/api/directions/json"

        waypoints_str = "|".join([
            f"{normalize_location(wp)[0]},{normalize_location(wp)[1]}"
            for wp in waypoints
        ]) if waypoints else ""

        origin = normalize_location(origin)
        destination = normalize_location(destination)

        if departure_time is None:
            departure_time = datetime.time(7, 0)

        now = datetime.datetime.now()
        days_ahead = (7 - now.weekday()) % 7 or 7
        next_monday = now + datetime.timedelta(days=days_ahead)
        departure_datetime = datetime.datetime.combine(next_monday.date(), departure_time)
        departure_unix = int(departure_datetime.timestamp())

        params = {
            "origin": f"{origin[0]},{origin[1]}",
            "destination": f"{destination[0]},{destination[1]}",
            "waypoints": waypoints_str,
            "optimizeWaypoints": "false",
            "key": api_key,
            "mode": "driving",
            "traffic_model": "best_guess",
            "departure_time": departure_unix
        }

        st.write("**[Debug] Requesting route from Google Maps with parameters:**", params)
        response = requests.get(base_url, params=params)
        data = response.json()

        if data["status"] == "OK":
            legs = data["routes"][0]["legs"]
            total_distance = sum(leg["distance"]["value"] for leg in legs) / 1609.34
            total_duration = sum(leg["duration"]["value"] for leg in legs) / 60

            leg_details = [{
                "Start Address": leg["start_address"],
                "End Address": leg["end_address"],
                "Distance (mi)": round(leg["distance"]["value"] / 1609.34, 2),
                "Duration (min)": round(leg["duration"]["value"] / 60, 1)
            } for leg in legs]

            overview_polyline = data["routes"][0]["overview_polyline"]["points"]
            return total_distance, total_duration, leg_details, overview_polyline

        else:
            st.write("**[Error] Google Maps API response:**", data.get("error_message", data["status"]))
            return None, None, []
        
def calculate_dac_overlap(overview_polyline, dac_gdf):
        import polyline
        from shapely.geometry import LineString

        try:
            decoded_coords = polyline.decode(overview_polyline)
            reversed_coords = [(lng, lat) for lat, lng in decoded_coords]  # reverse order
            route_line = LineString(reversed_coords)

            intersection_length = sum(
                route_line.intersection(dac).length
                for dac in dac_gdf["multipolygon"]
                if route_line.intersects(dac)
            )

            if route_line.length > 0:
                return (intersection_length / route_line.length) * 100
            else:
                return 0.0
        except Exception as e:
            st.warning(f"Error calculating DAC overlap: {e}")
            return 0.0
        





def get_min_temperature(location):
        """
        Placeholder for weather API. For demo purposes, if the depot's latitude is below 40, 
        simulate a min temp of 35°F; otherwise, 45°F.
        """
        lat = location[0]
        return 35 if lat < 40 else 45



#Session State
if "view_mode" not in st.session_state:
    st.session_state.view_mode = "Main"
if "routes" not in st.session_state:
    st.session_state.routes = []
if "selected_route_index" not in st.session_state:
    st.session_state.selected_route_index = 0
if "fleet" not in st.session_state:
    st.session_state.fleet = [{}]
if "last_clicked_location" not in st.session_state:
    st.session_state.last_clicked_location = None
if "route_bus_types" not in st.session_state:
    st.session_state.route_bus_types = {}

# ------------------------------
# MAIN TAB
# ------------------------------


if st.session_state.view_mode == "Main":



    st.sidebar.header("Fleet Configuration")

    if st.sidebar.button("Save Fleet Data", key="save_fleet"):
            fleet_data = pd.DataFrame(st.session_state.fleet)
            st.session_state.ev_fleet = process_fleet_data(fleet_data)
            st.success("✅ Fleet data processed and saved.")

    if "fleet" not in st.session_state:
        st.session_state.fleet = [{}]  # Start with one empty bus input

    # Add button to append more buses (max 20)
    if len(st.session_state.fleet) < 20:
        if st.sidebar.button("Add Another Bus"):
            st.session_state.fleet.append({})

    # Iterate through each bus input block
    for i, bus in enumerate(st.session_state.fleet):
        with st.sidebar.expander(f"Bus {i + 1}", expanded=True):
            name = st.text_input(f"Name", key=f"name_{i}")
            powertrain = st.selectbox(f"Powertrain", ["EV", "Gas"], key=f"powertrain_{i}")
            bus_type = st.selectbox(f"Type", ["A", "C"], key=f"type_{i}")
            quantity = st.number_input(f"Quantity", min_value=1, value=1, step=1, key=f"quantity_{i}")
            battery_size = None
            if powertrain == "EV":
                battery_size = st.number_input(f"Battery Capacity (kWh)", min_value=1.0, value=200.0, key=f"battery_{i}")
            
            # Save to session state
            st.session_state.fleet[i] = {
                "Name": name,
                "Powertrain": powertrain,
                "Type": bus_type,
                "Quantity": quantity,
                "Battery Capacity (kWh)": battery_size if powertrain == "EV" else None
            }

        fleet_data = pd.DataFrame(st.session_state.fleet)
        ev_fleet = fleet_data[fleet_data["Powertrain"] == "EV"].copy()

        fleet_data = pd.DataFrame(st.session_state.fleet)
        st.session_state.fleet_data = fleet_data

    st.title("Electric Bus Route Planning")
    st.markdown("Welcome to the NYCSBUS EV Route Machine. Please define your fleet to the left. You can either enter routes through a CSV file or by interactive map.")
    st.markdown("Once your routes and buses are entered, click *Process Route Electrification* to begin developing a plan.")

    st.session_state.input_mode = st.radio("How would you like to define routes?", ["Interactive Map", "Upload CSV"], horizontal=True)
    

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
        - Time: Time (school start time, only at Dropoff Locations) HH:MM
        """)

        st.info("🔒 Uploaded files are processed in memory only and are not stored or shared. Click 'Process CSV' to ensure your data is in the correct format. Then, click GO!")

        
        st.markdown("""
        **CSV Format Required:**

        | Route | Location Type | Address                          | Time     | Sequence Number |
        |-------|----------------|----------------------------------|----------|------------------|
        | A123  | Depot          | 123 Main St, Bronx, NY 10451     |          | 0                |
        | A123  | Pickup         | 456 1st Ave, Bronx, NY 10455     |          | 1                |
        | A123  | Pickup         | 789 3rd Ave, Bronx, NY 10457     |          | 2                |
        | A123  | Dropoff        | 101 School Rd, Bronx, NY 10460   | 08:00    | 3                |
        | B321  | Depot          | 12 Depot Ln, Queens, NY 11368    |          | 0                |
        | B321  | Pickup         | 200 Park Ave, Queens, NY 11369   |          | 1                |
        | B321  | Dropoff        | 400 Academy St, Queens, NY 11370 | 08:10    | 2                |
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
                                            parsed_time = datetime.datetime.strptime(time_str.strip(), "%H:%M").time()
                                        except ValueError:
                                            try:
                                                parsed_time = datetime.datetime.strptime(time_str.strip() + " AM", "%I:%M %p").time()
                                            except ValueError:
                                                st.warning(f"Invalid time format for {address}: {time_str}")


                                    if location_type == "Depot":
                                        route_dict[route_id]["depot"] = coords
                                    elif location_type == "Pickup":
                                        route_dict[route_id]["pickups"].append({"location": coords})
                                    elif location_type == "Dropoff":
                                        route_dict[route_id]["dropoffs"].append({"location": coords, "bell_time": parsed_time})
                                else:
                                    st.warning(f"Geocoding failed for {address}: {data['status']}")

                            except Exception as geocode_error:
                                st.warning(f"Failed to geocode: {address} - {geocode_error}")

                        st.session_state.routes = list(route_dict.values())
                        st.success("CSV processed successfully.")
                        #for r in st.session_state.routes:
                            #st.write(r)

            except Exception as e:
                st.error(f"Error reading CSV: {e}")

    # ------------------------------
    # Helper Functions
    # ------------------------------

    
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

    if st.button("Process Routes for Electrification") and google_maps_api_key:
        results = []
        efficiency = 2.5  # miles per kWh

        for route in st.session_state.routes:
            #st.write(f"### Route {route['route_id']}")

            if not route["depot"]:
                st.warning("Depot not set.")
                continue
            if not route["dropoffs"]:
                st.warning("No school dropoffs set.")
                continue

            destination = route["dropoffs"][0]["location"]
            waypoints = []

            if route["pickups"]:
                waypoints.extend(route["pickups"])
            if len(route["dropoffs"]) > 1:
                waypoints.extend([d["location"] for d in route["dropoffs"][1:] if d.get("location")])

            first_pickup_time = None
            if route["pickups"] and isinstance(route["pickups"][0], dict):
                first_pickup_time = route["pickups"][0].get("pickup_time")

            total_distance, total_duration, leg_details, overview_polyline = get_route_distance(
                google_maps_api_key,
                route["depot"],
                waypoints,
                destination,
                departure_time=first_pickup_time
            )

            if total_distance is None:
                st.warning("Failed to calculate route distance.")
                continue

            battery_capacity = fleet_data["Battery Capacity (kWh)"].iloc[0]
            effective_range = battery_capacity * 0.6 * efficiency
            min_temp = get_min_temperature(route["depot"])

            if min_temp < 40:
                effective_range *= 0.8
            
            # -- Calculate drive time to first school --
            num_schools = len(route["dropoffs"])
            if num_schools > 1:
                legs_to_first_school = leg_details[:-(num_schools - 1)]
            else:
                legs_to_first_school = leg_details

            drive_time_to_first_school = sum(leg["Duration (min)"] for leg in legs_to_first_school)

            # -- Calculate suggested depot departure time --
            first_bell = route["dropoffs"][0].get("bell_time")
            suggested_departure_time = None
            if first_bell:
                try:
                    # Combine bell time with arbitrary date and subtract drive time
                    arrival_dt = datetime.datetime.combine(datetime.date.today(), first_bell)
                    departure_dt = arrival_dt - datetime.timedelta(minutes=drive_time_to_first_school + 15)
                    suggested_departure_time = departure_dt.time()
                except Exception as e:
                    st.warning(f"Failed to calculate suggested departure time: {e}")


            # Store all leg data directly inside the feasibility result
            route["feasibility"] = {
                "Route ID": route["route_id"],
                "AM Distance (miles)": round(total_distance, 2),
                "AM Duration (min)": round(total_duration, 1),
                "Effective Range (miles)": round(effective_range, 2),
                "Min Temp (°F)": min_temp,
                "Feasible": "Yes" if total_distance <= effective_range else "No",
                "Drive Time to First School (min)": round(drive_time_to_first_school, 1),
                "First School Bell Time": first_bell.strftime("%I:%M %p") if first_bell else None,
                "Suggested Depot Departure Time": suggested_departure_time.strftime("%I:%M %p") if suggested_departure_time else None,
                "Leg Details": leg_details
            }

            try:
        # PM trip: reverse trip from last school back to depot
                pm_origin = route["dropoffs"][-1]["location"]
                pm_destination = route["depot"]

                pm_waypoints = []

                if len(route["dropoffs"]) > 1:
                    pm_waypoints.extend([
                        d["location"] for d in reversed(route["dropoffs"][:-1])
                    ])

                if route["pickups"]:
                    pm_waypoints.extend([
                        p["location"] if isinstance(p, dict) else p
                        for p in reversed(route["pickups"])
                    ])

                pm_distance, pm_duration, _, _ = get_route_distance(
                    google_maps_api_key,
                    pm_origin,
                    pm_waypoints,
                    pm_destination,
                    departure_time=None  # No traffic/time needed for PM route
                )

                route["feasibility"]["PM Distance (miles)"] = round(pm_distance, 2) if pm_distance else None
                route["feasibility"]["PM Duration (min)"] = round(pm_duration, 1) if pm_duration else None

            except Exception as e:
                st.warning(f"PM route calculation failed for Route {route['route_id']}: {e}")


            percent_in_dac = calculate_dac_overlap(overview_polyline, dac_locs)
            route["feasibility"]["Percent in DAC"] = round(percent_in_dac, 2)


            route["leg_details"] = leg_details
            results.append(route["feasibility"])
            st.session_state.results = results

            switch_view("EV Route Planning")


            # Show per-route debug info
            #st.write(f"**Feasibility for Route {route['route_id']}:**")
            #st.json(route["feasibility"])  # Cleaner than raw dict print

        #st.markdown("---")

    #if st.button("Calculate EV Route Planning", key="ev_plan_button"):
            #switch_view("EV Route Planning")
    st.markdown("---")
    if st.button("🔁 Reset App"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()




