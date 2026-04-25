import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('supabase helpers', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it('insertReport sends correct POST to Supabase', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify([{ id: 'abc-123' }]), { status: 201 })
    );

    const { insertReport } = await import('../src/supabase.js');

    const id = await insertReport(
      { url: 'https://proj.supabase.co', key: 'service-key' },
      { lat: -24.19, lng: -65.30, photoUrl: 'https://cdn/photo.jpg', senderHash: 'abc' }
    );

    expect(id).toBe('abc-123');
    expect(mockFetch).toHaveBeenCalledWith(
      'https://proj.supabase.co/rest/v1/community_reports',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'apikey': 'service-key',
          'Authorization': 'Bearer service-key',
          'Content-Type': 'application/json',
          'Prefer': 'return=representation',
        }),
        body: JSON.stringify({
          lat: -24.19,
          lng: -65.30,
          photo_url: 'https://cdn/photo.jpg',
          sender_hash: 'abc',
          source: 'whatsapp',
          status: 'pending',
        }),
      })
    );
  });

  it('insertReport includes source in body', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify([{ id: 'xyz-789' }]), { status: 201 })
    );
    const { insertReport } = await import('../src/supabase.js');
    await insertReport(
      { url: 'https://proj.supabase.co', key: 'service-key' },
      { lat: -24.19, lng: -65.30, photoUrl: 'https://cdn/photo.jpg', senderHash: 'abc', source: 'web' }
    );
    const callBody = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(callBody.source).toBe('web');
  });

  it('insertContestation sends correct POST', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify([{ id: 'con-111' }]), { status: 201 })
    );
    const { insertContestation } = await import('../src/supabase.js');
    const id = await insertContestation(
      { url: 'https://proj.supabase.co', key: 'service-key' },
      { lat: -24.19, lng: -65.30, photoUrl: 'https://cdn/photo.jpg', senderHash: 'abc', source: 'whatsapp' }
    );
    expect(id).toBe('con-111');
    expect(mockFetch).toHaveBeenCalledWith(
      'https://proj.supabase.co/rest/v1/contestations',
      expect.objectContaining({ method: 'POST' })
    );
  });
});

describe('bot helpers', () => {
  it('parseTwilioBody extracts location message', async () => {
    const { parseTwilioBody, hashSender } = await import('../src/bot.js');
    const body = new URLSearchParams({
      From: 'whatsapp:+5491100000000',
      MessageType: 'location',
      Latitude: '-24.1857',
      Longitude: '-65.2995',
    });
    const msg = parseTwilioBody(body);
    expect(msg.type).toBe('location');
    expect(msg.lat).toBe(-24.1857);
    expect(msg.lng).toBe(-65.2995);
    const hash = await hashSender(msg.rawFrom);
    expect(hash).toMatch(/^[a-f0-9]{64}$/);
  });

  it('parseTwilioBody extracts media message', async () => {
    const { parseTwilioBody } = await import('../src/bot.js');
    const body = new URLSearchParams({
      From: 'whatsapp:+5491100000000',
      MessageType: 'image',
      NumMedia: '1',
      MediaUrl0: 'https://api.twilio.com/media/xyz',
      MediaContentType0: 'image/jpeg',
    });
    const msg = parseTwilioBody(body);
    expect(msg.type).toBe('media');
    expect(msg.mediaUrl).toBe('https://api.twilio.com/media/xyz');
    expect(msg.contentType).toBe('image/jpeg');
  });

  it('parseTwilioBody returns text type for plain messages', async () => {
    const { parseTwilioBody } = await import('../src/bot.js');
    const body = new URLSearchParams({ From: 'whatsapp:+54911', Body: 'hola' });
    const msg = parseTwilioBody(body);
    expect(msg.type).toBe('text');
    expect(msg.body).toBe('hola');
  });

  it('parseTwilioBody returns type text with body for numeric message', async () => {
    const { parseTwilioBody } = await import('../src/bot.js');
    const body = new URLSearchParams({ From: 'whatsapp:+54911', Body: '1' });
    const msg = parseTwilioBody(body);
    expect(msg.type).toBe('text');
    expect(msg.body).toBe('1');
  });

  it('parseMapsUrl extracts coords from /@lat,lng format', async () => {
    const { parseMapsUrl } = await import('../src/bot.js');
    const url = 'https://www.google.com/maps/place/Jujuy/@-24.1857,-65.2995,15z/data=abc';
    const coords = parseMapsUrl(url);
    expect(coords).toEqual({ lat: -24.1857, lng: -65.2995 });
  });

  it('parseMapsUrl extracts coords from ?q=lat,lng format', async () => {
    const { parseMapsUrl } = await import('../src/bot.js');
    const url = 'https://maps.google.com/?q=-24.1923,-65.3041';
    const coords = parseMapsUrl(url);
    expect(coords).toEqual({ lat: -24.1923, lng: -65.3041 });
  });

  it('parseMapsUrl returns null for non-maps text', async () => {
    const { parseMapsUrl } = await import('../src/bot.js');
    expect(parseMapsUrl('hola cómo estás')).toBeNull();
  });
});

async function twilioSig(url, body, authToken) {
  const params = new URLSearchParams(body);
  const sortedKeys = [...params.keys()].sort();
  let toSign = url;
  for (const key of sortedKeys) toSign += key + (params.get(key) ?? '');
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(authToken), { name: 'HMAC', hash: 'SHA-1' }, false, ['sign']
  );
  const signed = await crypto.subtle.sign('HMAC', key, enc.encode(toSign));
  return btoa(String.fromCharCode(...new Uint8Array(signed)));
}

describe('worker routing', () => {
  it('returns 404 for unknown routes', async () => {
    const { default: worker } = await import('../src/index.js');
    const req = new Request('https://worker.example/unknown', { method: 'GET' });
    const env = { SESSIONS: { get: vi.fn(), put: vi.fn(), delete: vi.fn() } };
    const res = await worker.fetch(req, env, {});
    expect(res.status).toBe(404);
  });

  it('POST /webhook returns 403 without valid Twilio signature', async () => {
    const { default: worker } = await import('../src/index.js');
    const req = new Request('https://worker.example/webhook', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'From=whatsapp%3A%2B123&MessageType=text&Body=hi',
    });
    const env = { TWILIO_AUTH_TOKEN: 'real-token', SESSIONS: { get: vi.fn(), put: vi.fn(), delete: vi.fn() } };
    const res = await worker.fetch(req, env, {});
    expect(res.status).toBe(403);
  });

  it('POST /webhook returns TwiML for location message with valid signature', async () => {
    const { default: worker } = await import('../src/index.js');
    const authToken = 'test-token';
    const url = 'https://worker.example/webhook';
    const body = new URLSearchParams({
      From: 'whatsapp:+5491100000000',
      MessageType: 'location',
      Latitude: '-24.1857',
      Longitude: '-65.2995',
    });
    const bodyStr = body.toString();
    const sig = await twilioSig(url, bodyStr, authToken);

    const req = new Request(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-Twilio-Signature': sig,
      },
      body: bodyStr,
    });
    const env = {
      TWILIO_AUTH_TOKEN: authToken,
      SESSIONS: { get: vi.fn().mockResolvedValue(JSON.stringify({ flow: 'report' })), put: vi.fn().mockResolvedValue(null), delete: vi.fn() },
      SUPABASE_URL: 'https://proj.supabase.co',
      SUPABASE_SERVICE_ROLE_KEY: 'key',
    };
    const res = await worker.fetch(req, env, {});
    expect(res.status).toBe(200);
    expect(res.headers.get('Content-Type')).toBe('text/xml');
    const text = await res.text();
    expect(text).toContain('<Message>');
    expect(env.SESSIONS.put).toHaveBeenCalledWith(
      expect.stringMatching(/^[a-f0-9]{64}$/),
      expect.stringContaining('-24.1857'),
      { expirationTtl: 300 }
    );
  });

  it('POST /webhook returns menu when no session and text message', async () => {
    vi.resetModules();
    const { default: worker } = await import('../src/index.js');
    const authToken = 'test-token';
    const url = 'https://worker.example/webhook';
    const body = new URLSearchParams({ From: 'whatsapp:+54911', Body: 'hola', MessageType: 'text' });
    const bodyStr = body.toString();
    const sig = await twilioSig(url, bodyStr, authToken);
    const req = new Request(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Twilio-Signature': sig },
      body: bodyStr,
    });
    const env = {
      TWILIO_AUTH_TOKEN: authToken,
      SESSIONS: { get: vi.fn().mockResolvedValue(null), put: vi.fn().mockResolvedValue(null) },
    };
    const res = await worker.fetch(req, env, {});
    expect(res.status).toBe(200);
    const text = await res.text();
    expect(text).toContain('1️⃣');
  });

  it('POST /submit returns 400 without lat/lng', async () => {
    vi.resetModules();
    const { default: worker } = await import('../src/index.js');
    const formData = new FormData();
    formData.append('lat', 'notanumber');
    const req = new Request('https://worker.example/submit', {
      method: 'POST',
      headers: { 'Origin': 'https://guyonleft.github.io' },
      body: formData,
    });
    const env = {
      SESSIONS: { get: vi.fn(), put: vi.fn() },
      SUPABASE_URL: 'https://proj.supabase.co',
      SUPABASE_SERVICE_ROLE_KEY: 'key',
    };
    const res = await worker.fetch(req, env, {});
    expect(res.status).toBe(400);
  });
});
