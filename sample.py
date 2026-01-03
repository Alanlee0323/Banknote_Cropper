export default {
  async fetch(request, env) {
    // 定義通用的 CORS 標頭
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*", // 允許所有網域
      "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };

    // 1. 處理 OPTIONS 預檢請求 (瀏覽器會先發送這個)
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: corsHeaders,
      });
    }

    // 2. 只允許 POST
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { 
        status: 405,
        headers: corsHeaders 
      });
    }

    try {
      const formData = await request.formData();
      const imageFile = formData.get("image");
      const labelText = formData.get("label");
      const originalName = formData.get("filename");

      if (!imageFile || !labelText) {
        return new Response("Missing image or label", { 
          status: 400,
          headers: corsHeaders 
        });
      }

      // 3. 生成唯一 ID
      const timestamp = Date.now();
      const random = Math.floor(Math.random() * 10000);
      const safeName = (originalName || "unknown").replace(/\.[^/.]+$/, "").replace(/[^a-zA-Z0-9-_]/g, "_");
      const uniqueId = `${timestamp}_${random}_${safeName}`;

      // 4. 存入 R2
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
          ...corsHeaders,
        },
      });

    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 500,
        headers: { 
          ...corsHeaders,
          "Content-Type": "application/json"
        },
      });
    }
  },
};
