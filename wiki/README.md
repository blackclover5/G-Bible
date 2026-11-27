# Publishing these pages to GitHub Wiki

These Markdown files use GitHub Wiki page naming and links. To publish them:

1. Open the repository’s **Wiki** tab and create/enable the wiki if GitHub prompts you.
2. Clone the wiki repository. Its URL is usually `https://github.com/blackclover5/G-Bible.wiki.git`.
3. Copy the `.md` files from this `wiki/` directory into the cloned wiki repository.
4. Commit and push the wiki repository.

GitHub Wiki is a separate Git repository, so these source pages are maintained here for review and copied/published to the Wiki when ready. The wiki `Home.md` becomes its landing page. `README.md` here is publishing guidance and does not need to be copied.

Keep links between wiki pages in the `[[Page-Name]]` form. Links to the project’s regular repository documentation use relative paths and should be converted to repository URLs if they are moved into the standalone wiki repository. The pages currently use paths to `../docs/` where useful; after copying, replace those with links to the corresponding files on the default branch, for example `https://github.com/blackclover5/G-Bible/blob/main/docs/GETTING_STARTED.md`.
