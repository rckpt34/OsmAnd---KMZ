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
def convert_osmand_to_kmz(input_zip, keep_nth_point):
    color_map = {}
    name_color_map = {}
    distance_map = {}
    used_colors = set()
    folders = {}

    ET.register_namespace('', "http://www.opengis.net/kml/2.2")
    kml_namespace = "{http://www.opengis.net/kml/2.2}"

    kml = ET.Element(f"{kml_namespace}kml")
    document = ET.SubElement(kml, f"{kml_namespace}Document")
    ET.SubElement(document, f"{kml_namespace}name").text = "OsmAnd Compiled Tracks"

    with zipfile.ZipFile(input_zip, 'r') as z:
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
            try:
                basename = os.path.basename(gpx_file)
                track_name = os.path.splitext(basename)[0]

                dir_name = os.path.dirname(gpx_file)
                parent_folder = os.path.basename(dir_name) if dir_name else "Uncategorized Tracks"

                if parent_folder not in folders:
                    folder_elem = ET.Element(f"{kml_namespace}Folder")
                    ET.SubElement(folder_elem, f"{kml_namespace}name").text = parent_folder
                    folders[parent_folder] = folder_elem

                current_layer = folders[parent_folder]

                with z.open(gpx_file) as f:
                    xml_content = f.read()

                try:
                    root = ET.fromstring(xml_content)
                except ET.ParseError:
                    continue

                for elem in root.iter():
                    if '}' in elem.tag:
                        elem.tag = elem.tag.split('}', 1)[1]

                track_raw_color = color_map.get(basename, '#FF0000')
                track_distance_meters = distance_map.get(basename)
                line_kml_color, line_mymaps_hex = parse_color(track_raw_color)
                used_colors.add((line_kml_color, line_mymaps_hex))
                line_style_url = f"#line-{line_mymaps_hex}-4000-nodesc"

                # Parse Tracks
                for trk in root.findall('.//trk'):
                    trk_desc = trk.findtext('desc') or ''
                    coords = []
                    calc_total_km = 0.0

                    for trkseg in trk.findall('.//trkseg'):
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

                        if track_distance_meters is not None:
                            final_km = track_distance_meters / 1000.0
