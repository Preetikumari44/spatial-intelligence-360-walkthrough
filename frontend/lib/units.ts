export type UnitSystem = "mm" | "cm" | "m" | "in" | "ft";

export function formatLength(mm: number | null | undefined, unit: UnitSystem): string {
  if (mm == null || Number.isNaN(mm)) return "–";
  switch (unit) {
    case "mm": return `${mm.toFixed(0)} mm`;
    case "cm": return `${(mm / 10).toFixed(1)} cm`;
    case "m": return `${(mm / 1000).toFixed(2)} m`;
    case "in": return `${(mm / 25.4).toFixed(1)} in`;
    case "ft": {
      const totalIn = mm / 25.4;
      const ft = Math.floor(totalIn / 12);
      return `${ft}′ ${(totalIn - ft * 12).toFixed(1)}″`;
    }
  }
}
