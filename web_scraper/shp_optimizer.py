import csv
import os
import time
import geopandas as gpd
from shapely.geometry import Polygon, LinearRing

from .settings import OUTPUT_DIR, TOLERANCE, DOWNLOAD_DIR


# INPUT_SHP = "special_use_airspace/Special_Use_Airspace.shp"
# OUTPUT_GEOJSON = "special_use_airspace/Special_Use_Airspace_optimized_from_shp.geojson"
INPUT_SHP = "class_airspace/Class_Airspace.shp"
OUTPUT_GEOJSON = "Class_Airspace_optimized.geojson"
OUTPUT_CSV = "Class_Airspace_optimized.csv"


def get_file_size(file_path):
    size = os.path.getsize(file_path)
    return round(size / 1024, 2)  # in KB


def read_shp(shp_file_path=INPUT_SHP):
    gdf = gpd.read_file(shp_file_path)
    print(f"\nInput SHP file size: {get_file_size(shp_file_path)} KB\n")
    return gdf


def round_coords(coords, precision=6):
    return [[round(coord, precision) for coord in point] for point in coords]


def optimize_to_geojson(gdf, output_geojson=OUTPUT_GEOJSON):
    # Simplify and round geometry
    gdf["geometry"] = gdf["geometry"].apply(lambda g: optimize_geometry(g, tolerance=0.00001, precision=5))

    # Set the CRS if not already set
    if gdf.crs is None:
        gdf.set_crs("EPSG:4326", inplace=True)  # Assuming WGS84 CRS

    # Save the optimized geojson
    gdf.to_file(output_geojson, driver="GeoJSON")
    print(f"Output GeoJSON size: {get_file_size(output_geojson)} KB")
    return gdf


def optimize_to_csv(gdf, output_csv=OUTPUT_CSV):
    # Debugging: Check the columns
    print(f"Columns in the input GeoDataFrame: {gdf.columns}")
    # Define the columns to keep
    columns_to_keep = [
        "IDENT",
        "NAME",
        "UPPER_VAL",
        "UPPER_CODE",
        "LOWER_VAL",
        "LOWER_CODE",
        "CLASS",
        "SECTOR",
        "SHAPE_Leng",
        "SHAPE_Area",
        "geometry",
    ]
    
    # Simplify and round geometry
    gdf["geometry"] = gdf["geometry"].apply(lambda g: optimize_geometry(g, tolerance=0.00001, precision=5))

    # Check if all required columns are present
    missing_columns = set(columns_to_keep) - set(gdf.columns)
    if missing_columns:
        raise KeyError(f"Missing columns: {missing_columns}")

    # Drop columns not needed
    gdf = gdf[columns_to_keep]

    # Filter rows based on CLASS column
    gdf = gdf[gdf["CLASS"].isin(["B", "C", "D"])]

    # Set the CRS if not already set
    if gdf.crs is None:
        gdf.set_crs("EPSG:4326", inplace=True)  # Assuming WGS84 CRS

    # Define the output file path
    output_file_path = os.path.join(OUTPUT_DIR, output_csv)

    # Convert geometry to WKT for CSV export
    gdf_copy = gdf.copy()
    gdf_copy['geometry'] = gdf_copy['geometry'].apply(lambda geom: geom.wkt if geom is not None else None)
    
    # Save as CSV using pandas — QUOTE_MINIMAL ensures fields with commas
    # (e.g. geometry WKT, date ranges) are properly double-quoted.
    gdf_copy.to_csv(output_csv, index=False, quoting=csv.QUOTE_MINIMAL, quotechar='"')
    print(f"Output CSV size: {get_file_size(output_csv)} KB")
    return output_file_path


def optimize_geometry(geom, tolerance=0.00001, precision=5):
    """
    Simplify and round coordinates of a shapely geometry.
    """
    if geom is None:
        return None
    
    # Simplify
    geom = geom.simplify(tolerance, preserve_topology=True)
    
    if geom.geom_type == "Polygon":
        exterior = LinearRing(round_coords(geom.exterior.coords, precision))
        interiors = [
            LinearRing(round_coords(interior.coords, precision))
            for interior in geom.interiors
        ]
        return Polygon(exterior, interiors)
    elif geom.geom_type == "MultiPolygon":
        from shapely.geometry import MultiPolygon
        polys = []
        for g in geom.geoms:
            exterior = LinearRing(round_coords(g.exterior.coords, precision))
            interiors = [
                LinearRing(round_coords(interior.coords, precision))
                for interior in g.interiors
            ]
            polys.append(Polygon(exterior, interiors))
        return MultiPolygon(polys)
    elif geom.geom_type == "Point":
        from shapely.geometry import Point
        return Point(round(geom.x, precision), round(geom.y, precision))
    return geom


def create_class_airspace(
    shape_file_path, download_dir=DOWNLOAD_DIR, output_dir=OUTPUT_DIR
):
    """
    Create a Class_Airspace.csv file from a shapefile.
    """
    print("Creating Class_Airspace.csv ...")
    file_name = os.path.join(download_dir, shape_file_path)

    gdf = gpd.read_file(file_name)
    
    output_filename = "c.csv.gz"
    output_file_path = os.path.join(output_dir, output_filename)
    
    # Process and save the file
    columns_to_keep = [
        "IDENT",
        "NAME",
        "UPPER_VAL",
        "UPPER_UOM",
        "LOWER_VAL",
        "LOWER_UOM",
        "CLASS",
        "geometry",
    ]
    
    # Check if all required columns exist
    missing_columns = set(columns_to_keep) - set(gdf.columns)
    if missing_columns:
        raise KeyError(f"Missing columns: {missing_columns}")
    
    # Keep only required columns
    gdf = gdf[columns_to_keep]
    
    # Filter by CLASS
    gdf = gdf[gdf["CLASS"].isin(["B", "C", "D"])]
    
    # Set CRS if needed
    if gdf.crs is None:
        gdf.set_crs("EPSG:4326", inplace=True)
        
    # Apply optimization (Simplify and Round)
    gdf["geometry"] = gdf["geometry"].apply(lambda g: optimize_geometry(g, tolerance=0.00001, precision=5))
    
    # Convert geometry to WKT for CSV export
    gdf_copy = gdf.copy()
    gdf_copy['geometry'] = gdf_copy['geometry'].apply(lambda geom: geom.wkt if geom is not None else None)
    
    # Save as CSV — QUOTE_MINIMAL wraps comma-containing fields in double quotes
    gdf_copy.to_csv(output_file_path, index=False, quoting=csv.QUOTE_MINIMAL, quotechar='"')
    print(f"Output CSV size: {get_file_size(output_file_path)} KB")
    print(f"Saved to: {output_file_path}")
    
    return output_file_path


def _extract_altitude(gdf, field_candidates, default_value):
    """Search GeoDataFrame columns for altitude data.

    Checks ``field_candidates`` (case-insensitive) in order and returns
    the first column that exists.  Falls back to ``default_value``.
    """
    cols_lower = {c.lower(): c for c in gdf.columns}
    for candidate in field_candidates:
        real_col = cols_lower.get(candidate.lower())
        if real_col is not None:
            return gdf[real_col].fillna(default_value)
    return default_value


def _extract_alt_type(gdf, field_candidates, default_type="MSL"):
    """Search GeoDataFrame columns for altitude-type data (MSL / AGL).

    Falls back to ``default_type`` if nothing is found.
    """
    cols_lower = {c.lower(): c for c in gdf.columns}
    for candidate in field_candidates:
        real_col = cols_lower.get(candidate.lower())
        if real_col is not None:
            return gdf[real_col].fillna(default_type)
    return default_type


def optimize_shape_trf_file(gdf, output_csv=OUTPUT_CSV):
    """Optimize TFR shapefile data and remap to mobile-app schema.

    Target columns (strict order):
        NOTAM_ID, TFR_TYPE, TFR_AREA, LOWER_ALT, LALT_TYPE,
        UPPER_ALT, UALT_TYPE, EFFECTIVE, geometry

    Converts geometry to WKT strings and uses ``csv.QUOTE_MINIMAL`` so
    that fields containing commas (EFFECTIVE dates, POLYGON WKT) are
    properly wrapped in double quotes — required by the mobile client.
    """
    # Ensure the directory for the output CSV exists
    output_dir_path = os.path.dirname(output_csv)
    if output_dir_path and not os.path.exists(output_dir_path):
        os.makedirs(output_dir_path)

    # Simplify and round geometry
    gdf["geometry"] = gdf["geometry"].apply(
        lambda g: optimize_geometry(g, tolerance=0.00001, precision=5)
    )

    # Check for invalid geometries
    gdf = gdf[gdf.geometry.notnull() & gdf.geometry.is_valid]
    gdf = gdf[~gdf.geometry.is_empty]

    # Set the CRS if not already set
    if gdf.crs is None:
        gdf.set_crs("EPSG:4326", inplace=True)

    # ------------------------------------------------------------------
    # Build a helper dict: lowercase column name → original column name
    # ------------------------------------------------------------------
    cols_lower = {c.lower(): c for c in gdf.columns}

    # ------------------------------------------------------------------
    # NOTAM_ID  ← NOTAM_KEY | NOTAM_ID | GID (first match wins)
    # ------------------------------------------------------------------
    notam_candidates = ["notam_key", "notam_id", "gid"]
    notam_col = None
    for c in notam_candidates:
        if c in cols_lower:
            notam_col = cols_lower[c]
            break
    notam_id = gdf[notam_col].astype(str) if notam_col else "UNKNOWN"

    # ------------------------------------------------------------------
    # TFR_TYPE  ← LEGAL | TYPE | TYPE_CODE (mapped to short-type)
    # ------------------------------------------------------------------
    type_candidates = ["legal", "type", "type_code"]
    type_col = None
    for c in type_candidates:
        if c in cols_lower:
            type_col = cols_lower[c]
            break
    if type_col is not None:
        tfr_type = gdf[type_col].fillna("Other").astype(str)
    else:
        tfr_type = "Other"

    # ------------------------------------------------------------------
    # TFR_AREA  ← TITLE | CNS_LOCATI | NAME | STATE
    # ------------------------------------------------------------------
    area_candidates = ["title", "cns_locati", "name", "state"]
    area_col = None
    for c in area_candidates:
        if c in cols_lower:
            area_col = cols_lower[c]
            break
    tfr_area = gdf[area_col].fillna("").astype(str) if area_col else ""

    # ------------------------------------------------------------------
    # Altitude fields: LOWER_ALT, LALT_TYPE, UPPER_ALT, UALT_TYPE
    # FAA shapefiles may contain: LOWALT / MIN_ALT / LOWER_VAL / FLOOR
    #                              HIALT  / MAX_ALT / UPPER_VAL / CEILING
    #   Type columns:              LOWALT_TYPE / LOWER_UOM / LOWTYPECD
    #                              HIALT_TYPE  / UPPER_UOM / HIGHTYPECD
    # ------------------------------------------------------------------
    lower_alt = _extract_altitude(
        gdf,
        ["lowalt", "min_alt", "lower_val", "floor", "low_alt"],
        default_value=0,
    )
    lalt_type = _extract_alt_type(
        gdf,
        ["lowalt_type", "lower_uom", "lowtypecd", "lalt_type"],
        default_type="MSL",
    )
    upper_alt = _extract_altitude(
        gdf,
        ["hialt", "max_alt", "upper_val", "ceiling", "hi_alt"],
        default_value=2400,
    )
    ualt_type = _extract_alt_type(
        gdf,
        ["hialt_type", "upper_uom", "hightypecd", "ualt_type"],
        default_type="MSL",
    )

    # ------------------------------------------------------------------
    # EFFECTIVE  — already set by the caller; format nicely if needed.
    # Expected format: "From [START_DATE] to [END_DATE]"
    # ------------------------------------------------------------------
    if "EFFECTIVE" in gdf.columns:
        effective = gdf["EFFECTIVE"].fillna("").astype(str)
    else:
        # Try composing from date fields
        start_col = cols_lower.get("last_modif") or cols_lower.get("start_date")
        end_col = cols_lower.get("end_date")
        if start_col and end_col:
            effective = (
                "From " + gdf[start_col].fillna("").astype(str)
                + " to " + gdf[end_col].fillna("").astype(str)
            )
        elif start_col:
            effective = "From " + gdf[start_col].fillna("").astype(str)
        else:
            effective = ""

    # ------------------------------------------------------------------
    # Convert geometry to WKT strings for CSV export
    # ------------------------------------------------------------------
    geometry_wkt = gdf["geometry"].apply(
        lambda geom: geom.wkt if geom is not None else None
    )

    # ------------------------------------------------------------------
    # Assemble the final DataFrame with STRICT column order
    # ------------------------------------------------------------------
    import pandas as pd

    final_columns = [
        "NOTAM_ID", "TFR_TYPE", "TFR_AREA",
        "LOWER_ALT", "LALT_TYPE", "UPPER_ALT", "UALT_TYPE",
        "EFFECTIVE", "geometry",
    ]
    final_df = pd.DataFrame({
        "NOTAM_ID":  notam_id,
        "TFR_TYPE":  tfr_type,
        "TFR_AREA":  tfr_area,
        "LOWER_ALT": lower_alt,
        "LALT_TYPE": lalt_type,
        "UPPER_ALT": upper_alt,
        "UALT_TYPE": ualt_type,
        "EFFECTIVE": effective,
        "geometry":  geometry_wkt,
    })[final_columns]

    # ------------------------------------------------------------------
    # Write CSV with proper quoting (RFC 4180)
    # csv.QUOTE_MINIMAL wraps only fields that contain the delimiter
    # (comma), quotechar, or newline.
    # ------------------------------------------------------------------
    final_df.to_csv(
        output_csv,
        index=False,
        quoting=csv.QUOTE_MINIMAL,
        quotechar='"',
    )
    print(f"Output CSV size: {get_file_size(output_csv)} KB")
    print(f"Output CSV columns: {list(final_df.columns)}")
    return gdf



def main():
    gdf = read_shp()
    optimized_gdf = optimize_to_geojson(gdf)
    print(optimized_gdf.head())


if __name__ == "__main__":
    print("Optimizing the shape file...")
    start_time = time.time()
    main()
    print(f"\nTime taken: {round(time.time() - start_time, 2)} seconds")
    print("Optimization completed successfully!")
