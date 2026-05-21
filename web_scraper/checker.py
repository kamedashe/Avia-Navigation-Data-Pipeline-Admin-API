import geopandas as gpd
from matplotlib import pyplot as plt

CLASS_AIRSPACE = "class_airspace/Class_Airspace_optimized.geojson"
SPECIAL_USE_AIRSPACE = "special_use_airspace/Special_Use_Airspace_optimized.geojson"

cls_airsp_gdf = gpd.read_file(CLASS_AIRSPACE)
special_airsp_gdf = gpd.read_file(SPECIAL_USE_AIRSPACE)

print(cls_airsp_gdf.head())
print(special_airsp_gdf.head())

cls_airsp_gdf = cls_airsp_gdf.to_crs("EPSG:3395")

# Plot the Class Airspace GeoDataFrame
fig1, ax1 = plt.subplots(1, 1, figsize=(10, 10))
cls_airsp_gdf.plot(ax=ax1, legend=True, color="blue", edgecolor="black")
plt.title("Class Airspace")
plt.savefig("images/class_airspace_plot.png", dpi=600)

# Plot the Special Use Airspace GeoDataFrame
fig2, ax2 = plt.subplots(1, 1, figsize=(10, 10))
special_airsp_gdf.plot(ax=ax2, legend=True, color="red", edgecolor="black")
plt.title("Special Use Airspace")
plt.savefig("images/special_use_airspace_plot.png", dpi=600)

# Show the plots
plt.show()
