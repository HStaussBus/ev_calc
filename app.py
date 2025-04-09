
# Step 1: Apply Guided Workflow with Tabs
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
from shapely.geometry import LineString, MultiPolygon, Polygon, Point, base # Import base
import polyline # Make sure polyline is imported
import geopandas as gpd
from shapely import wkt
from shapely.errors import GEOSException # Import GEOSException
import os
import base64
import traceback
import io # Import io for download button later

st.set_page_config(layout="wide") # Use wide layout for better tab spacing

st.markdown("""
<style>
    /* Keep sidebar style if you still want it for other potential uses,
       or remove if sidebar is completely gone */
    /* [data-testid=stSidebar] > div:first-child {
        background-color: #f6e782;
    } */

    /* Reduce vertical space used by tabs */
     div[data-testid="stTabs"] button {
         padding-top: 0.5rem !important;
         padding-bottom: 0.5rem !important;
     }

     /* Make containers within tabs look distinct */
     div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlock"] > div[data-testid="element-container"] > div[data-testid="stExpander"] {
         border: 1px solid #e0e0e0;
         border-radius: 5px;
         padding-left: 10px; /* Add some padding inside expander */
         margin-bottom: 10px; /* Space below expander */
     }

</style>
""", unsafe_allow_html=True)

# --- Constants ---
DEPOT_COLOR = 'red'
PICKUP_COLOR = 'blue'
DROPOFF_COLOR = 'green'
AM_ROUTE_COLOR = 'purple'
PM_ROUTE_COLOR = 'orange'

# --- Existing Helper Functions (Keep them as they are - no changes needed for tabs) ---
# def switch_view(mode): # REMOVED - Tabs handle view switching now
#     st.session_state.view_mode = mode
#     st.rerun()

def load_logo_as_base64(path):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        st.warning(f"Logo file not found at {path}. Skipping logo display.")
        return None

def process_fleet_data(fleet_df):
    # ... (keep existing function logic) ...
    ev_fleet = fleet_df[fleet_df["Powertrain"] == "EV"].copy()

    def calc_ranges(row):
        kWh = row["Battery Capacity (kWh)"]
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
        else:
            return pd.Series({col: None for col in ["Cold Weather Range", "Average Weather Range", "Warm Weather Range"]})

    range_cols = ["Cold Weather Range", "Average Weather Range", "Warm Weather Range"]
    ev_fleet[range_cols] = ev_fleet.apply(calc_ranges, axis=1)

    required_cols = ["Name", "Type", "Quantity", "Battery Capacity (kWh)"] + range_cols
    existing_cols = [col for col in required_cols if col in ev_fleet.columns]
    return ev_fleet[existing_cols]

def get_route_distance(api_key, origin, waypoints, destination, departure_time=None):
    # ... (keep existing function logic, including error handling) ...
    import datetime

    def normalize_location(point):
        if isinstance(point, (list, tuple)) and len(point) == 2 and all(isinstance(x, (int, float)) for x in point):
            return point
        elif isinstance(point, dict) and "location" in point:
            loc = point["location"]
            if isinstance(loc, (list, tuple)) and len(loc) == 2 and all(isinstance(x, (int, float)) for x in loc):
                return loc
        st.error(f"Invalid location format encountered: {point}")
        raise ValueError(f"Invalid location format: {point}")

    base_url = "https://maps.googleapis.com/maps/api/directions/json"
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
         return None, None, [], None

    departure_unix = "now"
    if departure_time:
        try:
            now = datetime.datetime.now()
            if isinstance(departure_time, str):
                 departure_time = datetime.datetime.strptime(departure_time, "%H:%M").time()
            elif not isinstance(departure_time, datetime.time):
                 st.warning(f"Unexpected departure_time format: {departure_time}. Using current time.")
                 departure_time = now.time()

            days_ahead = (0 - now.weekday() + 7) % 7
            if days_ahead == 0 and now.time() > departure_time : days_ahead = 7
            elif days_ahead == 0 and now.time() <= departure_time: days_ahead = 0
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
        "key": api_key,
        "mode": "driving",
    }
    if isinstance(departure_unix, int):
         params["traffic_model"] = "best_guess"
         params["departure_time"] = departure_unix

    try:
        response = requests.get(base_url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error during Google Maps API request: {e}")
        return None, None, [], None
    except Exception as e:
        st.error(f"An unexpected error occurred fetching directions: {e}")
        return None, None, [], None

    if data["status"] == "OK" and data.get("routes"):
        route_info = data["routes"][0]
        legs = route_info.get("legs", [])
        overview_polyline = route_info.get("overview_polyline", {}).get("points")
        if not legs:
             st.warning("Google Maps API returned OK status but no route legs.")
             return None, None, [], overview_polyline

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
        return None, None, [], None

def calculate_dac_overlap(overview_polyline, dac_gdf):
    # ... (keep existing function logic) ...
    import polyline
    from shapely.geometry import LineString, MultiPolygon, Polygon
    from shapely.errors import GEOSException

    if not overview_polyline or not isinstance(overview_polyline, str): return 0.0
    if dac_gdf is None or dac_gdf.empty: return 0.0

    try:
        decoded_coords = polyline.decode(overview_polyline)
        if not decoded_coords: return 0.0
        shapely_coords = [(lng, lat) for lat, lng in decoded_coords]
        route_line = LineString(shapely_coords)
        if not route_line.is_valid or route_line.is_empty: return 0.0

        # Ensure 'multipolygon' is the correct geometry column name in dac_gdf
        if 'multipolygon' not in dac_gdf.columns:
             st.error("DAC GeoDataFrame missing 'multipolygon' geometry column.")
             return 0.0
        valid_dac_geoms = dac_gdf[dac_gdf.geometry.is_valid].geometry # Use the geometry accessor

        total_intersection_length = 0.0
        for dac_geom in valid_dac_geoms:
            try:
                 if route_line.intersects(dac_geom):
                     intersection = route_line.intersection(dac_geom)
                     if intersection.geom_type in ['LineString', 'MultiLineString']:
                         total_intersection_length += intersection.length
            except GEOSException as intersection_error: st.warning(f"Error during intersection: {intersection_error}.")
            except Exception as general_error: st.warning(f"Unexpected error during intersection: {general_error}")

        route_total_length = route_line.length
        if route_total_length > 0:
             overlap_percentage = (total_intersection_length / route_total_length) * 100
             return max(0.0, min(overlap_percentage, 100.0))
        else: return 0.0
    except (ImportError, NameError) as import_error: st.error(f"Missing lib for DAC calc: {import_error}"); return 0.0
    except ValueError as decode_error: st.warning(f"Error decoding polyline: {decode_error}"); return 0.0
    except Exception as e: st.warning(f"Unexpected error calculating DAC overlap: {e}"); return 0.0


def get_min_temperature(location):
    # ... (keep existing placeholder function) ...
    try:
        if isinstance(location, (list, tuple)) and len(location) == 2 and all(isinstance(x, (int, float)) for x in location):
            lat = location[0]
            return 35 if lat < 40 else 45
        else: return 45
    except Exception: return 45

def convert_df_to_csv(df): # Helper for download button later
    output = io.StringIO()
    df.to_csv(output, index=False)
    return output.getvalue().encode('utf-8')

# ------------------------ Load Data (Do this once) ---------------------
@st.cache_data
def load_spatial_data():
    """
    Loads zipcode data (lat/lon) from uszips.csv and DAC spatial data.
    Returns zipcode df, zip lookup dict, and DAC GeoDataFrame (or None).
    """
    #st.write("DEBUG: Entering load_spatial_data...")
    zipcodes_df = pd.DataFrame()
    zip_lookup = {}
    # Initialize the variable that will be returned
    dac_locs_gdf = None

    try:
        # --- Load and Process New Zipcode Data ---
        #st.write("DEBUG: Attempting to load zipcode data...")
        zip_file_path = ".data/uszips.csv"
        zipcodes_df = pd.read_csv(zip_file_path, dtype={'zip': str})
        #st.write(f"DEBUG: Zipcode file read. Shape: {zipcodes_df.shape}")

        required_zip_cols = ['zip', 'lat', 'lng']
        if not all(col in zipcodes_df.columns for col in required_zip_cols):
            missing_cols_str = ", ".join(c for c in required_zip_cols if c not in zipcodes_df.columns)
            st.error(f"Zipcode file '{zip_file_path}' missing required columns: {missing_cols_str}")
        else:
            zipcodes_df['zip'] = zipcodes_df['zip'].astype(str).str.zfill(5)
            zipcodes_df.rename(columns={'lat': 'latitude', 'lng': 'longitude'}, inplace=True)
            zip_lookup = zipcodes_df.set_index('zip')[['latitude', 'longitude']].to_dict("index")
            #st.write("DEBUG: Zipcode processing complete. Lookup created.")

        # --- Load and Process DAC Data ---
        #st.write("DEBUG: Attempting to load DAC data...")
        dac_file_path = ".data/dac_file.csv"
        dac_locs_raw = pd.read_csv(dac_file_path)
        #st.write(f"DEBUG: DAC file read. Shape: {dac_locs_raw.shape}")

        dac_locs = dac_locs_raw[dac_locs_raw['DAC_Designation'] == 'Designated as DAC'].copy()
        required_dac_cols = ['the_geom', 'GEOID']
        if not all(col in dac_locs.columns for col in required_dac_cols):
             st.error(f"DAC file '{dac_file_path}' missing required columns: {required_dac_cols}")
        else:
            dac_locs = dac_locs[required_dac_cols]
            def safe_wkt_load(geom_str):
                try: return wkt.loads(geom_str)
                except Exception: return None
            dac_locs['multipolygon'] = dac_locs['the_geom'].apply(safe_wkt_load)
            dac_locs = dac_locs.dropna(subset=['multipolygon'])
            #st.write(f"DEBUG: DAC WKT loaded. Shape after dropna: {dac_locs.shape}")

            if not dac_locs.empty:
                try:
                     # *** FIX: Use dac_locs_gdf consistently ***
                     temp_gdf = gpd.GeoDataFrame(dac_locs, geometry='multipolygon', crs="EPSG:4326")
                     # Assign the potentially filtered result to the main variable
                     dac_locs_gdf = temp_gdf[temp_gdf.is_valid].copy()

                     if dac_locs_gdf.empty:
                          st.warning("No valid DAC locations after GDF processing.")
                          #st.write("DEBUG: dac_locs_gdf became empty after .is_valid check.") # DEBUG
                          # Ensure it's None if empty after filtering
                          dac_locs_gdf = None
                     #else:
                          #st.write(f"DEBUG: DAC GeoDataFrame assigned successfully. Shape: {dac_locs_gdf.shape}") # DEBUG
                except Exception as gdf_error:
                     st.error(f"Error creating DAC GeoDataFrame: {gdf_error}")
                     #st.write(f"DEBUG: Error during GDF creation: {gdf_error}") # DEBUG
                     dac_locs_gdf = None # Ensure None on error
            else:
                 st.warning("No valid DAC locations found after initial processing.")
                 #st.write("DEBUG: dac_locs DataFrame was empty before GDF creation.") # DEBUG

    except FileNotFoundError as e:
        st.error(f"Error loading data file: {e}. Ensure files exist in '.data/'")
        #st.write(f"DEBUG: Caught FileNotFoundError: {e}") # DEBUG
        return pd.DataFrame(), {}, None
    except ImportError as e:
         st.error(f"Missing required spatial libraries: {e}")
         #st.write(f"DEBUG: Caught ImportError: {e}") # DEBUG
         return zipcodes_df, zip_lookup, None
    except Exception as e:
        st.error(f"An unexpected error occurred during data loading: {e}")
        #st.write(f"DEBUG: Caught general Exception: {e}") # DEBUG
        st.error(traceback.format_exc())
        # Return current state, dac_locs_gdf might be None
        return zipcodes_df, zip_lookup, dac_locs_gdf

    # Final check before returning
    #st.write(f"DEBUG: Exiting load_spatial_data. dac_locs_gdf is None? {dac_locs_gdf is None}")
    #if dac_locs_gdf is not None:
         #st.write(f"DEBUG: Type of dac_locs_gdf: {type(dac_locs_gdf)}, Shape: {dac_locs_gdf.shape}")

    # Return the potentially updated dac_locs_gdf
    return zipcodes_df, zip_lookup, dac_locs_gdf

zipcodes_df, zip_lookup, dac_locs_gdf = load_spatial_data()

# --- Logo Loading ---
logo_path = ".data/nycsbus-small-logo.png"
encoded_logo = load_logo_as_base64(logo_path)

if encoded_logo:
    st.markdown(f"""<style> .logo-container {{ position: fixed; top: 70px; right: 30px; z-index: 1000; }} .logo-container img {{ width: 150px; }} </style> <div class="logo-container"><img src="data:image/png;base64,{encoded_logo}"></div>""", unsafe_allow_html=True)

# --- Initialize Session State (Keep all existing keys) ---
# REMOVED: if "view_mode" not in st.session_state: st.session_state.view_mode = "Main"
if "routes" not in st.session_state: st.session_state.routes = []
if "selected_route_index" not in st.session_state: st.session_state.selected_route_index = 0
if "fleet" not in st.session_state: st.session_state.fleet = [{}]
if "last_clicked_location" not in st.session_state: st.session_state.last_clicked_location = None
if "route_bus_types" not in st.session_state: st.session_state.route_bus_types = {}
if "fleet_data" not in st.session_state: st.session_state.fleet_data = None
if "ev_fleet" not in st.session_state: st.session_state.ev_fleet = None
if "results" not in st.session_state: st.session_state.results = []
if "selected_route_id_map" not in st.session_state: st.session_state.selected_route_id_map = None
if "selected_trip_type_map" not in st.session_state: st.session_state.selected_trip_type_map = "AM Trip"
if "plan_results_df" not in st.session_state: st.session_state.plan_results_df = None # Added this explicitly

# --- API Key Check (early) ---
Maps_api_key = st.secrets.get("google_maps_api_key")
if not Maps_api_key:
    st.error("⚠️ Google Maps API key not found in secrets. Route calculations and map features requiring geocoding will be disabled.")

# --- Title ---
st.title("eReady by NYCSBUS")
st.markdown("NYCSBUS has created eReady - Electric Route Evaluation and Decision Readiness - as a tool to help companies operate EV buses. Follow the steps below to evaluate your E-Route capabilities, avoiding midday charging and prioritizing disadvantaged communities. No data entered here will be saved or viewed by NYCSBUS. Please avoid providing exact pupil locations in this app.")

# --- Place this block after st.title() and before st.tabs() ---

# Optional: Add some space below the title
st.write("")

# --- Global Reset Button ---
if st.button("🔁 Reset Application & Clear All Data",
             key="reset_app_global_top",
             help="Click to clear all uploaded data, routes, and results for this session.",
             type="secondary"): # Use 'secondary' for less emphasis than primary actions

    # Get a list of all keys currently in session state
    keys_to_clear = list(st.session_state.keys())

    # Iterate through the keys and delete them
    for key in keys_to_clear:
        try:
            del st.session_state[key]
        except KeyError:
            # Should not happen if key was just listed, but handle defensively
            pass

    # Display a confirmation message
    st.success("Application has been reset. Reloading...")

    # Pause briefly so the user sees the message
    time.sleep(1.5) # Pause for 1.5 seconds

    # Rerun the script from the top with the cleared state
    st.rerun()

# Add a separator before the tabs start
st.markdown("---")
# --- End of Reset Button block ---

# --- TABS IMPLEMENTATION ---
tab1, tab2, tab3, tab4 = st.tabs([
    "1. Step 1 - Setup & Fleet",
    "2. Step 2 - Define Routes",
    "3. Step 3 - Process & Assign",
    "4. Step 4 - Review Plan & Map"
])

# =======================================
# TAB 1: Setup & Fleet (Verified Variable Names)
# =======================================
with tab1:
    st.header("Step 1: Configure Your Fleet")

    # Check if fleet is already successfully processed and saved in session state
    fleet_saved = st.session_state.get("fleet_data") is not None

    if fleet_saved:
        # If already saved, show summary, guidance, and an edit button
        st.success("✅ Fleet data saved and processed.")
        if st.session_state.get("ev_fleet") is not None:
            st.write("Processed EV Fleet Summary:")
            st.dataframe(st.session_state.ev_fleet, use_container_width=True)
        else:
            st.info("Fleet data loaded, but no specific EV fleet summary available.")
        st.info("➡️ Proceed to **Tab 2: Define Routes**.")
        if st.button("✏️ Edit Fleet", key="edit_fleet_tab1"):
            st.session_state.fleet_data = None
            st.session_state.ev_fleet = None
            st.session_state.fleet_input_method = "Manual Entry"
            st.session_state.fleet = [{}]
            st.rerun()
    else:
        # --- Fleet Input Area (if not already saved) ---
        if 'fleet_input_method' not in st.session_state:
            st.session_state.fleet_input_method = "Manual Entry"

        st.session_state.fleet_input_method = st.radio(
            "Choose fleet input method:",
            ["Manual Entry", "Upload CSV"],
            key="fleet_input_method_radio",
            horizontal=True,
            index=["Manual Entry", "Upload CSV"].index(st.session_state.fleet_input_method)
        )
        st.markdown("---")

        if st.session_state.fleet_input_method == "Manual Entry":
            st.markdown("Define the types of buses in your fleet below. Press **Save Manually Entered Fleet Data** when done.")
            fleet_container = st.container(border=True)
            with fleet_container:
                # Add button logic
                if len(st.session_state.get('fleet', [{}])) < 20:
                    if st.button("Add Another Bus Type", key="add_bus_tab1_manual"):
                        if 'fleet' not in st.session_state: st.session_state.fleet = []
                        st.session_state.fleet.append({})
                        st.rerun()

                # Headers for columns
                hdr_col1, hdr_col2, hdr_col3, hdr_col4, hdr_col5, hdr_col_remove = st.columns([2, 1, 1, 1, 1.5, 0.5])
                hdr_col1.caption("Name"); hdr_col2.caption("Powertrain"); hdr_col3.caption("Type (A/C)"); hdr_col4.caption("Quantity"); hdr_col5.caption("Battery (kWh)"); hdr_col_remove.write("")
                st.divider()

                if 'fleet' not in st.session_state or not st.session_state.fleet: st.session_state.fleet = [{}]

                indices_to_remove = [] # Define before the loop where it's potentially used
                for i, bus in enumerate(st.session_state.fleet):
                    col1, col2, col3, col4, col5, col_remove = st.columns([2, 1, 1, 1, 1.5, 0.5])
                    # ... (widget definitions for manual entry using keys like name_{i}, etc.) ...
                    with col1: name = st.text_input(f"Name_{i}", value=bus.get("Name", ""), key=f"name_{i}", label_visibility="collapsed", placeholder=f"e.g., IC Bus CE")
                    with col2: powertrain = st.selectbox(f"Powertrain_{i}", ["EV", "Gas"], index=["EV", "Gas"].index(bus.get("Powertrain", "EV")), key=f"powertrain_{i}", label_visibility="collapsed")
                    with col3: bus_type = st.selectbox(f"Type_{i}", ["A", "C"], index=["A", "C"].index(bus.get("Type", "A")), key=f"type_{i}", label_visibility="collapsed")
                    with col4: quantity = st.number_input(f"Quantity_{i}", min_value=1, value=bus.get("Quantity", 1), step=1, key=f"quantity_{i}", label_visibility="collapsed")
                    battery_size = None
                    with col5:
                        if powertrain == "EV":
                            default_battery = bus.get("Battery Capacity (kWh)")
                            if not isinstance(default_battery, (int, float)) or default_battery <= 0: default_battery = 200.0
                            battery_size = st.number_input(f"Battery_{i}", min_value=1.0, value=default_battery, key=f"battery_{i}", label_visibility="collapsed", help="Enter Battery Capacity (kWh)")
                        else: st.write("") # Placeholder
                    with col_remove:
                         if len(st.session_state.fleet) > 1:
                            if st.button("🗑️", key=f"remove_bus_{i}_manual", help=f"Remove Bus Type {i+1}"):
                                indices_to_remove.append(i) # Append to list defined *outside* the loop

                    st.session_state.fleet[i] = {
                         "Name": name, "Powertrain": powertrain, "Type": bus_type,
                         "Quantity": quantity, "Battery Capacity (kWh)": battery_size if powertrain == "EV" else None
                    }

                if indices_to_remove:
                     for index in sorted(indices_to_remove, reverse=True):
                         if 0 <= index < len(st.session_state.fleet): del st.session_state.fleet[index]
                     st.rerun()
                st.divider()

                # Save Button for Manual Entry
                if st.button("💾 Save Manually Entered Fleet Data", key="save_fleet_manual_tab1", type="primary"):
                    manual_fleet_list = st.session_state.get('fleet', [])
                    if not any(bus.get("Name") for bus in manual_fleet_list):
                        st.warning("Please provide a name for at least one bus in the manual entry.")
                    else:
                        try:
                            # Definition is here:
                            valid_fleet_data = [bus for bus in manual_fleet_list if bus.get("Name")]
                            if valid_fleet_data: # Usage is here
                                fleet_df = pd.DataFrame(valid_fleet_data) # Usage is here
                                processed_ev_fleet = process_fleet_data(fleet_df)
                                st.session_state.fleet_data = fleet_df
                                st.session_state.ev_fleet = processed_ev_fleet
                                st.success("✅ Manual fleet data processed and saved. Move onto Step 2: Define Routes.")
                            else:
                                st.warning("No valid bus data entered to save.")
                                st.session_state.ev_fleet = None; st.session_state.fleet_data = None
                        except Exception as e:
                             st.error(f"Error processing manual fleet data: {e}"); st.error(traceback.format_exc())
                             st.session_state.ev_fleet = None; st.session_state.fleet_data = None

        elif st.session_state.fleet_input_method == "Upload CSV":
            st.markdown("Upload a CSV file containing your fleet information. Press **Process Uploaded Fleet** when ready.")
            fleet_csv_container = st.container(border=True)
            with fleet_csv_container:
                uploaded_fleet_file = st.file_uploader( # Uses uploaded_fleet_file
                    "Upload Fleet CSV", type=["csv"], key="fleet_csv_uploader_tab1",
                    help="Upload a CSV with columns like Name, Powertrain, Type, Quantity, Battery Capacity (kWh)"
                )
                # ... (Expander with format guide) ...
                with st.expander("Fleet CSV Format Guide & Example"):
                     st.markdown("""
                        **Required Columns:** Name, Powertrain (EV or Gas), Type (A or C), Quantity, Battery Capacity (kWh)
                        
                        | Name                            | Powertrain | Type | Quantity | Battery Capacity (kWh) |
                        |---------------------------------|------------|------|----------|------------------------|
                        | Bus 1                           | EV         | A    | 10       | 88                     |
                        | Bus 2                           | EV         | C    | 5        | 130                    |
                    """)

                if uploaded_fleet_file is not None:
                    # Button to trigger processing
                    if st.button("⚙️ Process Uploaded Fleet", key="process_fleet_csv_tab1", type="primary"):
                        try:
                            # Read the uploaded CSV file into a pandas DataFrame
                            df_upload = pd.read_csv(uploaded_fleet_file)

                            # Display a preview of the first few rows
                            st.write("Preview of Uploaded Data:")
                            st.dataframe(df_upload.head())

                            # --- Validation Logic ---
                            required_cols = ['Name', 'Powertrain', 'Type', 'Quantity'] # Core required columns
                            # Clean column names (remove leading/trailing whitespace)
                            actual_cols = [col.strip() for col in df_upload.columns]
                            df_upload.columns = actual_cols # Use cleaned names

                            missing_cols = [col for col in required_cols if col not in actual_cols]
                            if missing_cols:
                                # Fatal error if required columns are missing, stop processing here
                                st.error(f"Uploaded CSV is missing required columns: {', '.join(missing_cols)}. Please check the format guide and re-upload.")
                                # Clear potentially invalid state
                                st.session_state.fleet_data = None
                                st.session_state.ev_fleet = None
                            else:
                                # Proceed with detailed validation if required columns exist
                                errors = [] # Initialize list to collect validation errors

                                try:
                                    # --- Data Cleaning and Detailed Validation ---
                                    df_upload['Name'] = df_upload['Name'].astype(str).str.strip()
                                    df_upload['Powertrain'] = df_upload['Powertrain'].astype(str).str.strip().str.upper()
                                    df_upload['Type'] = df_upload['Type'].astype(str).str.strip().str.upper()

                                    # Validate 'Powertrain' values
                                    invalid_powertrains = df_upload[~df_upload['Powertrain'].isin(['EV', 'GAS'])] # Allow GAS or EV
                                    if not invalid_powertrains.empty:
                                        errors.append(f"Invalid Powertrain values found: {invalid_powertrains['Powertrain'].unique().tolist()}. Use 'EV' or 'Gas'.")

                                    # Validate 'Type' values
                                    invalid_types = df_upload[~df_upload['Type'].isin(['A', 'C'])]
                                    if not invalid_types.empty:
                                        errors.append(f"Invalid Type values found: {invalid_types['Type'].unique().tolist()}. Use 'A' or 'C'.")

                                    # Validate and convert 'Quantity'
                                    df_upload['Quantity'] = pd.to_numeric(df_upload['Quantity'], errors='coerce') # Convert, turn errors into NaN
                                    invalid_quantities = df_upload[df_upload['Quantity'].isna() | (df_upload['Quantity'] <= 0)]
                                    if not invalid_quantities.empty:
                                         errors.append("Found rows with missing, invalid, or zero Quantity.")
                                    # Fill NaN with 0 after check, then convert to int - assumes 0 is acceptable if not invalid
                                    df_upload['Quantity'] = df_upload['Quantity'].fillna(0).astype(int)


                                    # Validate and convert 'Battery Capacity (kWh)'
                                    if 'Battery Capacity (kWh)' not in actual_cols:
                                         df_upload['Battery Capacity (kWh)'] = None # Add column as None if missing entirely
                                         errors.append("Column 'Battery Capacity (kWh)' was missing; added but check EV entries.")
                                    else:
                                         # Convert to numeric, coercing errors. Keep as float for potential decimals.
                                         df_upload['Battery Capacity (kWh)'] = pd.to_numeric(df_upload['Battery Capacity (kWh)'], errors='coerce')

                                    # Ensure non-EVs have None or NaN battery capacity before checking EVs
                                    df_upload.loc[df_upload['Powertrain'] != 'EV', 'Battery Capacity (kWh)'] = None

                                    # Check if EVs have missing or invalid battery info AFTER setting non-EVs to None
                                    missing_battery_evs = df_upload[(df_upload['Powertrain'] == 'EV') & (df_upload['Battery Capacity (kWh)'].isna() | (df_upload['Battery Capacity (kWh)'] <= 0))]
                                    if not missing_battery_evs.empty:
                                         errors.append("Found EV buses with missing or invalid (>0) 'Battery Capacity (kWh)'.")

                                except Exception as validation_error:
                                    # Catch errors during the validation/conversion process itself
                                    errors.append(f"An unexpected error occurred during data validation: {validation_error}")
                                    st.error(traceback.format_exc()) # Log for debugging

                                # --- Handle Validation Results ---
                                if errors:
                                     # If any errors were found in the 'errors' list:
                                     st.error("Errors found in uploaded CSV data:")
                                     for error in errors:
                                         st.error(f"- {error}") # Display each specific error

                                     st.warning("Please correct the CSV file based on the errors listed above and re-upload.")

                                     # Clear potentially invalid state variables
                                     st.session_state.fleet_data = None
                                     st.session_state.ev_fleet = None
                                else:
                                     # --- If Validation Passes (no errors in the list) ---
                                     st.success("CSV validation passed.")

                                     # Filter out rows with no Name as a final safety check
                                     fleet_df_validated = df_upload[df_upload['Name'].ne('')].copy() # .ne('') is robust

                                     if fleet_df_validated.empty:
                                         st.warning("No valid fleet data rows found after processing (check for empty names).")
                                         st.session_state.fleet_data = None
                                         st.session_state.ev_fleet = None
                                     else:
                                         # Use the existing processing function on the validated DataFrame
                                         processed_ev_fleet = process_fleet_data(fleet_df_validated)

                                         # Store results in session state
                                         st.session_state.fleet_data = fleet_df_validated # Store the validated df used
                                         st.session_state.ev_fleet = processed_ev_fleet

                                         st.success("✅ Uploaded fleet data processed and saved. Move onto Step 2: Define Routes.")
                                         # Let Streamlit's natural rerun update the view to show summary

                        # --- Exception Handling for file reading/parsing ---
                        except pd.errors.EmptyDataError:
                             st.error("The uploaded CSV file appears to be empty.")
                             st.session_state.fleet_data = None; st.session_state.ev_fleet = None
                        except Exception as e:
                             st.error(f"An error occurred reading or processing the CSV file: {e}")
                             st.error(traceback.format_exc())
                             st.error("Please ensure the file is a valid CSV and matches the expected format.")
                             st.session_state.fleet_data = None; st.session_state.ev_fleet = None
# =======================================
# TAB 2: Define Routes (Complete Code)
# =======================================
with tab2:
    st.header("Step 2: Define Your Routes")

    # Check if fleet is saved before allowing route definition
    if st.session_state.get("fleet_data") is None:
        st.warning("⬅️ Please configure and save your fleet in **Tab 1: Setup & Fleet** before defining routes.")
        # Optionally disable the entire tab content if desired, but warning is usually sufficient
    else:
        # --- Fleet Data Loaded Confirmation ---
        st.success("Choose a method below to define routes.")

        # --- Input Method Selection ---
        # Use session state to remember the choice, default to Map
        if 'input_mode' not in st.session_state:
            st.session_state.input_mode = "Interactive Map"

        st.session_state.input_mode = st.radio(
            "How would you like to define routes?",
            ["Interactive Map", "Upload CSV"],
            horizontal=True,
            key="route_input_mode_tab2", # Unique key
            index=["Interactive Map", "Upload CSV"].index(st.session_state.input_mode) # Keep selection sticky
            )
        st.markdown("---") # Separator

        # --- Display Input Method based on Radio Choice ---
        if st.session_state.input_mode == "Interactive Map":
            st.subheader("Define Routes Interactively")
            st.markdown("Use the map below to define route stops. Select 'Depot', 'Pickup', or 'Dropoff', then click on the map. Assign a unique Route ID for each route.")

            # Check for API key before showing map functionality that relies on it
            if not Maps_api_key:
                 st.error("⚠️ Google Maps API Key missing in secrets. Interactive map features relying on geocoding may be limited or disabled.")
                 # Optionally, you could completely hide the map section here
            else:
                 try:
                     # Ensure the interactive map logic file exists and import the function
                     from interactive_map_logic import handle_map_route_input
                     # Execute the map handling logic
                     # This function is assumed to modify st.session_state.routes directly
                     handle_map_route_input(st, folium, st_folium, zipcodes_df, zip_lookup)

                     # --- Static Guidance for Map Input ---
                     # This message appears as long as the map mode is selected and loads correctly
                     st.info("ℹ️ Once routes are defined using the map tools above, proceed to **Tab 3: Process & Assign** to calculate details.")

                 except ImportError:
                     st.error("Critical Error: Could not find the required 'interactive_map_logic.py' file. Interactive map disabled.")
                 except Exception as e:
                     st.error(f"An error occurred while loading the interactive map logic: {e}")
                     st.error(traceback.format_exc()) # Log detailed error for debugging

        elif st.session_state.input_mode == "Upload CSV":
            st.subheader("Upload Your Route CSV")
            uploaded_file = st.file_uploader("Upload CSV file", type=["csv"], key="csv_uploader_tab2")

            # Display format instructions using Markdown Table
            with st.expander("CSV Format Guide & Example", expanded=False):
                 st.markdown("""
                    **Required Columns:**
                    - `Route`: Route ID (e.g., R101)
                    - `Location Type`: Must be `Depot`, `Pickup`, or `Dropoff`.
                    - `Address`: Full street address for geocoding.
                    - `Sequence Number`: Order of stops (Depot=0, then 1, 2, 3...).
                    - **Optional Column:** `Time`: School Bell Time for the *first* `Dropoff` location of that route (format `HH:MM`, e.g., `08:00`).

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
                 st.info("🔒 Uploaded files are processed in memory only. Click 'Process CSV' to load.")

            if uploaded_file is not None:
                process_csv_disabled = False # Default to enabled
                preview_df = None # Initialize preview dataframe

                try:
                    # Read just for preview and column check first
                    preview_df = pd.read_csv(uploaded_file)
                    st.write("Preview of Uploaded CSV:")
                    st.dataframe(preview_df.head())

                    # Check required columns based on preview
                    required_cols = ['Route', 'Location Type', 'Address', 'Sequence Number']
                    actual_cols_preview = [col.strip() for col in preview_df.columns]
                    missing_cols_preview = [col for col in required_cols if col not in actual_cols_preview]

                    if missing_cols_preview:
                         st.error(f"Preview shows CSV is missing required columns: {', '.join(missing_cols_preview)}. Please check the format before processing.")
                         process_csv_disabled = True
                    elif not Maps_api_key:
                         st.error("⚠️ Google Maps API Key missing. Cannot geocode addresses from CSV.")
                         process_csv_disabled = True
                    # else: process_csv_disabled remains False

                    # Reset file pointer before potentially reading again in button click
                    uploaded_file.seek(0)

                except pd.errors.EmptyDataError:
                     st.error("The uploaded CSV file is empty.")
                     process_csv_disabled = True # Disable button if file is empty
                except Exception as e:
                     st.error(f"Error reading or previewing CSV: {e}")
                     st.error(traceback.format_exc())
                     process_csv_disabled = True # Disable button on other read errors


                # Button to process the CSV - check disabled status
                if st.button("Process CSV", key="process_csv_button_tab2", disabled=process_csv_disabled):
                    try:
                        # Reread the file inside the button click for actual processing
                        uploaded_file.seek(0) # Ensure reading from the start
                        df_upload = pd.read_csv(uploaded_file)
                        df_upload.columns = [col.strip() for col in df_upload.columns] # Clean column names

                        with st.spinner("Geocoding addresses... This may take time."):
                            route_dict = {}
                            geocoding_failures = []

                            # Sort by Route and Sequence Number for correct processing order
                            df_upload = df_upload.sort_values(by=['Route', 'Sequence Number'])

                            for _, row in df_upload.iterrows():
                                # Standardize data extraction
                                route_id = str(row['Route']).strip() if pd.notna(row['Route']) else None
                                location_type = str(row['Location Type']).strip().capitalize() if pd.notna(row['Location Type']) else None
                                address = str(row['Address']).strip() if pd.notna(row['Address']) else None
                                time_str = row.get('Time') # Use .get for optional column
                                sequence = pd.to_numeric(row['Sequence Number'], errors='coerce') # Handle non-numeric sequence

                                # Input validation
                                if not route_id or not location_type or not address or pd.isna(sequence):
                                     st.warning(f"Skipping row with missing Route ID, Type, Address, or invalid Sequence: {row.to_dict()}")
                                     continue
                                sequence = int(sequence) # Convert to int after validation
                                if location_type not in ["Depot", "Pickup", "Dropoff"]:
                                    st.warning(f"Skipping row with invalid Location Type '{location_type}' for Route {route_id}. Use 'Depot', 'Pickup', or 'Dropoff'.")
                                    continue

                                try:
                                    # Simple rate limiting for geocoding
                                    time.sleep(0.05) # 50ms delay

                                    # --- Geocoding API Call ---
                                    geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
                                    params = {"address": address, "key": Maps_api_key}
                                    response = requests.get(geocode_url, params=params, timeout=10)
                                    response.raise_for_status() # Check for HTTP errors
                                    data = response.json()

                                    if data["status"] == "OK" and data.get("results"):
                                         # Extract coordinates
                                         location = data["results"][0]["geometry"]["location"]
                                         coords = (location["lat"], location["lng"])

                                         # Initialize route if not exists
                                         if route_id not in route_dict:
                                             route_dict[route_id] = {
                                                 "route_id": route_id, "depot": None,
                                                 "pickups": [], # Store as list of dicts: {'location': coords, 'sequence': seq}
                                                 "dropoffs": [], # Store as list of dicts: {'location': coords, 'sequence': seq, 'bell_time': time}
                                                 "csv_source": True # Flag origin
                                             }

                                         # --- Time Parsing (only for the first dropoff encountered for this route) ---
                                         parsed_time = None
                                         is_first_dropoff = (location_type == "Dropoff" and not any(d.get('bell_time') for d in route_dict[route_id]["dropoffs"]))

                                         if pd.notna(time_str) and isinstance(time_str, str) and time_str.strip() and is_first_dropoff:
                                            time_str_cleaned = time_str.strip()
                                            try:
                                                parsed_time = datetime.datetime.strptime(time_str_cleaned, "%H:%M").time()
                                            except ValueError:
                                                 st.warning(f"Route {route_id}: Invalid time format for address '{address}': '{time_str}'. Expected HH:MM. Bell time ignored.")

                                         # --- Assign to Route Structure ---
                                         if location_type == "Depot":
                                             if route_dict[route_id]["depot"] is None:
                                                 route_dict[route_id]["depot"] = coords
                                             else:
                                                  st.warning(f"Route {route_id}: Multiple Depot locations found. Using first at sequence {sequence}.")
                                         elif location_type == "Pickup":
                                             route_dict[route_id]["pickups"].append({"location": coords, "sequence": sequence})
                                         elif location_type == "Dropoff":
                                              route_dict[route_id]["dropoffs"].append({
                                                 "location": coords, "sequence": sequence,
                                                 "bell_time": parsed_time if is_first_dropoff else None # Store time only if it's the first dropoff
                                                 })
                                    else:
                                        # Handle geocoding API errors (ZERO_RESULTS, OVER_QUERY_LIMIT, etc.)
                                        st.warning(f"Geocoding failed for Route {route_id}, Address '{address}': {data.get('status', 'Unknown Error')}")
                                        geocoding_failures.append(f"Route {route_id}: {address} ({data.get('status', 'Failed')})")

                                except requests.exceptions.RequestException as req_err:
                                     st.error(f"Network error geocoding '{address}': {req_err}")
                                     geocoding_failures.append(f"Route {route_id}: {address} (Network Error)")
                                     # Consider adding a retry mechanism or stopping processing if too many errors occur
                                except Exception as geocode_error:
                                     st.error(f"Unexpected error geocoding '{address}': {geocode_error}")
                                     st.error(traceback.format_exc()) # Log full trace for debugging
                                     geocoding_failures.append(f"Route {route_id}: {address} (Processing Error)")

                            # --- Post-Processing after loop ---
                            processed_routes = []
                            for route_id, data in route_dict.items():
                                # Sort pickups and dropoffs by sequence number stored during processing
                                data["pickups"] = sorted(data["pickups"], key=lambda x: x['sequence'])
                                data["dropoffs"] = sorted(data["dropoffs"], key=lambda x: x['sequence'])
                                processed_routes.append(data)

                            # Replace existing routes in session state - typical for CSV upload
                            st.session_state.routes = processed_routes

                            # --- Success Message & Specific Guidance ---
                            st.success(f"CSV processed. {len(processed_routes)} routes loaded.")
                            if geocoding_failures:
                                 st.warning("Some addresses could not be geocoded:", icon="⚠️")
                                 st.json(geocoding_failures) # Use json for better list display
                            # Explicit guidance after successful processing
                            st.info("➡️ Routes loaded successfully. Proceed to **Tab 3: Process & Assign**.")
                            # Let natural rerun update the overview table below

                    except pd.errors.EmptyDataError:
                         st.error("The uploaded CSV file is empty.")
                    except Exception as e:
                         st.error(f"Error processing CSV after clicking button: {e}")
                         st.error(traceback.format_exc())


    # --- Display Defined Routes Overview (common section, shown if routes exist) ---
    if st.session_state.get("routes"):
        st.markdown("---") # Separator before overview
        st.subheader("Defined Routes Overview")
        routes_summary = []
        for r in st.session_state.routes:
            # Build the summary dictionary for each route
             routes_summary.append({
                "Route ID": r.get("route_id", "N/A"),
                "Source": "CSV" if r.get("csv_source") else "Map", # Indicate source
                "Depot": "Yes" if r.get("depot") else "No",
                "Pickups": len(r.get("pickups", [])),
                "Dropoffs": len(r.get("dropoffs", [])),
                # Safely get bell time from the first dropoff if it exists
                "Bell Time": r['dropoffs'][0]['bell_time'].strftime("%H:%M")
                             if r.get('dropoffs') and len(r['dropoffs']) > 0 and r['dropoffs'][0].get('bell_time')
                             else "N/A"
            })
        # Display the summary table
        st.dataframe(pd.DataFrame(routes_summary), use_container_width=True)
# =======================================
# TAB 3: Process & Assign (Revised Flow)
# =======================================
with tab3:
    st.header("Step 3: Process Routes & Assign Bus Types")

    # --- Section A: Calculate Route Details ---
    st.subheader("A. Calculate Route Details")
    st.markdown("Click the button below to calculate distances, durations, and DAC overlap using the Google Maps API based on your defined routes in Tab 2.")

    # Prerequisites Check
    fleet_ok = st.session_state.get("ev_fleet") is not None and not st.session_state.ev_fleet.empty
    routes_ok = st.session_state.get("routes") is not None and len(st.session_state.routes) > 0
    api_ok = Maps_api_key is not None
    results_exist = st.session_state.get("results") is not None and len(st.session_state.results) > 0

    process_ready = fleet_ok and routes_ok and api_ok # Basic readiness check

    # Display status messages based on checks
    if not fleet_ok: st.warning("⬅️ Please configure and save your EV fleet in **Tab 1**.")
    if not routes_ok: st.warning("⬅️ Please define routes in **Tab 2**.")
    if not api_ok: st.error("⚠️ Google Maps API Key missing in secrets. Route processing is disabled.")

    # Only allow processing if prerequisites met AND results don't already exist
    allow_processing = process_ready and not results_exist

    if results_exist:
         st.success(f"✅ Route details previously calculated for {len(st.session_state.results)} route(s). Proceed to assigning bus types below.")
         # Button is implicitly disabled because allow_processing is False

    # Calculation Button - Enabled only if ready and not already processed
    if st.button("⚙️ Process Routes for Electrification", disabled=not allow_processing, type="primary", key="process_electrification_tab3"):
         if process_ready: # Double-check prerequisites before running
             # --- (Route Calculation Logic - Full code from previous versions) ---
             results_list = []
             routes_to_process = st.session_state.routes
             progress_bar = st.progress(0, text="Starting route calculations...")
             total_routes = len(routes_to_process)
             api_errors_encountered = False

             for i, route in enumerate(routes_to_process):
                 route_id = route.get("route_id", f"Route_{i+1}")
                 progress_text = f"Processing Route: {route_id} ({i+1}/{total_routes})"
                 progress_bar.progress((i + 1) / total_routes, text=progress_text)

                 if not route.get("depot"): st.warning(f"Route {route_id}: Skip - Missing Depot."); continue
                 if not route.get("dropoffs"): st.warning(f"Route {route_id}: Skip - Missing Dropoffs."); continue

                 # Initialize feasibility dict for this route
                 feasibility_result = {
                    "Route ID": route_id, "AM Distance (miles)": None, "AM Duration (min)": None, "AM Overview Polyline": None,
                    "PM Distance (miles)": None, "PM Duration (min)": None, "PM Overview Polyline": None,
                    "Percent in DAC": 0.0, "Suggested Depot Departure Time": None,
                    "First School Bell Time": None, "Drive Time to First School (min)": None, "Leg Details": []
                 }

                 try:
                     # --- AM Route Calculation ---
                     am_origin = route["depot"]
                     if not route["dropoffs"] or not route["dropoffs"][0].get("location"): st.warning(f"Route {route_id}: Skip - Invalid first dropoff."); continue
                     am_destination = route["dropoffs"][0]["location"]
                     am_waypoints_data = route.get("pickups", []) + route.get("dropoffs", [])[1:]
                     am_waypoints = [wp.get("location") for wp in am_waypoints_data if wp.get("location")]
                     first_bell_time = route["dropoffs"][0].get("bell_time") # Already parsed datetime.time or None

                     am_distance, am_duration, am_leg_details, am_polyline = get_route_distance(Maps_api_key, am_origin, am_waypoints, am_destination, first_bell_time)

                     if am_distance is not None and am_duration is not None:
                         feasibility_result["AM Distance (miles)"] = round(am_distance, 2)
                         feasibility_result["AM Duration (min)"] = round(am_duration, 1)
                         feasibility_result["AM Overview Polyline"] = am_polyline
                         feasibility_result["Leg Details"] = am_leg_details # Store leg details
                         feasibility_result["Drive Time to First School (min)"] = round(am_duration, 1)
                         if first_bell_time:
                             feasibility_result["First School Bell Time"] = first_bell_time.strftime("%I:%M %p")
                             try:
                                 arrival_dt = datetime.datetime.combine(datetime.date.today(), first_bell_time)
                                 buffer_minutes = 15
                                 departure_dt = arrival_dt - datetime.timedelta(minutes=am_duration + buffer_minutes)
                                 feasibility_result["Suggested Depot Departure Time"] = departure_dt.time().strftime("%I:%M %p")
                             except Exception as e: st.warning(f"Route {route_id}: Error calculating departure time: {e}")
                         if am_polyline and dac_locs_gdf is not None: feasibility_result["Percent in DAC"] = round(calculate_dac_overlap(am_polyline, dac_locs_gdf), 2)
                     else:
                         st.warning(f"Route {route_id}: Failed AM route details calculation (check API key/quota?).")
                         api_errors_encountered = True

                     # --- PM Route Calculation ---
                     if not route["dropoffs"] or not route["dropoffs"][-1].get("location"): st.warning(f"Route {route_id}: Skip PM - Invalid last dropoff.");
                     else:
                          pm_origin = route["dropoffs"][-1]["location"]
                          pm_destination = route["depot"]
                          pm_waypoints_data = route.get("dropoffs", [])[:-1] + route.get("pickups", [])
                          pm_waypoints_data_sorted = sorted(pm_waypoints_data, key=lambda x: x.get('sequence', 0), reverse=True)
                          pm_waypoints = [wp.get("location") for wp in pm_waypoints_data_sorted if wp.get("location")]
                          pm_distance, pm_duration, _, pm_polyline = get_route_distance(Maps_api_key, pm_origin, pm_waypoints, pm_destination, None) # No time needed for PM estimate

                          if pm_distance is not None and pm_duration is not None:
                             feasibility_result["PM Distance (miles)"] = round(pm_distance, 2)
                             feasibility_result["PM Duration (min)"] = round(pm_duration, 1)
                             feasibility_result["PM Overview Polyline"] = pm_polyline
                          else:
                             st.warning(f"Route {route_id}: Failed PM route details calculation (check API key/quota?).")
                             api_errors_encountered = True

                 except Exception as route_calc_error:
                      st.error(f"Route {route_id}: Unexpected error during calculation: {route_calc_error}")
                      st.error(traceback.format_exc()) # Log detailed error

                 # Append result for this route, even if parts failed
                 results_list.append(feasibility_result)

             # After processing all routes
             progress_bar.empty() # Clear progress bar
             st.session_state.results = results_list # Store results in session state

             if results_list:
                  st.success(f"Route detail processing complete for {len(results_list)} route(s).")
                  if api_errors_encountered: st.warning("Some route calculations may have failed. Check warnings above and API key status.")
                  st.info("⬇️ Proceed to assigning bus types below.")
                  # RERUN is needed here to make the assignment section (which depends on results) appear correctly
                  st.rerun()
             else:
                  st.warning("Route processing finished, but no results were generated.")
         else:
              # This case should ideally not be reached due to disabled button, but as fallback:
              st.error("Cannot process routes. Please ensure prerequisites in Tab 1 and Tab 2 are met.")


    # --- Section B: Bus Type Assignment (Show only if results exist) ---
    if st.session_state.get("results"): # Check again in case rerun happened
        st.markdown("---")
        st.subheader("B. Assign Bus Type to Each Route")
        st.markdown('Select the type of bus (**Type A** or **Type C**) required for each route. This selection impacts the final feasibility calculation.')

        if "route_bus_types" not in st.session_state: st.session_state.route_bus_types = {}
        routes_with_results = st.session_state.results

        # Use columns for assignment layout
        num_assign_cols = 3 # Adjust number of columns as needed
        assign_cols = st.columns(num_assign_cols)
        col_idx = 0

        for result_data in routes_with_results:
             route_id = result_data.get("Route ID")
             if not route_id: continue # Skip if result has no ID

             container = assign_cols[col_idx % num_assign_cols].container(border=True)
             with container:
                 # Get current selection or default to 'A'
                 current_selection = st.session_state.route_bus_types.get(route_id, "A")
                 valid_types = ["A", "C"]
                 if current_selection not in valid_types: current_selection = "A" # Ensure valid default
                 try: default_index = valid_types.index(current_selection)
                 except ValueError: default_index = 0

                 # Radio button for selection
                 selected_type = st.radio(
                     f"**{route_id}** Bus Type:", # Use bold route ID as label
                     valid_types,
                     index=default_index,
                     key=f"route_bus_type_{route_id}_tab3", # Unique key for widget state
                     horizontal=True,
                 )
                 # Update session state immediately when radio button changes
                 st.session_state.route_bus_types[route_id] = selected_type

                 # Display route distance for context
                 am_dist_str = f"{result_data.get('AM Distance (miles)', 'N/A'):.1f}" if result_data.get('AM Distance (miles)') is not None else 'N/A'
                 pm_dist_str = f"{result_data.get('PM Distance (miles)', 'N/A'):.1f}" if result_data.get('PM Distance (miles)') is not None else 'N/A'
                 st.caption(f"AM: {am_dist_str} mi / PM: {pm_dist_str} mi")

             col_idx += 1 # Increment column index

        # --- Section C: Generate Plan ---
        st.markdown("---")
        st.subheader("C. Generate Electrification Plan")
        st.markdown("Click below to calculate which routes are feasible with your selected EV fleet and bus type assignments, assuming no midday charging.")

        # Button to generate the final plan
        if st.button("⚡ Show Me the Plan!", key="show_plan_button_tab3", type="primary"):
            _calculation_successful = False # Flag for success
            st.session_state.plan_results_df = None # Clear previous results first

            # --- (Plan Generation Logic - Full code from previous versions) ---
            try:
                # Ensure EV fleet data is available (should be if we got here)
                ev_fleet = st.session_state.ev_fleet
                plan_results_list = []

                # Iterate through route calculation results
                for result_data in st.session_state.results:
                     route_id = result_data.get("Route ID")
                     if not route_id: continue # Skip if missing route ID

                     # Extract necessary data
                     suggested_time = result_data.get("Suggested Depot Departure Time", "N/A")
                     percent_in_dac = result_data.get("Percent in DAC", 0.0)
                     am_miles = result_data.get("AM Distance (miles)", 0.0) or 0.0
                     pm_miles = result_data.get("PM Distance (miles)", 0.0) or 0.0
                     round_trip = am_miles + pm_miles

                     # Get the bus type assigned by the user for this route (defaulting if somehow missed)
                     selected_type = st.session_state.route_bus_types.get(route_id, "A")

                     # Filter the EV fleet to matching type
                     matching_fleet = ev_fleet[ev_fleet["Type"] == selected_type].copy()

                     # Helper function to find eligible buses based on range
                     def get_eligible_names(df, range_col_name, required_range):
                         if range_col_name in df.columns:
                             # Ensure range comparison handles potential non-numeric data gracefully
                             eligible_df = df[pd.to_numeric(df[range_col_name], errors='coerce').fillna(0) >= required_range]
                             names = eligible_df["Name"].dropna().unique()
                             return ", ".join(names) if len(names) > 0 else "None" # Return "None" string if empty
                         return "N/A" # Column missing

                     # Calculate eligibility for different weather conditions
                     cold_buses = get_eligible_names(matching_fleet, "Cold Weather Range", round_trip)
                     avg_buses = get_eligible_names(matching_fleet, "Average Weather Range", round_trip)
                     warm_buses = get_eligible_names(matching_fleet, "Warm Weather Range", round_trip)

                     # Append results for this route to the plan list
                     plan_results_list.append({
                         "Route ID": route_id, "Type Required": selected_type, "Round Trip (mi)": round(round_trip, 2),
                         "Eligible Buses < 50°F": cold_buses, "Eligible Buses 50–70°F": avg_buses, "Eligible Buses 70°F+": warm_buses,
                         "Percent in DAC": percent_in_dac, "Suggested Departure Time": suggested_time
                     })

                # Process the collected plan results list
                if plan_results_list:
                    plan_df = pd.DataFrame(plan_results_list)

                    # --- (Apply Classification and Sorting Logic - Same as before) ---
                    def classify_eligibility(row):
                         in_dac = pd.to_numeric(row.get("Percent in DAC"), errors='coerce')
                         dac_preference = (in_dac is not None and in_dac > 70)
                         # Check eligibility based on non-"None" and non-"N/A" strings
                         cold_ok = bool(row.get("Eligible Buses < 50°F") and row["Eligible Buses < 50°F"] not in ["None", "N/A"])
                         mild_ok = bool(row.get("Eligible Buses 50–70°F") and row["Eligible Buses 50–70°F"] not in ["None", "N/A"])
                         warm_ok = bool(row.get("Eligible Buses 70°F+") and row["Eligible Buses 70°F+"] not in ["None", "N/A"])
                         if dac_preference and cold_ok: return "Preferred - All Weather"
                         elif cold_ok: return "OK in All Weather"
                         elif mild_ok: return "OK > 50°F Weather"
                         elif warm_ok: return "OK > 70°F Weather"
                         else: return "NOT FEASIBLE (No Bus)"
                    eligibility_order = { "Preferred - All Weather": 0, "OK in All Weather": 1, "OK > 50°F Weather": 2, "OK > 70°F Weather": 3, "NOT FEASIBLE (No Bus)": 4 }
                    plan_df["EV Eligibility"] = plan_df.apply(classify_eligibility, axis=1)
                    plan_df["Eligibility Rank"] = plan_df["EV Eligibility"].map(eligibility_order)
                    plan_df = plan_df.sort_values(by=["Eligibility Rank", "Route ID"]).drop(columns=["Eligibility Rank"])
                    plan_df.rename(columns={'Type Required': 'Bus Type', 'Percent in DAC': '% in Disadvantaged Community'}, inplace=True)
                    final_cols_order = [ # Define final column order
                       'Route ID', 'Bus Type', 'EV Eligibility', 'Suggested Departure Time', '% in Disadvantaged Community', 'Round Trip (mi)',
                       'Eligible Buses < 50°F', 'Eligible Buses 50–70°F', 'Eligible Buses 70°F+' ]
                    # Reorder columns, handling potential missing ones defensively (though validation should prevent this)
                    plan_df_display = plan_df[[col for col in final_cols_order if col in plan_df.columns]]

                    # *** Store successful result in session state ***
                    st.session_state.plan_results_df = plan_df_display
                    _calculation_successful = True

                    # --- UPDATED GUIDANCE ---
                    # Display success message IN Tab 3, guiding user to Tab 4
                    st.success("✅ Plan generated successfully!")
                    st.info("➡️ Please click on **Tab 4: Review Plan & Map** above to view the results.")
                    # NO explicit st.rerun() here. Let the natural button rerun happen. User must click Tab 4.

                else: # No results in plan_results_list
                    st.info("No route results available to generate a plan.")

            except Exception as e:
                 st.error(f"An error occurred while generating the plan: {e}")
                 st.error(traceback.format_exc()) # Show detailed error
                 _calculation_successful = False
                 # Ensure plan results are cleared on error
                 st.session_state.plan_results_df = None
# Assuming necessary imports like streamlit, pandas, folium, polyline, Icon are done globally
# Assuming plan_df, st.session_state.routes, st.session_state.results,
# st.session_state.ev_fleet, zip_lookup, zipcodes_df etc. are available

with tab4:
    st.header("Step 4: Review Electrification Plan & Route Map")

    # Check if the final plan results DataFrame exists in session state
    if st.session_state.get("plan_results_df") is None or st.session_state.plan_results_df.empty:
        # If not, guide the user back to Tab 3
        st.warning("⬅️ Please generate the plan in **Tab 3: Process & Assign** first.")
    else:
        # Plan exists, proceed with displaying results
        plan_df = st.session_state.plan_results_df # Use the saved plan df

        # --- Display Summary Tables ---
        st.subheader("🚌 EV Route Feasibility Summary")
        st.dataframe(plan_df, use_container_width=True)

        st.subheader("⚡ EV Fleet Range Summary")
        # Ensure ev_fleet data exists before displaying its summary
        if st.session_state.get("ev_fleet") is not None:
             st.dataframe(st.session_state.ev_fleet, use_container_width=True)
        else:
             # This might happen if Tab 1 failed or fleet had no EVs
             st.warning("EV Fleet data not found (needed for summary). Please check Tab 1.")


        # --- Map Visualization Section ---
        st.markdown("---") # Separator
        st.subheader("🗺️ Route Map Visualization")

        # Check if the prerequisite route calculation results exist
        if not st.session_state.get("results"):
             st.error("Route results data (containing map polylines) is missing. Please re-process routes in Tab 3.")
        else:
             # Get the list of Route IDs present in the final plan
             route_ids_in_plan = plan_df['Route ID'].tolist()
             if not route_ids_in_plan:
                 # Handle case where plan exists but has no routes (unlikely but possible)
                 st.info("No routes found in the generated plan to display on map.")
             else:
                 # --- Map Controls (Route and Trip Type Selection) ---
                 # Ensure selection state exists and is valid, default to first route if not
                 current_selection = st.session_state.get("selected_route_id_map")
                 if current_selection not in route_ids_in_plan:
                     st.session_state.selected_route_id_map = route_ids_in_plan[0] # Default to first

                 # Use columns for controls layout
                 col1, col2 = st.columns([1, 1])
                 with col1:
                    # Find index safely for selectbox default
                    try: current_index = route_ids_in_plan.index(st.session_state.selected_route_id_map)
                    except ValueError: current_index = 0 # Default to 0 if ID not found (shouldn't happen)

                    # Route ID selector dropdown
                    st.session_state.selected_route_id_map = st.selectbox(
                        "Select Route ID to Display:",
                        options=route_ids_in_plan,
                        key="map_route_selector_tab4", # Unique key
                        index=current_index
                    )
                 with col2:
                     # Trip type selector radio buttons
                     trip_options = ["AM Trip", "PM Trip", "Round Trip"]
                     # Default to "AM Trip" if state is missing or invalid
                     current_trip_type = st.session_state.get("selected_trip_type_map", "AM Trip")
                     if current_trip_type not in trip_options: current_trip_type = "AM Trip"
                     try: trip_index = trip_options.index(current_trip_type)
                     except ValueError: trip_index = 0 # Default to AM Trip index

                     st.session_state.selected_trip_type_map = st.radio(
                        "Select Trip Type:",
                        options=trip_options,
                        key="map_trip_type_selector_tab4", # Unique key
                        index=trip_index,
                        horizontal=True
                     )

                 # --- Find Selected Route Data ---
                 # Get the original route definition (for stops)
                 selected_route_original_data = next((r for r in st.session_state.get("routes", []) if r.get("route_id") == st.session_state.selected_route_id_map), None)
                 # Get the calculated feasibility results (for polylines, distances etc.)
                 selected_feasibility_data = next((res for res in st.session_state.get("results", []) if res.get("Route ID") == st.session_state.selected_route_id_map), None)

                 # Proceed only if both original route data and feasibility data were found
                 if selected_route_original_data and selected_feasibility_data:
                    # Use columns for Map and Info Panel layout
                    map_col, info_col = st.columns([3, 2]) # Adjust ratio as needed (3 parts map, 2 parts info)

                    with map_col:
                        # --- Map Creation ---
                        # Find a default center point - fit_bounds will override this later
                        depot_loc = selected_route_original_data.get("depot")
                        pickups_list = selected_route_original_data.get("pickups", []) # Get lists safely
                        dropoffs_list = selected_route_original_data.get("dropoffs", [])
                        first_pickup = pickups_list[0].get("location") if pickups_list else None
                        first_dropoff = dropoffs_list[0].get("location") if dropoffs_list else None
                        # Determine initial center for map creation
                        map_center = depot_loc or first_pickup or first_dropoff or [40.7128, -74.0060] # Fallback

                        # Initialize map - start slightly zoomed out, fit_bounds will adjust
                        m = folium.Map(location=map_center, zoom_start=11, tiles="cartodbpositron", control_scale=True)

                        # --- Prepare ALL points for bounds fitting ---
                        points_to_fit = []
                        # Add depot location if valid
                        if depot_loc and isinstance(depot_loc, (list, tuple)) and len(depot_loc) == 2:
                             points_to_fit.append(depot_loc)
                        # Add all pickup locations if valid
                        for pickup in pickups_list:
                             loc = pickup.get("location")
                             if loc and isinstance(loc, (list, tuple)) and len(loc) == 2: points_to_fit.append(loc)
                        # Add all dropoff locations if valid
                        for dropoff in dropoffs_list:
                             loc = dropoff.get("location")
                             if loc and isinstance(loc, (list, tuple)) and len(loc) == 2: points_to_fit.append(loc)

                        # --- Add Markers ---
                        # Helper function to add markers safely
                        def add_marker(loc, pop, tip, ico_name, ico_color):
                            if loc and isinstance(loc, (list, tuple)) and len(loc) == 2:
                                try:
                                     # Use Icon from folium directly
                                     folium.Marker(location=loc, popup=pop, tooltip=tip, icon=folium.Icon(color=ico_color, icon=ico_name, prefix='fa')).add_to(m)
                                except Exception as marker_err:
                                     # Log warning but continue
                                     st.warning(f"Could not add marker for '{tip}': {marker_err}")

                        # Add markers for depot, pickups, dropoffs
                        add_marker(depot_loc, f"Depot ({selected_route_original_data.get('route_id', 'N/A')})", "Depot", 'bus', DEPOT_COLOR) # Uses constant
                        for i, pickup in enumerate(pickups_list): add_marker(pickup.get("location"), f"Pickup {i+1}", f"Pickup {i+1}", 'user-plus', PICKUP_COLOR) # Uses constant
                        for i, dropoff in enumerate(dropoffs_list):
                             # Include bell time in popup for first dropoff
                             bell_time_str = f" (Bell: {selected_feasibility_data.get('First School Bell Time', 'N/A')})" if i == 0 and selected_feasibility_data.get('First School Bell Time') else ""
                             add_marker(dropoff.get("location"), f"Dropoff {i+1}{bell_time_str}", f"Dropoff {i+1}", 'school', DROPOFF_COLOR) # Uses constant


                        # --- Add Polylines AND collect their points for bounds ---
                        # Helper function to add polyline and return decoded points
                        def add_polyline_to_map(map_obj, encoded_polyline, color, weight, opacity, tooltip):
                             # Make sure polyline library is available
                             if 'polyline' not in globals() or not encoded_polyline or not isinstance(encoded_polyline, str): return []
                             try:
                                 decoded_points = polyline.decode(encoded_polyline) # Use imported polyline library
                                 if decoded_points:
                                     folium.PolyLine(locations=decoded_points, color=color, weight=weight, opacity=opacity, tooltip=tooltip).add_to(map_obj)
                                     return decoded_points # Return points for bounds calculation
                             except Exception as poly_err:
                                 st.warning(f"Could not decode/add polyline '{tooltip}': {poly_err}")
                             return []

                        # Get polylines from feasibility results
                        am_poly = selected_feasibility_data.get("AM Overview Polyline")
                        pm_poly = selected_feasibility_data.get("PM Overview Polyline")

                        # Add selected polylines and collect their points for fitting bounds
                        if st.session_state.selected_trip_type_map in ["AM Trip", "Round Trip"]:
                             decoded_am_points = add_polyline_to_map(m, am_poly, AM_ROUTE_COLOR, 4, 0.7, "AM Route")
                             if decoded_am_points: points_to_fit.extend(decoded_am_points) # Add points to list
                        if st.session_state.selected_trip_type_map in ["PM Trip", "Round Trip"]:
                             decoded_pm_points = add_polyline_to_map(m, pm_poly, PM_ROUTE_COLOR, 4, 0.7, "PM Route")
                             if decoded_pm_points: points_to_fit.extend(decoded_pm_points) # Add points to list


                        # --- Fit Bounds Using ALL Collected Points ---
                        # Check if we have enough unique points to make bounds meaningful
                        # Use set() to find unique points before checking length
                        if len(set(map(tuple, points_to_fit))) >= 2: # Need at least 2 distinct points for bounds
                            try:
                                m.location = map_center
                                m.zoom_start = 11 # Increased padding
                            except Exception as bounds_err:
                                 st.warning(f"Could not automatically fit map bounds: {bounds_err}")
                                 # Fallback: Center on the initial map_center if bounds fail
                                 m.location = map_center
                                 m.zoom_start = 11 # Reset zoom if bounds fail
                        elif len(points_to_fit) == 1: # Center on single point if only one exists
                             m.location = points_to_fit[0]
                             m.zoom_start = 11 # Zoom closer for single point
                        # If points_to_fit is empty, the initial map center/zoom calculated earlier remains


                        # --- Display Map ---
                        # Use a unique key for the map component within the tab
                        st_folium(m, width='100%', height=500, key="route_map_display_tab4")

                    # --- Info Panel Column ---
                    with info_col:
                        st.subheader(f"Route Details: {st.session_state.selected_route_id_map}")

                        # Display distances/durations based on selected trip type
                        am_dist = selected_feasibility_data.get("AM Distance (miles)")
                        pm_dist = selected_feasibility_data.get("PM Distance (miles)")
                        am_dur = selected_feasibility_data.get("AM Duration (min)")
                        pm_dur = selected_feasibility_data.get("PM Duration (min)")

                        st.markdown(f"**Trip Type Shown:** {st.session_state.selected_trip_type_map}")
                        # Use st.metric for nice display
                        if st.session_state.selected_trip_type_map == "AM Trip":
                            st.metric("AM Distance", f"{am_dist:.1f} mi" if am_dist else "N/A")
                            st.metric("AM Duration", f"{am_dur:.0f} min" if am_dur else "N/A")
                        elif st.session_state.selected_trip_type_map == "PM Trip":
                            st.metric("PM Distance", f"{pm_dist:.1f} mi" if pm_dist else "N/A")
                            st.metric("PM Duration", f"{pm_dur:.0f} min" if pm_dur else "N/A")
                        else: # Round Trip
                             rt_dist = (am_dist or 0) + (pm_dist or 0)
                             rt_dur = (am_dur or 0) + (pm_dur or 0)
                             st.metric("Round Trip Distance", f"{rt_dist:.1f} mi")
                             st.metric("Round Trip Duration", f"{rt_dur:.0f} min")

                        st.divider() # Visual separator
                        # Display other route details
                        st.markdown(f"**Suggested Depot Departure:** {selected_feasibility_data.get('Suggested Depot Departure Time', 'N/A')}")
                        dac_percent = selected_feasibility_data.get('Percent in DAC')
                        st.markdown(f"**% Route in DAC:** {dac_percent:.1f}%" if dac_percent is not None else "N/A")

                        # --- Display Eligibility from Plan DataFrame ---
                        # Find the row in the plan_df for the selected route
                        route_plan_info = plan_df[plan_df['Route ID'] == st.session_state.selected_route_id_map]
                        # Check if info was found (it should be if route_id is valid)
                        if not route_plan_info.empty:
                            route_info_row = route_plan_info.iloc[0] # Get the first (and only) row
                            eligibility = route_info_row.get('EV Eligibility', 'N/A')
                            bus_type = route_info_row.get('Bus Type', 'N/A')

                            # Determine which list of eligible buses to display based on weather
                            eligible_bus_names = ""
                            if eligibility in ["Preferred - All Weather", "OK in All Weather"]: eligible_bus_names = route_info_row.get('Eligible Buses < 50°F', '')
                            elif eligibility == "OK > 50°F Weather": eligible_bus_names = route_info_row.get('Eligible Buses 50–70°F', '')
                            elif eligibility == "OK > 70°F Weather": eligible_bus_names = route_info_row.get('Eligible Buses 70°F+', '')

                            # Format the display string
                            eligibility_display = f"**EV Eligibility:** {eligibility}"
                            # Add bus names only if they are not empty/'None'/'N/A'
                            if eligible_bus_names and isinstance(eligible_bus_names, str) and eligible_bus_names not in ["None", "N/A", ""]:
                                eligibility_display += f" (with: *{eligible_bus_names}*)"

                            st.markdown(f"**Assigned Bus Type:** {bus_type}")
                            st.markdown(eligibility_display) # Display the combined string
                        else:
                             st.markdown("**EV Eligibility Status:** Not found in plan details.")

                 else: # Handle case where original route data or feasibility data wasn't found
                     st.warning(f"Could not retrieve all necessary data for Route ID: {st.session_state.selected_route_id_map} to display map/details.")