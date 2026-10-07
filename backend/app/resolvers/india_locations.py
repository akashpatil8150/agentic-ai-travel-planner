import math
from typing import Dict, List, Any, Optional, Tuple

# ============================================================
# HAVERSINE & ROAD DISTANCE CALCULATION
# ============================================================

def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate geographical distance between two lat/lon points in kilometers."""
    R = 6371.0  # Earth's radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 1)


def estimate_road_transfer(lat1: float, lon1: float, lat2: float, lon2: float, is_hilly: bool = False) -> Dict[str, Any]:
    """
    Estimate realistic road distance (km) and transfer duration based on geographic coordinates.
    Hilly routes use a higher winding factor and lower average speed.
    """
    direct_km = haversine_distance_km(lat1, lon1, lat2, lon2)
    
    if direct_km < 1.0:
        return {
            "road_distance_km": 5,
            "estimated_transfer_time": "15m",
            "duration_minutes": 15,
            "is_direct": True,
        }

    # Road winding factor: 2.15 for long-distance Himalayan mountain routes (>100 km), 1.55 for regional hills, 1.35 for plains
    if is_hilly and direct_km > 100:
        winding_factor = 2.15
        avg_speed_kmh = 35.0
    elif is_hilly or direct_km > 100:
        winding_factor = 1.55
        avg_speed_kmh = 38.0 if is_hilly else 48.0
    else:
        winding_factor = 1.35
        avg_speed_kmh = 45.0

    road_km = int(round(direct_km * winding_factor))
    total_hours = road_km / avg_speed_kmh
    
    hours = int(total_hours)
    minutes = int(round((total_hours - hours) * 60))
    if minutes == 60:
        hours += 1
        minutes = 0
        
    duration_str = f"~{hours}h {minutes:02d}m" if hours > 0 else f"~{minutes}m"
    duration_mins = hours * 60 + minutes

    return {
        "road_distance_km": road_km,
        "estimated_transfer_time": duration_str,
        "duration_minutes": duration_mins,
        "is_direct": False,
    }


# ============================================================
# COMPREHENSIVE INDIA LOCATIONS, STATIONS & AIRPORTS DATASET
# ============================================================

INDIA_LOCATIONS: Dict[str, Dict[str, Any]] = {
    "panvel": {
        "name": "Panvel",
        "state": "Maharashtra",
        "lat": 18.9894,
        "lon": 73.1175,
        "is_hilly": False,
        "stations": [
            {"code": "PNVL", "name": "Panvel Junction", "city": "Panvel", "lat": 18.9894, "lon": 73.1175, "is_major": True},
            {"code": "LTT", "name": "Lokmanya Tilak Terminus", "city": "Mumbai", "lat": 19.0688, "lon": 72.8906, "is_major": True},
            {"code": "CSMT", "name": "Chhatrapati Shivaji Maharaj Terminus", "city": "Mumbai", "lat": 18.9400, "lon": 72.8355, "is_major": True},
        ],
        "airports": [
            {"code": "BOM", "name": "Chhatrapati Shivaji Maharaj International Airport", "city": "Mumbai", "lat": 19.0896, "lon": 72.8656, "is_major": True},
        ],
    },
    "navi mumbai": {
        "name": "Navi Mumbai",
        "state": "Maharashtra",
        "lat": 19.0330,
        "lon": 73.0297,
        "is_hilly": False,
        "stations": [
            {"code": "PNVL", "name": "Panvel Junction", "city": "Panvel", "lat": 18.9894, "lon": 73.1175, "is_major": True},
            {"code": "LTT", "name": "Lokmanya Tilak Terminus", "city": "Mumbai", "lat": 19.0688, "lon": 72.8906, "is_major": True},
        ],
        "airports": [
            {"code": "BOM", "name": "Chhatrapati Shivaji Maharaj International Airport", "city": "Mumbai", "lat": 19.0896, "lon": 72.8656, "is_major": True},
        ],
    },
    "thane": {
        "name": "Thane",
        "state": "Maharashtra",
        "lat": 19.2183,
        "lon": 72.9781,
        "is_hilly": False,
        "stations": [
            {"code": "TNA", "name": "Thane Junction", "city": "Thane", "lat": 19.1860, "lon": 72.9750, "is_major": True},
            {"code": "LTT", "name": "Lokmanya Tilak Terminus", "city": "Mumbai", "lat": 19.0688, "lon": 72.8906, "is_major": True},
        ],
        "airports": [
            {"code": "BOM", "name": "Chhatrapati Shivaji Maharaj International Airport", "city": "Mumbai", "lat": 19.0896, "lon": 72.8656, "is_major": True},
        ],
    },
    "kalyan": {
        "name": "Kalyan",
        "state": "Maharashtra",
        "lat": 19.2437,
        "lon": 73.1355,
        "is_hilly": False,
        "stations": [
            {"code": "KYN", "name": "Kalyan Junction", "city": "Kalyan", "lat": 19.2355, "lon": 73.1300, "is_major": True},
            {"code": "LTT", "name": "Lokmanya Tilak Terminus", "city": "Mumbai", "lat": 19.0688, "lon": 72.8906, "is_major": True},
        ],
        "airports": [
            {"code": "BOM", "name": "Chhatrapati Shivaji Maharaj International Airport", "city": "Mumbai", "lat": 19.0896, "lon": 72.8656, "is_major": True},
        ],
    },
    "mumbai": {
        "name": "Mumbai",
        "state": "Maharashtra",
        "lat": 18.9388,
        "lon": 72.8353,
        "is_hilly": False,
        "stations": [
            {"code": "CSMT", "name": "Chhatrapati Shivaji Maharaj Terminus", "city": "Mumbai", "lat": 18.9400, "lon": 72.8355, "is_major": True},
            {"code": "LTT", "name": "Lokmanya Tilak Terminus", "city": "Mumbai", "lat": 19.0688, "lon": 72.8906, "is_major": True},
            {"code": "BDTS", "name": "Bandra Terminus", "city": "Mumbai", "lat": 19.0632, "lon": 72.8407, "is_major": True},
            {"code": "MMCT", "name": "Mumbai Central", "city": "Mumbai", "lat": 18.9696, "lon": 72.8193, "is_major": True},
            {"code": "DR", "name": "Dadar", "city": "Mumbai", "lat": 19.0180, "lon": 72.8438, "is_major": True, "aliases": ["dadar", "dadar central", "dadar railway station"]},
            {"code": "ADH", "name": "Andheri", "city": "Mumbai", "lat": 19.1197, "lon": 72.8468, "is_major": True, "aliases": ["andheri", "andheri railway station"]},
            {"code": "BVI", "name": "Borivali", "city": "Mumbai", "lat": 19.2290, "lon": 72.8574, "is_major": True, "aliases": ["borivali", "borivali railway station"]},
            {"code": "CLA", "name": "Kurla", "city": "Mumbai", "lat": 19.0726, "lon": 72.8797, "is_major": True, "aliases": ["kurla", "kurla railway station"]},
        ],
        "airports": [
            {"code": "BOM", "name": "Chhatrapati Shivaji Maharaj International Airport", "city": "Mumbai", "lat": 19.0896, "lon": 72.8656, "is_major": True},
        ],
    },
    "pune": {
        "name": "Pune",
        "state": "Maharashtra",
        "lat": 18.5204,
        "lon": 73.8567,
        "is_hilly": False,
        "stations": [
            {"code": "PUNE", "name": "Pune Junction", "city": "Pune", "lat": 18.5289, "lon": 73.8744, "is_major": True},
        ],
        "airports": [
            {"code": "PNQ", "name": "Pune Airport", "city": "Pune", "lat": 18.5822, "lon": 73.9197, "is_major": True},
        ],
    },
    "delhi": {
        "name": "Delhi",
        "state": "Delhi",
        "lat": 28.6139,
        "lon": 77.2090,
        "is_hilly": False,
        "stations": [
            {"code": "NDLS", "name": "New Delhi Railway Station", "city": "Delhi", "lat": 28.6425, "lon": 77.2195, "is_major": True},
            {"code": "DLI", "name": "Old Delhi Railway Station", "city": "Delhi", "lat": 28.6616, "lon": 77.2274, "is_major": True},
            {"code": "NZM", "name": "Hazrat Nizamuddin", "city": "Delhi", "lat": 28.5892, "lon": 77.2530, "is_major": True},
            {"code": "ANVT", "name": "Anand Vihar Terminal", "city": "Delhi", "lat": 28.6508, "lon": 77.3152, "is_major": True},
        ],
        "airports": [
            {"code": "DEL", "name": "Indira Gandhi International Airport", "city": "Delhi", "lat": 28.5562, "lon": 77.1000, "is_major": True},
        ],
    },
    "bengaluru": {
        "name": "Bengaluru",
        "state": "Karnataka",
        "lat": 12.9716,
        "lon": 77.5946,
        "is_hilly": False,
        "stations": [
            {"code": "SBC", "name": "KSR Bengaluru City Junction", "city": "Bengaluru", "lat": 12.9781, "lon": 77.5694, "is_major": True},
            {"code": "YPR", "name": "Yesvantpur Junction", "city": "Bengaluru", "lat": 13.0238, "lon": 77.5504, "is_major": True},
        ],
        "airports": [
            {"code": "BLR", "name": "Kempegowda International Airport", "city": "Bengaluru", "lat": 13.1986, "lon": 77.7066, "is_major": True},
        ],
    },
    "hyderabad": {
        "name": "Hyderabad",
        "state": "Telangana",
        "lat": 17.3850,
        "lon": 78.4867,
        "is_hilly": False,
        "stations": [
            {"code": "SC", "name": "Secunderabad Junction", "city": "Hyderabad", "lat": 17.4339, "lon": 78.5016, "is_major": True},
            {"code": "HYB", "name": "Hyderabad Deccan (Nampally)", "city": "Hyderabad", "lat": 17.3930, "lon": 78.4682, "is_major": True},
        ],
        "airports": [
            {"code": "HYD", "name": "Rajiv Gandhi International Airport", "city": "Hyderabad", "lat": 17.2403, "lon": 78.4294, "is_major": True},
        ],
    },
    "chennai": {
        "name": "Chennai",
        "state": "Tamil Nadu",
        "lat": 13.0827,
        "lon": 80.2707,
        "is_hilly": False,
        "stations": [
            {"code": "MAS", "name": "Chennai Central", "city": "Chennai", "lat": 13.0825, "lon": 80.2757, "is_major": True},
            {"code": "MS", "name": "Chennai Egmore", "city": "Chennai", "lat": 13.0784, "lon": 80.2612, "is_major": True},
        ],
        "airports": [
            {"code": "MAA", "name": "Chennai International Airport", "city": "Chennai", "lat": 12.9941, "lon": 80.1709, "is_major": True},
        ],
    },
    "kolkata": {
        "name": "Kolkata",
        "state": "West Bengal",
        "lat": 22.5726,
        "lon": 88.3639,
        "is_hilly": False,
        "stations": [
            {"code": "HWH", "name": "Howrah Junction", "city": "Kolkata", "lat": 22.5839, "lon": 88.3428, "is_major": True},
            {"code": "SDAH", "name": "Sealdah", "city": "Kolkata", "lat": 22.5670, "lon": 88.3712, "is_major": True},
            {"code": "KOAA", "name": "Kolkata Railway Station", "city": "Kolkata", "lat": 22.6019, "lon": 88.3789, "is_major": True},
        ],
        "airports": [
            {"code": "CCU", "name": "Netaji Subhas Chandra Bose International Airport", "city": "Kolkata", "lat": 22.6547, "lon": 88.4467, "is_major": True},
        ],
    },
    "ahmedabad": {
        "name": "Ahmedabad",
        "state": "Gujarat",
        "lat": 23.0225,
        "lon": 72.5714,
        "is_hilly": False,
        "stations": [
            {"code": "ADI", "name": "Ahmedabad Junction", "city": "Ahmedabad", "lat": 23.0216, "lon": 72.6006, "is_major": True},
        ],
        "airports": [
            {"code": "AMD", "name": "Sardar Vallabhbhai Patel International Airport", "city": "Ahmedabad", "lat": 23.0772, "lon": 72.6347, "is_major": True},
        ],
    },
    "jaipur": {
        "name": "Jaipur",
        "state": "Rajasthan",
        "lat": 26.9124,
        "lon": 75.7873,
        "is_hilly": False,
        "stations": [
            {"code": "JP", "name": "Jaipur Junction", "city": "Jaipur", "lat": 26.9202, "lon": 75.7878, "is_major": True},
        ],
        "airports": [
            {"code": "JAI", "name": "Jaipur International Airport", "city": "Jaipur", "lat": 26.8242, "lon": 75.8122, "is_major": True},
        ],
    },
    "goa": {
        "name": "Goa",
        "state": "Goa",
        "lat": 15.2993,
        "lon": 74.1240,
        "is_hilly": False,
        "stations": [
            {"code": "MAO", "name": "Madgaon Junction", "city": "Goa", "lat": 15.2740, "lon": 73.9806, "is_major": True},
            {"code": "VSG", "name": "Vasco da Gama", "city": "Goa", "lat": 15.3970, "lon": 73.8118, "is_major": True},
            {"code": "KRMI", "name": "Karmali", "city": "Goa", "lat": 15.4892, "lon": 73.9189, "is_major": False},
        ],
        "airports": [
            {"code": "GOI", "name": "Dabolim International Airport", "city": "Goa", "lat": 15.3808, "lon": 73.8314, "is_major": True},
            {"code": "GOX", "name": "Manohar International Airport (Mopa)", "city": "Goa", "lat": 15.7667, "lon": 73.8667, "is_major": True},
        ],
    },
    "manali": {
        "name": "Manali",
        "state": "Himachal Pradesh",
        "lat": 32.2432,
        "lon": 77.1892,
        "is_hilly": True,
        "stations": [],  # Hill station - no direct train terminal
        "airports": [
            {"code": "KUU", "name": "Kullu Manali Airport (Bhuntar)", "city": "Kullu", "lat": 31.8767, "lon": 77.1542, "is_major": False},
        ],
    },
    "kullu": {
        "name": "Kullu",
        "state": "Himachal Pradesh",
        "lat": 31.9579,
        "lon": 77.1095,
        "is_hilly": True,
        "stations": [],
        "airports": [
            {"code": "KUU", "name": "Kullu Manali Airport (Bhuntar)", "city": "Kullu", "lat": 31.8767, "lon": 77.1542, "is_major": True},
        ],
    },
    "shimla": {
        "name": "Shimla",
        "state": "Himachal Pradesh",
        "lat": 31.1048,
        "lon": 77.1734,
        "is_hilly": True,
        "stations": [
            {"code": "SML", "name": "Shimla Railway Station (Toy Train)", "city": "Shimla", "lat": 31.1030, "lon": 77.1666, "is_major": False},
        ],
        "airports": [
            {"code": "SLV", "name": "Shimla Jubbarhatti Airport", "city": "Shimla", "lat": 31.0818, "lon": 77.0686, "is_major": False},
        ],
    },
    "chandigarh": {
        "name": "Chandigarh",
        "state": "Chandigarh UT",
        "lat": 30.7333,
        "lon": 76.7794,
        "is_hilly": False,
        "stations": [
            {"code": "CDG", "name": "Chandigarh Junction", "city": "Chandigarh", "lat": 30.7060, "lon": 76.8242, "is_major": True},
        ],
        "airports": [
            {"code": "IXC", "name": "Shaheed Bhagat Singh International Airport", "city": "Chandigarh", "lat": 30.6735, "lon": 76.7885, "is_major": True},
        ],
    },
    "kalka": {
        "name": "Kalka",
        "state": "Haryana",
        "lat": 30.8358,
        "lon": 76.9356,
        "is_hilly": False,
        "stations": [
            {"code": "KLK", "name": "Kalka Railway Station", "city": "Kalka", "lat": 30.8340, "lon": 76.9348, "is_major": True},
        ],
        "airports": [],
    },
    "ambala": {
        "name": "Ambala",
        "state": "Haryana",
        "lat": 30.3782,
        "lon": 76.7767,
        "is_hilly": False,
        "stations": [
            {"code": "UMB", "name": "Ambala Cantt Junction", "city": "Ambala", "lat": 30.3340, "lon": 76.8377, "is_major": True},
        ],
        "airports": [],
    },
    "leh": {
        "name": "Leh",
        "state": "Ladakh",
        "lat": 34.1526,
        "lon": 77.5771,
        "is_hilly": True,
        "stations": [],  # High altitude - no railway line
        "airports": [
            {"code": "IXL", "name": "Kushok Bakula Rimpochee Airport", "city": "Leh", "lat": 34.1359, "lon": 77.5465, "is_major": True},
        ],
    },
    "srinagar": {
        "name": "Srinagar",
        "state": "Jammu & Kashmir",
        "lat": 34.0837,
        "lon": 74.7973,
        "is_hilly": True,
        "stations": [
            {"code": "SINA", "name": "Srinagar Railway Station", "city": "Srinagar", "lat": 33.9961, "lon": 74.7915, "is_major": False},
        ],
        "airports": [
            {"code": "SXR", "name": "Sheikh ul-Alam International Airport", "city": "Srinagar", "lat": 33.9871, "lon": 74.7741, "is_major": True},
        ],
    },
    "jammu": {
        "name": "Jammu",
        "state": "Jammu & Kashmir",
        "lat": 32.7266,
        "lon": 74.8570,
        "is_hilly": False,
        "stations": [
            {"code": "JAT", "name": "Jammu Tawi", "city": "Jammu", "lat": 32.7061, "lon": 74.8802, "is_major": True},
        ],
        "airports": [
            {"code": "IXJ", "name": "Jammu Airport", "city": "Jammu", "lat": 32.6891, "lon": 74.8374, "is_major": True},
        ],
    },
    "darjeeling": {
        "name": "Darjeeling",
        "state": "West Bengal",
        "lat": 27.0410,
        "lon": 88.2663,
        "is_hilly": True,
        "stations": [
            {"code": "DJ", "name": "Darjeeling Toy Train Station", "city": "Darjeeling", "lat": 27.0390, "lon": 88.2630, "is_major": False},
        ],
        "airports": [],
    },
    "siliguri": {
        "name": "Siliguri / New Jalpaiguri",
        "state": "West Bengal",
        "lat": 26.7271,
        "lon": 88.3953,
        "is_hilly": False,
        "stations": [
            {"code": "NJP", "name": "New Jalpaiguri Junction", "city": "Siliguri", "lat": 26.6859, "lon": 88.4428, "is_major": True},
            {"code": "SGUJ", "name": "Siliguri Junction", "city": "Siliguri", "lat": 26.7252, "lon": 88.4239, "is_major": True},
        ],
        "airports": [
            {"code": "IXB", "name": "Bagdogra International Airport", "city": "Siliguri", "lat": 26.6812, "lon": 88.3286, "is_major": True},
        ],
    },
    "rishikesh": {
        "name": "Rishikesh",
        "state": "Uttarakhand",
        "lat": 30.0869,
        "lon": 78.2676,
        "is_hilly": False,
        "stations": [
            {"code": "YNRK", "name": "Yog Nagari Rishikesh", "city": "Rishikesh", "lat": 30.0768, "lon": 78.2882, "is_major": True},
        ],
        "airports": [],
    },
    "haridwar": {
        "name": "Haridwar",
        "state": "Uttarakhand",
        "lat": 29.9457,
        "lon": 78.1642,
        "is_hilly": False,
        "stations": [
            {"code": "HW", "name": "Haridwar Junction", "city": "Haridwar", "lat": 29.9451, "lon": 78.1565, "is_major": True},
        ],
        "airports": [],
    },
    "dehradun": {
        "name": "Dehradun",
        "state": "Uttarakhand",
        "lat": 30.3165,
        "lon": 78.0322,
        "is_hilly": False,
        "stations": [
            {"code": "DDN", "name": "Dehradun Terminal", "city": "Dehradun", "lat": 30.3175, "lon": 78.0336, "is_major": True},
        ],
        "airports": [
            {"code": "DED", "name": "Dehradun Jolly Grant Airport", "city": "Dehradun", "lat": 30.1897, "lon": 78.1803, "is_major": True},
        ],
    },
    "ooty": {
        "name": "Ooty",
        "state": "Tamil Nadu",
        "lat": 11.4102,
        "lon": 76.6950,
        "is_hilly": True,
        "stations": [
            {"code": "UAM", "name": "Udagamandalam (Ooty Toy Train)", "city": "Ooty", "lat": 11.4057, "lon": 76.6917, "is_major": False},
        ],
        "airports": [],
    },
    "coimbatore": {
        "name": "Coimbatore",
        "state": "Tamil Nadu",
        "lat": 11.0168,
        "lon": 76.9558,
        "is_hilly": False,
        "stations": [
            {"code": "CBE", "name": "Coimbatore Junction", "city": "Coimbatore", "lat": 11.0006, "lon": 76.9672, "is_major": True},
            {"code": "MTP", "name": "Mettupalayam", "city": "Mettupalayam", "lat": 11.3000, "lon": 76.9500, "is_major": False},
        ],
        "airports": [
            {"code": "CJB", "name": "Coimbatore International Airport", "city": "Coimbatore", "lat": 11.0300, "lon": 77.0434, "is_major": True},
        ],
    },
    "kochi": {
        "name": "Kochi",
        "state": "Kerala",
        "lat": 9.9312,
        "lon": 76.2673,
        "is_hilly": False,
        "stations": [
            {"code": "ERS", "name": "Ernakulam Junction (South)", "city": "Kochi", "lat": 9.9670, "lon": 76.2905, "is_major": True},
            {"code": "ERN", "name": "Ernakulam Town (North)", "city": "Kochi", "lat": 9.9926, "lon": 76.2882, "is_major": True},
            {"code": "AWY", "name": "Aluva", "city": "Aluva", "lat": 10.1098, "lon": 76.3533, "is_major": True},
        ],
        "airports": [
            {"code": "COK", "name": "Cochin International Airport", "city": "Kochi", "lat": 10.1520, "lon": 76.4019, "is_major": True},
        ],
    },
    "munnar": {
        "name": "Munnar",
        "state": "Kerala",
        "lat": 10.0889,
        "lon": 77.0595,
        "is_hilly": True,
        "stations": [],
        "airports": [],
    },
    "udaipur": {
        "name": "Udaipur",
        "state": "Rajasthan",
        "lat": 24.5854,
        "lon": 73.7125,
        "is_hilly": False,
        "stations": [
            {"code": "UDZ", "name": "Udaipur City", "city": "Udaipur", "lat": 24.5702, "lon": 73.6974, "is_major": True},
        ],
        "airports": [
            {"code": "UDR", "name": "Maharana Pratap Airport", "city": "Udaipur", "lat": 24.6177, "lon": 73.8961, "is_major": True},
        ],
    },
    "jaisalmer": {
        "name": "Jaisalmer",
        "state": "Rajasthan",
        "lat": 26.9157,
        "lon": 70.9083,
        "is_hilly": False,
        "stations": [
            {"code": "JSM", "name": "Jaisalmer Railway Station", "city": "Jaisalmer", "lat": 26.9100, "lon": 70.9200, "is_major": True},
        ],
        "airports": [
            {"code": "JSA", "name": "Jaisalmer Airport", "city": "Jaisalmer", "lat": 26.8920, "lon": 70.8650, "is_major": False},
        ],
    },
    "amritsar": {
        "name": "Amritsar",
        "state": "Punjab",
        "lat": 31.6340,
        "lon": 74.8723,
        "is_hilly": False,
        "stations": [
            {"code": "ASR", "name": "Amritsar Junction", "city": "Amritsar", "lat": 31.6335, "lon": 74.8690, "is_major": True},
        ],
        "airports": [
            {"code": "ATQ", "name": "Sri Guru Ram Dass Jee International Airport", "city": "Amritsar", "lat": 31.7096, "lon": 74.7973, "is_major": True},
        ],
    },
    "varanasi": {
        "name": "Varanasi",
        "state": "Uttar Pradesh",
        "lat": 25.3176,
        "lon": 82.9739,
        "is_hilly": False,
        "stations": [
            {"code": "BSB", "name": "Varanasi Junction", "city": "Varanasi", "lat": 25.3278, "lon": 82.9864, "is_major": True},
            {"code": "BSBS", "name": "Banaras", "city": "Varanasi", "lat": 25.3117, "lon": 82.9669, "is_major": True},
            {"code": "DDU", "name": "Pt. Deen Dayal Upadhyaya Junction", "city": "Mughalsarai", "lat": 25.2816, "lon": 83.1190, "is_major": True},
        ],
        "airports": [
            {"code": "VNS", "name": "Lal Bahadur Shastri International Airport", "city": "Varanasi", "lat": 25.4524, "lon": 82.8593, "is_major": True},
        ],
    },
    "mysuru": {
        "name": "Mysuru",
        "state": "Karnataka",
        "lat": 12.2958,
        "lon": 76.6394,
        "is_hilly": False,
        "stations": [
            {"code": "MYS", "name": "Mysuru Junction", "city": "Mysuru", "lat": 12.3164, "lon": 76.6450, "is_major": True},
        ],
        "airports": [
            {"code": "MYQ", "name": "Mysore Airport", "city": "Mysuru", "lat": 12.2300, "lon": 76.6480, "is_major": False},
        ],
    },
    "coorg": {
        "name": "Coorg (Madikeri)",
        "state": "Karnataka",
        "lat": 12.4244,
        "lon": 75.7382,
        "is_hilly": True,
        "stations": [],
        "airports": [],
    },
    "gangtok": {
        "name": "Gangtok",
        "state": "Sikkim",
        "lat": 27.3389,
        "lon": 88.6065,
        "is_hilly": True,
        "stations": [],
        "airports": [
            {"code": "PYG", "name": "Pakyong Airport", "city": "Pakyong", "lat": 27.2344, "lon": 88.5886, "is_major": False},
        ],
    },
    "dharamshala": {
        "name": "Dharamshala",
        "state": "Himachal Pradesh",
        "lat": 32.2190,
        "lon": 76.3234,
        "is_hilly": True,
        "stations": [],
        "airports": [
            {"code": "DHM", "name": "Kangra Gaggal Airport", "city": "Dharamshala", "lat": 32.1651, "lon": 76.2634, "is_major": True},
        ],
    },
    "pathankot": {
        "name": "Pathankot",
        "state": "Punjab",
        "lat": 32.2643,
        "lon": 75.6420,
        "is_hilly": False,
        "stations": [
            {"code": "PTKC", "name": "Pathankot Cantt", "city": "Pathankot", "lat": 32.2530, "lon": 75.6450, "is_major": True},
            {"code": "PTK", "name": "Pathankot Junction", "city": "Pathankot", "lat": 32.2680, "lon": 75.6480, "is_major": True},
        ],
        "airports": [],
    },
    "manali": {
        "name": "Manali",
        "state": "Himachal Pradesh",
        "lat": 32.2396,
        "lon": 77.1887,
        "is_hilly": True,
        "stations": [],
        "airports": [
            {"code": "KUU", "name": "Kullu Manali Airport (Bhuntar)", "city": "Bhuntar", "lat": 31.8767, "lon": 77.1544, "is_major": False},
        ],
    },
    "shimla": {
        "name": "Shimla",
        "state": "Himachal Pradesh",
        "lat": 31.1048,
        "lon": 77.1734,
        "is_hilly": True,
        "stations": [
            {"code": "SML", "name": "Shimla Railway Station (Toy Train)", "city": "Shimla", "lat": 31.1030, "lon": 77.1650, "is_major": False},
        ],
        "airports": [
            {"code": "SLV", "name": "Shimla Airport (Jubbarhatti)", "city": "Shimla", "lat": 31.0817, "lon": 77.0683, "is_major": False},
        ],
    },
    "kullu": {
        "name": "Kullu",
        "state": "Himachal Pradesh",
        "lat": 31.9579,
        "lon": 77.1095,
        "is_hilly": True,
        "stations": [],
        "airports": [
            {"code": "KUU", "name": "Kullu Manali Airport", "city": "Bhuntar", "lat": 31.8767, "lon": 77.1544, "is_major": False},
        ],
    },
    "nainital": {
        "name": "Nainital",
        "state": "Uttarakhand",
        "lat": 29.3919,
        "lon": 79.4542,
        "is_hilly": True,
        "stations": [
            {"code": "KGM", "name": "Kathgodam", "city": "Kathgodam", "lat": 29.2730, "lon": 79.5410, "is_major": True},
        ],
        "airports": [
            {"code": "PGH", "name": "Pantnagar Airport", "city": "Pantnagar", "lat": 29.0322, "lon": 79.4736, "is_major": False},
        ],
    },
    "rishikesh": {
        "name": "Rishikesh",
        "state": "Uttarakhand",
        "lat": 30.0869,
        "lon": 78.2676,
        "is_hilly": True,
        "stations": [
            {"code": "YNRK", "name": "Yog Nagari Rishikesh", "city": "Rishikesh", "lat": 30.0980, "lon": 78.2890, "is_major": True},
        ],
        "airports": [
            {"code": "DED", "name": "Dehradun Jolly Grant Airport", "city": "Dehradun", "lat": 30.1897, "lon": 78.1803, "is_major": True},
        ],
    },
    "ooty": {
        "name": "Ooty (Udhagamandalam)",
        "state": "Tamil Nadu",
        "lat": 11.4102,
        "lon": 76.6950,
        "is_hilly": True,
        "stations": [
            {"code": "UAM", "name": "Udagamandalam", "city": "Ooty", "lat": 11.4050, "lon": 76.6960, "is_major": False},
        ],
        "airports": [
            {"code": "CJB", "name": "Coimbatore International Airport", "city": "Coimbatore", "lat": 11.0299, "lon": 77.0434, "is_major": True},
        ],
    },
    "munnar": {
        "name": "Munnar",
        "state": "Kerala",
        "lat": 10.0889,
        "lon": 77.0595,
        "is_hilly": True,
        "stations": [],
        "airports": [
            {"code": "COK", "name": "Cochin International Airport", "city": "Kochi", "lat": 10.1520, "lon": 76.4019, "is_major": True},
        ],
    },
    "leh": {
        "name": "Leh",
        "state": "Ladakh",
        "lat": 34.1526,
        "lon": 77.5771,
        "is_hilly": True,
        "stations": [],
        "airports": [
            {"code": "IXL", "name": "Kushok Bakula Rimpochee Airport", "city": "Leh", "lat": 34.1359, "lon": 77.5465, "is_major": True},
        ],
    },
    "srinagar": {
        "name": "Srinagar",
        "state": "Jammu and Kashmir",
        "lat": 34.0837,
        "lon": 74.7973,
        "is_hilly": True,
        "stations": [
            {"code": "SINA", "name": "Srinagar Railway Station", "city": "Srinagar", "lat": 34.0320, "lon": 74.8320, "is_major": True},
        ],
        "airports": [
            {"code": "SXR", "name": "Sheikh ul-Alam International Airport", "city": "Srinagar", "lat": 33.9871, "lon": 74.7741, "is_major": True},
        ],
    },
    "mussoorie": {
        "name": "Mussoorie",
        "state": "Uttarakhand",
        "lat": 30.4598,
        "lon": 78.0644,
        "is_hilly": True,
        "stations": [],
        "airports": [],
    },
    "agra": {
        "name": "Agra",
        "state": "Uttar Pradesh",
        "lat": 27.1767,
        "lon": 78.0081,
        "is_hilly": False,
        "stations": [
            {"code": "AGC", "name": "Agra Cantt", "city": "Agra", "lat": 27.1587, "lon": 77.9942, "is_major": True},
            {"code": "AF", "name": "Agra Fort", "city": "Agra", "lat": 27.1824, "lon": 78.0163, "is_major": True},
        ],
        "airports": [
            {"code": "AGR", "name": "Agra Kheria Airport", "city": "Agra", "lat": 27.1558, "lon": 77.9611, "is_major": False},
        ],
    },
    "patna": {
        "name": "Patna",
        "state": "Bihar",
        "lat": 25.5941,
        "lon": 85.1376,
        "is_hilly": False,
        "stations": [
            {"code": "PNBE", "name": "Patna Junction", "city": "Patna", "lat": 25.6022, "lon": 85.1374, "is_major": True},
        ],
        "airports": [
            {"code": "PAT", "name": "Jay Prakash Narayan Airport", "city": "Patna", "lat": 25.5913, "lon": 85.0880, "is_major": True},
        ],
    },
    "lucknow": {
        "name": "Lucknow",
        "state": "Uttar Pradesh",
        "lat": 26.8467,
        "lon": 80.9462,
        "is_hilly": False,
        "stations": [
            {"code": "LKO", "name": "Lucknow Charbagh", "city": "Lucknow", "lat": 26.8320, "lon": 80.9231, "is_major": True},
        ],
        "airports": [
            {"code": "LKO", "name": "Chaudhary Charan Singh International Airport", "city": "Lucknow", "lat": 26.7606, "lon": 80.8893, "is_major": True},
        ],
    },
    "bhopal": {
        "name": "Bhopal",
        "state": "Madhya Pradesh",
        "lat": 23.2599,
        "lon": 77.4126,
        "is_hilly": False,
        "stations": [
            {"code": "BPL", "name": "Bhopal Junction", "city": "Bhopal", "lat": 23.2662, "lon": 77.4116, "is_major": True},
            {"code": "RKMP", "name": "Rani Kamalapati (Habibganj)", "city": "Bhopal", "lat": 23.2064, "lon": 77.4370, "is_major": True},
        ],
        "airports": [
            {"code": "BHO", "name": "Raja Bhoj Airport", "city": "Bhopal", "lat": 23.2875, "lon": 77.3378, "is_major": True},
        ],
    },
    "indore": {
        "name": "Indore",
        "state": "Madhya Pradesh",
        "lat": 22.7196,
        "lon": 75.8577,
        "is_hilly": False,
        "stations": [
            {"code": "INDB", "name": "Indore Junction", "city": "Indore", "lat": 22.7169, "lon": 75.8679, "is_major": True},
        ],
        "airports": [
            {"code": "IDR", "name": "Devi Ahilya Bai Holkar Airport", "city": "Indore", "lat": 22.7217, "lon": 75.8011, "is_major": True},
        ],
    },
    "surat": {
        "name": "Surat",
        "state": "Gujarat",
        "lat": 21.1702,
        "lon": 72.8311,
        "is_hilly": False,
        "stations": [
            {"code": "ST", "name": "Surat Railway Station", "city": "Surat", "lat": 21.2048, "lon": 72.8408, "is_major": True},
        ],
        "airports": [
            {"code": "STV", "name": "Surat International Airport", "city": "Surat", "lat": 21.1158, "lon": 72.7417, "is_major": True},
        ],
    },
    "nagpur": {
        "name": "Nagpur",
        "state": "Maharashtra",
        "lat": 21.1458,
        "lon": 79.0882,
        "is_hilly": False,
        "stations": [
            {"code": "NGP", "name": "Nagpur Junction", "city": "Nagpur", "lat": 21.1528, "lon": 79.0882, "is_major": True},
        ],
        "airports": [
            {"code": "NAG", "name": "Dr. Babasaheb Ambedkar International Airport", "city": "Nagpur", "lat": 21.0922, "lon": 79.0472, "is_major": True},
        ],
    },
    "guwahati": {
        "name": "Guwahati",
        "state": "Assam",
        "lat": 26.1445,
        "lon": 91.7362,
        "is_hilly": False,
        "stations": [
            {"code": "GHY", "name": "Guwahati Railway Station", "city": "Guwahati", "lat": 26.1806, "lon": 91.7539, "is_major": True},
            {"code": "KYQ", "name": "Kamakhya Junction", "city": "Guwahati", "lat": 26.1550, "lon": 91.7050, "is_major": True},
        ],
        "airports": [
            {"code": "GAU", "name": "Lokpriya Gopinath Bordoloi International Airport", "city": "Guwahati", "lat": 26.1061, "lon": 91.5859, "is_major": True},
        ],
    },
    "shillong": {
        "name": "Shillong",
        "state": "Meghalaya",
        "lat": 25.5788,
        "lon": 91.8933,
        "is_hilly": True,
        "stations": [],
        "airports": [
            {"code": "SHL", "name": "Shillong Airport (Umroi)", "city": "Shillong", "lat": 25.7025, "lon": 91.9786, "is_major": False},
        ],
    },
    "puri": {
        "name": "Puri",
        "state": "Odisha",
        "lat": 19.8135,
        "lon": 85.8312,
        "is_hilly": False,
        "stations": [
            {"code": "PURI", "name": "Puri Terminal", "city": "Puri", "lat": 19.8130, "lon": 85.8330, "is_major": True},
        ],
        "airports": [],
    },
    "bhubaneswar": {
        "name": "Bhubaneswar",
        "state": "Odisha",
        "lat": 20.2961,
        "lon": 85.8245,
        "is_hilly": False,
        "stations": [
            {"code": "BBS", "name": "Bhubaneswar Railway Station", "city": "Bhubaneswar", "lat": 20.2642, "lon": 85.8436, "is_major": True},
        ],
        "airports": [
            {"code": "BBI", "name": "Biju Patnaik International Airport", "city": "Bhubaneswar", "lat": 20.2444, "lon": 85.8178, "is_major": True},
        ],
    },
    "kolhapur": {
        "name": "Kolhapur",
        "state": "Maharashtra",
        "lat": 16.7050,
        "lon": 74.2433,
        "is_hilly": False,
        "stations": [
            {"code": "KOP", "name": "Chhatrapati Shahu Maharaj Terminus", "city": "Kolhapur", "lat": 16.7000, "lon": 74.2389, "is_major": True},
        ],
        "airports": [
            {"code": "KLH", "name": "Chhatrapati Rajaram Maharaj Airport", "city": "Kolhapur", "lat": 16.6631, "lon": 74.2811, "is_major": False},
        ],
    },
    "ajmer": {
        "name": "Ajmer",
        "state": "Rajasthan",
        "lat": 26.4499,
        "lon": 74.6399,
        "is_hilly": False,
        "stations": [
            {"code": "AII", "name": "Ajmer Junction", "city": "Ajmer", "lat": 26.4526, "lon": 74.6342, "is_major": True},
            {"code": "MDJN", "name": "Madar Junction", "city": "Ajmer", "lat": 26.4912, "lon": 74.6853, "is_major": False},
            {"code": "DOZ", "name": "Daurai", "city": "Ajmer", "lat": 26.4024, "lon": 74.6035, "is_major": False},
            {"code": "KSG", "name": "Kishangarh", "city": "Kishangarh", "lat": 26.5768, "lon": 74.8647, "is_major": True},
        ],
        "airports": [
            {"code": "KQH", "name": "Kishangarh Airport (Ajmer)", "city": "Ajmer", "lat": 26.6022, "lon": 74.8144, "is_major": True},
            {"code": "JAI", "name": "Jaipur International Airport", "city": "Jaipur", "lat": 26.8242, "lon": 75.8122, "is_major": True},
        ],
    },
    "pushkar": {
        "name": "Pushkar",
        "state": "Rajasthan",
        "lat": 26.4897,
        "lon": 74.5511,
        "is_hilly": False,
        "stations": [
            {"code": "PUHT", "name": "Pushkar Terminus", "city": "Pushkar", "lat": 26.4910, "lon": 74.5550, "is_major": False},
            {"code": "AII", "name": "Ajmer Junction", "city": "Ajmer", "lat": 26.4526, "lon": 74.6342, "is_major": True},
            {"code": "MDJN", "name": "Madar Junction", "city": "Ajmer", "lat": 26.4912, "lon": 74.6853, "is_major": False},
        ],
        "airports": [
            {"code": "KQH", "name": "Kishangarh Airport (Ajmer)", "city": "Ajmer", "lat": 26.6022, "lon": 74.8144, "is_major": True},
            {"code": "JAI", "name": "Jaipur International Airport", "city": "Jaipur", "lat": 26.8242, "lon": 75.8122, "is_major": True},
        ],
    },
    "udaipur": {
        "name": "Udaipur",
        "state": "Rajasthan",
        "lat": 24.5854,
        "lon": 73.7125,
        "is_hilly": False,
        "stations": [
            {"code": "UDZ", "name": "Udaipur City Railway Station", "city": "Udaipur", "lat": 24.5770, "lon": 73.6990, "is_major": True},
            {"code": "RPZ", "name": "Ranapratapnagar", "city": "Udaipur", "lat": 24.5930, "lon": 73.7220, "is_major": False},
        ],
        "airports": [
            {"code": "UDR", "name": "Maharana Pratap Airport (Udaipur)", "city": "Udaipur", "lat": 24.6177, "lon": 73.8961, "is_major": True},
        ],
    },
    "jodhpur": {
        "name": "Jodhpur",
        "state": "Rajasthan",
        "lat": 26.2389,
        "lon": 73.0243,
        "is_hilly": False,
        "stations": [
            {"code": "JU", "name": "Jodhpur Junction", "city": "Jodhpur", "lat": 26.2847, "lon": 73.0203, "is_major": True},
            {"code": "BGKT", "name": "Bhagat Ki Kothi", "city": "Jodhpur", "lat": 26.2520, "lon": 73.0070, "is_major": True},
        ],
        "airports": [
            {"code": "JDH", "name": "Jodhpur Airport", "city": "Jodhpur", "lat": 26.2514, "lon": 73.0489, "is_major": True},
        ],
    },
    "bikaner": {
        "name": "Bikaner",
        "state": "Rajasthan",
        "lat": 28.0229,
        "lon": 73.3119,
        "is_hilly": False,
        "stations": [
            {"code": "BKN", "name": "Bikaner Junction", "city": "Bikaner", "lat": 28.0170, "lon": 73.3140, "is_major": True},
            {"code": "LGH", "name": "Lalgarh Junction", "city": "Bikaner", "lat": 28.0530, "lon": 73.3080, "is_major": True},
        ],
        "airports": [
            {"code": "BKB", "name": "Nal Airport Bikaner", "city": "Bikaner", "lat": 28.0708, "lon": 73.2069, "is_major": False},
        ],
    },
    "kota": {
        "name": "Kota",
        "state": "Rajasthan",
        "lat": 25.2138,
        "lon": 75.8648,
        "is_hilly": False,
        "stations": [
            {"code": "KOTA", "name": "Kota Junction", "city": "Kota", "lat": 25.2194, "lon": 75.8778, "is_major": True},
            {"code": "DKNT", "name": "Dakaniya Talav", "city": "Kota", "lat": 25.1380, "lon": 75.8570, "is_major": False},
        ],
        "airports": [
            {"code": "JAI", "name": "Jaipur International Airport", "city": "Jaipur", "lat": 26.8242, "lon": 75.8122, "is_major": True},
        ],
    },
    "vadodara": {
        "name": "Vadodara",
        "state": "Gujarat",
        "lat": 22.3072,
        "lon": 73.1812,
        "is_hilly": False,
        "stations": [
            {"code": "BRC", "name": "Vadodara Junction", "city": "Vadodara", "lat": 22.3108, "lon": 73.1813, "is_major": True},
        ],
        "airports": [
            {"code": "BDQ", "name": "Vadodara Airport", "city": "Vadodara", "lat": 22.3361, "lon": 73.2264, "is_major": True},
        ],
    },
    "rajkot": {
        "name": "Rajkot",
        "state": "Gujarat",
        "lat": 22.3039,
        "lon": 70.8022,
        "is_hilly": False,
        "stations": [
            {"code": "RJT", "name": "Rajkot Junction", "city": "Rajkot", "lat": 22.3150, "lon": 70.7980, "is_major": True},
        ],
        "airports": [
            {"code": "HSR", "name": "Rajkot International Airport (Hirasar)", "city": "Rajkot", "lat": 22.3689, "lon": 71.0119, "is_major": True},
        ],
    },
    "gwalior": {
        "name": "Gwalior",
        "state": "Madhya Pradesh",
        "lat": 26.2183,
        "lon": 78.1828,
        "is_hilly": False,
        "stations": [
            {"code": "GWL", "name": "Gwalior Junction", "city": "Gwalior", "lat": 26.2170, "lon": 78.1880, "is_major": True},
        ],
        "airports": [
            {"code": "GWL", "name": "Rajmata Vijaya Raje Scindia Airport", "city": "Gwalior", "lat": 26.2934, "lon": 78.2278, "is_major": True},
        ],
    },
    "jabalpur": {
        "name": "Jabalpur",
        "state": "Madhya Pradesh",
        "lat": 23.1815,
        "lon": 79.9864,
        "is_hilly": False,
        "stations": [
            {"code": "JBP", "name": "Jabalpur Junction", "city": "Jabalpur", "lat": 23.1600, "lon": 79.9500, "is_major": True},
            {"code": "MML", "name": "Madan Mahal", "city": "Jabalpur", "lat": 23.1530, "lon": 79.9160, "is_major": False},
        ],
        "airports": [
            {"code": "JLR", "name": "Jabalpur Dumna Airport", "city": "Jabalpur", "lat": 23.1778, "lon": 80.0522, "is_major": True},
        ],
    },
    "varanasi": {
        "name": "Varanasi",
        "state": "Uttar Pradesh",
        "lat": 25.3176,
        "lon": 82.9739,
        "is_hilly": False,
        "stations": [
            {"code": "BSB", "name": "Varanasi Junction", "city": "Varanasi", "lat": 25.3280, "lon": 82.9860, "is_major": True},
            {"code": "DDU", "name": "Pt. Deen Dayal Upadhyaya Junction", "city": "Varanasi", "lat": 25.2790, "lon": 83.1230, "is_major": True},
            {"code": "BSBS", "name": "Banaras Railway Station", "city": "Varanasi", "lat": 25.3160, "lon": 82.9620, "is_major": True},
        ],
        "airports": [
            {"code": "VNS", "name": "Lal Bahadur Shastri International Airport", "city": "Varanasi", "lat": 25.4525, "lon": 82.8592, "is_major": True},
        ],
    },
    "prayagraj": {
        "name": "Prayagraj",
        "state": "Uttar Pradesh",
        "lat": 25.4358,
        "lon": 81.8463,
        "is_hilly": False,
        "stations": [
            {"code": "PRYJ", "name": "Prayagraj Junction", "city": "Prayagraj", "lat": 25.4430, "lon": 81.8340, "is_major": True},
            {"code": "PRRB", "name": "Prayagraj Rambag", "city": "Prayagraj", "lat": 25.4400, "lon": 81.8540, "is_major": False},
        ],
        "airports": [
            {"code": "IXD", "name": "Prayagraj Airport", "city": "Prayagraj", "lat": 25.4400, "lon": 81.7340, "is_major": True},
        ],
    },
    "agra": {
        "name": "Agra",
        "state": "Uttar Pradesh",
        "lat": 27.1767,
        "lon": 78.0081,
        "is_hilly": False,
        "stations": [
            {"code": "AGC", "name": "Agra Cantt", "city": "Agra", "lat": 27.1580, "lon": 77.9900, "is_major": True},
            {"code": "AF", "name": "Agra Fort", "city": "Agra", "lat": 27.1850, "lon": 78.0180, "is_major": True},
        ],
        "airports": [
            {"code": "AGR", "name": "Agra Airport", "city": "Agra", "lat": 27.1558, "lon": 77.9608, "is_major": True},
        ],
    },
    "haridwar": {
        "name": "Haridwar",
        "state": "Uttarakhand",
        "lat": 29.9457,
        "lon": 78.1642,
        "is_hilly": False,
        "stations": [
            {"code": "HW", "name": "Haridwar Junction", "city": "Haridwar", "lat": 29.9490, "lon": 78.1560, "is_major": True},
        ],
        "airports": [
            {"code": "DED", "name": "Dehradun Jolly Grant Airport", "city": "Dehradun", "lat": 30.1897, "lon": 78.1803, "is_major": True},
        ],
    },
    "rishikesh": {
        "name": "Rishikesh",
        "state": "Uttarakhand",
        "lat": 30.0869,
        "lon": 78.2676,
        "is_hilly": True,
        "stations": [
            {"code": "YNRK", "name": "Yog Nagari Rishikesh", "city": "Rishikesh", "lat": 30.1000, "lon": 78.2800, "is_major": True},
            {"code": "RKSH", "name": "Rishikesh Railway Station", "city": "Rishikesh", "lat": 30.1030, "lon": 78.2930, "is_major": False},
            {"code": "HW", "name": "Haridwar Junction", "city": "Haridwar", "lat": 29.9490, "lon": 78.1560, "is_major": True},
        ],
        "airports": [
            {"code": "DED", "name": "Dehradun Jolly Grant Airport", "city": "Dehradun", "lat": 30.1897, "lon": 78.1803, "is_major": True},
        ],
    },
    "dehradun": {
        "name": "Dehradun",
        "state": "Uttarakhand",
        "lat": 30.3165,
        "lon": 78.0322,
        "is_hilly": False,
        "stations": [
            {"code": "DDN", "name": "Dehradun Terminal", "city": "Dehradun", "lat": 30.3160, "lon": 78.0320, "is_major": True},
        ],
        "airports": [
            {"code": "DED", "name": "Dehradun Jolly Grant Airport", "city": "Dehradun", "lat": 30.1897, "lon": 78.1803, "is_major": True},
        ],
    },
    "amritsar": {
        "name": "Amritsar",
        "state": "Punjab",
        "lat": 31.6340,
        "lon": 74.8723,
        "is_hilly": False,
        "stations": [
            {"code": "ASR", "name": "Amritsar Junction", "city": "Amritsar", "lat": 31.6340, "lon": 74.8650, "is_major": True},
        ],
        "airports": [
            {"code": "ATQ", "name": "Sri Guru Ram Dass Jee International Airport", "city": "Amritsar", "lat": 31.7096, "lon": 74.7973, "is_major": True},
        ],
    },
    "chandigarh": {
        "name": "Chandigarh",
        "state": "Chandigarh",
        "lat": 30.7333,
        "lon": 76.7794,
        "is_hilly": False,
        "stations": [
            {"code": "CDG", "name": "Chandigarh Junction", "city": "Chandigarh", "lat": 30.7022, "lon": 76.8222, "is_major": True},
            {"code": "KLK", "name": "Kalka", "city": "Kalka", "lat": 30.8350, "lon": 76.9360, "is_major": True},
        ],
        "airports": [
            {"code": "IXC", "name": "Shaheed Bhagat Singh International Airport", "city": "Chandigarh", "lat": 30.6735, "lon": 76.7885, "is_major": True},
        ],
    },
    "visakhapatnam": {
        "name": "Visakhapatnam",
        "state": "Andhra Pradesh",
        "lat": 17.6868,
        "lon": 83.2185,
        "is_hilly": False,
        "stations": [
            {"code": "VSKP", "name": "Visakhapatnam Junction", "city": "Visakhapatnam", "lat": 17.7210, "lon": 83.2870, "is_major": True},
            {"code": "DVD", "name": "Duvvada", "city": "Visakhapatnam", "lat": 17.7080, "lon": 83.1530, "is_major": True},
        ],
        "airports": [
            {"code": "VTZ", "name": "Visakhapatnam International Airport", "city": "Visakhapatnam", "lat": 17.7214, "lon": 83.2244, "is_major": True},
        ],
    },
    "vijayawada": {
        "name": "Vijayawada",
        "state": "Andhra Pradesh",
        "lat": 16.5062,
        "lon": 80.6480,
        "is_hilly": False,
        "stations": [
            {"code": "BZA", "name": "Vijayawada Junction", "city": "Vijayawada", "lat": 16.5180, "lon": 80.6200, "is_major": True},
        ],
        "airports": [
            {"code": "VGA", "name": "Vijayawada International Airport", "city": "Vijayawada", "lat": 16.5270, "lon": 80.7968, "is_major": True},
        ],
    },
    "coimbatore": {
        "name": "Coimbatore",
        "state": "Tamil Nadu",
        "lat": 11.0168,
        "lon": 76.9558,
        "is_hilly": False,
        "stations": [
            {"code": "CBE", "name": "Coimbatore Main Junction", "city": "Coimbatore", "lat": 10.9980, "lon": 76.9660, "is_major": True},
            {"code": "CBF", "name": "Coimbatore North", "city": "Coimbatore", "lat": 11.0260, "lon": 76.9580, "is_major": False},
        ],
        "airports": [
            {"code": "CJB", "name": "Coimbatore International Airport", "city": "Coimbatore", "lat": 11.0298, "lon": 77.0434, "is_major": True},
        ],
    },
    "madurai": {
        "name": "Madurai",
        "state": "Tamil Nadu",
        "lat": 9.9252,
        "lon": 78.1198,
        "is_hilly": False,
        "stations": [
            {"code": "MDU", "name": "Madurai Junction", "city": "Madurai", "lat": 9.9200, "lon": 78.1130, "is_major": True},
        ],
        "airports": [
            {"code": "IXM", "name": "Madurai International Airport", "city": "Madurai", "lat": 9.8345, "lon": 78.0934, "is_major": True},
        ],
    },
    "mysuru": {
        "name": "Mysuru",
        "state": "Karnataka",
        "lat": 12.2958,
        "lon": 76.6394,
        "is_hilly": False,
        "stations": [
            {"code": "MYS", "name": "Mysuru Junction", "city": "Mysuru", "lat": 12.3160, "lon": 76.6450, "is_major": True},
        ],
        "airports": [
            {"code": "MYQ", "name": "Mysuru Airport (Mandakalli)", "city": "Mysuru", "lat": 12.2300, "lon": 76.6530, "is_major": False},
            {"code": "BLR", "name": "Kempegowda International Airport", "city": "Bengaluru", "lat": 13.1986, "lon": 77.7066, "is_major": True},
        ],
    },
    "mangalore": {
        "name": "Mangalore",
        "state": "Karnataka",
        "lat": 12.9141,
        "lon": 74.8560,
        "is_hilly": False,
        "stations": [
            {"code": "MAQ", "name": "Mangaluru Central", "city": "Mangalore", "lat": 12.8630, "lon": 74.8430, "is_major": True},
            {"code": "MAJN", "name": "Mangaluru Junction", "city": "Mangalore", "lat": 12.8710, "lon": 74.8770, "is_major": True},
        ],
        "airports": [
            {"code": "IXE", "name": "Mangaluru International Airport", "city": "Mangalore", "lat": 12.9613, "lon": 74.8900, "is_major": True},
        ],
    },
    "thiruvananthapuram": {
        "name": "Thiruvananthapuram",
        "state": "Kerala",
        "lat": 8.5241,
        "lon": 76.9366,
        "is_hilly": False,
        "stations": [
            {"code": "TVC", "name": "Thiruvananthapuram Central", "city": "Thiruvananthapuram", "lat": 8.4870, "lon": 76.9530, "is_major": True},
            {"code": "KCVL", "name": "Kochuveli", "city": "Thiruvananthapuram", "lat": 8.5130, "lon": 76.9040, "is_major": True},
        ],
        "airports": [
            {"code": "TRV", "name": "Thiruvananthapuram International Airport", "city": "Thiruvananthapuram", "lat": 8.4821, "lon": 76.9200, "is_major": True},
        ],
    },
    "puducherry": {
        "name": "Puducherry",
        "state": "Puducherry",
        "lat": 11.9416,
        "lon": 79.8083,
        "is_hilly": False,
        "stations": [
            {"code": "PDY", "name": "Puducherry Railway Station", "city": "Puducherry", "lat": 11.9260, "lon": 79.8290, "is_major": True},
            {"code": "VM", "name": "Villupuram Junction", "city": "Villupuram", "lat": 11.9390, "lon": 79.4930, "is_major": True},
        ],
        "airports": [
            {"code": "PNY", "name": "Puducherry Airport", "city": "Puducherry", "lat": 11.9680, "lon": 79.8110, "is_major": False},
            {"code": "MAA", "name": "Chennai International Airport", "city": "Chennai", "lat": 12.9941, "lon": 80.1709, "is_major": True},
        ],
    },
}

# Add Aliases
ALIASES: Dict[str, str] = {
    "new delhi": "delhi",
    "delhi ncr": "delhi",
    "bombay": "mumbai",
    "mumbai city": "mumbai",
    "bandra": "mumbai",
    "bandra terminus": "mumbai",
    "andheri": "mumbai",
    "borivali": "mumbai",
    "dadar": "mumbai",
    "kurla": "mumbai",
    "vashi": "navi mumbai",
    "bangalore": "bengaluru",
    "bengaluru city": "bengaluru",
    "cochin": "kochi",
    "ernakulam": "kochi",
    "madras": "chennai",
    "calcutta": "kolkata",
    "gauhati": "guwahati",
    "mysore": "mysuru",
    "madikeri": "coorg",
    "pondicherry": "puducherry",
    "trivandrum": "thiruvananthapuram",
    "bhuntar": "kullu",
    "bagdogra": "siliguri",
    "njp": "siliguri",
    "new jalpaiguri": "siliguri",
    "allahabad": "prayagraj",
    "banaras": "varanasi",
    "kashi": "varanasi",
    "baroda": "vadodara",
    "mangaluru": "mangalore",
    "vizag": "visakhapatnam",
    "waltair": "visakhapatnam",
    "coimbatore junction": "coimbatore",
    "madurai junction": "madurai",
}


# ============================================================
# RESOLVER HELPER FUNCTIONS
# ============================================================

def get_location_entry(location_name: str) -> Optional[Dict[str, Any]]:
    """Lookup a location in INDIA_LOCATIONS using exact, alias, or substring match."""
    if not location_name:
        return None

    import re
    clean = " ".join(str(location_name).lower().strip().split())
    clean_alias = ALIASES.get(clean, clean)

    if clean_alias in INDIA_LOCATIONS:
        entry = dict(INDIA_LOCATIONS[clean_alias])
        # If the input was a specific locality alias (like 'bandra'), adjust coordinates to the matching station if found
        clean_upper = location_name.strip().upper()
        for st in entry.get("stations", []):
            if clean_upper == st["code"].upper() or clean.lower() in st["name"].lower():
                entry["lat"] = st.get("lat", entry.get("lat", 20.0))
                entry["lon"] = st.get("lon", entry.get("lon", 78.0))
                break
        return entry

    # Substring match on keys
    for k, v in INDIA_LOCATIONS.items():
        if k in clean or clean in k:
            return v

    # Extract code inside parentheses if present e.g. "Hazrat Nizamuddin (NZM)" -> "NZM"
    code_match = re.search(r'\(([A-Za-z0-9]+)\)', str(location_name))
    extracted_code = code_match.group(1).upper() if code_match else None
    clean_upper = location_name.strip().upper()
    upper_tokens = set(clean_upper.replace("(", " ").replace(")", " ").split())

    # Dynamic match on stations or airports across all entries
    for k, v in INDIA_LOCATIONS.items():
        for st in v.get("stations", []):
            st_name = st.get("name", "").upper()
            st_code = st.get("code", "").upper()
            st_city = st.get("city", "").upper()
            if (
                clean_upper == st_code
                or (extracted_code and extracted_code == st_code)
                or st_code in upper_tokens
                or clean_upper in st_name
                or (st_name and st_name in clean_upper)
                or clean.lower() in st_name.lower()
                or (st_city and clean.lower() == st_city.lower())
            ):
                entry = dict(v)
                entry["lat"] = st.get("lat", v.get("lat", 20.0))
                entry["lon"] = st.get("lon", v.get("lon", 78.0))
                entry["name"] = location_name.strip().title()
                return entry

        for ap in v.get("airports", []):
            ap_name = ap.get("name", "").upper()
            ap_code = ap.get("code", "").upper()
            if (
                clean_upper == ap_code
                or (extracted_code and extracted_code == ap_code)
                or ap_code in upper_tokens
                or clean_upper in ap_name
                or (ap_name and ap_name in clean_upper)
                or clean.lower() in ap_name.lower()
            ):
                entry = dict(v)
                entry["lat"] = ap.get("lat", v.get("lat", 20.0))
                entry["lon"] = ap.get("lon", v.get("lon", 78.0))
                entry["name"] = location_name.strip().title()
                return entry

    return None


def resolve_stations_for_location(
    location_name: str,
    geo_coords: Optional[Tuple[float, float]] = None,
) -> List[Dict[str, Any]]:
    """Discover railway stations from geographic proximity.

    Important architectural rule:
    ``INDIA_LOCATIONS`` is treated as a station metadata catalog, not as a
    city -> station mapping. The user's location is resolved to coordinates
    first, then every known station is scored by geographic/road proximity.
    This allows a location with no direct railway station to fall through to
    nearby railheads/junctions without destination-specific conditionals.
    """
    loc_entry = get_location_entry(location_name)

    if geo_coords and isinstance(geo_coords, (tuple, list)) and len(geo_coords) >= 2:
        target_lat = float(geo_coords[0])
        target_lon = float(geo_coords[1])
    elif loc_entry:
        target_lat = float(loc_entry.get("lat", 20.0))
        target_lon = float(loc_entry.get("lon", 78.0))
    else:
        # No coordinates means discovery cannot be performed safely.
        return []

    is_hilly = bool(
        loc_entry.get("is_hilly", False) if loc_entry else
        (target_lat >= 29.5 and 73.0 <= target_lon <= 96.0)
    )
    target_name = loc_entry.get("name", location_name.title()) if loc_entry else location_name.title()
    clean_query = " ".join(str(location_name).strip().lower().split())
    clean_query_upper = clean_query.upper()

    # Exact station intent must survive city-level geocoding.
    exact_station_candidates: List[Dict[str, Any]] = []
    for entry in INDIA_LOCATIONS.values():
        for station in entry.get("stations", []):
            code = str(station.get("code", "")).strip().upper()
            name = " ".join(str(station.get("name", "")).strip().lower().split())
            aliases = {
                " ".join(str(alias).strip().lower().split())
                for alias in station.get("aliases", [])
                if alias
            }
            if (
                clean_query_upper == code
                or clean_query == name
                or clean_query in aliases
            ):
                exact_station_candidates.append(dict(station))

    # Build a flat station catalog from all metadata entries. The location
    # key is deliberately ignored, so discovery is spatial rather than
    # city-assumption based.
    station_catalog: Dict[str, Dict[str, Any]] = {}
    for entry in INDIA_LOCATIONS.values():
        for station in entry.get("stations", []):
            code = str(station.get("code", "")).strip().upper()
            if not code or code in station_catalog:
                continue
            if station.get("lat") is None or station.get("lon") is None:
                continue
            station_catalog[code] = dict(station)

    # Wider radius for remote/hilly destinations because the nearest useful
    # railway endpoint can be a regional railhead rather than a city station.
    direct_cutoff_km = 80.0 if not is_hilly else 250.0
    candidates: List[Dict[str, Any]] = []

    for station in station_catalog.values():
        station_lat = float(station["lat"])
        station_lon = float(station["lon"])
        direct_distance = haversine_distance_km(
            target_lat, target_lon, station_lat, station_lon
        )
        if direct_distance > direct_cutoff_km:
            continue

        transfer = estimate_road_transfer(
            target_lat, target_lon, station_lat, station_lon, is_hilly=is_hilly
        )
        candidate = dict(station)
        candidate.update({
            "distance_km": transfer["road_distance_km"],
            "direct_distance_km": direct_distance,
            "estimated_transfer_time": transfer["estimated_transfer_time"],
            "duration_minutes": transfer["duration_minutes"],
            "target_location": target_name,
            "discovery_method": "geospatial_catalog",
        })
        candidates.append(candidate)

    # Exact user station first, then spatial alternatives.
    # Recalculate transfer metadata for the exact station because its exact
    # match may have been found independently of the geocoded city point.
    exact_codes = set()
    enriched_exact = []

    for exact in exact_station_candidates:
        code = str(exact.get("code", "")).strip().upper()
        if not code or code in exact_codes:
            continue
        exact_codes.add(code)

        lat = exact.get("lat")
        lon = exact.get("lon")
        if lat is not None and lon is not None:
            transfer = estimate_road_transfer(
                target_lat, target_lon, float(lat), float(lon), is_hilly=is_hilly
            )
            exact.update({
                "distance_km": transfer["road_distance_km"],
                "direct_distance_km": haversine_distance_km(
                    target_lat, target_lon, float(lat), float(lon)
                ),
                "estimated_transfer_time": transfer["estimated_transfer_time"],
                "duration_minutes": transfer["duration_minutes"],
            })
        exact.update({
            "target_location": target_name,
            "discovery_method": "exact_station_match",
            "is_exact_user_station": True,
        })
        enriched_exact.append(exact)

    candidates = [
        candidate for candidate in candidates
        if str(candidate.get("code", "")).strip().upper() not in exact_codes
    ]

    candidates.sort(
        key=lambda station: (
            station.get("direct_distance_km", 999999),
            0 if station.get("is_major") else 1,
        )
    )

    # The caller applies the final 6-candidate cap.
    return enriched_exact + candidates[:9]

def resolve_airports_for_location(
    location_name: str,
    geo_coords: Optional[Tuple[float, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Resolve a city/location to candidate airports.
    Returns direct airports (if any) PLUS nearby operational airports
    strictly within the destination region's geographic distance cutoff.
    """
    loc_entry = get_location_entry(location_name)
    candidates: List[Dict[str, Any]] = []
    seen_codes = set()

    if geo_coords and isinstance(geo_coords, (tuple, list)) and len(geo_coords) >= 2 and geo_coords[0] is not None and geo_coords[1] is not None:
        target_lat = float(geo_coords[0])
        target_lon = float(geo_coords[1])
    else:
        target_lat = loc_entry["lat"] if loc_entry else 20.0
        target_lon = loc_entry["lon"] if loc_entry else 78.0

    is_hilly = loc_entry.get("is_hilly", False) if loc_entry else False
    target_name = loc_entry.get("name", location_name.title()) if loc_entry else location_name.title()

    # 1. Direct airports defined for location
    if loc_entry and loc_entry.get("airports"):
        for ap in loc_entry["airports"]:
            ap_copy = dict(ap)
            transfer = estimate_road_transfer(
                target_lat, target_lon,
                ap_copy.get("lat", target_lat), ap_copy.get("lon", target_lon),
                is_hilly=is_hilly
            )
            ap_copy["distance_km"] = transfer["road_distance_km"]
            ap_copy["estimated_transfer_time"] = transfer["estimated_transfer_time"]
            ap_copy["duration_minutes"] = transfer["duration_minutes"]
            ap_copy["target_location"] = target_name
            if ap_copy["code"] not in seen_codes:
                seen_codes.add(ap_copy["code"])
                candidates.append(ap_copy)

    # 2. Match exact airport code or name query
    clean_query = location_name.strip().upper()
    for k, v in INDIA_LOCATIONS.items():
        for ap in v.get("airports", []):
            if ap["code"].upper() == clean_query or clean_query in ap["name"].upper() or (ap.get("city") and clean_query == ap["city"].upper()):
                if ap["code"] not in seen_codes:
                    ap_copy = dict(ap)
                    transfer = estimate_road_transfer(
                        target_lat, target_lon,
                        ap_copy.get("lat", target_lat), ap_copy.get("lon", target_lon),
                        is_hilly=is_hilly
                    )
                    ap_copy["distance_km"] = transfer["road_distance_km"]
                    ap_copy["estimated_transfer_time"] = transfer["estimated_transfer_time"]
                    ap_copy["duration_minutes"] = transfer["duration_minutes"]
                    ap_copy["target_location"] = target_name
                    seen_codes.add(ap_copy["code"])
                    candidates.append(ap_copy)

    has_direct_airport = bool(candidates and any(c.get("distance_km", 999) <= 50 for c in candidates))
    if has_direct_airport:
        max_cutoff_km = 120
    elif is_hilly:
        max_cutoff_km = 300
    else:
        max_cutoff_km = 200

    all_nearby = []
    is_default_coords = (loc_entry is None and geo_coords is None)

    if not is_default_coords:
        for k, v in INDIA_LOCATIONS.items():
            for ap in v.get("airports", []):
                if ap["code"] in seen_codes:
                    continue
                ap_lat = ap.get("lat", target_lat)
                ap_lon = ap.get("lon", target_lon)
                direct_dist = haversine_distance_km(target_lat, target_lon, ap_lat, ap_lon)
                if direct_dist > max_cutoff_km:
                    continue

                ap_copy = dict(ap)
                transfer = estimate_road_transfer(
                    target_lat, target_lon,
                    ap_lat, ap_lon,
                    is_hilly=is_hilly
                )
                if transfer["road_distance_km"] > max_cutoff_km:
                    continue

                ap_copy["distance_km"] = transfer["road_distance_km"]
                ap_copy["estimated_transfer_time"] = transfer["estimated_transfer_time"]
                ap_copy["duration_minutes"] = transfer["duration_minutes"]
                ap_copy["target_location"] = target_name
                all_nearby.append(ap_copy)

        all_nearby.sort(key=lambda a: (a["distance_km"], 0 if a.get("is_major") else 1))

        for ap in all_nearby:
            if ap["code"] not in seen_codes:
                seen_codes.add(ap["code"])
                candidates.append(ap)
                if len(candidates) >= 5:
                    break

    if not candidates:
        clean_code = "".join([c for c in location_name.upper() if c.isalnum()])[:3] or "APT"
        candidates = [
            {
                "code": clean_code,
                "name": f"{location_name.title()} Airport",
                "city": location_name.title(),
                "lat": target_lat,
                "lon": target_lon,
                "is_major": True,
                "distance_km": 0,
                "estimated_transfer_time": "0m",
                "duration_minutes": 0,
                "target_location": target_name,
            }
        ]

    candidates.sort(
        key=lambda a: (
            0 if (a.get("code", "").upper() == clean_query or clean_query in a.get("name", "").upper() or (a.get("city") and clean_query == a.get("city", "").upper())) else (1 if a.get("distance_km", 999) == 0 else 2),
            a.get("distance_km", 999),
            0 if a.get("is_major") else 1,
        )
    )

    return candidates


# ============================================================
# CANONICAL STATION CODE MAPPINGS & EQUIVALENCE
# ============================================================

# Official Indian Railways canonical code mapping for stations with legacy,
# colonial, or alternate abbreviations (e.g. CSTM / VT -> CSMT, BCT -> MMCT, MGR -> MAS).
STATION_CODE_CANONICAL_MAP: Dict[str, str] = {
    # Mumbai terminals
    "CSTM": "CSMT",
    "VT": "CSMT",
    "CSMT": "CSMT",
    "BCT": "MMCT",
    "MMCT": "MMCT",
    "BDTS": "BDTS",
    "LTT": "LTT",
    "PNVL": "PNVL",
    "TNA": "TNA",
    "KYN": "KYN",
    # Chennai terminals
    "MGR": "MAS",
    "MAS": "MAS",
    "MS": "MS",
    # Delhi terminals
    "NDLS": "NDLS",
    "DLI": "DLI",
    "NZM": "NZM",
    "ANVT": "ANVT",
    # Bengaluru terminals
    "SBC": "SBC",
    "YPR": "YPR",
    # Kolkata terminals
    "HWH": "HWH",
    "SDAH": "SDAH",
    "KOAA": "KOAA",
    # Goa stations
    "MAO": "MAO",
    "VSG": "VSG",
    "KRMI": "KRMI",
    # Hyderabad / Secunderabad
    "SC": "SC",
    "HYB": "HYB",
    # Other major hubs
    "ADI": "ADI",
    "JP": "JP",
    "PUNE": "PUNE",
    "CDG": "CDG",
    "KLK": "KLK",
    "UMB": "UMB",
    "BSB": "BSB",
    "BSBS": "BSBS",
    "DDU": "DDU",
    "ASR": "ASR",
    "UDZ": "UDZ",
    "JSM": "JSM",
    "AGC": "AGC",
    "AF": "AF",
    "PNBE": "PNBE",
    "LKO": "LKO",
    "BPL": "BPL",
    "RKMP": "RKMP",
    "INDB": "INDB",
    "ST": "ST",
    "NGP": "NGP",
    "CNB": "CNB",
    "MYS": "MYS",
    "GKP": "GKP",
    "PTKC": "PTKC",
    "PTK": "PTK",
    "KGM": "KGM",
    "HW": "HW",
    "YNRK": "YNRK",
    "DDN": "DDN",
    "CBE": "CBE",
    "MTP": "MTP",
    "ERS": "ERS",
    "ERN": "ERN",
    "AWY": "AWY",
    "NJP": "NJP",
    "SGUJ": "SGUJ",
    "SML": "SML",
    "DJ": "DJ",
    "UAM": "UAM",
    "SINA": "SINA",
    "JAT": "JAT",
}


def get_canonical_station_code(code: Optional[str]) -> str:
    """
    Return the normalized, canonical Indian Railways station code.
    Maps legacy or alternative abbreviations (e.g. CSTM/VT -> CSMT, BCT -> MMCT)
    to the official standard station code.
    """
    if not code:
        return ""
    clean = str(code).strip().upper()
    return STATION_CODE_CANONICAL_MAP.get(clean, clean)


def is_same_station(code1: Optional[str], code2: Optional[str]) -> bool:
    """
    Return True if both station codes identify the exact same physical railway station,
    accounting for canonical aliases (e.g. CSTM and CSMT).
    """
    if not code1 or not code2:
        return False
    return get_canonical_station_code(code1) == get_canonical_station_code(code2)