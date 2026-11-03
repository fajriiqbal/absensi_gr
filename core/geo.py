import math
from decimal import Decimal, InvalidOperation


EARTH_RADIUS_METERS = 6_371_000


def parse_coordinates(latitude, longitude):
    try:
        lat = Decimal(str(latitude))
        lng = Decimal(str(longitude))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Koordinat GPS tidak valid.") from None
    if not lat.is_finite() or not lng.is_finite() or not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ValueError("Koordinat GPS berada di luar rentang yang valid.")
    return lat, lng


def calculate_haversine(lat1, lon1, lat2, lon2):
    lat1, lon1 = parse_coordinates(lat1, lon1)
    lat2, lon2 = parse_coordinates(lat2, lon2)
    lat1, lon1, lat2, lon2 = map(math.radians, map(float, (lat1, lon1, lat2, lon2)))
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(min(1, haversine)))