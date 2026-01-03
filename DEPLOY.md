# How to Deploy to Cloudflare Pages

This application is a static web app powered by PyScript (Python in the browser) and Vite. It is ready for "one-click" deployment.

## Option 1: Direct Upload (Easiest for testing)

1.  Locate the `dist` folder in your project directory (created after running `npm run build`).
2.  Go to [Cloudflare Dashboard](https://dash.cloudflare.com/) > **Workers & Pages**.
3.  Click **Create Application** > **Pages** > **Upload Assets**.
4.  Name your project (e.g., `banknote-cropper`).
5.  Drag and drop the contents of the `dist` folder into the upload area.
6.  Click **Deploy Site**.

## Option 2: Connect to Git (Recommended for updates)

1.  Push this code to a GitHub/GitLab repository.
2.  Go to [Cloudflare Dashboard](https://dash.cloudflare.com/) > **Workers & Pages**.
3.  Click **Create Application** > **Pages** > **Connect to Git**.
4.  Select your repository.
5.  **Build Settings:**
    *   **Framework Preset:** Vite
    *   **Build Command:** `npm run build`
    *   **Build Output Directory:** `dist`
6.  Click **Save and Deploy**.

## Custom Domain

Once deployed, you can go to your Pages project settings > **Custom Domains** to connect it to your own domain (e.g., `cropper.yourdomain.com`).

## Note on Performance

The first time you load the page, it will download the PyScript runtime and OpenCV libraries (~30MB). This is normal for a serverless, client-side Python app. Subsequent loads will be faster due to browser caching.
