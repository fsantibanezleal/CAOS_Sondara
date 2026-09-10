# Deploy, GitHub Pages

The public static workbench is served at `https://sondara.ml.fasl-work.com/`. The Pages workflow validates a compact normalized project contract, builds the frontend and deploys `frontend/dist` with the `frontend/public/CNAME` file.

Enable once per repository: Settings -> Pages -> Source = GitHub Actions. The existing `*.ml.fasl-work.com` DNS wildcard covers the custom hostname. The optional VPS nginx path remains dormant until the API lane is activated.
