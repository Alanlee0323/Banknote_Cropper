export default {
  async fetch(request, env) {
    // 1. Handle CORS (Allow functionality from your website)
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    // 2. Only allow POST requests
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    try {
      const formData = await request.formData();
      const imageFile = formData.get("image");
      const labelText = formData.get("label");
      const originalName = formData.get("filename");

      if (!imageFile || !labelText) {
        return new Response("Missing image or label", { status: 400 });
      }

      // 3. Generate a unique ID
      const timestamp = Date.now();
      const random = Math.floor(Math.random() * 10000);
      const safeName = (originalName || "unknown").replace(/\.[^/.]+$/, "").replace(/[^a-zA-Z0-9-_]/g, "_");
      const uniqueId = `${timestamp}_${random}_${safeName}`;

      // 4. Save to R2
      // WARNING: Make sure you have bound the R2 bucket as 'DATASET_BUCKET' in Settings -> Variables
      await env.DATASET_BUCKET.put(
        `images/${uniqueId}.jpg`, 
        imageFile, 
        { httpMetadata: { contentType: imageFile.type } }
      );

      await env.DATASET_BUCKET.put(
        `labels/${uniqueId}.txt`, 
        labelText, 
        { httpMetadata: { contentType: "text/plain" } }
      );

      return new Response(JSON.stringify({ success: true, id: uniqueId }), {
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*",
        },
      });

    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 500,
        headers: { "Access-Control-Allow-Origin": "*" },
      });
    }
  },
};