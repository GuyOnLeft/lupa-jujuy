import { parseTwilioBody, parseMapsUrl, hashSender, MSG } from './bot.js';
import {
  insertReport, fetchPending, fetchApproved, updateStatus, uploadPhoto,
  insertContestation, fetchPendingContestations, updateContestationStatus, fetchContestationById,
} from './supabase.js';

const ALLOWED_ORIGIN = 'https://guyonleft.github.io';

function twiml(message) {
  const escaped = message.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return new Response(
    `<?xml version="1.0" encoding="UTF-8"?><Response><Message>${escaped}</Message></Response>`,
    { status: 200, headers: { 'Content-Type': 'text/xml' } }
  );
}

function twimlSilent() {
  return new Response(
    '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
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

// Returns true if allowed (first use), false if rate-limited.
async function checkRateLimit(kv, key, ttlSeconds) {
  const existing = await kv.get(key);
  if (existing) return false;
  await kv.put(key, '1', { expirationTtl: ttlSeconds });
  return true;
}

async function handleWebhook(request, env, ctx) {
  const text = await request.text();

  if (!await isTwilioRequest(request, text, env.TWILIO_AUTH_TOKEN)) {
    return new Response('Forbidden', { status: 403 });
  }

  const params = new URLSearchParams(text);
  const msg = parseTwilioBody(params);
  const senderHash = await hashSender(msg.rawFrom);
  const sb = { url: env.SUPABASE_URL, key: env.SUPABASE_SERVICE_ROLE_KEY };

  const sessionJson = await env.SESSIONS.get(senderHash);
  const session = sessionJson ? JSON.parse(sessionJson) : null;

  if (msg.type === 'location') {
    if (!session?.flow) {
      await env.SESSIONS.put(senderHash, JSON.stringify({ menuSent: true }), { expirationTtl: 300 });
      return twiml(MSG.menu);
    }
    await env.SESSIONS.put(
      senderHash,
      JSON.stringify({ flow: session.flow, lat: msg.lat, lng: msg.lng }),
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
        } catch (_) { /* network error — fall through */ }
      }
    }

    if (coords) {
      if (!session?.flow) {
        await env.SESSIONS.put(senderHash, JSON.stringify({ menuSent: true }), { expirationTtl: 300 });
        return twiml(MSG.menu);
      }
      await env.SESSIONS.put(
        senderHash,
        JSON.stringify({ flow: session.flow, lat: coords.lat, lng: coords.lng }),
        { expirationTtl: 300 }
      );
      return twiml(MSG.gotLocMaps);
    }

    const looksLikeMapsLink = /google\.com\/maps|maps\.app\.goo\.gl|goo\.gl\/maps/.test(msg.body);
    if (looksLikeMapsLink) {
      if (!session?.flow) {
        await env.SESSIONS.put(senderHash, JSON.stringify({ menuSent: true }), { expirationTtl: 300 });
        return twiml(MSG.menu);
      }
      return twiml(MSG.badUrl);
    }

    // Menu selection
    const trimmed = msg.body.trim();
    if (trimmed === '1') {
      await env.SESSIONS.put(senderHash, JSON.stringify({ flow: 'report' }), { expirationTtl: 300 });
      return twiml(MSG.askLocReport);
    }
    if (trimmed === '2') {
      await env.SESSIONS.put(senderHash, JSON.stringify({ flow: 'contest' }), { expirationTtl: 300 });
      return twiml(MSG.askLocContest);
    }

    // Any other text — send/re-send menu
    await env.SESSIONS.put(senderHash, JSON.stringify({ menuSent: true }), { expirationTtl: 300 });
    return twiml(MSG.menu);
  }

  if (msg.type === 'media') {
    if (!session?.flow || session.lat == null) {
      await env.SESSIONS.put(senderHash, JSON.stringify({ menuSent: true }), { expirationTtl: 300 });
      return twiml(MSG.menu);
    }

    const { flow, lat, lng, thanked, photoCount = 0 } = session;
    const MAX_PHOTOS = 10;

    if (photoCount >= MAX_PHOTOS) {
      return twimlSilent();
    }

    // Rate limit contestations: 1 per sender per site per 24h
    if (flow === 'contest') {
      const lat3 = Math.round(lat * 1000);
      const lng3 = Math.round(lng * 1000);
      const rlKey = `rl_contest:${senderHash}:${lat3}:${lng3}`;
      const allowed = await checkRateLimit(env.SESSIONS, rlKey, 86400);
      if (!allowed) {
        return twiml('⚠️ Ya enviaste una contestación para este lugar en las últimas 24 horas.');
      }
    }

    const newCount = photoCount + 1;
    await env.SESSIONS.put(senderHash, JSON.stringify({ flow, lat, lng, thanked: true, photoCount: newCount }), { expirationTtl: 120 });

    ctx.waitUntil((async () => {
      try {
        const mediaRes = await fetch(msg.mediaUrl, {
          headers: {
            'Authorization': 'Basic ' + btoa(`${env.TWILIO_ACCOUNT_SID}:${env.TWILIO_AUTH_TOKEN}`),
          },
        });
        const photoBuffer = await mediaRes.arrayBuffer();
        const tempId = crypto.randomUUID();
        const photoUrl = await uploadPhoto(sb, tempId, photoBuffer, msg.contentType);

        if (flow === 'contest') {
          await insertContestation(sb, { lat, lng, photoUrl, senderHash, source: 'whatsapp' });
        } else {
          await insertReport(sb, { lat, lng, photoUrl, senderHash, source: 'community' });
        }
      } catch (e) {
        console.error('submission error', e);
      }
    })());

    return thanked ? twimlSilent() : twiml(flow === 'contest' ? MSG.contestThanks : MSG.thanks);
  }

  return twiml(MSG.menu);
}

async function handleWebSubmit(request, env) {
  const origin = request.headers.get('Origin') || '';
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(origin) });
  }
  if (origin !== ALLOWED_ORIGIN) {
    return new Response('Forbidden', { status: 403 });
  }

  let formData;
  try {
    formData = await request.formData();
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid form data' }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
  }

  const lat = parseFloat(formData.get('lat'));
  const lng = parseFloat(formData.get('lng'));
  if (isNaN(lat) || isNaN(lng)) {
    return new Response(JSON.stringify({ error: 'lat and lng required' }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
  }

  const photoFile = formData.get('photo');
  if (!photoFile || typeof photoFile === 'string') {
    return new Response(JSON.stringify({ error: 'photo required' }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
  }

  // Rate limit: 5 web submissions per IP per hour (best-effort — KV reads are non-atomic)
  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
  const rlKey = `rl_web_submit:${ip}`;
  const existing = await env.SESSIONS.get(rlKey);
  const count = existing ? parseInt(existing) : 0;
  if (count >= 5) {
    return new Response(JSON.stringify({ error: 'Too many submissions. Try again later.' }), { status: 429, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
  }
  await env.SESSIONS.put(rlKey, String(count + 1), { expirationTtl: 3600 });

  const sb = { url: env.SUPABASE_URL, key: env.SUPABASE_SERVICE_ROLE_KEY };
  try {
    const photoBuffer = await photoFile.arrayBuffer();
    const tempId = crypto.randomUUID();
    const photoUrl = await uploadPhoto(sb, tempId, photoBuffer, photoFile.type || 'image/jpeg');
    const id = await insertReport(sb, { lat, lng, photoUrl, senderHash: null, source: 'community' });
    return new Response(JSON.stringify({ success: true, id }), { status: 201, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
  } catch (e) {
    console.error('web submit error', e);
    return new Response(JSON.stringify({ error: 'Server error' }), { status: 500, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
  }
}

async function handleWebContest(request, env) {
  const origin = request.headers.get('Origin') || '';
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(origin) });
  }
  if (origin !== ALLOWED_ORIGIN) {
    return new Response('Forbidden', { status: 403 });
  }

  let formData;
  try {
    formData = await request.formData();
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid form data' }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
  }

  const lat = parseFloat(formData.get('lat'));
  const lng = parseFloat(formData.get('lng'));
  if (isNaN(lat) || isNaN(lng)) {
    return new Response(JSON.stringify({ error: 'lat and lng required' }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
  }

  const photoFile = formData.get('photo');
  if (!photoFile || typeof photoFile === 'string') {
    return new Response(JSON.stringify({ error: 'photo required' }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
  }

  // Rate limit: 1 web contestation per IP per site per 24h
  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
  const lat3 = Math.round(lat * 1000);
  const lng3 = Math.round(lng * 1000);
  const rlKey = `rl_web_contest:${ip}:${lat3}:${lng3}`;
  const allowed = await checkRateLimit(env.SESSIONS, rlKey, 86400);
  if (!allowed) {
    return new Response(JSON.stringify({ error: 'Ya contestaste este lugar en las últimas 24 horas.' }), { status: 429, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
  }

  const sb = { url: env.SUPABASE_URL, key: env.SUPABASE_SERVICE_ROLE_KEY };
  try {
    const photoBuffer = await photoFile.arrayBuffer();
    const tempId = crypto.randomUUID();
    const photoUrl = await uploadPhoto(sb, tempId, photoBuffer, photoFile.type || 'image/jpeg');
    await insertContestation(sb, { lat, lng, photoUrl, senderHash: null, source: 'web' });
    return new Response(JSON.stringify({ success: true }), { status: 201, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
  } catch (e) {
    console.error('web contest error', e);
    return new Response(JSON.stringify({ error: 'Server error' }), { status: 500, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
  }
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

async function handleAdminContestations(request, env) {
  const origin = request.headers.get('Origin') || '';
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(origin, true) });
  }
  if (!isAuthed(request, env)) {
    return new Response('Unauthorized', { status: 401, headers: corsHeaders(origin, true) });
  }
  const sb = { url: env.SUPABASE_URL, key: env.SUPABASE_SERVICE_ROLE_KEY };
  const rows = await fetchPendingContestations(sb);
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

async function handleAdminContestAction(request, env, id, newStatus) {
  const origin = request.headers.get('Origin') || '';
  if (!isAuthed(request, env)) {
    return new Response('Unauthorized', { status: 401, headers: corsHeaders(origin, true) });
  }
  const sb = { url: env.SUPABASE_URL, key: env.SUPABASE_SERVICE_ROLE_KEY };
  await updateContestationStatus(sb, id, newStatus);

  if (newStatus === 'approved') {
    const contestation = await fetchContestationById(sb, id);
    if (contestation) {
      await triggerRemovedSitesUpdate(env, contestation.lat, contestation.lng);
    }
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

async function triggerRemovedSitesUpdate(env, lat, lng) {
  const res = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.GITHUB_TOKEN}`,
      'Accept': 'application/vnd.github.v3+json',
      'Content-Type': 'application/json',
      'User-Agent': 'lupa-submission-worker',
    },
    body: JSON.stringify({ event_type: 'update-removed-sites', client_payload: { lat, lng } }),
  });
  if (!res.ok) console.error('GitHub dispatch (removed-sites) failed:', res.status);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const pathname = url.pathname;
    const method = request.method;

    if (method === 'POST' && pathname === '/webhook') {
      return handleWebhook(request, env, ctx);
    }
    if ((method === 'POST' || method === 'OPTIONS') && pathname === '/submit') {
      return handleWebSubmit(request, env);
    }
    if ((method === 'POST' || method === 'OPTIONS') && pathname === '/contest') {
      return handleWebContest(request, env);
    }
    if (method === 'GET' && pathname === '/reports') {
      const origin = request.headers.get('Origin') || '';
      const sb = { url: env.SUPABASE_URL, key: env.SUPABASE_SERVICE_ROLE_KEY };
      try {
        const rows = await fetchApproved(sb);
        const sites = rows.map(r => ({
          latitude: r.lat,
          longitude: r.lng,
          photo_url: r.photo_url,
          source: 'community',
          submitted_at: r.submitted_at,
          id: r.id,
        }));
        return new Response(JSON.stringify(sites), {
          headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: 'Server error' }), { status: 500, headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) } });
      }
    }

    if (pathname === '/admin/pending') {
      return handleAdminPending(request, env);
    }
    if (pathname === '/admin/contestations') {
      return handleAdminContestations(request, env);
    }
    const approveMatch = pathname.match(/^\/admin\/approve\/([^/]+)$/);
    if (approveMatch) {
      if (method === 'OPTIONS') return new Response(null, { status: 204, headers: corsHeaders(request.headers.get('Origin') || '', true) });
      if (method === 'POST') return handleAdminAction(request, env, approveMatch[1], 'approved');
    }
    const rejectMatch = pathname.match(/^\/admin\/reject\/([^/]+)$/);
    if (rejectMatch) {
      if (method === 'OPTIONS') return new Response(null, { status: 204, headers: corsHeaders(request.headers.get('Origin') || '', true) });
      if (method === 'POST') return handleAdminAction(request, env, rejectMatch[1], 'rejected');
    }
    const approveContestMatch = pathname.match(/^\/admin\/approve-contest\/([^/]+)$/);
    if (approveContestMatch) {
      if (method === 'OPTIONS') return new Response(null, { status: 204, headers: corsHeaders(request.headers.get('Origin') || '', true) });
      if (method === 'POST') return handleAdminContestAction(request, env, approveContestMatch[1], 'approved');
    }
    const rejectContestMatch = pathname.match(/^\/admin\/reject-contest\/([^/]+)$/);
    if (rejectContestMatch) {
      if (method === 'OPTIONS') return new Response(null, { status: 204, headers: corsHeaders(request.headers.get('Origin') || '', true) });
      if (method === 'POST') return handleAdminContestAction(request, env, rejectContestMatch[1], 'rejected');
    }

    return new Response('Not found', { status: 404 });
  },
};
