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
        # Some apps use ARGB, some use RGBA. We assume ARGB for OsmAnd.
        a, r, g, b = raw_hex[0:2], raw_hex[2:4], raw_hex[4:6], raw_hex[6:8]
    else:
        a, r, g, b = 'ff', 'ff', '00', '00'

    # KML uses aabbggrr
    kml_color = f"{a}{b}{g}{r}".lower()
    mymaps_hex = f"{r}{g}{b}".upper()
    return kml_color, mymaps_hex

# --- CONVERSION ENGINE ---
def convert_osmand_to_kmz(uploaded_file, keep_nth_point):
    color_map = {}
    used_colors = set()
    folders = {}
    
    ET.register_namespace('', "http://www.opengis.net/kml/2.2")
    kml_namespace = "{http://www.opengis.net/kml/2.2}"
    kml = ET.Element(f"{kml_namespace}kml")
    document = ET.SubElement(kml, f"{kml_namespace}Document")
    ET.SubElement(document, f"{kml_namespace}name").text = "GPX Compiled Tracks"

    gpx_contents = []

    # 1. FILE TYPE DETECTION
    if zipfile.is_zipfile(uploaded_file):
        with zipfile.ZipFile(uploaded_file, 'r') as z:
            file_list = z.namelist()
            if 'items.json' in file_list:
                with z.open('items.json') as f:
                    try:
                        data = json.load(f)
                        for item in data.get('items', []):
                            if 'file' in item and 'color' in item:
                                color_map[os.path.basename(item['file'])] = item['color']
                    except: pass
            
            for f_name in [f for f in file_list if f.lower().endswith('.gpx')]:
                gpx_contents.append((f_name, z.read(f_name), True))
    else:
        uploaded_file.seek(0)
        gpx_contents.append((uploaded_file.name, uploaded_file.read(), False))

    # 2. PROCESS GPX DATA
    for filename, xml_content, was_zipped in gpx_contents:
        try:
            basename = os.path.basename(filename)
            track_name = os.path.splitext(basename)[0]
            
            current_layer = document
            if was_zipped:
                dir_name = os.path.dirname(filename)
                parent_folder = os.path.basename(dir_name) if dir_name else "Tracks"
                if parent_folder not in folders:
                    folder_elem = ET.SubElement(document, f"{kml_namespace}Folder")
                    ET.SubElement(folder_elem, f"{kml_namespace}name").text = parent_folder
                    folders[parent_folder] = folder_elem
                current_layer = folders[parent_folder]

            root = ET.fromstring(xml_content)
            # Remove namespaces from tags for easier searching
            for elem in root.iter():
                if '}' in elem.tag: elem.tag = elem.tag.split('}', 1)[1]

            # --- COLOR DISCOVERY ---
            track_raw_color = None
            # Check for <color> tags anywhere in the track extensions (Gaia/OsmAnd)
            for trk in root.findall('.//trk'):
                for child in trk.iter():
                    if 'color' in child.tag.lower() and child.text:
                        track_raw_color = child.text
                        break
                if track_raw_color: break
            
            if not track_raw_color:
                track_raw_color = color_map.get(basename, '#FF0000')
            
            lkml, lhex = parse_color(track_raw_color)
            used_colors.add((lkml, lhex))
            line_style_url = f"#line-{lhex}-4000-nodesc"

            # Process Track Segments
            for trk in root.findall('.//trk'):
                trk_desc = trk.findtext('desc') or ''
                for trkseg in trk.findall('.//trkseg'):
                    coords, calc_total_km = [], 0.0
                    prev_lat, prev_lon = None, None
                    for trkpt in trkseg.findall('.//trkpt'):
                        lat, lon = trkpt.attrib['lat'], trkpt.attrib['lon']
                        if prev_lat is not None: calc_total_km += calculate_distance(prev_lat, prev_lon, lat, lon)
                        prev_lat, prev_lon = lat, lon
                        coords.append(f"{lon},{lat},0")

                    downsampled = coords[::keep_nth_point]
                    if downsampled:
                        placemark = ET.SubElement(current_layer, f"{kml_namespace}Placemark")
                        dist = f"{round(calc_total_km, 1)}".replace(".0", "")
                        ET.SubElement(placemark, f"{kml_namespace}name").text = f"({dist}km) {track_name}"
                        ET.SubElement(placemark, f"{kml_namespace}styleUrl").text = line_style_url
                        linestring = ET.SubElement(placemark, f"{kml_namespace}LineString")
                        ET.SubElement(linestring, f"{kml_namespace}tessellate").text = "1"
                        ET.SubElement(linestring, f"{kml_namespace}coordinates").text = " ".join(downsampled)

            # Process Waypoints
            for wpt in root.findall('.//wpt'):
                wpt_name = wpt.findtext('name') or ''
                if wpt_name.lower().strip() in ['start', 'end', 'finish', 'destination']: continue
                
                lon, lat = wpt.attrib['lon'], wpt.attrib['lat']
                wpt_color_raw = None
                for child in wpt.iter():
                    if 'color' in child.tag.lower() and child.text:
                        wpt_color_raw = child.text
                        break
                if not wpt_color_raw: wpt_color_raw = track_raw_color
                
                wkml, whex = parse_color(wpt_color_raw)
                used_colors.add((wkml, whex))
                
                pm = ET.SubElement(current_layer, f"{kml_namespace}Placemark")
                ET.SubElement(pm, f"{kml_namespace}name").text = wpt_name
                ET.SubElement(pm, f"{kml_namespace}styleUrl").text = f"#icon-1899-{whex}-nodesc"
                point = ET.SubElement(pm, f"{kml_namespace}Point")
                ET.SubElement(point, f"{kml_namespace}coordinates").text = f"{lon},{lat},0"

        except Exception: continue

    # --- STYLE GENERATION (Strict Logic) ---
    for kml_color, mymaps_hex in used_colors:
        line_map_id = f"line-{mymaps_hex}-4000-nodesc"
        
        # Line Normal
        sn = ET.SubElement(document, f"{kml_namespace}Style", id=f"{line_map_id}-normal")
        lsn = ET.SubElement(sn, f"{kml_namespace}LineStyle")
        ET.SubElement(lsn, f"{kml_namespace}color").text = kml_color
        ET.SubElement(lsn, f"{kml_namespace}width").text = "4"
        
        # Line Highlight
        sh = ET.SubElement(document, f"{kml_namespace}Style", id=f"{line_map_id}-highlight")
        lsh = ET.SubElement(sh, f"{kml_namespace}LineStyle")
        ET.SubElement(lsh, f"{kml_namespace}color").text = kml_color
        ET.SubElement(lsh, f"{kml_namespace}width").text = "6"
        
        # Line StyleMap
        sm = ET.SubElement(document, f"{kml_namespace}StyleMap", id=line_map_id)
        p1 = ET.SubElement(sm, f"{kml_namespace}Pair")
        ET.SubElement(p1, f"{kml_namespace}key").text = "normal"
        ET.SubElement(p1, f"{kml_namespace}styleUrl").text = f"#{line_map_id}-normal"
        p2 = ET.SubElement(sm, f"{kml_namespace}Pair")
        ET.SubElement(p2, f"{kml_namespace}key").text = "highlight"
        ET.SubElement(p2, f"{kml_namespace}styleUrl").text = f"#{line_map_id}-highlight"

        icon_map_id = f"icon-1899-{mymaps_hex}-nodesc"
        
        # Icon Normal
        in_s = ET.SubElement(document, f"{kml_namespace}Style", id=f"{icon_map_id}-normal")
        isn = ET.SubElement(in_s, f"{kml_namespace}IconStyle")
        ET.SubElement(isn, f"{kml_namespace}color").text = kml_color
        icon_n = ET.SubElement(isn, f"{kml_namespace}Icon")
        ET.SubElement(icon_n, f"{kml_namespace}href").text = "https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png"
        ET.SubElement(isn, f"{kml_namespace}hotSpot", x="32", xunits="pixels", y="64", yunits="insetPixels")
        
        # Icon Highlight
        ih_s = ET.SubElement(document, f"{kml_namespace}Style", id=f"{icon_map_id}-highlight")
        ish = ET.SubElement(ih_s, f"{kml_namespace}IconStyle")
        ET.SubElement(ish, f"{kml_namespace}color").text = kml_color
        icon_h = ET.SubElement(ish, f"{kml_namespace}Icon")
        ET.SubElement(icon_h, f"{kml_namespace}href").text = "https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png"
        ET.SubElement(ish, f"{kml_namespace}hotSpot", x="32", xunits="pixels", y="64", yunits="insetPixels")
        
        # Icon StyleMap
        ism = ET.SubElement(document, f"{kml_namespace}StyleMap", id=icon_map_id)
        p3 = ET.SubElement(ism, f"{kml_namespace}Pair")
        ET.SubElement(p3, f"{kml_namespace}key").text = "normal"
        ET.SubElement(p3, f"{kml_namespace}styleUrl").text = f"#{icon_map_id}-normal"
        p4 = ET.SubElement(ism, f"{kml_namespace}Pair")
        ET.SubElement(p4, f"{kml_namespace}key").text = "highlight"
        ET.SubElement(p4, f"{kml_namespace}styleUrl").text = f"#{icon_map_id}-highlight"

    kml_str = ET.tostring(kml, encoding='utf-8', xml_declaration=True).decode('utf-8')
    kmz_io = io.BytesIO()
    with zipfile.ZipFile(kmz_io, 'w', zipfile.ZIP_DEFLATED) as kmz:
        kmz.writestr('doc.kml', kml_str)
    return kmz_io.getvalue()

# --- STREAMLIT UI ---
st.set_page_config(page_title="GPX to KMZ", page_icon="🗺️")
st.title("🗺️ Universal GPX to KMZ Converter")
st.write("Upload OsmAnd (.zip/.osf) or single GPX files (Gaia/OsmAnd).")

uploaded_file = st.file_uploader("Drop your file here", type=['zip', 'osf', 'gpx'])
density = st.selectbox("Point density?", ["All points", "Every 2nd point", "Every 3rd point"], index=1)

if uploaded_file:
    nth = 1 if "All" in density else (2 if "2nd" in density else 3)
    if st.button("Start Conversion", type="primary"):
        with st.spinner("Converting..."):
            kmz_data = convert_osmand_to_kmz(uploaded_file, nth)
            output_filename = os.path.splitext(uploaded_file.name)[0] + ".kmz"
            st.success("Conversion complete!")
            st.download_button("📥 Download KMZ File", data=kmz_data, file_name=output_filename, mime="application/vnd.google-earth.kmz")
        
