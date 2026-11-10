import type { IncidentCsvInspection, IncidentImportBody } from '@/lib/incidents'

export type ColumnChoice =
  { kind: 'unmapped' } | { kind: 'column'; header: string } | { kind: 'constant'; value: string }
export type ColumnChoices = Record<string, ColumnChoice>

export function columnMappingFile(profile: IncidentImportBody['profile'], choices: ColumnChoices) {
  return {
    version: 1,
    profile,
    column_mapping: Object.fromEntries(
      Object.entries(choices).flatMap(([field, choice]) =>
        choice.kind === 'column' ? [[field, choice.header]] : [],
      ),
    ),
  }
}

export function readColumnMapping(
  text: string,
  profile: IncidentImportBody['profile'],
  inspection: IncidentCsvInspection,
): ColumnChoices {
  const saved: unknown = JSON.parse(text)
  if (
    !saved ||
    typeof saved !== 'object' ||
    Array.isArray(saved) ||
    !('version' in saved) ||
    saved.version !== 1 ||
    !('profile' in saved) ||
    saved.profile !== profile ||
    !('column_mapping' in saved) ||
    !saved.column_mapping ||
    typeof saved.column_mapping !== 'object' ||
    Array.isArray(saved.column_mapping) ||
    Object.keys(saved).some((key) => !['version', 'profile', 'column_mapping'].includes(key))
  )
    throw new Error('Use a version 1 column mapping for the selected source profile.')

  const pairs = Object.entries(saved.column_mapping)
  if (new Set(pairs.map(([, header]) => header)).size !== pairs.length)
    throw new Error('Each source column can map to only one field.')
  if (
    pairs.some(
      ([name, header]) =>
        !inspection.fields.some((field) => field.name === name) ||
        typeof header !== 'string' ||
        !inspection.headers.includes(header),
    )
  )
    throw new Error(
      'The mapping contains unknown fields or columns absent from this CSV. Inspect and map this file again.',
    )

  const columns = new Map(pairs)
  return Object.fromEntries(
    inspection.fields.map((field): [string, ColumnChoice] => [
      field.name,
      columns.has(field.name)
        ? { kind: 'column', header: columns.get(field.name) as string }
        : { kind: 'unmapped' },
    ]),
  )
}
