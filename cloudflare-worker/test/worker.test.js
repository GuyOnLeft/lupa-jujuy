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
