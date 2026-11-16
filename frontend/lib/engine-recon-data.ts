// Réconciliation des prestations d'engins : saisie libre des durées,
// au format du desktop Horizon (« 8h30 », « 8:30 », « 8,5 » ou « 8.5 »).
export function parseDuree(text: string): number | null {
  const s = String(text ?? '').trim().toLowerCase();
  if (!s) return null;
  let m = /^(\d{1,2})\s*[h:]\s*(\d{1,2})$/.exec(s);
  if (m) {
    const h = Number(m[1]), mn = Number(m[2]);
    if (h > 47 || mn > 59) return null;
    return h * 60 + mn;
  }
  m = /^(\d{1,2})(?:[,.](\d+))?$/.exec(s.replace(/\s*h$/, ''));
  if (m) {
    const val = Number(`${m[1]}.${m[2] || 0}`);
    if (!Number.isFinite(val) || val > 48) return null;
    return Math.round(val * 60);
  }
  return null;
}

// Arrondi aux multiples de 5 minutes (mode « nearest » du serveur).
export function arrondir5(minutes: number): number {
  return Math.round(minutes / 5) * 5;
}

export function fmtHM(minutes: number | null | undefined): string {
  if (minutes == null) return '—';
  const neg = minutes < 0, m = Math.abs(Math.round(minutes));
  return `${neg ? '-' : ''}${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`;
}

export function fmtDec(minutes: number): string {
  return (arrondir5(minutes) / 60).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Valeur saisie -> minutes arrondies, ou lève une erreur lisible.
export function minutesSaisies(text: string, contexte: string): number | null {
  const v = parseDuree(text);
  if (text.trim() && v == null) throw new Error(`${contexte} : format invalide (« 8h30 », « 8:30 » ou « 8,5 »).`);
  return v == null ? null : arrondir5(v);
}
