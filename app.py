# <<< Keep all your existing imports at the top >>>
import streamlit as st
from streamlit_folium import st_folium
import folium
from folium import FeatureGroup, Icon # Import Icon
import requests
import pandas as pd
import datetime
from shapely import wkt
import matplotlib.pyplot as plt
import streamlit.components.v1 as components
from geopy.geocoders import Nominatim
import time
from shapely.geometry import LineString, MultiPolygon, Polygon, Point
import polyline # Make sure polyline is imported
import geopandas as gpd
from shapely import wkt
import os
import base64
import traceback

st.markdown("""
<style>
    [data-testid=stSidebar] > div:first-child {
        background-color: #f6e782;
    }
</style>
""", unsafe_allow_html=True)

# --- Constants ---
# Define colors for map elements
DEPOT_COLOR = 'red'
PICKUP_COLOR = 'blue'
DROPOFF_COLOR = 'green'
AM_ROUTE_COLOR = 'purple'
PM_ROUTE_COLOR = 'orange'

# --- Existing Helper Functions (Keep them as they are) ---
def switch_view(mode):
    st.session_state.view_mode = mode
    st.rerun()

def load_logo_as_base64(path):
    # ... (keep existing function)
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        st.warning(f"Logo file not found at {path}. Skipping logo display.")
        return None

def process_fleet_data(fleet_df):
    # ... (keep existing function)
    ev_fleet = fleet_df[fleet_df["Powertrain"] == "EV"].copy()

    def calc_ranges(row):
        kWh = row["Battery Capacity (kWh)"]
        # Ensure kWh is not None and is numeric before calculations
        if pd.isna(kWh):
            return pd.Series({col: None for col in ["Cold Weather Range", "Average Weather Range", "Warm Weather Range"]})

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
        else: # Handle unexpected types gracefully
            return pd.Series({col: None for col in ["Cold Weather Range", "Average Weather Range", "Warm Weather Range"]})

    # Apply calculations
    range_cols = ["Cold Weather Range", "Average Weather Range", "Warm Weather Range"]
    ev_fleet[range_cols] = ev_fleet.apply(calc_ranges, axis=1)

    # Ensure required columns exist before selecting
    required_cols = ["Name", "Type", "Quantity", "Battery Capacity (kWh)"] + range_cols
    existing_cols = [col for col in required_cols if col in ev_fleet.columns]

    return ev_fleet[existing_cols]


# --- MODIFIED get_route_distance ---
def get_route_distance(api_key, origin, waypoints, destination, departure_time=None):
    """
    Uses the Google Maps Directions API to compute total driving distance, duration, leg details,
    and the overview polyline.
    """
    import datetime

    def normalize_location(point):
         # Check if point is already a tuple/list of numbers
        if isinstance(point, (list, tuple)) and len(point) == 2 and all(isinstance(x, (int, float)) for x in point):
            return point
        # Check if it's a dictionary with 'location' key
        elif isinstance(point, dict) and "location" in point:
            loc = point["location"]
            if isinstance(loc, (list, tuple)) and len(loc) == 2 and all(isinstance(x, (int, float)) for x in loc):
                return loc
        # If it's neither, raise an error or return None, depending on desired handling
        st.error(f"Invalid location format encountered: {point}")
        raise ValueError(f"Invalid location format: {point}")
        # return None # Or handle appropriately

    base_url = "https://maps.googleapis.com/maps/api/directions/json"

    # Filter out invalid waypoints before joining
    valid_waypoints = []
    if waypoints:
        for wp in waypoints:
            try:
                normalized_wp = normalize_location(wp)
                valid_waypoints.append(f"{normalized_wp[0]},{normalized_wp[1]}")
            except (ValueError, TypeError, IndexError) as e:
                st.warning(f"Skipping invalid waypoint format: {wp} due to {e}")


    waypoints_str = "|".join(valid_waypoints) if valid_waypoints else ""

    try:
        origin_norm = normalize_location(origin)
        destination_norm = normalize_location(destination)
    except (ValueError, TypeError, IndexError) as e:
         st.error(f"Invalid origin or destination format: Origin={origin}, Dest={destination}, Error: {e}")
         return None, None, [], None # Return None for polyline

    # --- Departure Time Logic (ensure it handles None correctly) ---
    departure_unix = "now" # Default to 'now' if no specific time is needed/provided
    if departure_time:
        try:
            now = datetime.datetime.now()
            # Ensure departure_time is a datetime.time object
            if isinstance(departure_time, str):
                 departure_time = datetime.datetime.strptime(departure_time, "%H:%M").time() # Example format
            elif not isinstance(departure_time, datetime.time):
                 # Handle cases where departure_time might be unexpected format
                 st.warning(f"Unexpected departure_time format: {departure_time}. Using current time.")
                 departure_time = now.time()


            # Find next Monday logic (seems okay, but ensure robustness)
            days_ahead = (0 - now.weekday() + 7) % 7 # 0 for Monday
            if days_ahead == 0 and now.time() > departure_time : # If today is Monday but time has passed, go to next week
                days_ahead = 7
            elif days_ahead == 0 and now.time() <= departure_time: # If today is Monday and time is okay
                 days_ahead = 0 # Use today
            next_monday = now.date() + datetime.timedelta(days=days_ahead)


            departure_datetime = datetime.datetime.combine(next_monday, departure_time)
            departure_unix = int(departure_datetime.timestamp())
        except Exception as e:
            st.warning(f"Error processing departure time '{departure_time}': {e}. Using default.")
            departure_unix = "now"


    params = {
        "origin": f"{origin_norm[0]},{origin_norm[1]}",
        "destination": f"{destination_norm[0]},{destination_norm[1]}",
        "waypoints": waypoints_str,
        # "optimizeWaypoints": "false", # Usually keep this false unless needed
        "key": api_key,
        "mode": "driving",
    }
    # Only add traffic info if a specific future time is set
    if isinstance(departure_unix, int):
         params["traffic_model"] = "best_guess"
         params["departure_time"] = departure_unix


    # st.write("[Debug] Requesting route from Google Maps with parameters:", params) # Optional debug
    try:
        response = requests.get(base_url, params=params, timeout=20) # Add timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        data = response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error during Google Maps API request: {e}")
        return None, None, [], None
    except Exception as e: # Catch other potential errors like JSON decoding
        st.error(f"An unexpected error occurred fetching directions: {e}")
        return None, None, [], None


    if data["status"] == "OK" and data.get("routes"): # Check if routes list exists and is not empty
        route_info = data["routes"][0]
        legs = route_info.get("legs", [])
        overview_polyline = route_info.get("overview_polyline", {}).get("points")

        if not legs:
             st.warning("Google Maps API returned OK status but no route legs.")
             return None, None, [], overview_polyline # Still return polyline if available

        total_distance = sum(leg.get("distance", {}).get("value", 0) for leg in legs) / 1609.34
        total_duration = sum(leg.get("duration", {}).get("value", 0) for leg in legs) / 60

        leg_details = [{
            "Start Address": leg.get("start_address", "N/A"),
            "End Address": leg.get("end_address", "N/A"),
            "Distance (mi)": round(leg.get("distance", {}).get("value", 0) / 1609.34, 2),
            "Duration (min)": round(leg.get("duration", {}).get("value", 0) / 60, 1)
        } for leg in legs]


        return total_distance, total_duration, leg_details, overview_polyline

    else:
        st.warning(f"Google Maps API Error: {data.get('status', 'Unknown Status')}. Message: {data.get('error_message', 'No error message provided.')}")
        # st.write("[Debug] Full API Response:", data) # Optional: show full error response
        return None, None, [], None

def calculate_dac_overlap(overview_polyline, dac_gdf):
    # ... (keep existing function)
    # Ensure polyline library is imported
    import polyline
    from shapely.geometry import LineString, MultiPolygon, Polygon
    from shapely.errors import GEOSException


    if not overview_polyline or not isinstance(overview_polyline, str):
        # st.warning("Invalid or missing overview polyline for DAC calculation.")
        return 0.0


    if dac_gdf is None or dac_gdf.empty:
        st.warning("DAC GeoDataFrame is missing or empty.")
        return 0.0


    try:
        # Decode polyline - assumes standard Google format (lat, lng)
        decoded_coords = polyline.decode(overview_polyline)


        # Check if coordinates were successfully decoded
        if not decoded_coords:
            st.warning("Polyline decoding resulted in empty coordinates.")
            return 0.0


        # Create LineString (expects lng, lat)
        # Important: Google polyline decodes to (lat, lng), Shapely LineString usually expects (x, y) i.e., (lng, lat)
        shapely_coords = [(lng, lat) for lat, lng in decoded_coords]
        route_line = LineString(shapely_coords)


        # Ensure the created line is valid
        if not route_line.is_valid or route_line.is_empty:
            st.warning(f"Created route LineString is invalid or empty. Validity: {route_line.is_valid}")
            return 0.0


        # Prepare DAC geometries if they aren't valid MultiPolygons/Polygons
        # This might be slow if done every time; ideally, clean DAC data once upfront
        valid_dac_geoms = []
        for geom in dac_gdf["multipolygon"]: # Assuming 'multipolygon' is the geometry column name
            if geom is not None and geom.is_valid:
                 valid_dac_geoms.append(geom)
            # Optional: Add handling for invalid DAC geoms if needed


        # Calculate intersection - use prepared geometries for potential speedup
        # Use spatial index if DAC dataset is large (though might be overkill here)
        total_intersection_length = 0.0
        for dac_geom in valid_dac_geoms:
            try:
                # Check intersection first (faster than calculating it)
                 if route_line.intersects(dac_geom):
                     intersection = route_line.intersection(dac_geom)
                     # Intersection could be points, lines, collections - sum lengths only for linear parts
                     if intersection.geom_type == 'LineString':
                         total_intersection_length += intersection.length
                     elif intersection.geom_type == 'MultiLineString':
                         total_intersection_length += intersection.length # MultiLineString has a length property
                     elif intersection.geom_type in ['GeometryCollection', 'MultiPoint', 'Point']:
                          # Iterate through collection if necessary, though intersection with polygon should ideally be lines
                          pass # Ignore points or handle specific geometry types if needed
            except GEOSException as intersection_error:
                 st.warning(f"Error during intersection calculation: {intersection_error}. Skipping geometry.")
            except Exception as general_error: # Catch other potential errors
                 st.warning(f"Unexpected error during intersection: {general_error}")


        route_total_length = route_line.length


        if route_total_length > 0:
             overlap_percentage = (total_intersection_length / route_total_length) * 100
             # Ensure percentage is within [0, 100] due to potential floating point issues
             return max(0.0, min(overlap_percentage, 100.0))
        else:
             # st.warning("Route line has zero length.") # Avoid warning if it's expected for very short routes
             return 0.0


    except (ImportError, NameError) as import_error:
         st.error(f"Missing required library for DAC calculation: {import_error}")
         return 0.0
    except ValueError as decode_error: # Catch polyline decoding errors
         st.warning(f"Error decoding polyline '{overview_polyline[:30]}...': {decode_error}")
         return 0.0
    except Exception as e:
        # Log the error for debugging without stopping the app if possible
        st.warning(f"An unexpected error occurred calculating DAC overlap: {e}")
        # Optionally: log detailed traceback
        # import traceback
        # st.error(traceback.format_exc())
        return 0.0 # Return a default value


def get_min_temperature(location):
    # ... (keep existing function)
     # Placeholder - replace with actual weather API call if possible
    try:
        # Basic check: location should be a tuple/list of numbers
        if isinstance(location, (list, tuple)) and len(location) == 2 and all(isinstance(x, (int, float)) for x in location):
            lat = location[0]
            # Example logic: colder north of lat 40
            return 35 if lat < 40 else 45
        else:
            st.warning(f"Invalid location format for temperature: {location}. Returning default.")
            return 45 # Return a default temperature
    except Exception as e:
        st.warning(f"Error determining temperature for {location}: {e}. Returning default.")
        return 45 # Return a default temperature


# ------------------------ Load Data (Do this once) ---------------------
import geopandas as gpd # Make sure geopandas is imported
from shapely import wkt
from shapely.geometry import base # Import base geometry types if needed for checking

@st.cache_data # Cache the data loading
def load_spatial_data():
    try:
        zipcodes_df = pd.read_csv(".data/Modified_Zip_Code_Tabulation_Areas__MODZCTA_.csv")
        dac_locs_raw = pd.read_csv(".data/dac_file.csv")

        # --- Process Zipcodes ---
        # Create geometry objects
        zipcodes_df["geometry"] = zipcodes_df["the_geom"].apply(wkt.loads)

        # Filter based on validity of EACH geometry object
        # Check if the object is a valid geometry before calling .is_valid
        is_valid_geometry = zipcodes_df['geometry'].apply(lambda geom: isinstance(geom, base.BaseGeometry) and geom.is_valid)
        zipcodes_df = zipcodes_df[is_valid_geometry].copy() # Filter and make a copy

        # Calculate centroids only on valid geometries
        zipcodes_df["centroid_lat"] = zipcodes_df["geometry"].apply(lambda g: g.centroid.y)
        zipcodes_df["centroid_lng"] = zipcodes_df["geometry"].apply(lambda g: g.centroid.x)
        zip_lookup = zipcodes_df.set_index("MODZCTA")[["centroid_lat", "centroid_lng"]].to_dict("index")

        # --- Process DAC Locations ---
        dac_locs = dac_locs_raw[dac_locs_raw['DAC_Designation'] == 'Designated as DAC'].copy()
        cols = ['the_geom', 'GEOID']
        # Check if necessary columns exist
        if not all(col in dac_locs.columns for col in cols):
             st.error(f"DAC file is missing required columns: {cols}")
             return zipcodes_df, zip_lookup, None # Return partial data

        dac_locs = dac_locs[cols]

        # Safely load geometries
        def safe_wkt_load(geom_str):
            try:
                return wkt.loads(geom_str)
            except Exception:
                return None
        dac_locs['multipolygon'] = dac_locs['the_geom'].apply(safe_wkt_load)
        dac_locs = dac_locs.dropna(subset=['multipolygon'])

        # Convert to GeoDataFrame *after* creating geometries and dropping invalid ones
        if not dac_locs.empty:
            dac_gdf = gpd.GeoDataFrame(dac_locs, geometry='multipolygon', crs="EPSG:4326") # Assuming WGS84
            # Optional: Further filter GeoDataFrame for valid geometries just in case
            dac_gdf = dac_gdf[dac_gdf.is_valid].copy()
        else:
             st.warning("No valid DAC locations found after processing.")
             dac_gdf = None # Set to None if empty

        return zipcodes_df, zip_lookup, dac_gdf

    except FileNotFoundError as e:
        st.error(f"Error loading data file: {e}. Please ensure '.data/Modified_Zip_Code_Tabulation_Areas__MODZCTA_.csv' and '.data/dac_file.csv' exist.")
        return pd.DataFrame(), {}, None
    except ImportError:
         st.error("Missing required spatial libraries (geopandas, shapely). Please install them.")
         return pd.DataFrame(), {}, None
    except Exception as e:
        st.error(f"An unexpected error occurred during spatial data loading: {e}")
        import traceback
        st.error(traceback.format_exc()) # Print detailed traceback for debugging
        return pd.DataFrame(), {}, None

zipcodes_df, zip_lookup, dac_locs_gdf = load_spatial_data() # Load data


# --- Logo Loading ---
logo_path = ".data/nycsbus-small-logo.png"
encoded_logo = load_logo_as_base64(logo_path)

if encoded_logo:
    st.markdown(
        f"""
        <style>
            .logo-container {{
                position: fixed; top: 70px; right: 20px; z-index: 100;
            }}
            .logo-container img {{ width: 120px; }}
        </style>
        <div class="logo-container">
            <img src="data:image/png;base64,{encoded_logo}">
        </div>
        """,
        unsafe_allow_html=True
    )

# --- Initialize Session State ---
if "view_mode" not in st.session_state:
    st.session_state.view_mode = "Main"
if "routes" not in st.session_state:
    st.session_state.routes = []
if "selected_route_index" not in st.session_state:
    st.session_state.selected_route_index = 0
if "fleet" not in st.session_state:
    st.session_state.fleet = [{}] # Start with one empty bus input
if "last_clicked_location" not in st.session_state:
    st.session_state.last_clicked_location = None
if "route_bus_types" not in st.session_state:
    st.session_state.route_bus_types = {}
if "fleet_data" not in st.session_state:
    st.session_state.fleet_data = None
if "ev_fleet" not in st.session_state:
    st.session_state.ev_fleet = None
if "results" not in st.session_state: # To store processing results
     st.session_state.results = []

# --- NEW state for map view ---
if "selected_route_id_map" not in st.session_state:
    st.session_state.selected_route_id_map = None
if "selected_trip_type_map" not in st.session_state:
    st.session_state.selected_trip_type_map = "AM Trip"

# ------------------------------
# MAIN TAB
# ------------------------------
if st.session_state.view_mode == "Main":

    # --- Sidebar for Fleet Configuration ---
    with st.sidebar:
        st.header("Fleet Configuration")

        # Ensure fleet list exists and has at least one item
        if not st.session_state.fleet:
            st.session_state.fleet = [{}]

        # Add button logic
        if len(st.session_state.fleet) < 20:
            if st.button("Add Another Bus", key="add_bus_sidebar"):
                st.session_state.fleet.append({})
                st.rerun() # Rerun to update the UI immediately

        # Iterate through bus inputs
        indices_to_remove = []
        for i, bus in enumerate(st.session_state.fleet):
             with st.expander(f"Bus {i + 1}", expanded=True):
                 # Use get() with default values for robustness
                 name = st.text_input(f"Name", value=bus.get("Name", ""), key=f"name_{i}")
                 powertrain = st.selectbox(f"Powertrain", ["EV", "Gas"], index=["EV", "Gas"].index(bus.get("Powertrain", "EV")), key=f"powertrain_{i}")
                 bus_type = st.selectbox(f"Type", ["A", "C"], index=["A", "C"].index(bus.get("Type", "A")), key=f"type_{i}")
                 quantity = st.number_input(f"Quantity", min_value=1, value=bus.get("Quantity", 1), step=1, key=f"quantity_{i}")
                 battery_size = None
                 if powertrain == "EV":
                     # Provide a sensible default like 200.0 if not present or invalid
                     default_battery = bus.get("Battery Capacity (kWh)")
                     if not isinstance(default_battery, (int, float)) or default_battery <= 0:
                         default_battery = 200.0
                     battery_size = st.number_input(f"Battery Capacity (kWh)", min_value=1.0, value=default_battery, key=f"battery_{i}")

                 # Update session state directly (Streamlit handles rerun on widget interaction)
                 st.session_state.fleet[i] = {
                     "Name": name,
                     "Powertrain": powertrain,
                     "Type": bus_type,
                     "Quantity": quantity,
                     "Battery Capacity (kWh)": battery_size if powertrain == "EV" else None
                 }

                 # Add a remove button for each bus (except the first one if you want)
                 if len(st.session_state.fleet) > 1: # Only show remove if more than one bus
                    if st.button(f"Remove Bus {i + 1}", key=f"remove_bus_{i}"):
                        indices_to_remove.append(i)


        # Process removals after the loop
        if indices_to_remove:
             # Remove indices in reverse order to avoid index shifting issues
             for index in sorted(indices_to_remove, reverse=True):
                 del st.session_state.fleet[index]
             st.rerun()

        # Save Fleet Button
        if st.button("Save Fleet Data", key="save_fleet"):
            # Basic Validation: Check if at least one bus has a name
            if not any(bus.get("Name") for bus in st.session_state.fleet):
                st.warning("Please provide a name for at least one bus.")
            else:
                try:
                    # Filter out potentially empty/incomplete entries before creating DataFrame
                    valid_fleet_data = [bus for bus in st.session_state.fleet if bus.get("Name")] # Example: Require name
                    if valid_fleet_data:
                        fleet_data = pd.DataFrame(valid_fleet_data)
                        st.session_state.ev_fleet = process_fleet_data(fleet_data)
                        st.session_state.fleet_data = fleet_data # Store the raw valid data too
                        st.success("✅ Fleet data processed and saved.")
                        # Optionally display the processed EV fleet in the sidebar
                        if st.session_state.ev_fleet is not None and not st.session_state.ev_fleet.empty:
                            st.write("Processed EV Fleet Summary:")
                            st.dataframe(st.session_state.ev_fleet)
                        elif st.session_state.fleet_data is not None:
                             st.info("No EV buses found or processed in the fleet.")

                    else:
                        st.warning("No valid bus data entered to save.")
                        st.session_state.ev_fleet = None # Clear previous results if invalid save
                        st.session_state.fleet_data = None

                except Exception as e:
                     st.error(f"Error processing fleet data: {e}")
                     # Consider logging the full error traceback for debugging
                     st.session_state.ev_fleet = None # Clear results on error
                     st.session_state.fleet_data = None



    # --- Main Page Content ---
    st.title("Electric Bus Route Planning")
    st.markdown("Welcome to the NYCSBUS EV Route Machine.")
    st.markdown("**Step 1:** Please define your fleet in the sidebar to the left. When completed, press *Save Fleet Data*.")
    st.markdown("**Step 2:** Define your routes using one of the methods below.")
    st.markdown("**Step 3:** Once your routes and fleet are entered, click *Process Routes for Electrification* to analyze feasibility.")

    st.session_state.input_mode = st.radio(
        "How would you like to define routes?",
        ["Interactive Map", "Upload CSV"],
        horizontal=True,
        key="route_input_mode" # Add a key for stability
        )

    # --- Route Input Section ---
    if st.session_state.input_mode == "Interactive Map":
        st.subheader("Define Routes Interactively")
        # Import and call your map logic function here
        # Make sure the interactive_map_logic.py file exists and is correct
        try:
            from interactive_map_logic import handle_map_route_input
            # Pass necessary data to the function
            handle_map_route_input(st, folium, st_folium, zipcodes_df, zip_lookup)
        except ImportError:
            st.error("Could not find 'interactive_map_logic.py'. Please ensure the file exists.")
        except Exception as e:
            st.error(f"Error loading interactive map logic: {e}")


    elif st.session_state.input_mode == "Upload CSV":
        st.subheader("Upload Your Route CSV")
        uploaded_file = st.file_uploader("Upload CSV file", type=["csv"], key="csv_uploader")

        # Display format instructions clearly
        st.markdown("""
        **CSV Format Guide:**
        - **Required Columns:** `Route` (Route ID), `Location Type` (`Depot`, `Pickup`, or `Dropoff`), `Address` (Full address for geocoding), `Sequence Number` (Order of stops: 0 for Depot, 1+ for stops).
        - **Optional Column:** `Time` (School Bell Time for the *first* `Dropoff` location of that route, format `HH:MM` e.g., `08:00` or `14:30`). This is used to estimate departure time.
        """)
        st.info("🔒 Uploaded files are processed in memory only. Click 'Process CSV' to load and geocode addresses. Review the geocoded points before proceeding.")

        # Example Table
        st.markdown("""
        **Example CSV Structure:**

        | Route | Location Type | Address                          | Time   | Sequence Number |
        |-------|---------------|----------------------------------|--------|-----------------|
        | R101  | Depot         | 123 Depot Way, Bronx, NY 10451   |        | 0               |
        | R101  | Pickup        | 456 Park Ave, Bronx, NY 10455    |        | 1               |
        | R101  | Pickup        | 789 Grand Concourse, Bronx, NY 10457|      | 2               |
        | R101  | Dropoff       | 10 School St, Bronx, NY 10460    | 08:00  | 3               |
        | R101  | Dropoff       | 25 Academy Pl, Bronx, NY 10462   |        | 4               |
        | B205  | Depot         | 50 Bus Terminal, Queens, NY 11368|        | 0               |
        | B205  | Pickup        | 200 Main St, Queens, NY 11369    |        | 1               |
        | B205  | Dropoff       | 400 Education Dr, Queens, NY 11370| 08:15  | 2               |
        """)

        if uploaded_file:
            try:
                df_upload = pd.read_csv(uploaded_file)
                st.write("Preview of Uploaded CSV:")
                st.dataframe(df_upload.head())

                # Basic column check
                required_cols = ['Route', 'Location Type', 'Address', 'Sequence Number']
                if not all(col in df_upload.columns for col in required_cols):
                     st.error(f"CSV is missing one or more required columns: {required_cols}. Please check the format.")
                else:
                    if st.button("Process CSV", key="process_csv_button"):
                        Maps_api_key = st.secrets.get("google_maps_api_key")
                        if not Maps_api_key:
                            st.error("Google Maps API key not found in secrets.")
                        else:
                             # Geocode addresses from CSV
                            with st.spinner("Geocoding addresses... This may take a while."):
                                route_dict = {}
                                geocoding_failures = []

                                # Sort by Route and Sequence Number for correct processing order
                                df_upload = df_upload.sort_values(by=['Route', 'Sequence Number'])

                                for _, row in df_upload.iterrows():
                                    route_id = str(row['Route']).strip() # Ensure string type and remove whitespace
                                    location_type = str(row['Location Type']).strip().capitalize() # Standardize
                                    address = str(row['Address']).strip()
                                    time_str = row.get('Time') # Okay if missing
                                    sequence = int(row['Sequence Number']) # Should be integer

                                    # Input validation
                                    if not route_id or not location_type or not address:
                                         st.warning(f"Skipping row with missing Route ID, Location Type, or Address: {row.to_dict()}")
                                         continue
                                    if location_type not in ["Depot", "Pickup", "Dropoff"]:
                                        st.warning(f"Skipping row with invalid Location Type '{location_type}' for Route {route_id}. Use 'Depot', 'Pickup', or 'Dropoff'.")
                                        continue


                                    try:
                                        # Simple rate limiting
                                        time.sleep(0.1) # Adjust sleep time as needed


                                        # --- Geocoding API Call ---
                                        geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
                                        params = {"address": address, "key": Maps_api_key}
                                        response = requests.get(geocode_url, params=params, timeout=10)
                                        response.raise_for_status()
                                        data = response.json()


                                        if data["status"] == "OK" and data.get("results"):
                                             location = data["results"][0]["geometry"]["location"]
                                             coords = (location["lat"], location["lng"])


                                             # Initialize route if not exists
                                             if route_id not in route_dict:
                                                 route_dict[route_id] = {
                                                     "route_id": route_id,
                                                     "depot": None,
                                                     "pickups": [], # Store as list of dicts: {'location': coords, 'sequence': seq}
                                                     "dropoffs": [], # Store as list of dicts: {'location': coords, 'sequence': seq, 'bell_time': time}
                                                     "csv_source": True # Flag that it came from CSV
                                                 }


                                             # --- Time Parsing ---
                                             parsed_time = None
                                             # Only parse time for the FIRST dropoff location
                                             is_first_dropoff = (location_type == "Dropoff" and not any(d['bell_time'] for d in route_dict[route_id]["dropoffs"] if d.get('bell_time')))

                                             if pd.notna(time_str) and isinstance(time_str, str) and time_str.strip() and is_first_dropoff:
                                                time_str_cleaned = time_str.strip()
                                                try:
                                                    # Try HH:MM format first
                                                    parsed_time = datetime.datetime.strptime(time_str_cleaned, "%H:%M").time()
                                                except ValueError:
                                                     try:
                                                         # Try H:MM format
                                                         parsed_time = datetime.datetime.strptime(time_str_cleaned, "%H:%M").time() # Typo Correction H:MM
                                                     except ValueError:
                                                         st.warning(f"Route {route_id}: Invalid time format for address '{address}': '{time_str}'. Expected HH:MM or H:MM. Bell time ignored.")


                                             # --- Assign to Route Structure ---
                                             if location_type == "Depot":
                                                 # Allow only one depot per route, potentially overwrite if multiple found? Or take first?
                                                 if route_dict[route_id]["depot"] is None:
                                                     route_dict[route_id]["depot"] = coords
                                                 else:
                                                      st.warning(f"Route {route_id}: Multiple Depot locations found. Using the first one encountered at sequence {sequence}.") # Provide more context
                                             elif location_type == "Pickup":
                                                 route_dict[route_id]["pickups"].append({"location": coords, "sequence": sequence})
                                             elif location_type == "Dropoff":
                                                  route_dict[route_id]["dropoffs"].append({
                                                     "location": coords,
                                                     "sequence": sequence,
                                                     "bell_time": parsed_time # Store parsed time only for the first dropoff
                                                     })


                                        else:
                                            st.warning(f"Geocoding failed for Route {route_id}, Address '{address}': {data.get('status', 'Unknown Error')}")
                                            geocoding_failures.append(f"Route {route_id}: {address}")


                                    except requests.exceptions.RequestException as req_err:
                                         st.error(f"Network error geocoding '{address}': {req_err}")
                                         geocoding_failures.append(f"Route {route_id}: {address} (Network Error)")
                                    except Exception as geocode_error:
                                         st.error(f"Unexpected error geocoding '{address}': {geocode_error}")
                                         geocoding_failures.append(f"Route {route_id}: {address} (Processing Error)")


                            # --- Post-Processing ---
                            processed_routes = []
                            for route_id, data in route_dict.items():
                                # Sort pickups and dropoffs by sequence number stored during processing
                                data["pickups"] = sorted(data["pickups"], key=lambda x: x['sequence'])
                                data["dropoffs"] = sorted(data["dropoffs"], key=lambda x: x['sequence'])
                                processed_routes.append(data)


                            # Append or replace routes in session state
                            # Decide if you want to add to existing or replace
                            # st.session_state.routes.extend(processed_routes) # Adds to existing map routes
                            st.session_state.routes = processed_routes # Replaces any existing routes
                            st.success(f"CSV processed. {len(processed_routes)} routes loaded.")
                            if geocoding_failures:
                                 st.warning("Some addresses could not be geocoded:")
                                 st.json(geocoding_failures) # Use json for better list display

                            # Display loaded routes summary (optional)
                            # st.write("Loaded Routes Overview:")
                            # for r in st.session_state.routes:
                            #     st.write(f" - Route: {r['route_id']}, Depot: {'Yes' if r['depot'] else 'No'}, Pickups: {len(r['pickups'])}, Dropoffs: {len(r['dropoffs'])}")


            except pd.errors.EmptyDataError:
                 st.error("The uploaded CSV file is empty.")
            except Exception as e:
                 st.error(f"Error reading or processing CSV: {e}")
                 st.error("Please ensure the file is a valid CSV and matches the specified format.")


    # ------------------------------
    # Route Calculation Button
    # ------------------------------
    st.markdown("---") # Separator before calculation button
    st.header("Calculate Route Feasibility")

    # Check if API key exists
    Maps_api_key = st.secrets.get("google_maps_api_key")
    if not Maps_api_key:
        st.error("Google Maps API key not found in secrets. Please add it to your Streamlit secrets to enable route calculations.")
        can_calculate = False
    else:
        can_calculate = True

    # Check if fleet data is processed
    if st.session_state.get("ev_fleet") is None or st.session_state.ev_fleet.empty:
        st.warning("Fleet data not processed or no EV buses found. Please configure and save your fleet in the sidebar.")
        can_calculate = False

    # Check if routes exist
    if not st.session_state.routes:
        st.warning("No routes defined. Please define routes using the map or CSV upload.")
        can_calculate = False

    # Calculation Button - Disable if checks fail
    if st.button("Process Routes for Electrification", disabled=not can_calculate, key="process_electrification"):
        if can_calculate:
             results_list = [] # Store results here
             routes_to_process = st.session_state.routes
             # Use a progress bar
             progress_bar = st.progress(0, text="Starting route calculations...")
             total_routes = len(routes_to_process)

             for i, route in enumerate(routes_to_process):
                 route_id = route.get("route_id", f"Route_{i+1}")
                 progress_text = f"Processing Route: {route_id} ({i+1}/{total_routes})"
                 progress_bar.progress((i + 1) / total_routes, text=progress_text)

                 # --- Validate Route Structure ---
                 if not route.get("depot"): st.warning(f"Route {route_id}: Skipping - Missing Depot."); continue
                 if not route.get("dropoffs"): st.warning(f"Route {route_id}: Skipping - Missing Dropoffs."); continue

                 # Initialize feasibility dict
                 feasibility_result = {
                    "Route ID": route_id,
                    "AM Distance (miles)": None, "AM Duration (min)": None, "AM Overview Polyline": None,
                    "PM Distance (miles)": None, "PM Duration (min)": None, "PM Overview Polyline": None,
                    "Percent in DAC": 0.0, "Suggested Depot Departure Time": None,
                    "First School Bell Time": None, "Drive Time to First School (min)": None,
                    "Leg Details": []
                 }

                 # --- Prepare & Calculate AM Route ---
                 try:
                     am_origin = route["depot"]
                     # Ensure dropoffs list is not empty and first dropoff has location
                     if not route["dropoffs"] or not route["dropoffs"][0].get("location"):
                          st.warning(f"Route {route_id}: Skipping - Invalid first dropoff location.")
                          continue
                     am_destination = route["dropoffs"][0]["location"]
                     am_waypoints_data = route.get("pickups", []) + route.get("dropoffs", [])[1:]
                     am_waypoints = [wp.get("location") for wp in am_waypoints_data if wp.get("location")]
                     first_bell_time = route["dropoffs"][0].get("bell_time")

                     am_distance, am_duration, am_leg_details, am_polyline = get_route_distance(
                         Maps_api_key, am_origin, am_waypoints, am_destination, first_bell_time
                     )

                     if am_distance is not None and am_duration is not None:
                         feasibility_result["AM Distance (miles)"] = round(am_distance, 2)
                         feasibility_result["AM Duration (min)"] = round(am_duration, 1)
                         feasibility_result["AM Overview Polyline"] = am_polyline
                         feasibility_result["Leg Details"] = am_leg_details
                         feasibility_result["Drive Time to First School (min)"] = round(am_duration, 1) # AM duration is time to first school

                         if first_bell_time:
                             feasibility_result["First School Bell Time"] = first_bell_time.strftime("%I:%M %p")
                             try:
                                 arrival_dt = datetime.datetime.combine(datetime.date.today(), first_bell_time)
                                 buffer_minutes = 15
                                 departure_dt = arrival_dt - datetime.timedelta(minutes=am_duration + buffer_minutes)
                                 feasibility_result["Suggested Depot Departure Time"] = departure_dt.time().strftime("%I:%M %p")
                             except Exception as e: st.warning(f"Route {route_id}: Error calculating departure time: {e}")

                         if am_polyline and dac_locs_gdf is not None:
                            feasibility_result["Percent in DAC"] = round(calculate_dac_overlap(am_polyline, dac_locs_gdf), 2)
                     else:
                         st.warning(f"Route {route_id}: Failed to calculate AM route details.")


                     # --- Prepare & Calculate PM Route ---
                     # Ensure last dropoff exists and has location
                     if not route["dropoffs"] or not route["dropoffs"][-1].get("location"):
                          st.warning(f"Route {route_id}: Skipping PM calculation - Invalid last dropoff location.")
                     else:
                          pm_origin = route["dropoffs"][-1]["location"]
                          pm_destination = route["depot"]
                          pm_waypoints_data = route.get("dropoffs", [])[:-1] + route.get("pickups", [])
                          # Sort intermediate points by sequence descending for logical reverse path
                          pm_waypoints_data_sorted = sorted(pm_waypoints_data, key=lambda x: x.get('sequence', 0), reverse=True)
                          pm_waypoints = [wp.get("location") for wp in pm_waypoints_data_sorted if wp.get("location")]

                          pm_distance, pm_duration, _, pm_polyline = get_route_distance(
                              Maps_api_key, pm_origin, pm_waypoints, pm_destination, None
                          )

                          if pm_distance is not None and pm_duration is not None:
                             feasibility_result["PM Distance (miles)"] = round(pm_distance, 2)
                             feasibility_result["PM Duration (min)"] = round(pm_duration, 1)
                             feasibility_result["PM Overview Polyline"] = pm_polyline
                          else:
                              st.warning(f"Route {route_id}: Failed to calculate PM route details.")

                 except Exception as route_calc_error:
                      st.error(f"Route {route_id}: Unexpected error during calculation: {route_calc_error}")
                      st.error(traceback.format_exc()) # Log detailed error

                 results_list.append(feasibility_result) # Append result even if parts failed

             progress_bar.empty() # Clear progress bar
             st.session_state.results = results_list # Store results
             if results_list:
                  st.success(f"Route processing complete for {len(results_list)} route(s).")
                  switch_view("EV Route Planning") # Switch to results view
                  st.rerun() # Ensure immediate switch
             else:
                  st.warning("Route processing finished, but no results were generated.")

    # --- Reset Button ---
    st.markdown("---")
    if st.button("🔁 Reset App State", key="reset_app"):
        keys_to_clear = list(st.session_state.keys()) # Get all keys
        for key in keys_to_clear:
             # Optionally keep some keys like 'view_mode' if needed, otherwise clear all
             # if key not in ['some_key_to_keep']:
             del st.session_state[key]
        st.success("App state reset.")
        time.sleep(0.5) # Brief pause before rerun
        st.rerun()


# -------------------------------------
# EV Route Planning / Results View
# -------------------------------------
elif st.session_state.view_mode == "EV Route Planning":

    st.subheader("🔧 Assign Bus Type to Each Route")
    st.markdown('Select which type of bus each route operates on. Then, click "Show Me the Plan!" to see the bus assignment summary, based on routes that can be completed without midday charging.')
    st.markdown(f"*Route feasibility is calculated assuming a 20% buffer for battery health (80% usable capacity). These estimates do not include deadhead mileage outside of the defined stops, nor a return to the depot midday.*")

    # Ensure route/fleet data exist
    if not st.session_state.get("results"):
        st.warning("No route results found. Please go back to the Main page and process routes first.")
        if st.button("⬅ Back to Main", key="back_to_main_no_results"):
            switch_view("Main")
            st.rerun()
    elif st.session_state.get("ev_fleet") is None or st.session_state.ev_fleet.empty:
         st.warning("No EV Fleet data found. Please configure and save your EV fleet on the Main page.")
         if st.button("⬅ Back to Main", key="back_to_main_no_fleet"):
            switch_view("Main")
            st.rerun()
    else:
        # --- Bus Type Assignment ---
        if "route_bus_types" not in st.session_state: st.session_state.route_bus_types = {}
        routes_with_results = st.session_state.results
        # Use a columns layout for better density if many routes
        # num_columns = 2 # Adjust number of columns
        # cols = st.columns(num_columns)
        col_index = 0
        for result_data in routes_with_results:
             route_id = result_data.get("Route ID")
             if not route_id: continue
             # current_col = cols[col_index % num_columns] # Use if using columns layout
             # with current_col: # Use if using columns layout
             current_selection = st.session_state.route_bus_types.get(route_id, "A")
             valid_types = ["A", "C"]
             if current_selection not in valid_types: current_selection = "A"
             try: default_index = valid_types.index(current_selection)
             except ValueError: default_index = 0
             selected_type = st.selectbox(
                 f"Bus Type for Route {route_id}", # Shorter label
                 valid_types, index=default_index, key=f"route_bus_type_{route_id}"
             )
             st.session_state.route_bus_types[route_id] = selected_type
             # col_index += 1 # Use if using columns layout

        # --- Back Button ---
        if st.button("⬅ Back to Main", key="back_to_main_plan_view"):
            switch_view("Main")
            st.rerun()

        st.markdown("---")

        # --- Show Plan Button and Logic ---
        if st.button("Show Me the Plan!", key="show_plan_button"):
            _calculation_successful = False # Flag to track success
            # Clear previous plan results first before attempting calculation
            st.session_state.plan_results_df = None
            try:
                ev_fleet = st.session_state.ev_fleet
                plan_results_list = []

                for result_data in st.session_state.results:
                     route_id = result_data.get("Route ID")
                     if not route_id: continue

                     suggested_time = result_data.get("Suggested Depot Departure Time", "N/A")
                     percent_in_dac = result_data.get("Percent in DAC", 0.0)
                     am_miles = result_data.get("AM Distance (miles)", 0.0) or 0.0
                     pm_miles = result_data.get("PM Distance (miles)", 0.0) or 0.0
                     round_trip = am_miles + pm_miles
                     selected_type = st.session_state.route_bus_types.get(route_id, "A")
                     matching_fleet = ev_fleet[ev_fleet["Type"] == selected_type].copy()

                     def get_eligible_names(df, range_col_name, required_range):
                         if range_col_name in df.columns:
                             eligible_df = df[pd.to_numeric(df[range_col_name], errors='coerce') >= required_range]
                             names = eligible_df["Name"].dropna().unique()
                             return ", ".join(names) if len(names) > 0 else ""
                         return ""
                     cold_buses = get_eligible_names(matching_fleet, "Cold Weather Range", round_trip)
                     avg_buses = get_eligible_names(matching_fleet, "Average Weather Range", round_trip)
                     warm_buses = get_eligible_names(matching_fleet, "Warm Weather Range", round_trip)

                     plan_results_list.append({
                         "Route ID": route_id, "Type Required": selected_type,
                         "Round Trip (mi)": round(round_trip, 2),
                         "Eligible Buses < 50°F": cold_buses, "Eligible Buses 50–70°F": avg_buses,
                         "Eligible Buses 70°F+": warm_buses, "Percent in DAC": percent_in_dac,
                         "Suggested Departure Time": suggested_time
                     })

                if plan_results_list:
                    plan_df = pd.DataFrame(plan_results_list)

                    def classify_eligibility(row):
                         in_dac = pd.to_numeric(row.get("Percent in DAC"), errors='coerce')
                         dac_preference = (in_dac is not None and in_dac > 70)
                         cold_ok = bool(row.get("Eligible Buses < 50°F"))
                         mild_ok = bool(row.get("Eligible Buses 50–70°F"))
                         warm_ok = bool(row.get("Eligible Buses 70°F+"))
                         if dac_preference and cold_ok: return "Preferred - All Weather"
                         elif cold_ok: return "OK in All Weather"
                         elif mild_ok: return "OK > 50°F Weather"
                         elif warm_ok: return "OK > 70°F Weather"
                         else: return "NOT FEASIBLE (No Bus)"
                    eligibility_order = { "Preferred - All Weather": 0, "OK in All Weather": 1, "OK > 50°F Weather": 2, "OK > 70°F Weather": 3, "NOT FEASIBLE (No Bus)": 4 }
                    plan_df["EV Eligibility"] = plan_df.apply(classify_eligibility, axis=1)
                    plan_df["Eligibility Rank"] = plan_df["EV Eligibility"].map(eligibility_order)
                    plan_df = plan_df.sort_values(by=["Eligibility Rank", "Route ID"]).drop(columns=["Eligibility Rank"])

                    plan_df.rename(columns={
                        'Type Required': 'Bus Type',
                        'Percent in DAC': '% in Disadvantaged Community'
                    }, inplace=True)

                    final_cols_order = [
                       'Route ID', 'Bus Type', 'EV Eligibility', 'Suggested Departure Time',
                       '% in Disadvantaged Community', 'Round Trip (mi)',
                       'Eligible Buses < 50°F', 'Eligible Buses 50–70°F', 'Eligible Buses 70°F+'
                    ]

                    missing_cols = [col for col in final_cols_order if col not in plan_df.columns]
                    if missing_cols:
                        st.error(f"Internal Error: Missing expected columns after processing: {missing_cols}")
                        st.write("Available columns:", plan_df.columns.tolist())
                        # Keep state as None (already cleared)
                    else:
                        plan_df_display = plan_df[final_cols_order]
                        # *** Set state ONLY on full success ***
                        st.session_state.plan_results_df = plan_df_display
                        _calculation_successful = True
                        st.success("Plan generated successfully!")

                else: # No results in plan_results_list
                    st.info("No eligible route results available to generate a plan.")
                    # Keep state as None (already cleared)

            except Exception as e:
                 st.error(f"An error occurred while generating the plan: {e}")
                 st.error(traceback.format_exc()) # Show detailed error
                 # Keep state as None (already cleared)
                 _calculation_successful = False

        # --- Display Section (Tables and Map) ---
        # Check if the state variable exists and holds a non-empty DataFrame from the LAST button click
        if st.session_state.get("plan_results_df") is not None and not st.session_state.plan_results_df.empty:

             # --- Display Tables ---
             st.subheader("🚌 EV Route Feasibility Summary")
             st.dataframe(st.session_state.plan_results_df, use_container_width=True)
             st.subheader("⚡ EV Fleet Range Summary")
             st.dataframe(st.session_state.ev_fleet, use_container_width=True)

             # --- Map Visualization Section ---
             st.markdown("---")
             st.subheader("🗺️ Route Map Visualization")

             if st.session_state.get("results"): # Check if original results with polylines still exist
                 route_ids_in_plan = st.session_state.plan_results_df['Route ID'].tolist()
                 if not route_ids_in_plan:
                     st.info("No routes found in the generated plan to display on map.")
                 else:
                     # --- Map Controls ---
                     valid_selection = st.session_state.selected_route_id_map in route_ids_in_plan
                     if not valid_selection or st.session_state.selected_route_id_map is None:
                         st.session_state.selected_route_id_map = route_ids_in_plan[0]

                     col1, col2 = st.columns([1, 1])
                     with col1:
                        current_index = route_ids_in_plan.index(st.session_state.selected_route_id_map)
                        st.session_state.selected_route_id_map = st.selectbox(
                            "Select Route ID to Display:", options=route_ids_in_plan,
                            key="map_route_selector", index=current_index
                        )
                     with col2:
                         trip_options = ["AM Trip", "PM Trip", "Round Trip"]
                         current_trip_type = st.session_state.selected_trip_type_map
                         if current_trip_type not in trip_options: current_trip_type = "AM Trip"
                         st.session_state.selected_trip_type_map = st.radio(
                            "Select Trip Type:", options=trip_options, key="map_trip_type_selector",
                            index=trip_options.index(current_trip_type), horizontal=True
                         )
                     # --- Find Selected Route Data ---
                     selected_route_original_data = None
                     selected_feasibility_data = None
                     if isinstance(st.session_state.get("routes"), list):
                        for r in st.session_state.routes:
                             if r.get("route_id") == st.session_state.selected_route_id_map:
                                 selected_route_original_data = r; break
                     if isinstance(st.session_state.get("results"), list):
                        for res in st.session_state.results:
                             if res.get("Route ID") == st.session_state.selected_route_id_map:
                                 selected_feasibility_data = res; break

                     if selected_route_original_data and selected_feasibility_data:
                        map_col, info_col = st.columns([3, 2])
                        with map_col:
                            # --- Map Creation ---
                            map_center = selected_route_original_data.get("depot") or \
                                         (selected_route_original_data.get("pickups",[{}])[0].get("location")) or \
                                         (selected_route_original_data.get("dropoffs",[{}])[0].get("location")) or \
                                         [40.7128, -74.0060]
                            m = folium.Map(location=map_center, zoom_start=12, tiles="cartodbpositron")
                            # --- Add Markers ---
                            def add_marker(loc, pop, tip, ico): # Shorter args
                                if loc and isinstance(loc, (list, tuple)) and len(loc) == 2:
                                    folium.Marker(location=loc, popup=pop, tooltip=tip, icon=ico).add_to(m)
                            depot_loc = selected_route_original_data.get("depot")
                            add_marker(depot_loc, f"Depot ({selected_route_original_data.get('route_id', 'N/A')})", "Depot", Icon(color=DEPOT_COLOR, icon='bus', prefix='fa'))
                            for i, pickup in enumerate(selected_route_original_data.get("pickups", [])): add_marker(pickup.get("location"), f"Pickup {i+1}", f"Pickup {i+1}", Icon(color=PICKUP_COLOR, icon='user-plus', prefix='fa'))
                            for i, dropoff in enumerate(selected_route_original_data.get("dropoffs", [])):
                                 bell_time_str = f" (Bell: {selected_feasibility_data['First School Bell Time']})" if i == 0 and selected_feasibility_data.get('First School Bell Time') else ""
                                 add_marker(dropoff.get("location"), f"Dropoff {i+1}{bell_time_str}", f"Dropoff {i+1}", Icon(color=DROPOFF_COLOR, icon='school', prefix='fa'))
                            # --- Add Polylines ---
                            points_to_fit = []
                            def add_polyline_to_map(map_obj, encoded_polyline, color, weight, opacity, tooltip):
                                 if 'polyline' not in globals(): return []
                                 if encoded_polyline and isinstance(encoded_polyline, str):
                                     try:
                                         decoded_points = polyline.decode(encoded_polyline)
                                         if decoded_points:
                                             folium.PolyLine(locations=decoded_points, color=color, weight=weight, opacity=opacity, tooltip=tooltip).add_to(map_obj)
                                             return decoded_points
                                     except Exception: pass
                                 return []
                            am_poly = selected_feasibility_data.get("AM Overview Polyline")
                            if st.session_state.selected_trip_type_map in ["AM Trip", "Round Trip"]: points_to_fit.extend(add_polyline_to_map(m, am_poly, AM_ROUTE_COLOR, 4, 0.7, "AM Route"))
                            pm_poly = selected_feasibility_data.get("PM Overview Polyline")
                            if st.session_state.selected_trip_type_map in ["PM Trip", "Round Trip"]: points_to_fit.extend(add_polyline_to_map(m, pm_poly, PM_ROUTE_COLOR, 4, 0.7, "PM Route"))
                            # --- Fit Bounds ---
                            if points_to_fit:
                                 try: m.fit_bounds([[min(p[0] for p in points_to_fit), min(p[1] for p in points_to_fit)], [max(p[0] for p in points_to_fit), max(p[1] for p in points_to_fit)]], padding=(0.01, 0.01))
                                 except ValueError: pass
                            elif depot_loc: m.location = depot_loc; m.zoom_start = 14
                            # --- Display Map ---
                            st_folium(m, width='100%', height=500, key="route_map_display")

                        # Inside the EV Route Planning view -> Map Visualization Section -> with info_col:

                        with info_col:
                            # --- Info Panel ---
                            st.subheader(f"Route Details: {st.session_state.selected_route_id_map}")
                            st.markdown(f"**Trip Type:** {st.session_state.selected_trip_type_map}")
                            # ... (Keep the distance/duration metric display logic) ...
                            st.divider()
                            st.markdown(f"**Suggested Depot Departure:** {selected_feasibility_data.get('Suggested Depot Departure Time', 'N/A')}")
                            dac_percent = selected_feasibility_data.get('Percent in DAC')
                            st.markdown(f"**% Route in DAC:** {dac_percent:.1f}%" if dac_percent is not None else "N/A")

                            # --- Enhanced Eligibility Display ---
                            plan_df = st.session_state.plan_results_df # Already checked it exists
                            route_plan_info = plan_df[plan_df['Route ID'] == st.session_state.selected_route_id_map]

                            if not route_plan_info.empty:
                                 route_info_row = route_plan_info.iloc[0] # Get the row data
                                 eligibility = route_info_row.get('EV Eligibility', 'N/A')
                                 bus_type = route_info_row.get('Bus Type', 'N/A')
                                 eligible_bus_names = "" # Initialize

                                 # Determine which bus list to show based on eligibility status
                                 if eligibility in ["Preferred - All Weather", "OK in All Weather"]:
                                     eligible_bus_names = route_info_row.get('Eligible Buses < 50°F', '')
                                 elif eligibility == "OK > 50°F Weather":
                                     eligible_bus_names = route_info_row.get('Eligible Buses 50–70°F', '')
                                 elif eligibility == "OK > 70°F Weather":
                                     eligible_bus_names = route_info_row.get('Eligible Buses 70°F+', '')
                                 # No specific buses to list for "NOT FEASIBLE"

                                 # Format the final eligibility string
                                 eligibility_display = f"**EV Eligibility Status:** {eligibility}"
                                 if eligible_bus_names and isinstance(eligible_bus_names, str) and eligible_bus_names.strip():
                                     eligibility_display += f" (with: *{eligible_bus_names}*)" # Add bus names if they exist

                                 st.markdown(f"**Assigned Bus Type:** {bus_type}")
                                 st.markdown(eligibility_display) # Display the combined string
                            else:
                                 st.markdown("**EV Eligibility Status:** Route not found in plan details.")
                         # --- End of Enhanced Display ---

                     else: # End if selected_route_original_data and selected_feasibility_data
                        st.warning(f"Could not retrieve all necessary data for Route ID: {st.session_state.selected_route_id_map}")

             else: # End if st.session_state.get("results")
                 st.error("Route results data (containing map details) is missing. Please re-process routes from the Main page.")
        # else: # Optional Message shown when plan_results_df is None
             # st.info("Click 'Show Me the Plan!' to generate the summary and view the route map.")

# --- End of the EV Route Planning view block ---