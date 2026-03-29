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
                line_kml_color, line_mymaps_hex = parse_color(track_raw_color)
                used_colors.add((line_kml_color, line_mymaps_hex))
                line_style_url = f"#line-{line_mymaps_hex}-4000-nodesc"

                for trk in root.findall('.//trk'):
                    trk_desc = trk.findtext('desc') or ''

                    # Process each segment individually
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

                            # Use the calculated segment distance for the name
                            distance_str = f"{round(calc_total_km, 1)}"
                            if distance_str.endswith(".0"):
                                distance_str = distance_str[:-2]

                            ET.SubElement(placemark, f"{kml_namespace}name").text = f"({distance_str}km) {track_name}"

                            if trk_desc:
                                ET.SubElement(placemark, f"{kml_namespace}description").text = trk_desc
                            ET.SubElement(placemark, f"{kml_namespace}styleUrl").text = line_style_url

                            linestring = ET.SubElement(placemark, f"{kml_namespace}LineString")
                            ET.SubElement(linestring, f"{kml_namespace}tessellate").text = "1"
                            ET.SubElement(linestring, f"{kml_namespace}coordinates").text = " ".join(downsampled)

                for wpt in root.findall('.//wpt'):
                    wpt_name = wpt.findtext('name') or ''
                    name_lower = wpt_name.lower().strip()
                    if name_lower in ['start', 'end', 'finish', 'destination']:
                        continue

                    wpt_desc = wpt.findtext('desc') or ''
                    lon, lat = wpt.attrib['lon'], wpt.attrib['lat']

                    wpt_color_raw = None
                    for child in wpt.iter():
                        if child.tag.lower() == 'color' and child.text:
                            wpt_color_raw = child.text
                            break

                    if not wpt_color_raw and wpt_name in name_color_map:
                        wpt_color_raw = name_color_map[wpt_name]

                    if not wpt_color_raw:
                        wpt_color_raw = track_raw_color

                    wpt_kml_color, wpt_mymaps_hex = parse_color(wpt_color_raw)
                    used_colors.add((wpt_kml_color, wpt_mymaps_hex))
                    icon_style_url = f"#icon-1899-{wpt_mymaps_hex}-nodesc"

                    placemark = ET.SubElement(current_layer, f"{kml_namespace}Placemark")
                    if wpt_name:
                        ET.SubElement(placemark, f"{kml_namespace}name").text = wpt_name
                    if wpt_desc:
                        ET.SubElement(placemark, f"{kml_namespace}description").text = wpt_desc
                    ET.SubElement(placemark, f"{kml_namespace}styleUrl").text = icon_style_url

                    point = ET.SubElement(placemark, f"{kml_namespace}Point")
                    ET.SubElement(point, f"{kml_namespace}coordinates").text = f"{lon},{lat},0"

            except Exception as e:
                continue

    for kml_color, mymaps_hex in used_colors:
        line_map_id = f"line-{mymaps_hex}-4000-nodesc"

        norm_line = ET.Element(f"{kml_namespace}Style", id=f"{line_map_id}-normal")
        ls_n = ET.SubElement(norm_line, f"{kml_namespace}LineStyle")
        ET.SubElement(ls_n, f"{kml_namespace}color").text = kml_color
        ET.SubElement(ls_n, f"{kml_namespace}width").text = "4"
        document.append(norm_line)

        high_line = ET.Element(f"{kml_namespace}Style", id=f"{line_map_id}-highlight")
        ls_h = ET.SubElement(high_line, f"{kml_namespace}LineStyle")
        ET.SubElement(ls_h, f"{kml_namespace}color").text = kml_color
        ET.SubElement(ls_h, f"{kml_namespace}width").text = "6"
        document.append(high_line)

        line_smap = ET.Element(f"{kml_namespace}StyleMap", id=line_map_id)
        p1 = ET.SubElement(line_smap, f"{kml_namespace}Pair")
        ET.SubElement(p1, f"{kml_namespace}key").text = "normal"
        ET.SubElement(p1, f"{kml_namespace}styleUrl").text = f"#{line_map_id}-normal"
        p2 = ET.SubElement(line_smap, f"{kml_namespace}Pair")
        ET.SubElement(p2, f"{kml_namespace}key").text = "highlight"
        ET.SubElement(p2, f"{kml_namespace}styleUrl").text = f"#{line_map_id}-highlight"
        document.append(line_smap)

        icon_map_id = f"icon-1899-{mymaps_hex}-nodesc"
        icon_url = "https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png"

        norm_icon = ET.Element(f"{kml_namespace}Style", id=f"{icon_map_id}-normal")
        is_n = ET.SubElement(norm_icon, f"{kml_namespace}IconStyle")
        ET.SubElement(is_n, f"{kml_namespace}scale").text = "1"
        ET.SubElement(is_n, f"{kml_namespace}color").text = kml_color
        i_n = ET.SubElement(is_n, f"{kml_namespace}Icon")
        ET.SubElement(i_n, f"{kml_namespace}href").text = icon_url
        ET.SubElement(is_n, f"{kml_namespace}hotSpot", x="32", xunits="pixels", y="64", yunits="insetPixels")
        document.append(norm_icon)

        high_icon = ET.Element(f"{kml_namespace}Style", id=f"{icon_map_id}-highlight")
        is_h = ET.SubElement(high_icon, f"{kml_namespace}IconStyle")
        ET.SubElement(is_h, f"{kml_namespace}scale").text = "1"
        ET.SubElement(is_h, f"{kml_namespace}color").text = kml_color
        i_h = ET.SubElement(is_h, f"{kml_namespace}Icon")
        ET.SubElement(i_h, f"{kml_namespace}href").text = icon_url
        ET.SubElement(is_h, f"{kml_namespace}hotSpot", x="32", xunits="pixels", y="64", yunits="insetPixels")
        document.append(high_icon)

        icon_smap = ET.Element(f"{kml_namespace}StyleMap", id=icon_map_id)
        p3 = ET.SubElement(icon_smap, f"{kml_namespace}Pair")
        ET.SubElement(p3, f"{kml_namespace}key").text = "normal"
        ET.SubElement(p3, f"{kml_namespace}styleUrl").text = f"#{icon_map_id}-normal"
        p4 = ET.SubElement(icon_smap, f"{kml_namespace}Pair")
        ET.SubElement(p4, f"{kml_namespace}key").text = "highlight"
        ET.SubElement(p4, f"{kml_namespace}styleUrl").text = f"#{icon_map_id}-highlight"
        document.append(icon_smap)

    for folder_elem in folders.values():
        document.append(folder_elem)

    kml_str = ET.tostring(kml, encoding='utf-8', xml_declaration=True).decode('utf-8')
    
    kmz_io = io.BytesIO()
    with zipfile.ZipFile(kmz_io, 'w', zipfile.ZIP_DEFLATED) as kmz:
        kmz.writestr('doc.kml', kml_str)
        
    return kmz_io.getvalue()
                    
