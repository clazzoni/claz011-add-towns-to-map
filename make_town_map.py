"""Generate a static PNG map of towns from CSV with regional context."""

import csv
import re
import time
import unicodedata
from pathlib import Path

import contextily as cx
import matplotlib.pyplot as plt
import pandas as pd
from geopy.geocoders import Nominatim
from pyproj import Transformer

# --- config ---
SCRIPT_DIR = Path(__file__).resolve().parent
TOWNS_CSV = SCRIPT_DIR / "towns_to_add_to_map.csv"
LARGER_TOWNS_CSV = SCRIPT_DIR / "larger_towns.csv"
HARBOUR_PAGES_DIR = SCRIPT_DIR.parent / "download-website-tmp" / "html_pages"
OUTPUT_PNG = SCRIPT_DIR / "towns_map.png"
OUTPUT_PDF = SCRIPT_DIR / "towns_map.pdf"

TITLE = "Towns in Southern Denmark and Schleswig-Holstein"
FIG_HEIGHT = 12
DPI = 250
PADDING_FRACTION = 0.04
PADDING_LEFT_FRACTION = 0.02
SAVE_PAD_INCHES = 0.05

FEATURED_COLOR = "#c0392b"
FEATURED_SIZE = 45
FEATURED_FONT_SIZE = 7
LARGER_COLOR = "#7f8c8d"
LARGER_SIZE = 35
LARGER_FONT_SIZE = 8

COORD_ROUND_DIGITS = 2
GEOCODE_DELAY_SECONDS = 1.1


def normalize_key(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.replace("ö", "o").replace("ø", "o").replace("æ", "ae").replace("å", "a")


def extract_search_names(name: str) -> list[str]:
    primary = name.strip()
    names = [primary]

    no_parens = re.sub(r"\s*\([^)]*\)", "", primary).strip()
    if no_parens and no_parens not in names:
        names.append(no_parens)

    paren_match = re.search(r"\(([^)]+)\)", primary)
    if paren_match:
        alias = paren_match.group(1).strip()
        if alias and alias not in names:
            names.append(alias)

    first_part = primary.split(",")[0].strip()
    if first_part and first_part not in names:
        names.append(first_part)

    return names


def load_harbour_coords_by_title() -> dict[str, tuple[float, float]]:
    coords_by_title: dict[str, tuple[float, float]] = {}
    if not HARBOUR_PAGES_DIR.exists():
        return coords_by_title

    for page_path in HARBOUR_PAGES_DIR.glob("*/page.html"):
        text = page_path.read_text(encoding="utf-8", errors="ignore")
        title_match = re.search(r"<h1><strong>(.*?)</strong></h1>", text, re.DOTALL)
        coord_match = re.search(
            r"Latitude:\s*([\d.]+),\s*Longitude:\s*([\d.]+)", text
        )
        if title_match and coord_match:
            title = re.sub(r"\s+", " ", title_match.group(1)).strip()
            lat = float(coord_match.group(1))
            lon = float(coord_match.group(2))
            coords_by_title[normalize_key(title)] = (lat, lon)

    return coords_by_title


HARBOUR_COORDS_BY_TITLE = load_harbour_coords_by_title()
_GEOCODER: Nominatim | None = None


def get_geocoder() -> Nominatim:
    global _GEOCODER
    if _GEOCODER is None:
        _GEOCODER = Nominatim(user_agent="tmp-download-map-town-map")
    return _GEOCODER


def geocode_town(name: str) -> tuple[float, float] | None:
    geolocator = get_geocoder()
    for query in extract_search_names(name):
        for suffix in ("Denmark", "Germany", ""):
            search = f"{query}, {suffix}".strip(", ") if suffix else query
            location = geolocator.geocode(search, timeout=10)
            if location is not None:
                return location.latitude, location.longitude
        time.sleep(GEOCODE_DELAY_SECONDS)
    return None


def resolve_coords(name: str, lat: float | None, lon: float | None) -> tuple[float, float] | None:
    if lat is not None and lon is not None and not (pd.isna(lat) or pd.isna(lon)):
        return float(lat), float(lon)

    harbour_coords = HARBOUR_COORDS_BY_TITLE.get(normalize_key(name))
    if harbour_coords is not None:
        return harbour_coords

    return geocode_town(name)


def coord_key(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, COORD_ROUND_DIGITS), round(lon, COORD_ROUND_DIGITS)


def read_towns_csv(csv_path: Path) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames and "name" not in reader.fieldnames:
            handle.seek(0)
            reader = csv.reader(handle)
            next(reader, None)
            for row in reader:
                if not row:
                    continue
                rows.append({"name": row[0].strip(), "lat": None, "lon": None})
            return pd.DataFrame(rows)

        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            lat = row.get("lat")
            lon = row.get("lon")
            rows.append(
                {
                    "name": name,
                    "lat": float(lat) if lat not in (None, "") else None,
                    "lon": float(lon) if lon not in (None, "") else None,
                }
            )

    return pd.DataFrame(rows)


def load_towns(csv_path: Path) -> pd.DataFrame:
    df = read_towns_csv(csv_path)

    rows = []
    seen_names: set[str] = set()
    seen_coords: set[tuple[float, float]] = set()
    excluded: list[str] = []

    for _, row in df.iterrows():
        name = str(row["name"]).strip()
        if not name:
            continue

        name_key = normalize_key(name)
        if name_key in seen_names:
            excluded.append(f"{name} (duplicate name)")
            continue

        lat = row["lat"] if "lat" in row else None
        lon = row["lon"] if "lon" in row else None
        coords = resolve_coords(name, lat, lon)
        if coords is None:
            excluded.append(f"{name} (not found)")
            continue

        location_key = coord_key(*coords)
        if location_key in seen_coords:
            excluded.append(f"{name} (duplicate location)")
            continue

        seen_names.add(name_key)
        seen_coords.add(location_key)
        rows.append({"name": name, "lat": coords[0], "lon": coords[1]})

    if excluded:
        print("Excluded towns:")
        for item in excluded:
            print(f"  - {item}")

    return pd.DataFrame(rows)


def save_towns(csv_path: Path, towns: pd.DataFrame) -> None:
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["name", "lat", "lon"], quoting=csv.QUOTE_MINIMAL
        )
        writer.writeheader()
        for row in towns.itertuples(index=False):
            writer.writerow(
                {
                    "name": row.name,
                    "lat": f"{row.lat:.10g}",
                    "lon": f"{row.lon:.10g}",
                }
            )
    print(f"Updated {csv_path} with {len(towns)} towns")


def load_larger_towns(csv_path: Path, featured: pd.DataFrame) -> pd.DataFrame:
    larger = pd.read_csv(csv_path)
    featured_keys = {normalize_key(name) for name in featured["name"]}
    featured_coords = {coord_key(row.lat, row.lon) for row in featured.itertuples()}
    keep = []
    for row in larger.itertuples():
        if normalize_key(row.name) in featured_keys:
            continue
        if coord_key(row.lat, row.lon) in featured_coords:
            continue
        keep.append(row._asdict())
    return pd.DataFrame(keep)


def to_web_mercator(lon: float, lat: float) -> tuple[float, float]:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    return transformer.transform(lon, lat)


def add_web_mercator_columns(df: pd.DataFrame) -> pd.DataFrame:
    coords = df.apply(lambda r: to_web_mercator(r["lon"], r["lat"]), axis=1)
    df = df.copy()
    df["x"] = [c[0] for c in coords]
    df["y"] = [c[1] for c in coords]
    return df


def compute_extent(
    featured: pd.DataFrame,
    larger: pd.DataFrame,
    padding_fraction: float,
    padding_left_fraction: float,
) -> tuple[float, float, float, float]:
    all_x = pd.concat([featured["x"], larger["x"]])
    all_y = pd.concat([featured["y"], larger["y"]])
    xmin, xmax = all_x.min(), all_x.max()
    ymin, ymax = all_y.min(), all_y.max()
    x_pad_right = (xmax - xmin) * padding_fraction
    x_pad_left = (xmax - xmin) * padding_left_fraction
    y_pad = (ymax - ymin) * padding_fraction
    return xmin - x_pad_left, xmax + x_pad_right, ymin - y_pad, ymax + y_pad


def figure_size_for_extent(extent: tuple[float, float, float, float]) -> tuple[float, float]:
    width = extent[1] - extent[0]
    height = extent[3] - extent[2]
    if height == 0:
        return 14.0, FIG_HEIGHT
    return FIG_HEIGHT * width / height, FIG_HEIGHT


def label_text(name: str) -> str:
    text = name.split(",")[0].strip()
    text = re.sub(r"\s*\([^)]*\)", "", text).strip()
    return text


def make_map(featured: pd.DataFrame, larger: pd.DataFrame) -> None:
    featured = add_web_mercator_columns(featured)
    larger = add_web_mercator_columns(larger)
    extent = compute_extent(
        featured, larger, PADDING_FRACTION, PADDING_LEFT_FRACTION
    )

    fig, ax = plt.subplots(figsize=figure_size_for_extent(extent))
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal", adjustable="box")
    ax.margins(0)
    ax.axis("off")
    fig.subplots_adjust(left=0, right=1, top=0.94, bottom=0.02)

    cx.add_basemap(
        ax,
        source=cx.providers.OpenStreetMap.Mapnik,
        crs="EPSG:3857",
    )

    ax.scatter(
        larger["x"],
        larger["y"],
        s=LARGER_SIZE,
        c="white",
        edgecolors=LARGER_COLOR,
        linewidths=1.2,
        zorder=3,
    )
    for _, row in larger.iterrows():
        ax.annotate(
            row["name"],
            (row["x"], row["y"]),
            textcoords="offset points",
            xytext=(5, 4),
            fontsize=LARGER_FONT_SIZE,
            color="#555555",
            zorder=4,
        )

    ax.scatter(
        featured["x"],
        featured["y"],
        s=FEATURED_SIZE,
        c=FEATURED_COLOR,
        edgecolors="white",
        linewidths=1.0,
        zorder=5,
    )
    for _, row in featured.iterrows():
        ax.annotate(
            label_text(row["name"]),
            (row["x"], row["y"]),
            textcoords="offset points",
            xytext=(4, 4),
            fontsize=FEATURED_FONT_SIZE,
            fontweight="bold",
            color="#1a1a1a",
            zorder=6,
        )

    ax.set_title(TITLE, fontsize=14, fontweight="bold", pad=12)
    fig.text(
        0.01,
        0.01,
        "© OpenStreetMap contributors",
        fontsize=7,
        color="#666666",
    )

    fig.savefig(
        OUTPUT_PNG,
        dpi=DPI,
        bbox_inches="tight",
        pad_inches=SAVE_PAD_INCHES,
        facecolor="white",
    )
    fig.savefig(
        OUTPUT_PDF,
        bbox_inches="tight",
        pad_inches=SAVE_PAD_INCHES,
        facecolor="white",
    )
    plt.close(fig)
    print(f"Saved {OUTPUT_PNG}")
    print(f"Saved {OUTPUT_PDF}")


def main() -> None:
    featured = load_towns(TOWNS_CSV)
    if featured.empty:
        raise SystemExit("No towns to plot after filtering.")

    save_towns(TOWNS_CSV, featured)
    larger = load_larger_towns(LARGER_TOWNS_CSV, featured)
    make_map(featured, larger)
    print(f"Plotted {len(featured)} featured towns and {len(larger)} larger towns")


if __name__ == "__main__":
    main()
