// Django conserve historiquement les horodatages en UTC sans suffixe.
// Préserver les dates civiles et les offsets explicitement transmis.
export function serverTimestamp(value: string) {
  return /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(value) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value.replace(' ', 'T') + 'Z' : value;
}
