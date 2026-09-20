export type Cell = string | number | null;
export function selectTableRows(rows: Cell[][], search: string, sort: number, direction: number) {
  const normal = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const words = normal(search).trim().split(/\s+/).filter(Boolean);
  const selected = rows.filter(row => words.every(word => normal(row.join(' ')).includes(word)));
  if (sort >= 0) selected.sort((a, b) => direction * (typeof a[sort] === 'number' && typeof b[sort] === 'number' ? (a[sort] as number) - (b[sort] as number) : String(a[sort] ?? '').localeCompare(String(b[sort] ?? ''), 'fr', { numeric: true, sensitivity: 'base' })));
  return selected;
}
export function tableCSV(columns: string[], rows: Cell[][]) {
  const escape = (cell: Cell) => { let value = String(cell ?? ''); if (/^[\s\uFEFF]*[=+@-]/.test(value) && !/^-?\d+(?:[.,]\d+)?$/.test(value.trim())) value = "'" + value; return '"' + value.replace(/"/g, '""') + '"'; };
  return '\uFEFF' + [columns, ...rows].map(row => row.map(escape).join(';')).join('\r\n');
}
