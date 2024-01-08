"""Helpers for managing the site structure."""
import json
import os
import glob

from pyprojroot import here

OUTPUT_DIR = "docs"

def create_sub_listings(output_dir=OUTPUT_DIR):

    with open(here(f"{output_dir}/listings.json"), "r") as f:
        listings = json.load(f)
        f.close()
    for i, d in enumerate(listings):
        # filter out the index listing
        sub_ind = d["listing"]
        if sub_ind == "/index.html":
            _ = listings.pop(i)
        else:
            # make valid paths for all listings that remain
            pth_str = f"{OUTPUT_DIR}{sub_ind}"
            pth = here(pth_str)
            pth = os.path.join(os.path.dirname(pth), "listings.json")
            with open(pth, "w", encoding="utf-8") as f:
                print(f"Writing to {pth}")
                json.dump(d["items"], f, ensure_ascii=False, indent=4)
                f.close()
    return None

if __name__ == "__main__":
    create_sub_listings()
