"""Bundled local mushroom pictograms. No network or runtime image generation."""
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets" / "species_icons"

def icon_path(name):
    """Return a packaged pictogram for known species, or empty string."""
    key = str(name).strip().lower()
    from mushroom_forecast import SPECIES
    slugs = {"белый": "belyi", "подберёзовик": "podberezovik",
             "подосиновик": "podosinovik", "лисичка": "lisichka",
             "маслёнок": "maslenok", "опёнок": "openok",
             "груздь": "gruzd", "сыроежка": "syroezhka",
             "вешенка": "veshenka", "сморчок": "smorchok",
             "строчок": "strochok"}
    for species_id, species in SPECIES.items():
        if species.name.lower() == key:
            path = ASSETS / (slugs[species_id] + ".png")
            return str(path) if path.is_file() else ""
    return ""
