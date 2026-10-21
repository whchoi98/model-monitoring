import { createHmac, randomUUID } from "node:crypto";
import { createServer, request as httpRequest } from "node:http";
import type { AddressInfo } from "node:net";

/** Real same-origin HTTP cookies: WebKit omits Cookie in intercepted request headers. */
export async function presenceHttpFixture(upstreamOrigin: string) {
  const seen = new Set<string>();
  const posts: string[] = [];
  const secret = randomUUID();
  const sign = (id: string) => createHmac("sha256", secret).update(id).digest("hex");
  let bootstraps = 0;
  let origin = "";
  const server = createServer((request, reply) => {
    if (request.url === "/api/presence") {
      const raw = /llm_monitor_visitor=([^;]+)/.exec(request.headers.cookie ?? "")?.[1];
      const [id, signature] = (raw ?? "").split(".");
      const valid = !!id && signature === sign(id);
      reply.setHeader("Content-Type", "application/json");
      reply.setHeader("Cache-Control", "no-store");
      if (request.method === "GET" && !valid) {
        const visitor = randomUUID().replaceAll("-", "");
        bootstraps++;
        reply.setHeader("Set-Cookie", `llm_monitor_visitor=${visitor}.${sign(visitor)}; Max-Age=31536000; Path=/api/presence; HttpOnly; SameSite=Lax`);
      }
      if (request.method === "POST") {
        request.resume();
        if (!valid || request.headers["x-llm-monitor-client"] !== "1" || request.headers.origin !== origin) {
          reply.writeHead(401); reply.end("{}"); return;
        }
        seen.add(id);
        posts.push(id);
      }
      reply.end(JSON.stringify({
        active_visitors: seen.size, total_visitors: 10000 + seen.size, initial_total: 10000,
        window_seconds: 90, as_of: new Date().toISOString(),
        counting_since: seen.size ? new Date().toISOString() : null,
      }));
      return;
    }
    const target = new URL(request.url ?? "/", upstreamOrigin);
    const upstream = httpRequest(target, { method: request.method, headers: request.headers }, (response) => {
      reply.writeHead(response.statusCode ?? 502, response.headers);
      response.pipe(reply);
    });
    upstream.on("error", () => { if (!reply.headersSent) reply.writeHead(502); reply.end(); });
    request.pipe(upstream);
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return {
    origin, seen, posts,
    bootstraps: () => bootstraps,
    close: () => new Promise<void>((resolve) => {
      server.closeAllConnections();
      server.close(() => resolve());
    }),
  };
}
