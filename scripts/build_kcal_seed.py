"""
Validates and reformats meal_planning_bot/data/kcal_seed.json.

The values in that file are hand-curated approximations for generic Spanish
ingredients (a "chicken breast", not any particular brand's), entered by
reading typical nutrition labels and well-known reference figures. They are
NOT pulled from an automated download of USDA FoodData Central, BEDCA,
CIQUAL or any other database — this script reads no external source, only
the committed JSON file itself.

This script re-reads the JSON, checks every entry against the `Unit` and
`Category` enums and the 0-900 kcal_ref bound used by the nutrition tests,
and rewrites the file sorted by key. Run it by hand after editing the seed;
it is never invoked by the bot at runtime.
"""

import json
from pathlib import Path

from meal_planning_bot.models import Category, Unit

SEED_PATH = Path(__file__).resolve().parent.parent / "meal_planning_bot" / "data" / "kcal_seed.json"


def main() -> None:
    raw = json.loads(SEED_PATH.read_text("utf-8"))

    for name, entry in raw.items():
        if name != name.lower():
            raise ValueError(f"{name!r} is not lower-cased")
        Unit(entry["unit"])
        Category(entry["category"])
        kcal_ref = float(entry["kcal_ref"])
        if not 0 <= kcal_ref <= 900:
            raise ValueError(f"{name!r} has an implausible kcal_ref: {kcal_ref}")

    sorted_entries = dict(sorted(raw.items()))
    SEED_PATH.write_text(json.dumps(sorted_entries, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"validated and rewrote {len(sorted_entries)} entries")


if __name__ == "__main__":
    main()
