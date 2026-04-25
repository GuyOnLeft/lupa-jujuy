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
  return { type: 'unknown', rawFrom };
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
  intro:   '👋 ¡Hola! Para reportar un basural mandá primero tu 📍 ubicación y después una 📷 foto.',
  gotLoc:  '📍 Ubicación recibida. Ahora mandá la foto del basural.',
  thanks:  '✅ ¡Gracias! Tu reporte está en revisión y va a aparecer en el mapa pronto. Podés verlo acá: https://guyonleft.github.io/lupa-jujuy/map.html',
  timeout: '¿Todavía estás ahí? Cuando puedas, mandá la foto del basural 📷',
  error:   'Hubo un problema al procesar tu reporte. Probá de nuevo en unos minutos.',
};
