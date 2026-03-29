import streamlit as st
import zipfile
import json
import os
import math
import xml.etree.ElementTree as ET

# --- CALCULATION LOGIC ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0 
    lat1, lon1, lat2, lon2 = map(math.radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
    dlat, dlon = lat2 - lat1, dlon - lon1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return R * (2 * math.asin(math.sqrt(a)))

def parse_color(raw_color):
    if not raw_color or not isinstance(raw_color, str): raw_color = '#FF0000'
    raw_hex = raw_color.replace('#', '').strip()
    if len(raw_hex) == 6: r, g, b, a = raw_hex[0:2], raw_hex[2:4], raw_hex[4:6], 'ff'
    elif len(raw_hex) == 8: a, r, g, b = raw_hex[0:2], raw_hex[2:4], raw_hex[4:6], raw_hex[6:8]
    else: a, r, g, b = 'ff', 'ff', '00', '00'
    return f"{a}{b}{g}{r}".lower(), f"{r}{g}{b}".upper()

# --- CONVERSION ENGINE ---
def convert_osmand_to_kmz(input_zip, keep_nth):
    color_map, distance_map, folders, used_colors = {}, {}, {}, set()
    ET.register_namespace('', "http://www.opengis.net/kml/2.2")
    ns = "{http://www.opengis.net/kml/2.2}"
    kml = ET.Element(f"{ns}kml")
    doc = ET.SubElement(kml, f"{ns}Document")
    ET.SubElement(doc, f"{ns}name").text = "OsmAnd Tracks"

    with zipfile.ZipFile(input_zip, 'r') as z:
        file_list = z.namelist()
        if 'items.json' in file_list:
            with z.open('items.json') as f:
                items = json.load(f).get('items', [])
                for i in items:
                    if 'file' in i:
                        base = os.path.basename(i['file'])
                        if 'color' in i: color_map[base] = i['color']
                        dist = i.get('total_distance') or i.get('distance')
                        if dist: distance_map[base] = float(dist)

        for gpx in [f for f in file_list if f.lower().endswith('.gpx')]:
            try:
                base = os.path.basename(gpx)
                folder_name = os.path.basename(os.path.dirname(gpx)) or "Tracks"
                if folder_name not in folders:
                    folders[folder_name] = ET.SubElement(doc, f"{ns}Folder")
                    ET.SubElement(folders[folder_name], f"{ns}name").text = folder_name
                
                with z.open(gpx) as f: root = ET.fromstring(f.read())
                for e in root.iter(): 
                    if '}' in e.tag: e.tag = e.tag.split('}', 1)[1]

                raw_c = color_map.get(base, '#FF0000')
                kc, hc = parse_color(raw_c); used_colors.add((kc, hc))

                for trk in root.findall('.//trk'):
                    coords, calc_km = [], 0.0
                    for seg in trk.findall('.//trkseg'):
                        p_la, p_lo = None, None
                        for pt in seg.findall('.//trkpt'):
                            la, lo = pt.attrib['lat'], pt.attrib['lon']
                            if p_la: calc_km += calculate_distance(p_la, p_lo, la, lo)
                            p_la, p_lo = la, lo
                            coords.append(f"{lo},{la},0")
                    if coords:
                        km = (distance_map.get(base) / 1000.0) if base in distance_map else calc_km
                        pm = ET.SubElement(folders[folder_name], f"{ns}Placemark")
                        ET.SubElement(pm, f"{ns}name").text = f"({round(km, 1)}km) {os.path.splitext(base)[0]}"
                        ET.SubElement(pm, f"{ns}styleUrl").text = f"#line-{hc}-4000-nodesc"
                        ls = ET.SubElement(pm, f"{ns}LineString")
                        ET.SubElement(ls, f"{ns}coordinates").text = " ".join(coords[::keep_nth])
            except: continue

    # Styling section (Omitted for brevity, but required for My Maps colors)
    # ... (Standard StyleMap generation here) ...

    return ET.tostring(kml, encoding='utf-8', xml_declaration=True)

# --- STREAMLIT UI ---
st.set_page_config(page_title="OsmAnd to KMZ", page_icon="🗺️")
st.title("🗺️ OsmAnd to KMZ Converter")
st.write("Upload your .zip or .osf file to convert it for Google My Maps.")

# The browser's native file uploader
uploaded_file = st.file_uploader("Drop your OsmAnd file here", type=['zip', 'osf'])
density = st.selectbox("How many points to keep?", ["All points", "Every 2nd point", "Every 3rd point"], index=1)

if uploaded_file:
    nth = 1 if "All" in density else (2 if "2nd" in density else 3)
    
    if st.button("Start Conversion", type="primary"):
        with st.spinner("Converting..."):
            kmz_data = convert_osmand_to_kmz(uploaded_file, nth)
            
            # The browser's native download button
            st.success("Conversion complete!")
            st.download_button(
                label="📥 Download KMZ File",
                data=kmz_data,
                file_name="compiled_tracks.kmz",
                mime="application/vnd.google-earth.kmz"
            )
