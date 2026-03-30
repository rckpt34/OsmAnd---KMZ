import streamlit as st
import zipfile
import json
import os
import math
import xml.etree.ElementTree as ET
import io

# --- CALCULATION LOGIC ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def parse_color(raw_color):
    if not raw_color or not isinstance(raw_color, str):
        raw_color = '#FF0000'
    raw_hex = raw_color.replace('#', '').strip()

    if len(raw_hex) == 6:
        r, g, b = raw_hex[0:2], raw_hex[2:4], raw_hex[4:6]
        a = 'ff'
    elif len(raw_hex) == 8:
        a, r, g, b = raw_hex[0:2], raw_hex[2:4], raw_hex[4:6], raw_hex[6:8]
    else:
        a, r, g, b = 'ff', 'ff', '00', '00'

    kml_color = f"{a}{b}{g}{r}".lower()
    mymaps_hex = f"{r}{g}{b}".upper()
    return kml_color, mymaps_hex

# --- CONVERSION ENGINE ---
def convert_osmand_to_kmz(input_file, keep_nth_point, uploaded_filename):
    color_map = {}
    name_color_map = {}
    distance_map = {}
    used_colors = set()
    folders = {}
    gpx_files_data = []

    ET.register_namespace('', "http://www.opengis.net/kml/2.2")
    kml_namespace = "{http://www.opengis.net/kml/2.2}"

    kml = ET.Element(f"{kml_namespace}kml")
    document = ET.SubElement(kml, f"{kml_namespace}Document")
    ET.SubElement(document, f"{kml_namespace}name").text = "OsmAnd Compiled Tracks"

    is_zip = uploaded_filename.lower().endswith(('.zip', '.osf'))

    if is_zip:
        with zipfile.ZipFile(input_file, 'r') as z:
            file_list = z.namelist()

            if 'items.json' in file_list:
                with z.open('items.json') as f:
                    data = json.load(f)
                    for item in data.get('items', []):
                        if 'file' in item:
                            basename = os.path.basename(item['file'])
                            if 'color' in item:
                                color_map[basename] = item['color']
                            if 'total_distance' in item:
                                try:
                                    distance_map[basename] = float(item['total_distance'])
                                except ValueError:
                                    pass
                            elif 'distance' in item:
                                try:
                                    distance_map[basename] = float(item['distance'])
                                except ValueError:
                                    pass
                        if 'name' in item and 'color' in item:
                            name_color_map[item['name']] = item['color']

            gpx_files = [f for f in file_list if f.lower().endswith('.gpx')]

            for gpx_file in gpx_files:
                basename = os.path.basename(gpx_file)
                dir_name = os.path.dirname(gpx_file)
                with z.open(gpx_file) as f:
                    gpx_files_data.append((basename, dir_name, f.read()))
    else:
        basename = os.path.basename(uploaded_filename)
        dir_name = ""
        gpx_files_data.append((basename, dir_name, input_file.read()))

    for basename, dir_name, xml_content in gpx_files_data:
        try:
            track_name = os.path.splitext(basename)[0]
            
            if not is_zip:
                # If it's a single GPX file, name the layer after the file name
                parent_folder = track_name
            else:
                # If it's from a zip/osf, name the layer after the immediate parent folder
                parent_folder = os.path.basename(dir_name) if dir_name else "Uncategorized Tracks"

            if parent_folder not in folders:
                folder_elem = ET.Element(f"{kml_namespace}Folder")
                ET.SubElement(folder_elem, f"{kml_namespace}name").text = parent_folder
                folders[parent_folder] = folder_elem

            current_layer = folders[parent_folder]

            try:
                root = ET.fromstring(xml_content)
            except ET.ParseError:
                continue

            for elem in root.iter():
                if '}' in elem.tag:
                    elem.tag = elem.tag.split('}', 1)[1]

            # Determine Track Color Priority
            # 1. Try taking it from the JSON color_map first
            track_raw_color = color_map.get(basename)
            
            # 2. If no JSON color is available, fall back to GPX extensions
            if not track_raw_color:
                track_color_from_gpx = None
                for ext in root.findall('./extensions'):
                    for color_elem in ext.findall('.//color'):
                        if color_elem.text:
                            track_color_from_gpx = color_elem.text
                            break
                    if track_color_from_gpx:
                        break
                
                if not track_color_from_gpx:
                    for trk in root.findall('.//trk'):
                        for ext in trk.findall('.//extensions'):
                            for color_elem in ext.findall('.//color'):
                                if color_elem.text:
                                    track_color_from_gpx = color_elem.text
                                    break
                            if track_color_from_gpx:
                                break
                        if track_color_from_gpx:
                            break
                            
                track_raw_color = track_color_from_gpx if track_color_from_gpx else '#FF0000'

            line_kml_color, line_mymaps_hex = parse_color(track_raw_color)
            used_colors.add((line_kml_color, line_mymaps_hex))
            line_style_url = f"#line-{line_mymaps_hex}-4000-nodesc"

            for trk in root.findall('.//trk'):
                trk_desc = trk.findtext('desc') or ''
                
                # Split into segments
                for trkseg in trk.findall('.//trkseg'):
                    coords = []
                    calc_total_km = 0.0
                    prev_lat, prev_lon = None, None

                    for trkpt in trkseg.findall('.//trkpt'):
                        lat = trkpt.attrib['lat']
                        lon = trkpt.attrib['lon']
                        if prev_lat is not None and prev_lon is not None:
                            calc_total_km += calculate_distance(prev_lat, prev_lon, lat, lon)
                        prev_lat, prev_lon = lat, lon
                        coords.append(f"{lon},{lat},0")

                    downsampled = coords[::keep_nth_point]

                    if downsampled:
                        placemark = ET.SubElement(current_layer, f"{kml_namespace}Placemark")
                        distance_str = f"{round(calc_total_km, 1)}"
                        if distance_str.endswith(".0"):
                            distance_str = distance_str[:-2]

                        ET.SubElement(placemark, f"{kml_namespace}name").text = f"({distance_str}km) {track_name}"
                        if trk_desc:
                            ET.SubElement(placemark, f"{kml_namespace}description").text = trk_desc
                        
                        # Use the color URL generated before the loop
                        ET.SubElement(placemark, f"{kml_namespace}styleUrl").text = line_style_url

                        linestring = ET.SubElement(placemark, f"{kml_namespace}LineString")
                        ET.SubElement(linestring, f"{kml_namespace}tessellate").text = "1"
                        ET.SubElement(linestring, f"{kml_namespace}coordinates").text = " ".join(downsampled)

            for wpt in root.findall('.//wpt'):
                wpt_name = wpt.findtext('name') or ''
                if wpt_name.lower().strip() in ['start', 'end', 'finish', 'destination']:
                    continue

                wpt_desc = wpt.findtext('desc') or ''
                lon, lat = wpt.attrib['lon'], wpt.attrib['lat']
                
                # Put waypoints in the exact same layer as the track/file
                target_layer = current_layer

                wpt_color_raw = None
                
                # Robust namespace check for waypoint color
                for child in wpt.iter():
                    if child.tag.split('}')[-1].split(':')[-1].lower() == 'color' and child.text:
                        wpt_color_raw = child.text
                        break

                if not wpt_color_raw and wpt_name in name_color_map:
                    wpt_color_raw = name_color_map[wpt_name]
                if not wpt_color_raw:
                    wpt_color_raw = track_raw_color

                wpt_kml_color, wpt_mymaps_hex = parse_color(wpt_color_raw)
                used_colors.add((wpt_kml_color, wpt_mymaps_hex))
                icon_style_url = f"#icon-1899-{wpt_mymaps_hex}-nodesc"

                placemark = ET.SubElement(target_layer, f"{kml_namespace}Placemark")
                if wpt_name: ET.SubElement(placemark, f"{kml_namespace}name").text = wpt_name
                if wpt_desc: ET.SubElement(placemark, f"{kml_namespace}description").text = wpt_desc
                ET.SubElement(placemark, f"{kml_namespace}styleUrl").text = icon_style_url

                point = ET.SubElement(placemark, f"{kml_namespace}Point")
                ET.SubElement(point, f"{kml_namespace}coordinates").text = f"{lon},{lat},0"

        except Exception:
            continue

    # --- STYLE DEFINITIONS (Crucial for Colors) ---
    for kml_color, mymaps_hex in used_colors:
        line_map_id = f"line-{mymaps_hex}-4000-nodesc"

        norm_line = ET.SubElement(document, f"{kml_namespace}Style", id=f"{line_map_id}-normal")
        ls_n = ET.SubElement(norm_line, f"{kml_namespace}LineStyle")
        ET.SubElement(ls_n, f"{kml_namespace}color").text = kml_color
        ET.SubElement(ls_n, f"{kml_namespace}width").text = "4"

        high_line = ET.SubElement(document, f"{kml_namespace}Style", id=f"{line_map_id}-highlight")
        ls_h = ET.SubElement(high_line, f"{kml_namespace}LineStyle")
        ET.SubElement(ls_h, f"{kml_namespace}color").text = kml_color
        ET.SubElement(ls_h, f"{kml_namespace}width").text = "6"

        line_smap = ET.SubElement(document, f"{kml_namespace}StyleMap", id=line_map_id)
        p1 = ET.SubElement(line_smap, f"{kml_namespace}Pair")
        ET.SubElement(p1, f"{kml_namespace}key").text = "normal"
        ET.SubElement(p1, f"{kml_namespace}styleUrl").text = f"#{line_map_id}-normal"
        p2 = ET.SubElement(line_smap, f"{kml_namespace}Pair")
        ET.SubElement(p2, f"{kml_namespace}key").text = "highlight"
        ET.SubElement(p2, f"{kml_namespace}styleUrl").text = f"#{line_map_id}-highlight"

        icon_map_id = f"icon-1899-{mymaps_hex}-nodesc"
        icon_url = "https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png"

        norm_icon = ET.SubElement(document, f"{kml_namespace}Style", id=f"{icon_map_id}-normal")
        is_n = ET.SubElement(norm_icon, f"{kml_namespace}IconStyle")
        ET.SubElement(is_n, f"{kml_namespace}scale").text = "1"
        ET.SubElement(is_n, f"{kml_namespace}color").text = kml_color
        i_n = ET.SubElement(is_n, f"{kml_namespace}Icon")
        ET.SubElement(i_n, f"{kml_namespace}href").text = icon_url
        ET.SubElement(is_n, f"{kml_namespace}hotSpot", x="32", xunits="pixels", y="64", yunits="insetPixels")

        high_icon = ET.SubElement(document, f"{kml_namespace}Style", id=f"{icon_map_id}-highlight")
        is_h = ET.SubElement(high_icon, f"{kml_namespace}IconStyle")
        ET.SubElement(is_h, f"{kml_namespace}scale").text = "1"
        ET.SubElement(is_h, f"{kml_namespace}color").text = kml_color
        i_h = ET.SubElement(is_h, f"{kml_namespace}Icon")
        ET.SubElement(i_h, f"{kml_namespace}href").text = icon_url
        ET.SubElement(is_h, f"{kml_namespace}hotSpot", x="32", xunits="pixels", y="64", yunits="insetPixels")

        icon_smap = ET.SubElement(document, f"{kml_namespace}StyleMap", id=icon_map_id)
        p3 = ET.SubElement(icon_smap, f"{kml_namespace}Pair")
        ET.SubElement(p3, f"{kml_namespace}key").text = "normal"
        ET.SubElement(p3, f"{kml_namespace}styleUrl").text = f"#{icon_map_id}-normal"
        p4 = ET.SubElement(icon_smap, f"{kml_namespace}Pair")
        ET.SubElement(p4, f"{kml_namespace}key").text = "highlight"
        ET.SubElement(p4, f"{kml_namespace}styleUrl").text = f"#{icon_map_id}-highlight"

    for folder_elem in folders.values():
        document.append(folder_elem)

    kml_str = ET.tostring(kml, encoding='utf-8', xml_declaration=True).decode('utf-8')
    kmz_io = io.BytesIO()
    with zipfile.ZipFile(kmz_io, 'w', zipfile.ZIP_DEFLATED) as kmz:
        kmz.writestr('doc.kml', kml_str)
    return kmz_io.getvalue()

# --- STREAMLIT UI ---
st.set_page_config(page_title="OsmAnd to KMZ", page_icon="🗺️")
st.title("🗺️ OsmAnd to KMZ Converter")
st.write("Upload your .zip, .osf, or .gpx file to convert it for Google My Maps.")

uploaded_file = st.file_uploader("Drop your OsmAnd file here", type=['zip', 'osf', 'gpx'])
density = st.selectbox("How many points to keep?", ["All points", "Every 2nd point", "Every 3rd point"], index=1)

if uploaded_file:
    nth = 1 if "All" in density else (2 if "2nd" in density else 3)
    if st.button("Start Conversion", type="primary"):
        with st.spinner("Converting..."):
            kmz_data = convert_osmand_to_kmz(uploaded_file, nth, uploaded_file.name)
            base_name = os.path.splitext(uploaded_file.name)[0]
            output_filename = f"{base_name}.kmz"
            st.success("Conversion complete!")
            st.download_button(
                label="📥 Download KMZ File",
                data=kmz_data,
                file_name=output_filename,
                mime="application/vnd.google-earth.kmz"
        )
