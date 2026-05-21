import os
import time
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, LinearRing

INPUT_GEOJSON = "special_use_airspace/Special_Use_Airspace.geojson"
OUTPUT_GEOJSON = "special_use_airspace/Special_Use_Airspace_optimized.geojson"
OUTPUT_CSV = "special_use_airspace/Special_Use_Airspace_optimized.csv"
TOLERANCE = 0.005


def get_file_size(file_path):
    size = os.path.getsize(file_path)
    return round(size / (1024 * 1024), 2)  # in MB


def read_geo():
    gdf = gpd.read_file(INPUT_GEOJSON)
    print(f"Input geojson file size: {get_file_size(INPUT_GEOJSON)} MB")
    return gdf


def round_coords(coords, precision=6):
    return [[round(coord, precision) for coord in point] for point in coords]


def optimize_geo(gdf):
    # Do some optimization
    gdf["geometry"] = gdf["geometry"].simplify(TOLERANCE, preserve_topology=True)

    # round the coordinates
    new_geometries = []
    for feature in gdf["geometry"]:
        if feature.geom_type == "Polygon":
            exterior = LinearRing(round_coords(feature.exterior.coords))
            interiors = [
                LinearRing(round_coords(interior.coords))
                for interior in feature.interiors
            ]
            new_geometries.append(Polygon(exterior, interiors))
        elif feature.geom_type == "MultiPolygon":
            new_polygons = []
            for polygon in feature:
                exterior = LinearRing(round_coords(polygon.exterior.coords))
                interiors = [
                    LinearRing(round_coords(interior.coords))
                    for interior in polygon.interiors
                ]
                new_polygons.append(Polygon(exterior, interiors))
            new_geometries.append(MultiPolygon(new_polygons))
        else:
            new_geometries.append(feature)

    gdf["geometry"] = new_geometries

    # Save the optimized geojson
    gdf.to_file(OUTPUT_GEOJSON, driver="GeoJSON")
    print(f"Output GeoJSON size: {get_file_size(OUTPUT_GEOJSON)} MB")

    gdf.to_csv(OUTPUT_CSV, index=False)
    print(f"Output CSV size: {get_file_size(OUTPUT_CSV)} MB")
    return gdf


def main():
    print("\nStarting optimization...")
    start_time = time.time()
    gdf = read_geo()
    optimized_gdf = optimize_geo(gdf)
    print(optimized_gdf.head())
    print("Optimization completed.")
    print(f"Time taken: {round(time.time() - start_time, 2)} seconds")


if __name__ == "__main__":
    main()
