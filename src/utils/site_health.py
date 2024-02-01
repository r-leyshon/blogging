"""Helpers for managing the site structure."""
import json
import os
import glob

from pyprojroot import here

def create_sub_listings(output_dir:str="docs") -> None:
    """Create nested listing files in site subdirectories.

    Run this after a `quarto render`. The updated listings.json created by
    quarto will appear in the root of the rendered site output_dir. This file
    will be read and used to write listings files for all found sub-indexes.

    Parameters
    ----------
    output_dir : str, optional
        The output directory as specified in `_quarto.yml`, by default "docs"

    Returns
    -------
    NoneType
        None. Used for side effects.

    """
    with open(here(f"{output_dir}/listings.json"), "r") as f:
        listings = json.load(f)
        f.close()
    for d in listings:
        # filter out the index listing
        sub_ind = d["listing"]
        if sub_ind == "/index.html":
            pass
        else:
            # make valid paths for all listings that remain
            pth_str = f"{output_dir}{sub_ind}"
            pth = here(pth_str)
            pth = os.path.join(os.path.dirname(pth), "listings.json")
            with open(pth, "w", encoding="utf-8") as f:
                print(f"Writing to {pth}")
                json.dump(d["items"], f, ensure_ascii=False, indent=4)
                f.close()
    return None

if __name__ == "__main__":
    create_sub_listings()
