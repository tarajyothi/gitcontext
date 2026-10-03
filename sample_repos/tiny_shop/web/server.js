// Minimal HTTP API exposing checkout.
const http = require("http");

function handleCheckout(req, res) {
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    try {
      const { items } = JSON.parse(body);
      if (!Array.isArray(items) || items.length === 0) {
        res.writeHead(400);
        return res.end(JSON.stringify({ error: "EmptyCartError: cannot checkout an empty cart" }));
      }
      res.writeHead(200);
      res.end(JSON.stringify({ ok: true }));
    } catch (e) {
      res.writeHead(400);
      res.end(JSON.stringify({ error: "invalid JSON" }));
    }
  });
}

http.createServer((req, res) => {
  if (req.method === "POST" && req.url === "/checkout") return handleCheckout(req, res);
  res.writeHead(404);
  res.end();
}).listen(3001);
