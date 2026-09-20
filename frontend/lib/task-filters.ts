export interface Task {
  id: string; document_id: string; type: string; reference: string; action: string; detail: string; module: string; niveau: string;
  responsables: { id: string; nom: string }[]; roles: string[]; affectation: string; impact: string; blocage: string; vue: string;
  age_heures: number | null; echeance_depassee: boolean; debut: string | null; base_date: string; relance_at: string | null; escalade_at: string | null; echeance: string | null;
}
export interface TaskFilters { q: string; module: string; user: string; niveau: string }
export const levels: Record<string, string> = { a_attribuer: 'Affectation à vérifier', escalade: 'Remontée DFI', relance: 'Relance', a_traiter: 'À traiter' };
const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
export function filterTasks(tasks: Task[], filters: TaskFilters) {
  return tasks.filter(task => (!filters.module || task.module === filters.module) && (!filters.niveau || task.niveau === filters.niveau) && (!filters.user || task.responsables.some(u => u.id === filters.user)) && normalize([task.reference, task.action, task.detail, ...task.responsables.map(u => u.nom), ...task.roles].join(' ')).includes(normalize(filters.q)));
}
export function validateRules(rules: Record<string, { relance_h: number; escalade_h: number } | null>) {
  return Object.values(rules).every(rule => !rule || (Number.isInteger(rule.relance_h) && Number.isInteger(rule.escalade_h) && rule.relance_h >= 1 && rule.relance_h < rule.escalade_h && rule.escalade_h <= 8760));
}
