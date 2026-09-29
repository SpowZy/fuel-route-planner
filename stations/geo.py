"""Place-name helpers shared by the geodata build script and the location resolver.

Pure Python on purpose: no Django import, so scripts can use it directly.
"""

import re
import unicodedata

US_STATES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}

CA_PROVINCES = {
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "ON": "Ontario",
    "PE": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "YT": "Yukon",
}

# The price file covers the 48 contiguous states (plus Canadian provinces).
# Alaska and Hawaii are rejected at input time: no road route from the lower 48 to Hawaii,
# and the dataset has no stations there.
NOT_COVERED = {"AK", "HI"}

_STATE_BY_NAME = {name.upper(): code for code, name in US_STATES.items()}

_SUFFIXES = (
    "CITY AND BOROUGH",
    "CONSOLIDATED GOVERNMENT",
    "METROPOLITAN GOVERNMENT",
    "UNIFIED GOVERNMENT",
    "URBAN COUNTY",
    "MUNICIPALITY",
    "BOROUGH",
    "TOWNSHIP",
    "PLANTATION",
    "VILLAGE",
    "CITY",
    "TOWN",
    "CDP",
)
_ABBREVIATIONS = {"SAINT": "ST", "SAINTE": "STE", "FORT": "FT", "MOUNT": "MT"}


def country_of(state: str) -> str:
    return "CA" if state in CA_PROVINCES else "US"


def norm_place(name: str, strip_suffix: bool = False) -> str:
    """Normalize a place name so 'St. Louis city' and 'SAINT LOUIS' compare equal.

    strip_suffix is for Census names only ("Bay City city" -> "BAY CITY"). User input keeps
    its words, otherwise "Bay City" would collapse to "BAY".
    """
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    text = text.replace("&", " AND ")
    text = re.sub(r"\(.*?\)", " ", text)
    text = text.split("/")[0]
    text = re.sub(r"[.'`,]", "", text)
    text = re.sub(r"[-_]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if strip_suffix:
        for suffix in _SUFFIXES:
            if text.endswith(" " + suffix):
                text = text[: -len(suffix) - 1].strip()
                break
    return " ".join(_ABBREVIATIONS.get(token, token) for token in text.split())


def parse_state(token: str) -> str | None:
    """Accept 'TX', 'tx' or 'Texas'; return the two-letter code or None."""
    token = token.strip().upper().rstrip(".")
    if token in US_STATES:
        return token
    return _STATE_BY_NAME.get(token)
