import { JURISDICTIONS, citationStyle } from "@/lib/jurisdictions";

export function JurisdictionPicker({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (code: string) => void;
  disabled?: boolean;
}) {
  const groups = [...new Set(JURISDICTIONS.map((j) => j.group))];
  return (
    <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
      <span className="hidden sm:inline">Jurisdiction</span>
      <select
        aria-label="Jurisdiction"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="min-w-0 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-800 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
      >
        {groups.map((group) => (
          <optgroup key={group} label={group}>
            {JURISDICTIONS.filter((j) => j.group === group).map((j) => (
              <option key={j.code} value={j.code}>
                {j.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <span className="hidden rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500 lg:inline dark:bg-slate-800">
        {citationStyle(value)}
      </span>
    </label>
  );
}
