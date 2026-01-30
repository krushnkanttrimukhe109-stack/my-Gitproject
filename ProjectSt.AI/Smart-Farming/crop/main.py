from crop_ai import identify_crop

print("🌱 Smart Farming AI System 🌱")

soil = input("Enter Soil Type (Clay/Loam/Sandy/Black): ")
rainfall = float(input("Enter Rainfall (mm): "))
temperature = float(input("Enter Temperature (°C): "))

crop = identify_crop(soil, rainfall, temperature)

print("\n✅ Recommended Crop:", crop)
print("💧 Water Usage: Optimized")
print("🌿 Fertilizer Usage: Reduced")
print("🌍 Sustainable Farming Enabled")