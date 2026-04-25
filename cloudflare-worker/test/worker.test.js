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

  it('parseTwilioBody returns unknown for text messages', async () => {
    const { parseTwilioBody } = await import('../src/bot.js');
    const body = new URLSearchParams({ From: 'whatsapp:+54911', Body: 'hola' });
    const msg = parseTwilioBody(body);
    expect(msg.type).toBe('unknown');
  });
});
