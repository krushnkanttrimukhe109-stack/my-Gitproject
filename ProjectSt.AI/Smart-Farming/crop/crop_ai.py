def identify_crop(soil, rainfall, temperature):
    if soil == "Clay" and rainfall > 1000:
        return "Rice"
    elif soil == "Loam" and temperature < 30:
        return "Wheat"
    elif soil == "Sandy":
        return "Maize"
    elif soil == "Black":
        return "Cotton"
    else:
        return "Sugarcane"