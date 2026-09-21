export interface Stop { nature: string; debut: string; fin: string }
export function duration(start: string, end: string) { const parse = (s: string) => { if (!/^\d{2}:\d{2}$/.test(s)) return null; const [h, m] = s.split(':').map(Number); return h < 24 && m < 60 ? h * 60 + m : null; }; const a = parse(start), b = parse(end); return a == null || b == null ? 0 : b > a ? b - a : b + 1440 - a; }
export function roundMinutes(value: number, mode: string) { return (mode === 'up' ? Math.ceil(value / 5) : mode === 'down' ? Math.floor(value / 5) : Math.round(value / 5)) * 5; }
export function hoursPreview(start: string, end: string, stops: Stop[], mode: string) { const gross = duration(start, end), paused = stops.reduce((s, a) => s + duration(a.debut, a.fin), 0); return { gross, paused, net: roundMinutes(Math.max(0, gross - paused), mode) }; }
export function hoursPayload(v: Record<string, string>, stops: Stop[]) {
  if (!v.engin_id || !v.date || !duration(v.heure_debut, v.heure_fin)) throw new Error('Renseignez l’engin, la date et les heures.');
  if (stops.some(a => !a.nature || !duration(a.debut, a.fin))) throw new Error('Complétez les heures de chaque arrêt ou retirez la ligne.');
  const index = (value: string) => { if (value === '') return null; const n = Number(value); if (!Number.isFinite(n) || n < 0) throw new Error('Les index doivent être des nombres positifs ou nuls.'); return n; };
  return { engin_id: v.engin_id, date: v.date, poste: v.poste, operateur: v.operateur.trim() || null, heure_debut: v.heure_debut, heure_fin: v.heure_fin, index_debut: index(v.index_debut), index_fin: index(v.index_fin), affectation: v.affectation.trim() || null, arrets: stops };
}
