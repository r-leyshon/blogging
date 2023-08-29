# blogging
[![Netlify Status](https://api.netlify.com/api/v1/badges/981c5fe4-bbc9-42ee-92b3-2087884fbdc8/deploy-status)](https://app.netlify.com/sites/anothernerdblog/deploys)

Musings, ramblings, generally putting things down in text so I don't forget them.

## Quarto Notes

* When re-rendering the site, be sure to use quarto cli `quarto render` rather
than the GUI render button, which only renders the active quarto doc.
* Include a .nojekyll file in the root.
* Ensure the index.qmd references the above .nojekyll in the YAML under
`resources`. This will ensure it's copied into the output folder `docs` once 
rendered. 
* Ensure the site is rendered to a `docs` folder and that GitHub Pages is set to
build from this directory, instead of root.
* Be sure to check that the `docs` folder is not gitignored! Some template
gitignores will blanket ignore a docs folder.
* Quarto deletes any markdown file with the extension `.MD` on render, but not
files with the extension `.md`.
