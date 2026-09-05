# CS2py skin-share relay

This is the Cloudflare Worker used by the optional skin-share feature. It uses
one Durable Object per settled match fingerprint, forwards only validated
skin snapshots to the other connected clients in that room, and expires room
state after a short idle period.

The Worker does not need a server or an open port on a player's computer. The
public endpoint can use the free `workers.dev` hostname.

## Deploy

From this directory:

```powershell
npm install
npx wrangler login
npx wrangler secret put ROOM_TOKEN
npm run deploy
```

When prompted for `ROOM_TOKEN`, enter a long random token shared only with the
people using the tool. Never commit that value, a GitHub token, or a Discord
webhook to this directory.

The deployed relay URL for the client is:

```text
wss://<worker-subdomain>.workers.dev/ws
```

The client appends the current settled match fingerprint to that path. Set
the same `ROOM_TOKEN` in each user's local `settings.json` under `SkinShare`.

## Verify

The health endpoint should return JSON:

```text
https://<worker-subdomain>.workers.dev/health
```

The relay is intentionally disabled in the main app until `SkinShare.enabled`
is set to `true` and both `relay` and `auth_token` are configured.
