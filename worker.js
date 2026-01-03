/**
 * Cloudflare Worker for collecting YOLO training data.
 * 
 * Instructions:
 * 1. Create a new Worker in Cloudflare Dashboard.
 * 2. Create an R2 Bucket (e.g., named "yolo-datasets").
 * 3. In Worker Settings -> R2 Object Storage Bindings:
 *    - Variable Name: DATASET_BUCKET
 *    - R2 Bucket: (Select your bucket)
 * 4. Copy this code into the Worker editor.
 * 5. Deploy and copy the Worker URL.
 */

export default {
  async fetch(request, env) {
    // 1. Handle CORS (Allow functionality from your website)
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*", // Or restrict to your specific domain
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

      // 3. Generate a unique ID (Timestamp + Random) to prevent overwrites
      const timestamp = Date.now();
      const random = Math.floor(Math.random() * 10000);
      // Clean filename (remove extension)
      const safeName = originalName.replace(/\.[^/.]+$/, "").replace(/[^a-zA-Z0-9-_]/g, "_");
      const uniqueId = `${timestamp}_${random}_${safeName}`;

      // 4. Save to R2
      // Save Image
      await env.DATASET_BUCKET.put(
        `images/${uniqueId}.jpg`, 
        imageFile, 
        { httpMetadata: { contentType: imageFile.type } }
      );

      // Save Label
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
