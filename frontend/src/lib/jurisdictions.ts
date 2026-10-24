// Codes understood by the API (app/services/jurisdiction_service.py).
export const JURISDICTIONS: { code: string; label: string; group: string }[] = [
  { code: "IN", label: "India (BNS / BNSS / BSA)", group: "India" },
  { code: "US", label: "United States: Federal", group: "United States" },
  { code: "US-CA", label: "US: California", group: "United States" },
  { code: "US-NY", label: "US: New York", group: "United States" },
  { code: "US-TX", label: "US: Texas", group: "United States" },
  { code: "US-FL", label: "US: Florida", group: "United States" },
  { code: "US-IL", label: "US: Illinois", group: "United States" },
  { code: "US-WA", label: "US: Washington", group: "United States" },
  { code: "UK", label: "UK: England & Wales", group: "United Kingdom" },
];

export const CITATION_STYLE: Record<string, string> = { IN: "SCC / AIR", US: "Bluebook", UK: "OSCOLA" };

export function citationStyle(code: string): string {
  return CITATION_STYLE[code.startsWith("US") ? "US" : code] ?? "";
}
