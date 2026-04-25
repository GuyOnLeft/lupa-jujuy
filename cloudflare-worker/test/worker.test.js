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
          status: 'pending',
        }),
      })
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

describe('worker routing', () => {
  it('returns 404 for unknown routes', async () => {
    const { default: worker } = await import('../src/index.js');
    const req = new Request('https://worker.example/unknown', { method: 'GET' });
    const env = { SESSIONS: { get: vi.fn(), put: vi.fn(), delete: vi.fn() } };
    const res = await worker.fetch(req, env, {});
    expect(res.status).toBe(404);
  });

  it('POST /webhook returns 200 for location message', async () => {
    mockFetch.mockResolvedValue(new Response('{}', { status: 200 })); // Twilio reply
    const { default: worker } = await import('../src/index.js');

    const body = new URLSearchParams({
      From: 'whatsapp:+5491100000000',
      MessageType: 'location',
      Latitude: '-24.1857',
      Longitude: '-65.2995',
    });
    const req = new Request('https://worker.example/webhook', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });
    const env = {
      SESSIONS: { get: vi.fn().mockResolvedValue(null), put: vi.fn().mockResolvedValue(null), delete: vi.fn() },
      TWILIO_ACCOUNT_SID: 'sid',
      TWILIO_AUTH_TOKEN: 'token',
      SUPABASE_URL: 'https://proj.supabase.co',
      SUPABASE_SERVICE_ROLE_KEY: 'key',
    };
    const res = await worker.fetch(req, env, {});
    expect(res.status).toBe(200);
    expect(env.SESSIONS.put).toHaveBeenCalledWith(
      expect.stringMatching(/^[a-f0-9]{64}$/),
      expect.stringContaining('-24.1857'),
      { expirationTtl: 300 }
    );
  });
});
