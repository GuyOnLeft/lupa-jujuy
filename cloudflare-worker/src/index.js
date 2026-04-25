import { parseTwilioBody, parseMapsUrl, hashSender, MSG } from './bot.js';
import { insertReport, fetchPending, updateStatus, uploadPhoto } from './supabase.js';

const ALLOWED_ORIGIN = 'https://guyonleft.github.io';

function twiml(message) {
  const escaped = message.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return new Response(
    `<?xml version="1.0" encoding="UTF-8"?><Response><Message>${escaped}</Message></Response>`,
    { status: 200, headers: { 'Content-Type': 'text/xml' } }
  );
}

async function isTwilioRequest(request, body, authToken) {
  if (!authToken) return false;
  const signature = request.headers.get('X-Twilio-Signature') || '';
  if (!signature) return false;

  const url = new URL(request.url).toString();
  const params = new URLSearchParams(body);
  const sortedKeys = [...params.keys()].sort();
  let toSign = url;
  for (const key of sortedKeys) toSign += key + (params.get(key) ?? '');

  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(authToken), { name: 'HMAC', hash: 'SHA-1' }, false, ['sign']
  );
  const signed = await crypto.subtle.sign('HMAC', key, enc.encode(toSign));
  const expected = btoa(String.fromCharCode(...new Uint8Array(signed)));
  return signature === expected;
}

// Webhook: strict origin. Admin: open (protected by Bearer token instead).
function corsHeaders(origin, forAdmin = false) {
  const allowedOrigin = forAdmin ? (origin || '*') : (origin === ALLOWED_ORIGIN ? ALLOWED_ORIGIN : null);
  if (!allowedOrigin) return {};
  return {
    'Access-Control-Allow-Origin': allowedOrigin,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
  };
}

function isAuthed(request, env) {
  const auth = request.headers.get('Authorization') || '';
  return auth === `Bearer ${env.ADMIN_PASSWORD}`;
}

async function handleWebhook(request, env) {
  const text = await request.text();

  if (!await isTwilioRequest(request, text, env.TWILIO_AUTH_TOKEN)) {
    return new Response('Forbidden', { status: 403 });
  }

  const params = new URLSearchParams(text);
  const msg = parseTwilioBody(params);
  const senderHash = await hashSender(msg.rawFrom);
  const sb = { url: env.SUPABASE_URL, key: env.SUPABASE_SERVICE_ROLE_KEY };

  if (msg.type === 'location') {
    await env.SESSIONS.put(
      senderHash,
      JSON.stringify({ lat: msg.lat, lng: msg.lng }),
      { expirationTtl: 300 }
    );
    return twiml(MSG.gotLoc);
  }

  if (msg.type === 'text') {
    let coords = parseMapsUrl(msg.body);

    // Short URLs (maps.app.goo.gl / goo.gl/maps) — follow redirect to get the real URL
    if (!coords && /maps\.app\.goo\.gl|goo\.gl\/maps/.test(msg.body)) {
      const shortMatch = msg.body.match(/https?:\/\/[^\s]+/);
      if (shortMatch) {
        try {
          const res = await fetch(shortMatch[0], { redirect: 'follow' });
          coords = parseMapsUrl(res.url);
        } catch (_) { /* network error — fall through to badUrl */ }
      }
    }

    if (coords) {
      await env.SESSIONS.put(
        senderHash,
        JSON.stringify({ lat: coords.lat, lng: coords.lng }),
        { expirationTtl: 300 }
      );
      return twiml(MSG.gotLocMaps);
    }

    const looksLikeMapsLink = /google\.com\/maps|maps\.app\.goo\.gl|goo\.gl\/maps/.test(msg.body);
    if (looksLikeMapsLink) return twiml(MSG.badUrl);

    return twiml(MSG.intro);
  }

  if (msg.type === 'media') {
    const sessionJson = await env.SESSIONS.get(senderHash);
    if (!sessionJson) return twiml(MSG.intro);

    const { lat, lng } = JSON.parse(sessionJson);

    try {
      const mediaRes = await fetch(msg.mediaUrl, {
        headers: {
          'Authorization': 'Basic ' + btoa(`${env.TWILIO_ACCOUNT_SID}:${env.TWILIO_AUTH_TOKEN}`),
        },
      });
      const photoBuffer = await mediaRes.arrayBuffer();

      const tempId = crypto.randomUUID();
      const photoUrl = await uploadPhoto(sb, tempId, photoBuffer, msg.contentType);
      await insertReport(sb, { lat, lng, photoUrl, senderHash });
      await env.SESSIONS.delete(senderHash);
      return twiml(MSG.thanks);
    } catch (e) {
      console.error('submission error', e);
      return twiml(MSG.error);
    }
  }

  return twiml(MSG.intro);
}

async function handleAdminPending(request, env) {
  const origin = request.headers.get('Origin') || '';
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(origin, true) });
  }
  if (!isAuthed(request, env)) {
    return new Response('Unauthorized', { status: 401, headers: corsHeaders(origin, true) });
  }
  const sb = { url: env.SUPABASE_URL, key: env.SUPABASE_SERVICE_ROLE_KEY };
  const rows = await fetchPending(sb);
  return new Response(JSON.stringify(rows), {
    status: 200,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(origin, true) },
  });
}

async function handleAdminAction(request, env, id, newStatus) {
  const origin = request.headers.get('Origin') || '';
  if (!isAuthed(request, env)) {
    return new Response('Unauthorized', { status: 401, headers: corsHeaders(origin, true) });
  }
  const sb = { url: env.SUPABASE_URL, key: env.SUPABASE_SERVICE_ROLE_KEY };
  await updateStatus(sb, id, newStatus);

  if (newStatus === 'approved') {
    await triggerMapRegeneration(env);
  }

  return new Response('OK', { status: 200, headers: corsHeaders(origin, true) });
}

async function triggerMapRegeneration(env) {
  const res = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.GITHUB_TOKEN}`,
      'Accept': 'application/vnd.github.v3+json',
      'Content-Type': 'application/json',
      'User-Agent': 'lupa-submission-worker',
    },
    body: JSON.stringify({ event_type: 'regenerate-map' }),
  });
  if (!res.ok) console.error('GitHub dispatch failed:', res.status);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const pathname = url.pathname;
    const method = request.method;

    if (method === 'POST' && pathname === '/webhook') {
      return handleWebhook(request, env);
    }
    if (pathname === '/admin/pending') {
      return handleAdminPending(request, env);
    }
    const approveMatch = pathname.match(/^\/admin\/approve\/([^/]+)$/);
    if (method === 'POST' && approveMatch) {
      return handleAdminAction(request, env, approveMatch[1], 'approved');
    }
    const rejectMatch = pathname.match(/^\/admin\/reject\/([^/]+)$/);
    if (method === 'POST' && rejectMatch) {
      return handleAdminAction(request, env, rejectMatch[1], 'rejected');
    }

    return new Response('Not found', { status: 404 });
  },
};
