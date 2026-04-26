// sha256 using Web Crypto (available in Workers runtime)
async function sha256(text) {
  const encoder = new TextEncoder();
  const data = encoder.encode(text);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, '0')).join('');
}

export function parseTwilioBody(params) {
  const from = params.get('From') || '';
  const type = params.get('MessageType') || '';

  const rawFrom = from.replace('whatsapp:', '');

  if (type === 'location') {
    return {
      type: 'location',
      lat: parseFloat(params.get('Latitude')),
      lng: parseFloat(params.get('Longitude')),
      rawFrom,
    };
  }
  if (type === 'image' || (params.get('NumMedia') && parseInt(params.get('NumMedia')) > 0)) {
    return {
      type: 'media',
      mediaUrl: params.get('MediaUrl0'),
      contentType: params.get('MediaContentType0') || 'image/jpeg',
      rawFrom,
    };
  }
  const body = (params.get('Body') || '').trim();
  if (body) {
    return { type: 'text', body, rawFrom };
  }
  return { type: 'unknown', rawFrom };
}

// Parses lat/lng from a standard Google Maps share URL.
// Returns { lat, lng } or null if not found.
export function parseMapsUrl(text) {
  const atMatch = text.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/);
  if (atMatch) return { lat: parseFloat(atMatch[1]), lng: parseFloat(atMatch[2]) };
  const qMatch = text.match(/[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)/);
  if (qMatch) return { lat: parseFloat(qMatch[1]), lng: parseFloat(qMatch[2]) };
  return null;
}

export async function hashSender(rawFrom) {
  return sha256(rawFrom);
}

export async function twilioReply(accountSid, authToken, to, body) {
  const res = await fetch(
    `https://api.twilio.com/2010-04-01/Accounts/${accountSid}/Messages.json`,
    {
      method: 'POST',
      headers: {
        'Authorization': 'Basic ' + btoa(`${accountSid}:${authToken}`),
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({
        From: 'whatsapp:+14155238886', // Twilio sandbox number — replace with prod number
        To: `whatsapp:${to}`,
        Body: body,
      }),
    }
  );
  if (!res.ok) {
    const text = await res.text();
    console.error('Twilio reply failed:', res.status, text);
  }
}

export const MSG = {
  menu:          '👋 ¡Hola! ¿Qué querés reportar?\n\n1️⃣ Hay un basural\n2️⃣ Quiero contestar que un lugar está limpio',
  askLocReport:  '📍 ¿Estás en el lugar?\n\n• *Si estás ahí*: tocá el + → Ubicación y mandala.\n• *Si ya te fuiste*: abrí Google Maps, poné un pin y pegá el link acá.',
  askLocContest: '📍 ¿Dónde está el lugar que querés contestar? Mandá tu ubicación o un link de Google Maps.',
  gotLoc:        '📍 Ubicación recibida. Ahora mandá una o más fotos 📷',
  gotLocMaps:    '🗺 Ubicación registrada. Ahora mandá una o más fotos 📷',
  thanks:        '✅ ¡Gracias! Tu reporte está en revisión y va a aparecer en el mapa pronto. Podés verlo acá: https://guyonleft.github.io/lupa-jujuy/map.html',
  contestThanks: '✅ ¡Gracias! Tu contestación está en revisión.',
  timeout:       '¿Todavía estás ahí? Cuando puedas, mandá las fotos 📷',
  badUrl:        '⚠️ No pude leer las coordenadas de ese link. Probá con "Compartir → Copiar enlace" en Google Maps.',
  error:         'Hubo un problema al procesar tu reporte. Probá de nuevo en unos minutos.',
};
