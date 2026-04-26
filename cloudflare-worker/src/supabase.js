export async function insertReport(sb, { lat, lng, photoUrl, senderHash, source = 'whatsapp' }) {
  const res = await fetch(`${sb.url}/rest/v1/community_reports`, {
    method: 'POST',
    headers: {
      'apikey': sb.key,
      'Authorization': `Bearer ${sb.key}`,
      'Content-Type': 'application/json',
      'Prefer': 'return=representation',
    },
    body: JSON.stringify({
      lat,
      lng,
      photo_url: photoUrl,
      sender_hash: senderHash,
      source,
      status: 'pending',
    }),
  });
  if (!res.ok) throw new Error(`Supabase insert failed: ${res.status}`);
  const rows = await res.json();
  return rows[0].id;
}

export async function fetchPending(sb) {
  const res = await fetch(
    `${sb.url}/rest/v1/community_reports?status=eq.pending&order=submitted_at.asc`,
    {
      headers: {
        'apikey': sb.key,
        'Authorization': `Bearer ${sb.key}`,
      },
    }
  );
  if (!res.ok) throw new Error(`Supabase fetch failed: ${res.status}`);
  return res.json();
}

export async function updateStatus(sb, id, status) {
  const res = await fetch(
    `${sb.url}/rest/v1/community_reports?id=eq.${id}`,
    {
      method: 'PATCH',
      headers: {
        'apikey': sb.key,
        'Authorization': `Bearer ${sb.key}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ status }),
    }
  );
  if (!res.ok) throw new Error(`Supabase update failed: ${res.status}`);
}

export async function fetchApproved(sb) {
  const res = await fetch(
    `${sb.url}/rest/v1/community_reports?status=eq.approved&order=submitted_at.asc`,
    {
      headers: {
        'apikey': sb.key,
        'Authorization': `Bearer ${sb.key}`,
      },
    }
  );
  if (!res.ok) throw new Error(`Supabase fetch failed: ${res.status}`);
  return res.json();
}

export async function uploadPhoto(sb, id, arrayBuffer, contentType) {
  const res = await fetch(
    `${sb.url}/storage/v1/object/report-photos/${id}.jpg`,
    {
      method: 'POST',
      headers: {
        'apikey': sb.key,
        'Authorization': `Bearer ${sb.key}`,
        'Content-Type': contentType || 'image/jpeg',
        'x-upsert': 'true',
      },
      body: arrayBuffer,
    }
  );
  if (!res.ok) throw new Error(`Supabase storage upload failed: ${res.status}`);
  return `${sb.url}/storage/v1/object/public/report-photos/${id}.jpg`;
}

export async function insertContestation(sb, { lat, lng, photoUrl, senderHash, source = 'whatsapp' }) {
  const res = await fetch(`${sb.url}/rest/v1/contestations`, {
    method: 'POST',
    headers: {
      'apikey': sb.key,
      'Authorization': `Bearer ${sb.key}`,
      'Content-Type': 'application/json',
      'Prefer': 'return=representation',
    },
    body: JSON.stringify({
      lat,
      lng,
      photo_url: photoUrl,
      sender_hash: senderHash,
      source,
      status: 'pending',
    }),
  });
  if (!res.ok) throw new Error(`Supabase contestation insert failed: ${res.status}`);
  const rows = await res.json();
  return rows[0].id;
}

export async function fetchPendingContestations(sb) {
  const res = await fetch(
    `${sb.url}/rest/v1/contestations?status=eq.pending&order=submitted_at.asc`,
    {
      headers: {
        'apikey': sb.key,
        'Authorization': `Bearer ${sb.key}`,
      },
    }
  );
  if (!res.ok) throw new Error(`Supabase fetch failed: ${res.status}`);
  return res.json();
}

export async function updateContestationStatus(sb, id, status) {
  const res = await fetch(
    `${sb.url}/rest/v1/contestations?id=eq.${id}`,
    {
      method: 'PATCH',
      headers: {
        'apikey': sb.key,
        'Authorization': `Bearer ${sb.key}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ status }),
    }
  );
  if (!res.ok) throw new Error(`Supabase contestation update failed: ${res.status}`);
}

export async function fetchContestationById(sb, id) {
  const res = await fetch(
    `${sb.url}/rest/v1/contestations?id=eq.${id}&select=id,lat,lng`,
    {
      headers: {
        'apikey': sb.key,
        'Authorization': `Bearer ${sb.key}`,
      },
    }
  );
  if (!res.ok) throw new Error(`Supabase fetch failed: ${res.status}`);
  const rows = await res.json();
  return rows[0] || null;
}
