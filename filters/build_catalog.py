"""Build the hotel filter catalog (filters/catalog.json + filters/catalog.csv).

The catalog is the single source of truth shared by:
  * the backend search API (which filters exist, their types and bounds),
  * the validator (conflicts / implications / value bounds),
  * the assistant (a compact "top filters" list goes into the prompt, the full
    catalog is reachable through the `search_filter_catalog` tool).

Every filter has:
  id              stable machine id, `<category>.<name>`
  label           human label shown in the UI chip
  category        UI group
  type            boolean | range | enum
  unit / min / max / step       (range only)
  options                       (enum only)
  synonyms        phrases users actually write; used for retrieval, not for the model's reasoning
  exclusive_group filters in the same group cannot all be `true` at once (e.g. pets allowed / no pets)
  conflicts_with  explicit pairwise conflicts across groups
  implies         setting this filter also satisfies these (e.g. king bed => double-size bed)

Run:  python filters/build_catalog.py
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

OUT_DIR = Path(__file__).parent
CATALOG: list[dict] = []
_IDS: set[str] = set()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def add(category, name, label=None, type_="boolean", synonyms=(), **extra):
    fid = f"{category}.{slug(name)}"
    if fid in _IDS:
        raise ValueError(f"duplicate filter id {fid}")
    _IDS.add(fid)
    item = {
        "id": fid,
        "label": label or name.replace("_", " ").capitalize(),
        "category": category,
        "type": type_,
        "synonyms": list(synonyms),
    }
    item.update({k: v for k, v in extra.items() if v not in (None, [], ())})
    CATALOG.append(item)
    return fid


def rng(category, name, label, unit, lo, hi, step=1, synonyms=(), **extra):
    return add(category, name, label, "range", synonyms, unit=unit, min=lo, max=hi, step=step, **extra)


def bools(category, names):
    """names: list of str or (name, label, [synonyms]) tuples."""
    for n in names:
        if isinstance(n, tuple):
            name, label, *rest = n
            add(category, name, label, synonyms=rest[0] if rest else ())
        else:
            add(category, n, n.replace("_", " ").capitalize())


# --------------------------------------------------------------------------- price & deals
rng("price", "per_night", "Price per night", "EUR", 0, 5000, 5, ["budget", "under", "max price", "cheap", "per night"])
rng("price", "total_stay", "Total price for stay", "EUR", 0, 50000, 10, ["total budget", "whole trip budget"])
rng("price", "discount_percent", "Discount vs. usual price", "%", 0, 90, 5, ["deal", "sale", "best deals", "discount"])
rng("price", "deal_score", "Deal score (price vs. area median)", "score", 0, 100, 1, ["good value", "bargain", "best deal"])
bools("price", [
    ("free_cancellation", "Free cancellation", ["refundable", "can cancel"]),
    ("non_refundable_ok", "Show non-refundable rates", ["non refundable fine", "cheapest rate"]),
    ("no_prepayment", "No prepayment", ["pay later", "no deposit"]),
    ("pay_at_property", "Pay at the property", ["pay on arrival", "pay at hotel"]),
    ("book_now_pay_later", "Book now, pay later", []),
    ("taxes_included", "Price includes taxes & fees", ["all in price", "no hidden fees"]),
    ("member_price", "Member / loyalty price available", []),
    ("mobile_only_deal", "Mobile-only deal", []),
    ("last_minute_deal", "Last-minute deal", ["last minute"]),
    ("early_booking_deal", "Early-booking deal", ["early bird"]),
    ("long_stay_discount", "Long-stay discount", ["weekly rate", "monthly rate"]),
    ("price_drop_recent", "Price dropped recently", []),
    ("installments", "Pay in installments", []),
    ("crypto_payment", "Accepts cryptocurrency", []),
    ("cash_payment", "Accepts cash", []),
    ("amex_accepted", "Accepts American Express", []),
    ("visa_mastercard_accepted", "Accepts Visa / Mastercard", []),
    ("unionpay_accepted", "Accepts UnionPay", []),
    ("jcb_accepted", "Accepts JCB", []),
    ("apple_google_pay", "Apple Pay / Google Pay", []),
    ("no_credit_card_needed", "No credit card needed to book", []),
    ("city_tax_included", "City tax included", []),
    ("free_breakfast_deal", "Deal includes free breakfast", []),
    ("free_upgrade_deal", "Deal includes room upgrade", []),
    ("price_match", "Price-match guarantee", []),
])

# --------------------------------------------------------------------------- ratings & reviews
rng("rating", "stars", "Star rating", "stars", 0, 5, 1, ["star", "5 star", "luxury", "3-star"])
rng("rating", "guest_score", "Guest review score", "score", 0, 10, 0.5, ["well rated", "good reviews", "highly rated"])
rng("rating", "review_count", "Number of reviews", "reviews", 0, 50000, 10, ["popular", "lots of reviews"])
for sub in ["cleanliness", "comfort", "location", "staff", "value", "facilities", "wifi", "breakfast",
            "quietness", "bed_comfort", "bathroom", "food", "check_in_experience", "family_friendliness",
            "romance", "business_friendliness", "accessibility", "sustainability", "pet_experience", "pool"]:
    rng("rating", f"{sub}_score", f"{sub.replace('_', ' ').capitalize()} score", "score", 0, 10, 0.5)
bools("rating", [
    ("travellers_choice", "Guest favourite / traveller's choice award", []),
    ("verified_reviews_only", "Rating from verified stays only", []),
    ("recently_renovated", "Renovated in the last 3 years", ["renovated", "newly refurbished"]),
    ("newly_opened", "Opened in the last 2 years", ["new hotel"]),
    ("solo_traveller_favourite", "Popular with solo travellers", ["solo"]),
    ("couples_favourite", "Popular with couples", []),
    ("families_favourite", "Popular with families", []),
    ("business_favourite", "Popular with business travellers", []),
    ("digital_nomad_favourite", "Popular with digital nomads", ["remote work"]),
    ("groups_favourite", "Popular with groups", []),
])
rng("rating", "year_built", "Year built", "year", 1100, 2027, 1, ["historic", "modern building"])
rng("rating", "year_renovated", "Year last renovated", "year", 1950, 2027, 1)

# --------------------------------------------------------------------------- property type
PROPERTY_TYPES = [
    "hotel", "boutique_hotel", "design_hotel", "bed_and_breakfast", "guesthouse", "inn", "motel", "hostel",
    "capsule_hotel", "pod_hotel", "aparthotel", "serviced_apartment", "apartment", "holiday_home", "villa",
    "chalet", "cottage", "cabin", "bungalow", "lodge", "resort", "all_inclusive_resort", "spa_resort",
    "ski_resort_hotel", "golf_resort", "beach_resort", "eco_lodge", "farm_stay", "agritourism", "ryokan",
    "minshuku", "machiya", "riad", "dar", "kasbah", "castle", "palace", "manor_house", "country_house",
    "monastery_stay", "lighthouse", "houseboat", "boat_hotel", "treehouse", "glamping", "tented_camp",
    "yurt", "igloo", "cave_hotel", "overwater_bungalow", "love_hotel", "homestay", "pension", "pousada",
    "parador", "hacienda", "trullo", "dammuso", "masseria", "gite", "tiny_house", "container_hotel",
    "condo_hotel", "residence", "student_residence", "extended_stay_hotel", "airport_hotel", "casino_hotel",
    "heritage_hotel", "safari_lodge", "mountain_hut", "wine_estate",
]
PROPERTY_SYNONYMS = {
    "boutique_hotel": ["boutique", "small hotel", "intimate hotel"],
    "bed_and_breakfast": ["b&b", "bnb"],
    "apartment": ["flat", "airbnb style", "self-catering"],
    "hostel": ["backpacker", "dorm"],
    "ryokan": ["japanese inn", "tatami"],
}
for pt in PROPERTY_TYPES:
    add("property_type", pt, pt.replace("_", " ").title().replace("And", "&"), synonyms=PROPERTY_SYNONYMS.get(pt, ()))

# --------------------------------------------------------------------------- style & atmosphere
bools("style", [
    ("independent", "Independent (not part of a chain)", ["not a chain", "no chain", "non-chain", "independent"]),
    ("chain", "Part of a hotel chain", ["chain hotel", "big brand"]),
    ("family_run", "Family-run", ["family owned", "run by a family", "owner operated"]),
    ("small_property", "Small property (≤ 30 rooms)", ["small", "intimate", "cozy", "cosy"]),
    ("large_property", "Large property (200+ rooms)", ["big hotel", "large hotel"]),
    ("quiet_atmosphere", "Quiet atmosphere", ["quiet", "calm", "peaceful", "tranquil"]),
    ("party_atmosphere", "Lively / party atmosphere", ["party", "lively", "social", "nightlife hotel"]),
    ("romantic", "Romantic", ["honeymoon", "couples getaway"]),
    ("luxury", "Luxury", ["luxurious", "high end", "5-star feel"]),
    ("budget_style", "Budget / no-frills", ["cheap", "basic", "no frills"]),
    ("design_focus", "Design-led interiors", ["designer", "stylish", "instagrammable"]),
    ("historic_building", "Historic building", ["historic", "old building", "monument", "heritage"]),
    ("modern_building", "Modern / contemporary building", ["modern", "contemporary"]),
    ("minimalist", "Minimalist style", []),
    ("rustic", "Rustic style", ["countryside feel"]),
    ("art_hotel", "Art hotel / gallery on site", ["art"]),
    ("cozy", "Cozy / homely", ["cosy", "homely", "warm atmosphere"]),
    ("adults_only", "Adults only", ["no kids", "child free", "adults-only"]),
    ("kids_welcome", "Kids welcome", ["child friendly", "family friendly"]),
    ("lgbtq_friendly", "LGBTQ+ friendly", ["gay friendly", "queer friendly"]),
    ("women_only_floor", "Women-only floor / rooms", []),
    ("digital_detox", "Digital detox", ["no wifi retreat"]),
    ("wellness_retreat", "Wellness retreat", []),
    ("eco_style", "Eco / sustainable style", ["eco", "green hotel"]),
    ("hip_trendy", "Hip / trendy", ["trendy", "cool"]),
    ("traditional_local", "Traditional local style", ["authentic", "local style"]),
    ("secluded", "Secluded / remote", ["remote", "off the beaten path", "isolated"]),
    ("instagram_worthy", "Photogenic / instagram-worthy", []),
    ("pet_themed", "Pet-themed / cat café hotel", []),
    ("themed_rooms", "Themed rooms", []),
    ("smoke_free_property", "Entirely smoke-free property", ["no smoking at all"]),
    ("smoking_allowed_property", "Smoking allowed areas", ["smoker friendly"]),
    ("alcohol_free_property", "Alcohol-free property", ["dry hotel", "no alcohol"]),
    ("muslim_friendly", "Muslim-friendly", ["halal friendly"]),
    ("kosher_friendly", "Kosher-friendly", []),
    ("religious_retreat", "Religious / spiritual retreat", []),
    ("student_friendly", "Student-friendly", []),
    ("senior_friendly", "Senior-friendly", ["elderly"]),
    ("solo_friendly", "Solo-traveller friendly (no single supplement)", ["solo", "single traveller"]),
    ("group_friendly", "Group-friendly", ["large group", "stag", "hen party"]),
])

# --------------------------------------------------------------------------- location
rng("location", "distance_to_center", "Distance to city centre", "km", 0, 50, 0.5, ["central", "city centre", "downtown", "walking distance"])
POIS = ["airport", "main_train_station", "metro_station", "tram_stop", "bus_station", "ferry_terminal", "cruise_port",
        "beach", "ski_lift", "old_town", "convention_center", "exhibition_center", "stadium", "university",
        "hospital", "theme_park", "national_park", "lake", "river", "harbour", "shopping_mall", "main_shopping_street",
        "nightlife_district", "museum_quarter", "business_district", "golf_course", "marina", "hiking_trailhead",
        "zoo", "casino", "concert_hall", "christmas_market", "vineyard", "hot_spring", "landmark"]
for poi in POIS:
    rng("location", f"distance_to_{poi}", f"Distance to {poi.replace('_', ' ')}", "km", 0, 100, 0.1,
        [f"near {poi.replace('_', ' ')}", f"close to {poi.replace('_', ' ')}"])
rng("location", "walk_score", "Walkability score", "score", 0, 100, 5, ["walkable"])
rng("location", "transit_score", "Public transport score", "score", 0, 100, 5, ["good transport"])
rng("location", "neighbourhood_safety", "Neighbourhood safety score", "score", 0, 10, 0.5, ["safe area"])
rng("location", "neighbourhood_noise", "Neighbourhood noise level (lower = quieter)", "dB", 30, 90, 5, ["quiet street", "noisy"])
rng("location", "elevation", "Elevation", "m", 0, 5000, 50, ["altitude", "mountain"])
bools("location", [
    ("beachfront", "Beachfront", ["on the beach", "beach front"]),
    ("lakefront", "Lakefront", ["on the lake"]),
    ("riverside", "Riverside", ["by the river", "canal side"]),
    ("canal_side", "Canal-side", ["on a canal"]),
    ("oceanfront", "Oceanfront", ["sea front", "seafront"]),
    ("ski_in_ski_out", "Ski-in / ski-out", ["ski in", "slope side"]),
    ("in_old_town", "In the old town", ["historic centre", "old town"]),
    ("city_centre", "In the city centre", ["central", "centre", "downtown"]),
    ("quiet_street", "On a quiet street", ["no traffic noise", "quiet location"]),
    ("pedestrian_zone", "In a pedestrian zone", []),
    ("near_nightlife", "Near nightlife", ["bars nearby", "going out"]),
    ("near_restaurants", "Many restaurants nearby", []),
    ("near_supermarket", "Supermarket within 500 m", []),
    ("near_park", "Park within 500 m", ["green area"]),
    ("near_public_transport", "Public transport within 300 m", []),
    ("countryside", "Countryside", ["rural", "nature"]),
    ("mountain_location", "In the mountains", ["alps", "mountains"]),
    ("island_location", "On an island", []),
    ("desert_location", "In the desert", []),
    ("forest_location", "In a forest", ["woods"]),
    ("vineyard_location", "In a vineyard / wine region", []),
    ("airport_area", "Airport area", ["near airport", "layover"]),
    ("business_area", "Business district", []),
    ("residential_area", "Residential area", ["local neighbourhood"]),
    ("waterfront", "Waterfront", []),
    ("hilltop", "Hilltop", []),
    ("cliffside", "Cliffside", []),
    ("private_island", "Private island", []),
    ("gated_area", "Gated community", []),
    ("car_free_area", "Car-free area", []),
])

# --------------------------------------------------------------------------- room: size & layout
rng("room", "size", "Room size", "m2", 5, 500, 1, ["square meters", "sqm", "m2", "spacious", "big room"])
rng("room", "bedrooms", "Number of bedrooms", "rooms", 0, 10, 1, ["2 bedroom", "separate bedroom"])
rng("room", "bathrooms", "Number of bathrooms", "rooms", 1, 8, 1, ["two bathrooms"])
rng("room", "beds", "Number of beds", "beds", 1, 12, 1)
rng("room", "floor_level", "Floor level", "floor", -1, 100, 1, ["high floor", "ground floor", "top floor"])
rng("room", "ceiling_height", "Ceiling height", "m", 2, 6, 0.1, ["high ceilings"])
rng("room", "max_occupancy", "Max occupancy of the room", "people", 1, 20, 1)
bools("room", [
    ("studio", "Studio layout", []),
    ("suite", "Suite", ["junior suite"]),
    ("separate_living_room", "Separate living room", ["living area", "lounge area"]),
    ("loft", "Loft / duplex", ["duplex", "mezzanine"]),
    ("penthouse", "Penthouse", []),
    ("connecting_rooms", "Connecting rooms available", ["interconnecting", "adjoining rooms"]),
    ("family_room", "Family room", ["room for 4"]),
    ("dormitory", "Dormitory bed", ["dorm bed", "shared room"]),
    ("female_dorm", "Female-only dorm", []),
    ("private_room", "Private room", []),
    ("entire_place", "Entire place to yourself", ["whole apartment", "entire home"]),
    ("single_room", "Single room", []),
    ("floor_space_exercise", "Open floor space (yoga / exercise)", ["yoga", "stretch", "floor space", "workout space"]),
    ("dining_area", "Dining area", []),
    ("walk_in_closet", "Walk-in closet", []),
    ("ground_floor_room", "Ground-floor room", ["no stairs room"]),
    ("top_floor_room", "Top-floor room", []),
    ("corner_room", "Corner room", []),
    ("private_entrance", "Private entrance", []),
    ("private_garden", "Private garden", []),
    ("private_pool", "Private pool", ["plunge pool"]),
    ("private_hot_tub", "Private hot tub", ["private jacuzzi"]),
    ("private_sauna", "Private sauna", []),
    ("rooftop_access", "Private rooftop access", []),
])

# --------------------------------------------------------------------------- beds & sleep
BED_TYPES = [
    ("double_bed", "Double bed (single mattress)", ["real double bed", "proper double", "not two twins", "double bed"]),
    ("queen_bed", "Queen bed", ["queen"]),
    ("king_bed", "King bed", ["king size", "king"]),
    ("super_king_bed", "Super-king bed", []),
    ("twin_beds", "Twin beds", ["two single beds", "twins"]),
    ("single_bed", "Single bed", []),
    ("bunk_bed", "Bunk bed", []),
    ("sofa_bed", "Sofa bed", ["pull out couch"]),
    ("futon", "Futon", ["tatami bed"]),
    ("water_bed", "Water bed", []),
    ("round_bed", "Round bed", []),
    ("canopy_bed", "Four-poster / canopy bed", []),
    ("extra_long_bed", "Extra-long bed (≥ 210 cm)", ["tall person", "long bed"]),
    ("adjustable_bed", "Adjustable bed", []),
]
for name, label, syn in BED_TYPES:
    add("beds", name, label, synonyms=syn)
rng("beds", "bed_width", "Bed width", "cm", 80, 240, 10, ["wide bed"])
bools("beds", [
    ("crib_available", "Cot / crib available", ["baby cot", "crib"]),
    ("extra_bed_available", "Extra bed available", ["rollaway"]),
    ("pillow_menu", "Pillow menu", []),
    ("hypoallergenic_bedding", "Hypoallergenic bedding", ["allergy", "allergies"]),
    ("feather_free_bedding", "Feather-free bedding", []),
    ("memory_foam_mattress", "Memory foam mattress", []),
    ("firm_mattress", "Firm mattress", ["hard mattress"]),
    ("soft_mattress", "Soft mattress", []),
    ("premium_linen", "Premium linen (Egyptian cotton etc.)", []),
    ("blackout_curtains", "Blackout curtains", ["dark room", "blackout blinds"]),
    ("soundproofing", "Soundproofed room", ["soundproof", "no hallway noise", "can't hear bar", "quiet room", "good insulation"]),
    ("away_from_elevator", "Room away from elevator / bar", ["away from noise"]),
    ("sleep_kit", "Sleep kit (earplugs, eye mask)", ["earplugs"]),
    ("white_noise_machine", "White-noise machine", []),
    ("reading_lights_both_sides", "Reading light on both sides of the bed", ["bedside lamps both sides", "reading light"]),
    ("sockets_by_bed", "Power sockets next to the bed", ["plug by bed"]),
    ("turndown_service", "Turndown service", []),
])

# --------------------------------------------------------------------------- bathroom
bools("bathroom", [
    ("private_bathroom", "Private bathroom", ["ensuite", "en-suite"]),
    ("shared_bathroom", "Shared bathroom", []),
    ("rain_shower", "Rain shower", ["rainfall shower"]),
    ("walk_in_shower", "Walk-in shower", []),
    ("bathtub", "Bathtub", ["bath", "tub"]),
    ("freestanding_bathtub", "Freestanding bathtub", []),
    ("shower_and_bathtub", "Separate shower and bathtub", []),
    ("jacuzzi_bathtub", "Jacuzzi / whirlpool bathtub", []),
    ("double_sink", "Double sink", []),
    ("bidet", "Bidet", []),
    ("japanese_toilet", "Japanese smart toilet", ["washlet"]),
    ("separate_toilet", "Separate toilet", []),
    ("heated_floor_bathroom", "Heated bathroom floor", []),
    ("bathrobe", "Bathrobe", []),
    ("slippers", "Slippers", []),
    ("premium_toiletries", "Premium toiletries", []),
    ("refillable_toiletries", "Refillable toiletries (no mini bottles)", []),
    ("hairdryer", "Hairdryer", []),
    ("magnifying_mirror", "Magnifying mirror", []),
    ("towel_warmer", "Towel warmer", []),
    ("steam_shower", "Steam shower", []),
    ("outdoor_shower", "Outdoor shower", []),
    ("bathroom_window", "Bathroom with window", []),
    ("strong_water_pressure", "Strong water pressure", []),
])

# --------------------------------------------------------------------------- in-room amenities
bools("room_amenities", [
    ("air_conditioning", "Air conditioning", ["ac", "aircon"]),
    ("heating", "Heating", []),
    ("ceiling_fan", "Ceiling fan", []),
    ("individual_climate_control", "Individual climate control", []),
    ("fireplace", "Fireplace", []),
    ("balcony", "Balcony", []),
    ("terrace", "Terrace", ["patio"]),
    ("opening_windows", "Windows that open", ["fresh air", "window opens"]),
    ("floor_to_ceiling_windows", "Floor-to-ceiling windows", []),
    ("natural_light", "Lots of natural light", ["bright room", "sunny"]),
    ("desk", "Work desk", ["desk", "workspace"]),
    ("ergonomic_chair", "Ergonomic office chair", []),
    ("external_monitor", "External monitor", []),
    ("seating_area", "Seating area", ["armchair"]),
    ("sofa", "Sofa", ["couch"]),
    ("wardrobe", "Wardrobe", []),
    ("clothes_rack", "Clothes rack", []),
    ("iron", "Iron & ironing board", []),
    ("trouser_press", "Trouser press", []),
    ("in_room_safe", "In-room safe", ["safe"]),
    ("laptop_safe", "Laptop-size safe", []),
    ("tv", "TV", []),
    ("smart_tv", "Smart TV", []),
    ("streaming_services", "Streaming services (Netflix etc.)", ["netflix"]),
    ("chromecast", "Screen casting (Chromecast / AirPlay)", ["airplay"]),
    ("satellite_channels", "Satellite channels", []),
    ("bluetooth_speaker", "Bluetooth speaker", []),
    ("record_player", "Record player", []),
    ("game_console", "Game console", ["playstation", "xbox"]),
    ("usb_charging", "USB charging ports", []),
    ("universal_sockets", "Universal power sockets", ["adapter"]),
    ("wireless_charger", "Wireless phone charger", []),
    ("telephone", "Telephone", []),
    ("alarm_clock", "Alarm clock", []),
    ("smart_room_controls", "Smart room controls / tablet", []),
    ("voice_assistant", "Voice assistant", []),
    ("air_purifier", "Air purifier", []),
    ("humidifier", "Humidifier", []),
    ("dehumidifier", "Dehumidifier", []),
    ("mosquito_net", "Mosquito net", []),
    ("full_length_mirror", "Full-length mirror", []),
    ("yoga_mat", "Yoga mat in room", ["yoga mat"]),
    ("in_room_fitness", "In-room fitness equipment", ["peloton"]),
    ("hammock", "Hammock", []),
    ("telescope", "Telescope", []),
    ("piano", "Piano", []),
    ("board_games", "Board games", []),
    ("books_library", "Books in room", []),
    ("umbrella", "Umbrella provided", []),
    ("luggage_rack", "Luggage rack", []),
])

# --------------------------------------------------------------------------- kitchen & in-room F&B
bools("kitchen", [
    ("kitchen", "Full kitchen", ["self catering", "cook"]),
    ("kitchenette", "Kitchenette", []),
    ("refrigerator", "Refrigerator", ["fridge"]),
    ("minibar", "Minibar", []),
    ("free_minibar", "Free minibar", []),
    ("microwave", "Microwave", []),
    ("oven", "Oven", []),
    ("stovetop", "Stovetop", []),
    ("dishwasher", "Dishwasher", []),
    ("coffee_machine", "Coffee machine", ["nespresso", "espresso"]),
    ("kettle", "Electric kettle", ["tea"]),
    ("toaster", "Toaster", []),
    ("blender", "Blender", []),
    ("cookware", "Cookware & utensils", []),
    ("dining_table", "Dining table", []),
    ("bottled_water_free", "Free bottled water", []),
    ("wine_cooler", "Wine cooler", []),
    ("baby_bottle_warmer", "Baby bottle warmer", []),
    ("outdoor_grill", "Outdoor grill / BBQ", ["bbq", "barbecue"]),
    ("washing_machine", "Washing machine", ["washer"]),
    ("dryer", "Tumble dryer", []),
])

# --------------------------------------------------------------------------- views
VIEWS = ["sea", "ocean", "lake", "river", "canal", "mountain", "city", "skyline", "garden", "pool", "park",
         "courtyard", "landmark", "old_town", "volcano", "vineyard", "forest", "desert", "harbour", "sunset", "sunrise",
         "ski_slope", "northern_lights"]
for v in VIEWS:
    add("view", f"{v}_view", f"{v.replace('_', ' ').capitalize()} view", synonyms=[f"{v.replace('_', ' ')} view"])
add("view", "no_view_ok", "View not important (cheaper)")

# --------------------------------------------------------------------------- connectivity & work
rng("connectivity", "wifi_speed", "Wi-Fi speed (measured)", "Mbps", 1, 2000, 5, ["fast wifi", "strong wifi", "good internet"])
bools("connectivity", [
    ("free_wifi", "Free Wi-Fi", ["wifi", "internet"]),
    ("wifi_in_room", "Wi-Fi in the room (not only lobby)", ["in-room wifi", "wifi in room"]),
    ("wired_ethernet", "Wired ethernet", ["lan cable"]),
    ("mobile_hotspot", "Portable hotspot provided", ["pocket wifi"]),
    ("free_international_calls", "Free international calls", []),
    ("coworking_space", "Coworking lounge", ["coworking", "co-working", "shared workspace"]),
    ("reading_room", "Reading room / library", ["library", "quiet lounge", "reading room"]),
    ("business_centre", "Business centre", []),
    ("meeting_rooms", "Meeting rooms", []),
    ("conference_hall", "Conference hall", []),
    ("event_space", "Event space", ["wedding venue"]),
    ("printer_access", "Printer access", []),
    ("phone_booths", "Private phone / video-call booths", ["zoom booth"]),
    ("day_use_rooms", "Day-use rooms", []),
    ("long_stay_work_setup", "Remote-work room package", ["workation"]),
])

# --------------------------------------------------------------------------- common areas
bools("common_areas", [
    ("lounge", "Lounge", []),
    ("lounge_natural_light", "Lounge with natural light", ["bright lounge", "sunny lounge"]),
    ("garden", "Garden", []),
    ("rooftop_terrace", "Rooftop terrace", ["roof terrace"]),
    ("shared_kitchen", "Shared kitchen", []),
    ("games_room", "Games room", []),
    ("billiards", "Billiards", []),
    ("library", "Library", []),
    ("cinema_room", "Cinema room", []),
    ("music_room", "Music room", []),
    ("art_gallery", "Art gallery", []),
    ("chapel", "Chapel", []),
    ("prayer_room", "Prayer room", []),
    ("smoking_area", "Designated smoking area", []),
    ("courtyard", "Courtyard", []),
    ("sun_deck", "Sun deck", []),
    ("fire_pit", "Fire pit", []),
    ("picnic_area", "Picnic area", []),
    ("shared_lounge_tv", "Shared TV lounge", []),
    ("elevator", "Elevator", ["lift"]),
    ("luggage_storage", "Luggage storage", []),
    ("lockers", "Lockers", []),
    ("gift_shop", "Gift shop", []),
    ("convenience_store", "Convenience store on site", []),
    ("atm_on_site", "ATM on site", []),
    ("hair_salon", "Hair salon", []),
    ("laundry_service", "Laundry service", []),
    ("self_service_laundry", "Self-service laundry", []),
    ("dry_cleaning", "Dry cleaning", []),
    ("shoe_shine", "Shoe shine", []),
])

# --------------------------------------------------------------------------- food & drink
MEAL_PLANS = [
    ("room_only", "Room only"), ("breakfast_included", "Breakfast included"), ("half_board", "Half board"),
    ("full_board", "Full board"), ("all_inclusive", "All inclusive"), ("ultra_all_inclusive", "Ultra all inclusive"),
]
for name, label in MEAL_PLANS:
    add("meals", name, label, synonyms=[label.lower()], exclusive_group="meal_plan")
bools("meals", [
    ("buffet_breakfast", "Buffet breakfast", []),
    ("continental_breakfast", "Continental breakfast", []),
    ("english_breakfast", "Full English breakfast", []),
    ("american_breakfast", "American breakfast", []),
    ("asian_breakfast", "Asian breakfast", []),
    ("breakfast_in_bed", "Breakfast in bed", []),
    ("late_breakfast", "Breakfast served until 11:00+", ["late breakfast"]),
    ("early_breakfast", "Breakfast from 06:00", ["early breakfast"]),
    ("grab_and_go_breakfast", "Grab-and-go breakfast", []),
    ("vegetarian_options", "Vegetarian options", ["vegetarian"]),
    ("vegan_options", "Vegan options", ["vegan"]),
    ("gluten_free_options", "Gluten-free options", ["celiac", "coeliac"]),
    ("lactose_free_options", "Lactose-free options", []),
    ("nut_free_kitchen", "Nut-allergy aware kitchen", []),
    ("halal_food", "Halal food", ["halal"]),
    ("kosher_food", "Kosher food", ["kosher"]),
    ("keto_options", "Keto / low-carb options", []),
    ("organic_food", "Organic / local produce", ["farm to table"]),
    ("kids_menu", "Kids' menu", []),
    ("restaurant", "Restaurant on site", []),
    ("michelin_restaurant", "Michelin-starred restaurant", ["michelin"]),
    ("fine_dining", "Fine dining", []),
    ("rooftop_restaurant", "Rooftop restaurant", []),
    ("bar", "Bar", []),
    ("rooftop_bar", "Rooftop bar", []),
    ("wine_bar", "Wine bar", []),
    ("cocktail_bar", "Cocktail bar", []),
    ("pool_bar", "Pool bar", ["swim-up bar"]),
    ("cafe", "Café", ["coffee shop"]),
    ("bakery", "Bakery on site", []),
    ("room_service", "Room service", []),
    ("room_service_24h", "24-hour room service", []),
    ("snack_bar", "Snack bar", []),
    ("happy_hour", "Happy hour", []),
    ("free_drinks_evening", "Free evening drinks", []),
    ("afternoon_tea", "Afternoon tea", []),
    ("packed_lunch", "Packed lunch on request", []),
    ("private_chef", "Private chef available", []),
    ("bbq_facilities", "BBQ facilities", []),
    ("cooking_classes", "Cooking classes", []),
    ("wine_tasting", "Wine tasting", []),
    ("brewery_on_site", "Brewery / distillery on site", []),
    ("tea_ceremony", "Tea ceremony", []),
    ("in_room_dining_menu", "In-room dining menu", []),
    ("dinner_included", "Dinner included", []),
])
CUISINES = ["italian", "french", "japanese", "chinese", "thai", "indian", "mexican", "spanish", "greek", "turkish",
            "lebanese", "moroccan", "korean", "vietnamese", "seafood", "steakhouse", "local", "mediterranean",
            "middle_eastern", "fusion", "peruvian", "brazilian", "german", "dutch", "scandinavian", "georgian"]
for c in CUISINES:
    add("cuisine", c, f"{c.replace('_', ' ').capitalize()} cuisine on site", synonyms=[f"{c} food", f"{c} restaurant"])

# --------------------------------------------------------------------------- wellness
bools("wellness", [
    ("spa", "Spa", ["wellness"]),
    ("sauna", "Sauna", []),
    ("infrared_sauna", "Infrared sauna", []),
    ("steam_room", "Steam room", []),
    ("hammam", "Hammam / Turkish bath", ["turkish bath"]),
    ("onsen", "Onsen / hot spring bath", ["hot spring"]),
    ("hot_tub", "Hot tub", ["jacuzzi", "whirlpool"]),
    ("massage", "Massage", []),
    ("couples_massage", "Couples massage", []),
    ("facial_treatments", "Facial treatments", []),
    ("manicure_pedicure", "Manicure / pedicure", []),
    ("thalasso", "Thalassotherapy", []),
    ("cold_plunge", "Cold plunge / ice bath", ["ice bath"]),
    ("salt_room", "Salt room", []),
    ("float_tank", "Floatation tank", []),
    ("cryotherapy", "Cryotherapy", []),
    ("meditation_room", "Meditation room", ["meditation"]),
    ("yoga_classes", "Yoga classes", ["yoga class"]),
    ("pilates_classes", "Pilates classes", []),
    ("fitness_centre", "Fitness centre", ["gym"]),
    ("gym_24h", "24-hour gym", []),
    ("personal_trainer", "Personal trainer", []),
    ("free_weights", "Free weights", []),
    ("peloton_bikes", "Spin / Peloton bikes", []),
    ("running_routes", "Running routes / maps", ["jogging"]),
    ("boxing_studio", "Boxing studio", []),
    ("medical_spa", "Medical spa", []),
    ("detox_programme", "Detox programme", []),
    ("sleep_programme", "Sleep programme", []),
    ("ayurveda", "Ayurveda", []),
])

# --------------------------------------------------------------------------- pools
rng("pool", "pool_length", "Pool length", "m", 5, 100, 1, ["lap pool", "long pool"])
rng("pool", "pool_water_temperature", "Pool water temperature", "°C", 15, 40, 1, ["warm pool"])
bools("pool", [
    ("swimming_pool", "Swimming pool", ["pool"]),
    ("indoor_pool", "Indoor pool", []),
    ("outdoor_pool", "Outdoor pool", []),
    ("heated_pool", "Heated pool", []),
    ("infinity_pool", "Infinity pool", []),
    ("rooftop_pool", "Rooftop pool", []),
    ("saltwater_pool", "Saltwater pool", []),
    ("kids_pool", "Kids' pool", ["children's pool"]),
    ("adults_only_pool", "Adults-only pool", []),
    ("water_slide", "Water slide", ["waterpark"]),
    ("lazy_river", "Lazy river", []),
    ("swim_up_room", "Swim-up room", []),
    ("pool_open_all_year", "Pool open year-round", []),
    ("lifeguard", "Lifeguard on duty", []),
    ("pool_towels", "Pool towels provided", []),
    ("sun_loungers", "Sun loungers", []),
    ("cabanas", "Cabanas", []),
    ("natural_pool", "Natural / swimming pond", []),
    ("private_beach", "Private beach", []),
    ("beach_towels", "Beach towels & chairs", []),
])

# --------------------------------------------------------------------------- family & kids
rng("family", "min_child_age_allowed", "Minimum child age allowed", "years", 0, 18, 1)
bools("family", [
    ("kids_club", "Kids' club", []),
    ("teen_club", "Teen club", []),
    ("babysitting", "Babysitting", ["nanny"]),
    ("playground", "Playground", []),
    ("indoor_play_area", "Indoor play area", []),
    ("kids_stay_free", "Kids stay free", []),
    ("baby_equipment", "Baby equipment (high chair, bath)", ["high chair"]),
    ("stroller_rental", "Stroller rental", ["pram"]),
    ("baby_monitor", "Baby monitor", []),
    ("childproofed_rooms", "Child-proofed rooms", []),
    ("kids_activities", "Kids' activities programme", []),
    ("family_entertainment", "Evening family entertainment", ["mini disco"]),
    ("children_welcome_amenities", "Welcome gifts for kids", []),
    ("bunk_room_for_kids", "Separate kids' bunk room", []),
    ("changing_table", "Baby changing table", []),
    ("kids_tv_channels", "Kids' TV channels", []),
    ("family_bathroom", "Family bathroom", []),
    ("baby_food_available", "Baby food available", []),
])

# --------------------------------------------------------------------------- accessibility
bools("accessibility", [
    ("wheelchair_accessible", "Wheelchair accessible", ["wheelchair", "disabled access"]),
    ("step_free_access", "Step-free access", ["no steps"]),
    ("roll_in_shower", "Roll-in shower", []),
    ("shower_chair", "Shower chair", []),
    ("grab_bars", "Grab bars in bathroom", ["grab rails"]),
    ("raised_toilet", "Raised toilet", []),
    ("lowered_sink", "Lowered sink", []),
    ("wide_doorways", "Doorways ≥ 80 cm", []),
    ("accessible_parking", "Accessible parking", []),
    ("elevator_to_all_floors", "Elevator to all floors", []),
    ("braille_signage", "Braille / tactile signage", []),
    ("visual_alarms", "Visual fire alarms", []),
    ("hearing_loop", "Hearing loop", []),
    ("tty_phone", "TTY phone", []),
    ("service_animals_allowed", "Service animals allowed", ["guide dog"]),
    ("accessible_pool_lift", "Pool hoist / lift", []),
    ("hoist_in_room", "Ceiling hoist in room", []),
    ("adjustable_height_bed", "Adjustable-height bed", []),
    ("low_bed", "Low bed", []),
    ("emergency_cord", "Emergency cord in bathroom", []),
    ("accessible_restaurant", "Accessible restaurant", []),
    ("sign_language_staff", "Sign-language staff", []),
    ("sensory_friendly", "Sensory-friendly / autism-friendly", ["autism"]),
    ("allergy_friendly_rooms", "Allergy-friendly rooms", []),
    ("mobility_scooter_charging", "Mobility-scooter charging", []),
])

# --------------------------------------------------------------------------- pets
rng("pets", "max_pet_weight", "Max pet weight allowed", "kg", 1, 80, 1, ["big dog", "small dog"])
rng("pets", "max_pets", "Max number of pets", "pets", 1, 5, 1)
rng("pets", "pet_fee", "Pet fee per night", "EUR", 0, 200, 5)
add("pets", "pets_allowed", "Pets allowed", synonyms=["pet friendly", "pet-friendly", "bring my dog", "with my cat"],
    exclusive_group="pet_policy")
add("pets", "no_pets_on_property", "No pets on property (allergy-safe)", synonyms=["no pets", "pet free", "allergic to dogs"],
    exclusive_group="pet_policy")
bools("pets", [
    ("dogs_allowed", "Dogs allowed", ["dog friendly"]),
    ("cats_allowed", "Cats allowed", []),
    ("free_pet_stay", "Pets stay free", []),
    ("pet_bed_and_bowls", "Pet bed & bowls", []),
    ("dog_walking_service", "Dog-walking service", []),
    ("pet_sitting", "Pet sitting", []),
    ("dog_park_nearby", "Dog park nearby", []),
    ("pet_menu", "Pet menu", []),
    ("pets_in_restaurant", "Pets allowed in restaurant", []),
    ("pet_grooming", "Pet grooming", []),
])

# --------------------------------------------------------------------------- parking & transport
rng("parking", "parking_price", "Parking price per day", "EUR", 0, 100, 1)
rng("parking", "max_vehicle_height", "Max vehicle height in garage", "m", 1.5, 4.5, 0.1, ["van", "camper"])
bools("parking", [
    ("free_parking", "Free parking", []),
    ("on_site_parking", "On-site parking", []),
    ("private_parking", "Private parking", []),
    ("secure_parking", "Secure / guarded parking", []),
    ("covered_parking", "Covered / garage parking", ["garage"]),
    ("valet_parking", "Valet parking", []),
    ("street_parking", "Free street parking", []),
    ("parking_reservation", "Parking can be reserved", []),
    ("ev_charging", "EV charging", ["electric car", "tesla charger"]),
    ("ev_charging_free", "Free EV charging", []),
    ("rv_parking", "RV / camper parking", []),
    ("motorcycle_parking", "Motorcycle parking", []),
    ("bike_storage", "Bike storage", []),
    ("bike_rental", "Bike rental", ["bicycle"]),
    ("free_bikes", "Free bikes", []),
    ("e_bike_rental", "E-bike rental", []),
    ("scooter_rental", "Scooter rental", []),
    ("car_rental_desk", "Car rental desk", []),
    ("airport_shuttle", "Airport shuttle", []),
    ("free_airport_shuttle", "Free airport shuttle", []),
    ("train_station_shuttle", "Train-station shuttle", []),
    ("city_shuttle", "Shuttle to city centre", []),
    ("ski_shuttle", "Ski shuttle", []),
    ("beach_shuttle", "Beach shuttle", []),
    ("private_transfer", "Private transfer", []),
    ("limousine_service", "Limousine service", []),
    ("free_public_transport_pass", "Free public-transport pass", ["city card"]),
    ("helipad", "Helipad", []),
    ("boat_dock", "Boat dock / mooring", []),
])

# --------------------------------------------------------------------------- services & policies
rng("policies", "check_in_from", "Earliest check-in time", "hour", 0, 24, 1, ["early check-in"])
rng("policies", "check_out_until", "Latest check-out time", "hour", 0, 24, 1, ["late checkout"])
rng("policies", "min_guest_age", "Minimum guest age", "years", 0, 30, 1)
rng("policies", "security_deposit", "Security deposit", "EUR", 0, 2000, 10)
rng("policies", "min_nights", "Minimum stay required", "nights", 1, 30, 1)
bools("policies", [
    ("front_desk_24h", "24-hour front desk", ["24h reception", "late arrival"]),
    ("self_check_in", "Self check-in", ["keybox", "contactless check in"]),
    ("mobile_key", "Mobile room key", ["digital key"]),
    ("express_check_in_out", "Express check-in / check-out", []),
    ("early_check_in_available", "Early check-in available", []),
    ("late_check_out_available", "Late check-out available", []),
    ("concierge", "Concierge", []),
    ("butler_service", "Butler service", []),
    ("daily_housekeeping", "Daily housekeeping", []),
    ("eco_housekeeping_option", "Opt-out housekeeping (eco)", []),
    ("tour_desk", "Tour desk", []),
    ("ticket_service", "Ticket service", []),
    ("currency_exchange", "Currency exchange", []),
    ("wake_up_service", "Wake-up service", []),
    ("non_smoking_rooms", "Non-smoking rooms", ["non smoking"]),
    ("smoking_rooms", "Smoking rooms", ["smoker"]),
    ("parties_allowed", "Parties / events allowed", []),
    ("quiet_hours", "Enforced quiet hours", []),
    ("visitors_allowed", "Visitors allowed", []),
    ("unmarried_couples_allowed", "Unmarried couples welcome", []),
    ("local_couples_allowed", "Local-resident couples welcome", []),
    ("id_not_required_at_checkin", "No ID scan at check-in", []),
    ("private_check_in", "Private check-in / check-out", []),
    ("free_room_upgrade_possible", "Free upgrade on availability", []),
    ("welcome_drink", "Welcome drink", []),
    ("honesty_bar", "Honesty bar", []),
])

# --------------------------------------------------------------------------- staff languages
LANGUAGES = [
    "english", "dutch", "german", "french", "spanish", "italian", "portuguese", "russian", "ukrainian", "polish",
    "czech", "slovak", "hungarian", "romanian", "bulgarian", "greek", "turkish", "arabic", "hebrew", "persian",
    "hindi", "urdu", "bengali", "tamil", "thai", "vietnamese", "indonesian", "malay", "tagalog", "chinese_mandarin",
    "chinese_cantonese", "japanese", "korean", "swedish", "norwegian", "danish", "finnish", "icelandic", "estonian",
    "latvian", "lithuanian", "croatian", "serbian", "slovenian", "albanian", "georgian", "armenian", "azerbaijani",
    "kazakh", "swahili", "catalan", "basque", "sign_language_international",
]
for lang in LANGUAGES:
    nice = lang.replace("_", " ").title()
    add("language", f"staff_speaks_{lang}", f"Staff speak {nice}", synonyms=[f"{nice} speaking staff", f"speaks {nice}"])

# --------------------------------------------------------------------------- activities on site / nearby
ACTIVITIES = [
    "skiing", "snowboarding", "cross_country_skiing", "ice_skating", "sledding", "snowshoeing", "diving", "snorkelling",
    "surfing", "kitesurfing", "windsurfing", "sailing", "kayaking", "canoeing", "stand_up_paddle", "jet_ski",
    "fishing", "water_skiing", "golf", "mini_golf", "tennis", "padel", "squash", "badminton", "table_tennis",
    "volleyball", "basketball", "football_pitch", "horse_riding", "cycling_tours", "mountain_biking", "hiking",
    "rock_climbing", "via_ferrata", "paragliding", "hot_air_balloon", "zip_lining", "safari", "whale_watching",
    "bird_watching", "stargazing", "wine_tours", "city_tours", "walking_tours", "boat_tours", "cooking_school",
    "art_classes", "dance_classes", "live_music", "evening_entertainment", "karaoke", "nightclub_on_site", "casino",
    "bowling", "escape_room", "archery", "shooting_range", "spa_day_passes", "hot_springs_nearby", "caving",
    "canyoning", "rafting", "fishing_charters", "yacht_charter", "museum_passes", "theatre_nearby", "festival_nearby",
]
for a in ACTIVITIES:
    add("activities", a, a.replace("_", " ").capitalize(), synonyms=[a.replace("_", " ")])

# --------------------------------------------------------------------------- sustainability
bools("sustainability", [
    ("eco_certified", "Eco-certified (Green Key, EarthCheck…)", ["green key", "sustainable", "eco certified"]),
    ("carbon_neutral", "Carbon neutral", []),
    ("renewable_energy", "100% renewable energy", ["solar"]),
    ("no_single_use_plastic", "No single-use plastics", []),
    ("water_saving", "Water-saving measures", []),
    ("local_sourcing", "Locally sourced food", []),
    ("composting", "Composting / food-waste programme", []),
    ("ev_fleet", "Electric vehicle fleet", []),
    ("community_projects", "Supports local community projects", []),
    ("b_corp", "B Corp certified", []),
    ("passive_house", "Passive-house building", []),
    ("rainwater_harvesting", "Rainwater harvesting", []),
    ("wildlife_protection", "Wildlife protection programme", []),
    ("fair_trade_products", "Fair-trade products", []),
    ("green_roof", "Green roof", []),
])

# --------------------------------------------------------------------------- health, safety & hygiene
bools("safety", [
    ("security_24h", "24-hour security", []),
    ("cctv_common_areas", "CCTV in common areas", []),
    ("smoke_detectors", "Smoke detectors", []),
    ("carbon_monoxide_detector", "Carbon-monoxide detector", []),
    ("fire_extinguishers", "Fire extinguishers", []),
    ("first_aid_kit", "First-aid kit", []),
    ("doctor_on_call", "Doctor on call", []),
    ("defibrillator", "Defibrillator (AED)", []),
    ("key_card_access", "Key-card access", []),
    ("key_card_elevator", "Key-card elevator access", []),
    ("enhanced_cleaning", "Enhanced cleaning protocol", []),
    ("contactless_service", "Contactless service", []),
    ("in_room_hand_sanitizer", "Hand sanitiser in room", []),
    ("well_lit_entrance", "Well-lit entrance", []),
    ("door_chain_peephole", "Door chain / peephole", []),
])

# --------------------------------------------------------------------------- brand / loyalty (enum)
add("brand", "hotel_brand", "Hotel brand", "enum", ["marriott", "hilton", "hyatt", "accor", "ihg"],
    options=["Marriott", "Hilton", "Hyatt", "IHG", "Accor", "Wyndham", "Choice", "Best Western", "Radisson",
             "Meliá", "NH", "Barceló", "Four Seasons", "Mandarin Oriental", "Kempinski", "citizenM", "Motel One",
             "Premier Inn", "Ace Hotel", "Soho House"])
add("brand", "loyalty_programme", "Earn loyalty points with", "enum",
    options=["Marriott Bonvoy", "Hilton Honors", "World of Hyatt", "IHG One Rewards", "ALL Accor"])
add("brand", "exclude_brands", "Exclude brands", "enum", ["not marriott", "no hilton"],
    options=["Marriott", "Hilton", "Hyatt", "IHG", "Accor", "Wyndham", "Choice", "Best Western", "Radisson"])

# --------------------------------------------------------------------------- property size & structure
rng("property", "number_of_rooms", "Number of rooms in property", "rooms", 1, 3000, 1, ["small hotel", "big hotel"])
rng("property", "number_of_floors", "Number of floors in building", "floors", 1, 120, 1, ["low rise", "skyscraper"])
rng("property", "free_cancellation_until", "Free cancellation until N days before", "days", 0, 60, 1)
rng("property", "noise_rating_room", "Measured in-room noise rating (lower = quieter)", "dB", 20, 70, 1, ["very quiet"])
rng("property", "meeting_room_capacity", "Largest meeting room capacity", "people", 2, 5000, 5)
rng("property", "kids_club_min_age", "Kids' club minimum age", "years", 0, 17, 1)
rng("property", "desk_width", "Work desk width", "cm", 50, 250, 10, ["big desk"])
rng("property", "balcony_size", "Balcony / terrace size", "m2", 1, 200, 1, ["big balcony"])
rng("property", "garden_size", "Garden size", "m2", 10, 50000, 10)
rng("property", "beach_distance_walk_minutes", "Walking minutes to beach", "min", 0, 60, 1)
rng("property", "center_distance_walk_minutes", "Walking minutes to centre", "min", 0, 90, 1, ["walking distance"])
rng("property", "sleeps", "Sleeps (whole unit)", "people", 1, 30, 1, ["for 6 people", "sleeps"])
bools("property", [
    ("courtyard_facing_room", "Courtyard-facing room (away from street)", ["not facing street", "back side room"]),
    ("street_facing_room", "Street-facing room", []),
    ("no_bar_or_club_below", "No bar / club in the building", ["no bar downstairs", "no nightclub", "not above a bar"]),
    ("no_construction_nearby", "No construction work nearby", []),
    ("double_glazing", "Double / triple glazing", ["double glazed"]),
    ("carpeted_floors", "Carpeted floors", []),
    ("hardwood_floors", "Hardwood floors", []),
    ("tatami_floors", "Tatami floors", []),
    ("exclusive_use", "Exclusive use / buyout possible", []),
    ("listed_heritage", "Listed heritage monument", []),
    ("converted_building", "Converted building (warehouse, church…)", []),
])

# --------------------------------------------------------------------------- trip purpose (soft ranking signals)
for tp in ["business_trip", "honeymoon", "family_holiday", "solo_trip", "backpacking", "ski_trip", "beach_holiday",
           "city_break", "romantic_weekend", "wellness_trip", "road_trip_stopover", "event_or_concert",
           "medical_trip", "workation", "student_trip", "girls_trip", "bachelor_party", "wedding_guest",
           "layover", "anniversary", "babymoon", "pilgrimage", "sports_event", "conference_attendee"]:
    add("trip_purpose", tp, tp.replace("_", " ").capitalize(), synonyms=[tp.replace("_", " ")])

# --------------------------------------------------------------------------- activity-specific services
bools("services_ski", [
    ("ski_storage", "Ski storage", ["ski room"]), ("ski_rental", "Ski rental on site", []),
    ("boot_dryer", "Boot dryer", []), ("ski_school", "Ski school", []), ("ski_pass_sales", "Ski-pass sales", []),
    ("ski_valet", "Ski valet", []), ("apres_ski_bar", "Après-ski bar", ["apres ski"]),
    ("snow_chains_rental", "Snow-chain rental", []),
])
bools("services_beach", [
    ("beach_umbrellas", "Beach umbrellas included", []), ("water_sports_centre", "Water-sports centre", []),
    ("beach_club", "Beach club", []), ("snorkel_gear", "Free snorkel gear", []),
    ("dive_centre", "PADI dive centre", ["padi"]), ("beach_butler", "Beach butler", []),
    ("sandy_beach", "Sandy beach", ["sand beach"]), ("pebble_beach", "Pebble beach", []),
    ("calm_water_beach", "Calm-water / shallow beach", ["safe for kids swimming"]),
    ("blue_flag_beach", "Blue Flag beach", []),
])
bools("services_active", [
    ("bike_repair_kit", "Bike repair station", []), ("bike_wash", "Bike wash", []),
    ("cyclist_friendly", "Cyclist-friendly (Bett+Bike etc.)", ["cyclists"]),
    ("hiking_maps", "Hiking maps & advice", []), ("guided_hikes", "Guided hikes", []),
    ("boot_room", "Boot / drying room", ["drying room"]), ("motorcyclist_friendly", "Motorcyclist-friendly", ["bikers"]),
    ("golf_club_storage", "Golf-club storage", []), ("golf_discounts", "Golf green-fee discounts", []),
    ("tennis_coaching", "Tennis coaching", []), ("equipment_rental", "Sports equipment rental", []),
    ("marathon_friendly", "Runner / marathon packages", []),
])

# --------------------------------------------------------------------------- religion & culture
bools("culture", [
    ("qibla_direction", "Qibla direction marked", []), ("prayer_mat", "Prayer mat available", []),
    ("no_pork_served", "No pork served", []), ("alcohol_free_minibar", "Alcohol-free minibar", []),
    ("sabbath_elevator", "Sabbath elevator", ["shabbat"]), ("non_electronic_keys", "Mechanical keys (Shabbat-friendly)", []),
    ("synagogue_nearby", "Synagogue nearby", []), ("mosque_nearby", "Mosque nearby", []),
    ("church_nearby", "Church nearby", []), ("temple_nearby", "Temple nearby", []),
    ("separate_wellness_hours", "Gender-separated wellness hours", []), ("ramadan_meals", "Suhoor / iftar meals", []),
])

# --------------------------------------------------------------------------- MICE & events
bools("events", [
    ("av_equipment", "AV equipment", ["projector"]), ("video_conferencing", "Video-conferencing equipment", []),
    ("wedding_packages", "Wedding packages", []), ("banquet_hall", "Banquet hall", []),
    ("outdoor_event_space", "Outdoor event space", []), ("team_building", "Team-building activities", []),
    ("group_rates", "Group rates", []), ("event_coordinator", "Dedicated event coordinator", []),
])

# --------------------------------------------------------------------------- nearby everyday amenities
for amen in ["pharmacy", "laundromat", "gym", "coworking_space", "bakery", "cafe", "grocery_store", "atm",
             "hospital", "vegan_restaurant", "playground", "beach_bar", "bike_share_station", "ev_charging_station",
             "late_night_food", "tourist_information", "car_rental", "yoga_studio", "public_pool", "night_market"]:
    add("nearby", f"{amen}_within_500m", f"{amen.replace('_', ' ').capitalize()} within 500 m")

# --------------------------------------------------------------------------- seasonal & special occasions
bools("occasions", [
    ("christmas_programme", "Christmas programme", []), ("new_year_party", "New Year's Eve party", ["nye"]),
    ("valentines_package", "Valentine's package", []), ("birthday_package", "Birthday / celebration package", []),
    ("honeymoon_package", "Honeymoon package", []), ("proposal_package", "Proposal package", []),
    ("romantic_room_decoration", "Romantic room decoration", ["rose petals"]),
    ("champagne_on_arrival", "Champagne on arrival", []), ("summer_open_air_cinema", "Open-air cinema", []),
    ("festival_packages", "Festival / event packages", []),
])

# --------------------------------------------------------------------------- guest services (extra)
bools("guest_services", [
    ("personal_shopper", "Personal shopper", []), ("in_room_massage", "In-room massage", []),
    ("grocery_delivery", "Grocery delivery before arrival", []), ("luggage_forwarding", "Luggage forwarding", []),
    ("medical_assistance", "24-h medical assistance", []), ("multilingual_concierge", "Multilingual concierge", []),
    ("tailor_service", "Tailor service", []), ("photography_service", "Photography service", []),
    ("chauffeur_service", "Chauffeur service", []), ("pet_friendly_rooms_only_floor", "Dedicated pet-free floors", []),
    ("rooftop_yoga", "Rooftop yoga sessions", []), ("guest_bicycles_kids", "Kids' bicycles", []),
    ("free_welcome_snacks", "Free welcome snacks", []), ("free_evening_snacks", "Free evening snacks", []),
    ("free_coffee_all_day", "Free coffee all day", []), ("free_laundry", "Free laundry", []),
])

# --------------------------------------------------------------------------- explicit cross-group conflicts & implications
CONFLICTS = [
    ("style.independent", "style.chain"),
    ("style.family_run", "style.chain"),
    ("style.adults_only", "style.kids_welcome"),
    ("style.adults_only", "family.kids_club"),
    ("style.adults_only", "family.kids_stay_free"),
    ("style.small_property", "style.large_property"),
    ("style.smoke_free_property", "policies.smoking_rooms"),
    ("style.smoke_free_property", "style.smoking_allowed_property"),
    ("policies.non_smoking_rooms", "policies.smoking_rooms"),
    ("style.alcohol_free_property", "meals.bar"),
    ("style.alcohol_free_property", "meals.wine_bar"),
    ("style.alcohol_free_property", "meals.cocktail_bar"),
    ("style.digital_detox", "connectivity.free_wifi"),
    ("bathroom.private_bathroom", "bathroom.shared_bathroom"),
    ("room.dormitory", "room.private_room"),
    ("room.dormitory", "room.entire_place"),
    ("beds.double_bed", "beds.twin_beds"),
    ("price.free_cancellation", "price.non_refundable_ok"),
    ("pets.no_pets_on_property", "pets.dogs_allowed"),
    ("pets.no_pets_on_property", "pets.cats_allowed"),
    ("pets.no_pets_on_property", "pets.free_pet_stay"),
    ("style.budget_style", "style.luxury"),
    ("property_type.hostel", "style.luxury"),
    ("location.countryside", "location.city_centre"),
    ("room.ground_floor_room", "room.top_floor_room"),
    ("beds.firm_mattress", "beds.soft_mattress"),
    ("meals.room_only", "meals.buffet_breakfast"),
    ("property.courtyard_facing_room", "property.street_facing_room"),
    ("style.quiet_atmosphere", "style.party_atmosphere"),
]
# Soft conflicts: allowed together, but the assistant warns because results will be thin
# or the user may be contradicting themselves ("quiet" + "near nightlife").
SOFT_CONFLICTS = [
    ("style.quiet_atmosphere", "location.near_nightlife"),
    ("beds.soundproofing", "location.near_nightlife"),
    ("style.secluded", "location.city_centre"),
    ("style.budget_style", "meals.michelin_restaurant"),
    ("style.adults_only", "trip_purpose.family_holiday"),
    ("style.digital_detox", "connectivity.coworking_space"),
    ("property_type.hostel", "trip_purpose.honeymoon"),
]
IMPLIES = {
    "beds.queen_bed": ["beds.double_bed"],
    "beds.king_bed": ["beds.double_bed"],
    "beds.super_king_bed": ["beds.double_bed"],
    "style.family_run": ["style.independent"],
    "connectivity.wifi_in_room": ["connectivity.free_wifi"],
    "meals.all_inclusive": ["meals.breakfast_included", "meals.dinner_included"],
    "meals.half_board": ["meals.breakfast_included"],
    "meals.full_board": ["meals.breakfast_included", "meals.dinner_included"],
    "pets.dogs_allowed": ["pets.pets_allowed"],
    "pets.cats_allowed": ["pets.pets_allowed"],
    "pool.infinity_pool": ["pool.swimming_pool"],
    "pool.rooftop_pool": ["pool.swimming_pool"],
    "pool.heated_pool": ["pool.swimming_pool"],
    "wellness.gym_24h": ["wellness.fitness_centre"],
    "parking.free_parking": ["parking.on_site_parking"],
    "parking.ev_charging_free": ["parking.ev_charging"],
    "location.ski_in_ski_out": ["location.mountain_location"],
    "bathroom.rain_shower": ["bathroom.private_bathroom"],
}
# Filters that only make sense for certain destination kinds – the backend knows the destination's
# geo-features and flags these as "impossible here" instead of silently returning 0 hotels.
GEO_REQUIREMENTS = {
    "location.beachfront": "coast", "location.oceanfront": "coast", "view.sea_view": "coast",
    "view.ocean_view": "coast", "pool.private_beach": "coast", "location.distance_to_beach": "coast",
    "location.ski_in_ski_out": "ski_area", "location.distance_to_ski_lift": "ski_area",
    "view.ski_slope_view": "ski_area", "activities.skiing": "ski_area",
    "location.lakefront": "lake", "view.lake_view": "lake",
    "location.mountain_location": "mountains", "view.mountain_view": "mountains",
    "view.volcano_view": "volcano", "view.northern_lights_view": "aurora_zone",
    "location.desert_location": "desert", "location.canal_side": "canals", "view.canal_view": "canals",
}

by_id = {f["id"]: f for f in CATALOG}
for a, b in CONFLICTS:
    by_id[a].setdefault("conflicts_with", []).append(b)
    by_id[b].setdefault("conflicts_with", []).append(a)
for a, b in SOFT_CONFLICTS:
    by_id[a].setdefault("soft_conflicts_with", []).append(b)
    by_id[b].setdefault("soft_conflicts_with", []).append(a)
for src, targets in IMPLIES.items():
    by_id[src]["implies"] = targets
for fid, feature in GEO_REQUIREMENTS.items():
    by_id[fid]["requires_geo_feature"] = feature


def main() -> None:
    missing = [x for pair in CONFLICTS for x in pair if x not in by_id]
    missing += [t for ts in IMPLIES.values() for t in ts if t not in by_id]
    missing += [x for pair in SOFT_CONFLICTS for x in pair if x not in by_id]
    assert not missing, missing

    (OUT_DIR / "catalog.json").write_text(json.dumps(
        {"version": "2026-09-27", "count": len(CATALOG), "filters": CATALOG}, ensure_ascii=False, indent=1), encoding="utf-8")
    with (OUT_DIR / "catalog.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "label", "category", "type", "unit", "min", "max", "options", "synonyms",
                    "exclusive_group", "conflicts_with", "implies", "requires_geo_feature"])
        for f in CATALOG:
            w.writerow([f["id"], f["label"], f["category"], f["type"], f.get("unit", ""), f.get("min", ""),
                        f.get("max", ""), "|".join(f.get("options", [])), "|".join(f["synonyms"]),
                        f.get("exclusive_group", ""), "|".join(f.get("conflicts_with", [])),
                        "|".join(f.get("implies", [])), f.get("requires_geo_feature", "")])

    counts: dict[str, dict[str, int]] = {}
    for f in CATALOG:
        c = counts.setdefault(f["category"], {"boolean": 0, "range": 0, "enum": 0})
        c[f["type"]] += 1
    lines = ["| Category | Boolean | Range | Enum | Total |", "|---|---:|---:|---:|---:|"]
    for cat, c in counts.items():
        lines.append(f"| {cat} | {c['boolean']} | {c['range']} | {c['enum']} | {sum(c.values())} |")
    tb = sum(c["boolean"] for c in counts.values())
    tr = sum(c["range"] for c in counts.values())
    te = sum(c["enum"] for c in counts.values())
    lines.append(f"| **Total** | **{tb}** | **{tr}** | **{te}** | **{len(CATALOG)}** |")
    (OUT_DIR / "SUMMARY.md").write_text(
        "# Filter catalog summary\n\nGenerated by `filters/build_catalog.py`. Full list: `catalog.csv` / `catalog.json`.\n\n"
        + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(CATALOG)} filters ({tb} boolean, {tr} range, {te} enum)")


if __name__ == "__main__":
    main()
